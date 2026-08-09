"""
Elsevier / Scopus provider.

Requires ELSEVIER_API_KEY and/or SCOPUS_API_KEY.
Returns a structured "not configured" result when key is absent.
This provider requires an institutional Elsevier API key (ELSEVIER_API_KEY
and/or SCOPUS_API_KEY).  When the key is absent the provider returns a
structured "not configured" result without making any network call.

Allowed metadata fields (per Elsevier Text and Data Mining policy):
- title, authors, year, doi, journal, url, citation_count, subject_terms
Do NOT store full abstracts or restricted database payloads unless your
institutional licence explicitly permits it.

REST endpoint used:
  GET https://api.elsevier.com/content/search/scopus
  Headers: X-ELS-APIKey: <key>, Accept: application/json
  Response: search-results.entry[] — each entry maps to a LiteratureRecord.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from src.scientific_sources.base import BaseProvider
from src.scientific_sources.models import (
    LiteratureRecord,
    ProviderResult,
    SourceCapability,
    SourceEvidence,
)

_ALLOWED_FIELDS = [
    "title",
    "authors",
    "year",
    "doi",
    "journal",
    "url",
    "citation_count",
    "subject_terms",
    "source_id",
    "provider",
    "source_query",
    "retrieval_timestamp",
]

_SCOPUS_API_BASE = "https://api.elsevier.com/content/search/scopus"

# Fields requested from the Scopus API — deliberately excludes abstract/full-text.
_SCOPUS_FIELDS = (
    "dc:title,dc:creator,author,prism:doi,prism:coverDate,"
    "prism:publicationName,prism:url,citedby-count,authkeywords,eid"
)
_SCOPUS_MAX_COUNT = 25
_SCOPUS_PRESERVED_HYPHEN_TERMS = frozenset({"port-city", "de-base-re"})
_SCOPUS_PAYLOAD_KIND = "redistribution_safe_metadata_envelope"
_REDACTED_QUERY_PARAMS = frozenset({"api_key", "apikey", "key", "token", "secret"})

_LICENCE_NOTE = (
    "Elsevier/Scopus institutional metadata (Stage 1 compliant). "
    "Do not store full abstracts or restricted database payloads."
)


class ElsevierScopusProvider(BaseProvider):
    """Elsevier Scopus provider."""

    def __init__(self) -> None:
        self._api_key: str = os.getenv("ELSEVIER_API_KEY", "") or os.getenv(
            "SCOPUS_API_KEY", ""
        )
        self._api_base = "https://api.elsevier.com/content/search/scopus"

    @property
    def capability(self) -> SourceCapability:
        """Return capability descriptor for Elsevier/Scopus."""
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        return SourceCapability(
            name="scopus",
            provider="Elsevier / Scopus",
            requires_secret=True,
            configured=bool(self._api_key),
            live_test_allowed=live and bool(self._api_key),
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=(
                "Store only title, authors, year, DOI, journal, URL, "
                "citation count, and subject terms unless institutional "
                "licence permits additional fields."
            ),
        )

    def _request_json(self, url: str) -> Dict[str, Any]:
        req = urllib.request.Request(
            url, headers={"X-ELS-APIKey": self._api_key, "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode())
        return cast(Dict[str, Any], payload)

    @staticmethod
    def _project_protocol_query(query: str) -> Optional[str]:
        """Project protocol free-text query into Scopus TITLE-ABS-KEY syntax.

        Returns ``None`` when the query contains no extractable searchable tokens so
        that callers can reject the request with a structured provider error rather
        than substituting unrelated fallback terms that would contaminate provenance.

        Hyphen policy: only terms in ``_SCOPUS_PRESERVED_HYPHEN_TERMS`` (currently
        ``port-city`` and ``de-base-re``) are kept hyphenated. All other hyphens are
        split into mandatory AND-joined tokens (e.g. ``cyber-physical`` becomes
        ``"cyber" AND "physical"``).
        """
        normalized = query.replace("&amp;", " and ")
        # Protect preserved hyphen terms with placeholders before splitting
        preserved: Dict[str, str] = {}
        for index, term in enumerate(sorted(_SCOPUS_PRESERVED_HYPHEN_TERMS)):
            placeholder = f" SCOPUSPRESERVEDHYPHEN{index} "
            pattern = rf"\b{re.escape(term)}\b"
            normalized = re.sub(
                pattern,
                placeholder,
                normalized,
                flags=re.IGNORECASE,
            )
            preserved[placeholder.strip()] = term
        normalized = (
            normalized.replace("&", " and ")
            .replace("/", " ")
            .replace("(", " ")
            .replace(")", " ")
            .replace("-", " ")
        )
        tokens = []
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-\\.]*", normalized):
            if token and token.lower() not in {"and", "or", "not"}:
                tokens.append(preserved.get(token, token))
        if not tokens:
            return None
        scoped_terms = " AND ".join(f'"{token}"' for token in tokens)
        return f"TITLE-ABS-KEY({scoped_terms})"

    @staticmethod
    def _scopus_count(max_results: int) -> int:
        return max(1, min(int(max_results), _SCOPUS_MAX_COUNT))

    @staticmethod
    def _parse_year(entry: Dict[str, Any]) -> str:
        def _extract_4digit_year(text: str) -> str:
            for token in text.replace("/", " ").replace("-", " ").split():
                if len(token) == 4 and token.isdigit():
                    return token
            return ""

        cover_date = str(entry.get("prism:coverDate", "")).strip()
        year = _extract_4digit_year(cover_date)
        if year:
            return year
        cover_display = str(entry.get("prism:coverDisplayDate", "")).strip()
        return _extract_4digit_year(cover_display)

    @staticmethod
    def _parse_subject_terms(entry: Dict[str, Any]) -> List[str]:
        terms: List[str] = []
        raw_keywords = entry.get("authkeywords")
        if isinstance(raw_keywords, str):
            for separator in ("|", ";", ","):
                if separator in raw_keywords:
                    terms = [
                        t.strip() for t in raw_keywords.split(separator) if t.strip()
                    ]
                    break
            if not terms and raw_keywords.strip():
                terms = [raw_keywords.strip()]
        return terms

    @staticmethod
    def _parse_authors(entry: Dict[str, Any]) -> str:
        creator = str(entry.get("dc:creator", "")).strip()
        if creator:
            return creator
        author_block = entry.get("author")
        if isinstance(author_block, list):
            names: List[str] = []
            for author in author_block:
                if not isinstance(author, dict):
                    continue
                name = (
                    str(author.get("authname", "")).strip()
                    or str(author.get("preferred-name", "")).strip()
                )
                if name:
                    names.append(name)
            if names:
                return ", ".join(names)
        return "Unknown"

    def _parse_items(
        self, items: List[Dict[str, Any]], query: str
    ) -> List[LiteratureRecord]:
        records: List[LiteratureRecord] = []
        for item in items:
            title = str(item.get("dc:title", "")).strip()
            if not title:
                continue
            authors = self._parse_authors(item)
            doi = str(item.get("prism:doi", "")).strip()
            url = str(item.get("prism:url", "")).strip()
            journal = str(item.get("prism:publicationName", "")).strip()
            year = self._parse_year(item)
            citation_count = item.get("citedby-count")
            try:
                citation_count_int = (
                    int(citation_count) if citation_count is not None else None
                )
            except (TypeError, ValueError):
                citation_count_int = None
            records.append(
                LiteratureRecord(
                    title=title,
                    authors=authors,
                    year=year,
                    doi=doi,
                    source_id=f"scopus:{doi}" if doi else f"scopus:{url or title}",
                    provider="Scopus",
                    journal=journal,
                    url=url,
                    citation_count=citation_count_int,
                    subject_terms=self._parse_subject_terms(item),
                    source_query=query,
                    licence_note="Elsevier Scopus bibliographic metadata",
                )
            )
        return records

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        """Return Scopus API request headers."""
        return {"X-ELS-APIKey": self._api_key, "Accept": "application/json"}

    def _parse_entry(self, entry: Dict[str, Any], query: str) -> LiteratureRecord:
        """Convert a single Scopus search-results entry into a LiteratureRecord.

        Field mapping (Scopus JSON → LiteratureRecord):
          dc:title                → title
          author[].authname       → authors (comma-joined; falls back to dc:creator)
          prism:coverDate[:4]     → year
          prism:doi               → doi
          prism:publicationName   → journal
          prism:url               → url
          citedby-count           → citation_count (transient; Stage 1 filter drops this)
          authkeywords            → subject_terms (pipe-delimited)
          eid                     → source_id prefix

        Abstract and full-text fields are intentionally excluded.
        """
        title = (entry.get("dc:title") or "Unknown Title").strip()

        # Authors: prefer the structured author array; fall back to dc:creator.
        authors_list: List[str] = [
            a.get("authname", "").strip()
            for a in entry.get("author", [])
            if a.get("authname", "").strip()
        ]
        if not authors_list:
            creator = (entry.get("dc:creator") or "").strip()
            if creator:
                authors_list.append(creator)
        authors = ", ".join(authors_list) if authors_list else "Unknown"

        # Year: prism:coverDate is usually "YYYY-MM-DD".
        cover_date = (entry.get("prism:coverDate") or "").strip()
        year = cover_date[:4] if cover_date else ""

        doi = (entry.get("prism:doi") or "").strip()
        journal = (entry.get("prism:publicationName") or "").strip()
        url = (entry.get("prism:url") or "").strip()

        # Citation count (transient — Stage 1 compliance filter drops it from exports).
        citation_count: Optional[int] = None
        raw_count = entry.get("citedby-count")
        if raw_count is not None:
            try:
                citation_count = int(raw_count)
            except (ValueError, TypeError):
                pass

        # Subject terms: authkeywords is pipe-delimited ("ocean | maritime | governance").
        kw_raw = entry.get("authkeywords") or ""
        subject_terms = [k.strip() for k in kw_raw.split("|") if k.strip()]

        eid = (entry.get("eid") or "").strip()
        if doi:
            source_id = f"scopus:{doi}"
        elif eid:
            source_id = f"scopus:{eid}"
        else:
            source_id = f"scopus:{title[:40]}"

        ts = datetime.now(timezone.utc).isoformat()
        return LiteratureRecord(
            title=title,
            authors=authors,
            year=year,
            doi=doi,
            source_id=source_id,
            provider="Scopus",
            journal=journal,
            url=url,
            abstract_available=False,
            abstract_stored=False,
            citation_count=citation_count,
            subject_terms=subject_terms,
            source_query=query,
            retrieval_timestamp=ts,
            licence_note=_LICENCE_NOTE,
        )

    def _parse_entries(
        self, entries: List[Dict[str, Any]], query: str
    ) -> List[LiteratureRecord]:
        """Parse a list of Scopus entry dicts into LiteratureRecord objects.

        Scopus returns a single ``{"error": ...}`` entry when the result set
        is empty — those entries are silently skipped.
        """
        records: List[LiteratureRecord] = []
        for entry in entries:
            if entry.get("error"):
                continue
            records.append(self._parse_entry(entry, query))
        return records

    def _make_evidence(
        self, query: str, endpoint: str, records: List[LiteratureRecord]
    ) -> List[SourceEvidence]:
        """Create provenance evidence entries for a Scopus search call."""
        ts = datetime.now(timezone.utc).isoformat()
        evidence: List[SourceEvidence] = []
        for rec in records:
            raw = f"scopus|{query}|{rec.doi}|{rec.source_id}|{rec.title}|{ts}"
            phash = hashlib.sha256(raw.encode()).hexdigest()[:16]
            evidence.append(
                SourceEvidence(
                    record_id=rec.source_id,
                    source_provider="Scopus",
                    retrieval_mode="live",
                    query=query,
                    api_endpoint_label=endpoint,
                    timestamp=ts,
                    confidence_score=0.9,
                    provenance_hash=phash,
                )
            )
        return evidence

    @staticmethod
    def _redact_url(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            parsed = urllib.parse.urlparse(text)
            if not parsed.scheme or not parsed.netloc:
                return text
            params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            safe_params = [
                (
                    key,
                    "REDACTED" if key.lower() in _REDACTED_QUERY_PARAMS else raw_value,
                )
                for key, raw_value in params
            ]
            return urllib.parse.urlunparse(
                parsed._replace(query=urllib.parse.urlencode(safe_params))
            )
        except Exception:
            return "[url-redacted]"

    @classmethod
    def _safe_entry_envelope(cls, entry: Dict[str, Any]) -> Dict[str, Any]:
        doi = str(entry.get("prism:doi", "") or "").strip()
        url = cls._redact_url(entry.get("prism:url"))
        title = str(entry.get("dc:title", "") or "").strip()
        source_id = str(entry.get("eid", "") or "").strip()
        citation_count: int | None
        raw_citation_count = entry.get("citedby-count")
        try:
            citation_count = (
                int(raw_citation_count) if raw_citation_count is not None else None
            )
        except (TypeError, ValueError):
            citation_count = None
        return {
            "title": title,
            "authors": cls._parse_authors(entry),
            "year": cls._parse_year(entry),
            "doi": doi,
            "journal": str(entry.get("prism:publicationName", "") or "").strip(),
            "url": url,
            "citation_count": citation_count,
            "subject_terms": cls._parse_subject_terms(entry),
            "source_id": f"scopus:{doi}" if doi else f"scopus:{source_id or title}",
        }

    @classmethod
    def _safe_payload_envelope(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        search_results = payload.get("search-results", {})
        if not isinstance(search_results, dict):
            search_results = {}
        entries = search_results.get("entry", [])
        if not isinstance(entries, list):
            entries = []
        return {
            "payload_kind": _SCOPUS_PAYLOAD_KIND,
            "search_results": {
                "total_results": search_results.get("opensearch:totalResults"),
                "start_index": search_results.get("opensearch:startIndex"),
                "items_per_page": search_results.get("opensearch:itemsPerPage"),
                "entries": [
                    cls._safe_entry_envelope(entry)
                    for entry in entries
                    if isinstance(entry, dict)
                ],
            },
        }

    @staticmethod
    def _http_error_result(
        action: str,
        exc: urllib.error.HTTPError,
        *,
        physical_request_count: int = 0,
    ) -> ProviderResult:
        body_snippet = ""
        try:
            body_snippet = exc.read(240).decode("utf-8", errors="ignore").strip()
        except Exception:
            body_snippet = ""
        snippet = f" body={body_snippet[:180]!r}" if body_snippet else ""
        if exc.code == 429:
            return ProviderResult(
                warnings=[f"Scopus {action} rate limited (HTTP 429).{snippet}"],
                rate_limit_status="rate-limited",
                physical_request_count=physical_request_count,
            )
        if exc.code in (401, 403):
            return ProviderResult(
                errors=[f"Scopus {action} unauthorized (HTTP {exc.code}).{snippet}"],
                physical_request_count=physical_request_count,
            )
        return ProviderResult(
            errors=[f"Scopus {action} failed (HTTP {exc.code}).{snippet}"],
            physical_request_count=physical_request_count,
        )

    @staticmethod
    def _pre_network_rejected_result(query: str, error: str) -> ProviderResult:
        """Return a machine-readable zero-attempt result for rejected input."""
        return ProviderResult(
            errors=[error],
            physical_request_count=0,
            page_diagnostics=[
                {
                    "provider": "scopus",
                    "query": query,
                    "logical_page": 0,
                    "physical_request_index": 0,
                    "cursor_or_offset": "",
                    "requested_rows": 0,
                    "returned_rows": 0,
                    "normalized_rows": 0,
                    "pagination_status": "skipped",
                    "errors": error,
                }
            ],
        )

    # ------------------------------------------------------------------
    # Public API (BaseProvider contract)
    # ------------------------------------------------------------------

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Scopus."""
        if not self._api_key:
            return self._not_configured_result()
        projected_query = self._project_protocol_query(query)
        if projected_query is None:
            return self._pre_network_rejected_result(
                query,
                (
                    "Scopus query projection failed: no searchable tokens in "
                    f"query {query!r}. Query rejected to prevent provenance contamination."
                ),
            )
        requested_count = int(max_results)
        applied_count = self._scopus_count(requested_count)
        encoded_query = urllib.parse.quote(projected_query, safe="()")
        url = (
            f"{self._api_base}?query={encoded_query}&count={applied_count}&view=STANDARD"
            f"&field={urllib.parse.quote(_SCOPUS_FIELDS)}"
        )
        physical_request_count = 0
        try:
            physical_request_count += 1
            payload = self._request_json(url)
            items = payload.get("search-results", {}).get("entry", [])
            if not isinstance(items, list):
                items = []
            records = self._parse_items(items, query)
            warnings: List[str] = [
                (
                    f"Scopus diagnostics: projected_query={projected_query!r}; "
                    f"requested_count={requested_count}; applied_count={applied_count}"
                )
            ]
            return ProviderResult(
                records=records,
                warnings=warnings,
                provenance=self._make_evidence(query, "scopus/search", records),
                raw_payload=self._safe_payload_envelope(payload),
                physical_request_count=physical_request_count,
            )
        except urllib.error.HTTPError as exc:
            return self._http_error_result(
                f"search projected_query={projected_query!r}",
                exc,
                physical_request_count=physical_request_count,
            )
        except Exception as exc:
            return ProviderResult(
                errors=[
                    f"Scopus search error: {exc} (projected_query={projected_query!r})"
                ],
                physical_request_count=physical_request_count,
            )

    def search_paginated(
        self,
        query: str,
        *,
        pages: int = 1,
        logical_pages: int | None = None,
        rows_per_page: int = 50,
        sort_strategy: str = "",
        time_window: Dict[str, int] | None = None,
    ) -> Any:
        """Search Scopus using protocol logical pages composed from physical calls."""
        legacy_api = logical_pages is not None
        if not self._api_key:
            result = self._not_configured_result()
            return (result, result.page_diagnostics) if legacy_api else result
        projected_query = self._project_protocol_query(query)
        if projected_query is None:
            result = self._pre_network_rejected_result(
                query,
                (
                    "Scopus query projection failed: no searchable tokens in "
                    f"query {query!r}. Query rejected to prevent provenance contamination."
                ),
            )
            return (result, result.page_diagnostics) if legacy_api else result
        if time_window:
            from_year = int(time_window.get("from_year", 0) or 0)
            to_year = int(time_window.get("to_year", 9999) or 9999)
            year_clauses: List[str] = []
            if from_year > 0:
                year_clauses.append(f"PUBYEAR > {from_year - 1}")
            if to_year < 9999:
                year_clauses.append(f"PUBYEAR < {to_year + 1}")
            if year_clauses:
                projected_query = (
                    f"({projected_query}) AND {' AND '.join(year_clauses)}"
                )
        requested_pages = logical_pages if logical_pages is not None else pages
        safe_pages = max(1, int(requested_pages or 1))
        safe_rows = max(1, int(rows_per_page or 1))
        encoded_query = urllib.parse.quote(projected_query, safe="()")
        field_param = urllib.parse.quote(_SCOPUS_FIELDS)
        sort_clause = ""
        if sort_strategy == "date-desc":
            sort_clause = "&sort=-coverDate"

        records: List[LiteratureRecord] = []
        provenance: List[SourceEvidence] = []
        warnings: List[str] = [
            (
                f"Scopus diagnostics: projected_query={projected_query!r}; "
                f"logical_pages={safe_pages}; rows_per_page={safe_rows}; "
                f"physical_max_count={_SCOPUS_MAX_COUNT}"
            )
        ]
        page_diagnostics: List[Dict[str, Any]] = []
        raw_pages: List[Dict[str, Any]] = []
        physical_request_index = 0
        physical_request_count = 0

        for logical_page in range(1, safe_pages + 1):
            logical_offset = (logical_page - 1) * safe_rows
            page_returned = 0
            page_normalized = 0
            remaining = safe_rows
            chunk_index = 0
            while remaining > 0:
                chunk_index += 1
                physical_request_index += 1
                count = min(_SCOPUS_MAX_COUNT, remaining)
                start = logical_offset + (chunk_index - 1) * _SCOPUS_MAX_COUNT
                url = (
                    f"{self._api_base}?query={encoded_query}&count={count}&start={start}"
                    f"&view=STANDARD&field={field_param}{sort_clause}"
                )
                try:
                    physical_request_count += 1
                    payload = self._request_json(url)
                except urllib.error.HTTPError as exc:
                    result = self._http_error_result(
                        f"search projected_query={projected_query!r}",
                        exc,
                        physical_request_count=physical_request_count,
                    )
                    _pag_status = (
                        "rate_limited"
                        if result.rate_limit_status == "rate-limited"
                        else "failed"
                    )
                    page_diagnostics.append(
                        {
                            "provider": "scopus",
                            "query": query,
                            "logical_page": logical_page,
                            "physical_request_index": physical_request_index,
                            "cursor_or_offset": f"start:{start}",
                            "requested_rows": count,
                            "returned_rows": 0,
                            "normalized_rows": 0,
                            "pagination_status": _pag_status,
                            "rate_limit_status": result.rate_limit_status,
                            "errors": "|".join(result.errors),
                            "warnings": "|".join(result.warnings),
                        }
                    )
                    result.records = records
                    result.provenance = provenance
                    result.page_diagnostics = page_diagnostics
                    result.raw_payload = (
                        {
                            "payload_kind": _SCOPUS_PAYLOAD_KIND,
                            "physical_requests": raw_pages,
                        }
                        if raw_pages
                        else None
                    )
                    result.warnings = warnings + result.warnings
                    if legacy_api:
                        return result, self._legacy_page_diagnostics(
                            page_diagnostics, safe_pages, safe_rows
                        )
                    return result
                except Exception as exc:
                    result = ProviderResult(
                        records=records,
                        errors=[
                            f"Scopus search error: {exc} (projected_query={projected_query!r})"
                        ],
                        warnings=warnings,
                        provenance=provenance,
                        raw_payload=(
                            {
                                "payload_kind": _SCOPUS_PAYLOAD_KIND,
                                "physical_requests": raw_pages,
                            }
                            if raw_pages
                            else None
                        ),
                        page_diagnostics=page_diagnostics,
                        physical_request_count=physical_request_count,
                    )
                    if legacy_api:
                        return result, self._legacy_page_diagnostics(
                            page_diagnostics, safe_pages, safe_rows
                        )
                    return result
                items = payload.get("search-results", {}).get("entry", [])
                if not isinstance(items, list):
                    items = []
                page_records = self._parse_items(items, query)
                records.extend(page_records)
                provenance.extend(
                    self._make_evidence(query, "scopus/search", page_records)
                )
                raw_pages.append(
                    {
                        "logical_page": logical_page,
                        "physical_request_index": physical_request_index,
                        "start": start,
                        "count": count,
                        "payload": self._safe_payload_envelope(payload),
                    }
                )
                page_returned += len(items)
                page_normalized += len(page_records)
                remaining -= count
                status = "applied"
                if len(items) < count:
                    status = "end_of_results"
                page_diagnostics.append(
                    {
                        "provider": "scopus",
                        "query": query,
                        "logical_page": logical_page,
                        "physical_request_index": physical_request_index,
                        "cursor_or_offset": f"start:{start}",
                        "requested_rows": count,
                        "returned_rows": len(items),
                        "normalized_rows": len(page_records),
                        "pagination_status": status,
                    }
                )
                if status == "end_of_results":
                    remaining = 0
                    break
            if page_returned < safe_rows:
                warnings.append(
                    f"Scopus logical_page={logical_page} returned {page_returned}/{safe_rows}; end_of_results"
                )
                break
            if page_normalized == 0:
                warnings.append(
                    f"Scopus logical_page={logical_page} produced zero normalized records"
                )

        result = ProviderResult(
            records=records,
            warnings=warnings,
            provenance=provenance,
            raw_payload={
                "payload_kind": _SCOPUS_PAYLOAD_KIND,
                "physical_requests": raw_pages,
            },
            page_diagnostics=page_diagnostics,
            physical_request_count=physical_request_count,
        )
        if legacy_api:
            return result, self._legacy_page_diagnostics(
                page_diagnostics, safe_pages, safe_rows
            )
        return result

    @staticmethod
    def _legacy_page_diagnostics(
        diagnostics: List[Dict[str, Any]], safe_pages: int, safe_rows: int
    ) -> List[Dict[str, Any]]:
        """Adapt physical diagnostics to the historical logical-page contract."""
        legacy: List[Dict[str, Any]] = []
        for logical_page in range(1, safe_pages + 1):
            entries = [
                row for row in diagnostics if row.get("logical_page") == logical_page
            ]
            if not entries:
                continue
            first = dict(entries[0])
            first["physical_requests"] = len(entries)
            first["returned_rows"] = sum(
                int(row.get("returned_rows", 0) or 0) for row in entries
            )
            first["normalized_rows"] = sum(
                int(row.get("normalized_rows", 0) or 0) for row in entries
            )
            first["requested_rows"] = safe_rows
            first["offset"] = (logical_page - 1) * safe_rows
            first["pagination_method"] = "scopus_offset"
            legacy.append(first)
        return legacy

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify DOI via Scopus."""
        if not self._api_key:
            return self._not_configured_result()
        query = f'DOI("{doi}")'
        encoded_query = urllib.parse.quote(query)
        url = f"{self._api_base}?query={encoded_query}&count=1&view=STANDARD"
        physical_request_count = 0
        try:
            physical_request_count += 1
            payload = self._request_json(url)
            items = payload.get("search-results", {}).get("entry", [])
            if not isinstance(items, list):
                items = []
            records = self._parse_items(items[:1], doi)
            if records:
                records[0].source_query = doi
            return ProviderResult(
                records=records,
                provenance=self._make_evidence(doi, "scopus/search?query=DOI", records),
                raw_payload=self._safe_payload_envelope(payload),
                physical_request_count=physical_request_count,
            )
        except urllib.error.HTTPError as exc:
            return self._http_error_result(
                "DOI verification",
                exc,
                physical_request_count=physical_request_count,
            )
        except Exception as exc:
            return ProviderResult(
                errors=[f"Scopus DOI verification error: {exc}"],
                physical_request_count=physical_request_count,
            )
