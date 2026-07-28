"""OpenAlex provider with licence-safe retained metadata envelopes.

Requires ``OPENALEX_API_KEY``. OpenAlex is used as a low-cost bibliographic
retrieval provider, not as proof of upstream independence from Crossref or
other metadata infrastructures. Normalised records may report whether an
abstract exists, but reconstructable abstract inverted-index content is never
persisted in ``ProviderResult.raw_payload``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
_OPENALEX_API_BASE = "https://api.openalex.org/works"
_MAX_RETRY_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 1.0
_MAX_RETRY_AFTER_SECONDS = 60.0
_TRANSIENT_SERVER_HTTP_STATUSES = {500, 502, 503}
_PAYLOAD_KIND = "redistribution_safe_metadata_envelope"
_LICENCE_NOTE = (
    "OpenAlex bibliographic metadata and topic labels. OpenAlex improves "
    "acquisition-provider diversity but is not upstream-independent from all DOI "
    "metadata infrastructures. Abstract inverted-index content is not stored."
)


class OpenAlexProvider(BaseProvider):
    """OpenAlex works API provider."""

    def __init__(self) -> None:
        self._api_key: str = os.getenv("OPENALEX_API_KEY", "")
        self._api_base = _OPENALEX_API_BASE

    @property
    def capability(self) -> SourceCapability:
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        return SourceCapability(
            name="openalex",
            provider="OpenAlex",
            requires_secret=True,
            configured=bool(self._api_key),
            live_test_allowed=live and bool(self._api_key),
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=_LICENCE_NOTE,
        )

    @staticmethod
    def _retry_after_seconds(raw_retry_after: str) -> float | None:
        value = str(raw_retry_after or "").strip()
        if not value:
            return None
        if value.isdigit():
            return min(float(value), _MAX_RETRY_AFTER_SECONDS)
        try:
            retry_after_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        now = datetime.now(timezone.utc)
        if retry_after_at.tzinfo is None:
            retry_after_at = retry_after_at.replace(tzinfo=timezone.utc)
        delta = (retry_after_at - now).total_seconds()
        if delta <= 0:
            return 0.0
        return min(delta, _MAX_RETRY_AFTER_SECONDS)

    @staticmethod
    def _cursor_marker(cursor: str) -> str:
        if cursor == "*":
            return "*"
        digest = hashlib.sha256(cursor.encode("utf-8")).hexdigest()[:16]
        return f"sha256:{digest}"

    @staticmethod
    def _normalize_doi(raw_doi: Any) -> str:
        value = str(raw_doi or "").strip()
        value = value.removeprefix("https://doi.org/").removeprefix(
            "http://doi.org/"
        )
        return value.lower()

    @staticmethod
    def _extract_authors(work: Dict[str, Any]) -> str:
        names: List[str] = []
        authorships = work.get("authorships", [])
        if isinstance(authorships, list):
            for authorship in authorships:
                if not isinstance(authorship, dict):
                    continue
                author = authorship.get("author", {})
                if isinstance(author, dict):
                    name = str(author.get("display_name", "")).strip()
                    if name:
                        names.append(name)
        return ", ".join(names) if names else "Unknown"

    @staticmethod
    def _extract_source(work: Dict[str, Any]) -> str:
        primary_location = work.get("primary_location", {})
        if isinstance(primary_location, dict):
            source = primary_location.get("source", {})
            if isinstance(source, dict):
                display_name = str(source.get("display_name", "")).strip()
                if display_name:
                    return display_name
        host_venue = work.get("host_venue", {})
        if isinstance(host_venue, dict):
            display_name = str(host_venue.get("display_name", "")).strip()
            if display_name:
                return display_name
        return ""

    @staticmethod
    def _extract_url(work: Dict[str, Any]) -> str:
        for key in ("doi", "id"):
            value = str(work.get(key, "")).strip()
            if value:
                return value
        return ""

    @staticmethod
    def _extract_subject_terms(work: Dict[str, Any]) -> List[str]:
        terms: List[str] = []
        for field_name in ("topics", "keywords", "concepts"):
            raw_items = work.get(field_name, [])
            if not isinstance(raw_items, list):
                continue
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                label = str(
                    item.get("display_name", "") or item.get("keyword", "")
                ).strip()
                if label:
                    terms.append(label)
        return list(dict.fromkeys(terms))

    @classmethod
    def _safe_work_envelope(cls, work: Dict[str, Any]) -> Dict[str, Any]:
        """Return only redistribution-safe bibliographic fields.

        The boolean ``abstract_available`` is retained, but the reconstructable
        ``abstract_inverted_index`` object is deliberately excluded.
        """

        return {
            "id": str(work.get("id", "") or ""),
            "display_name": str(work.get("display_name", "") or ""),
            "title": str(work.get("title", "") or ""),
            "publication_year": work.get("publication_year"),
            "publication_date": str(work.get("publication_date", "") or ""),
            "doi": str(work.get("doi", "") or ""),
            "authors": cls._extract_authors(work),
            "source": cls._extract_source(work),
            "url": cls._extract_url(work),
            "cited_by_count": work.get("cited_by_count"),
            "subject_terms": cls._extract_subject_terms(work),
            "abstract_available": bool(work.get("abstract_inverted_index")),
        }

    @classmethod
    def _safe_payload_envelope(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        meta = payload.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        next_cursor = str(meta.get("next_cursor", "") or "")
        results = payload.get("results", [])
        if not isinstance(results, list):
            results = []
        return {
            "payload_kind": _PAYLOAD_KIND,
            "meta": {
                "count": meta.get("count"),
                "next_cursor_marker": (
                    cls._cursor_marker(next_cursor) if next_cursor else ""
                ),
            },
            "results": [
                cls._safe_work_envelope(item)
                for item in results
                if isinstance(item, dict)
            ],
        }

    def _parse_items(
        self,
        items: List[Dict[str, Any]],
        query: str,
    ) -> List[LiteratureRecord]:
        records: List[LiteratureRecord] = []
        for item in items:
            title = str(
                item.get("title", "") or item.get("display_name", "")
            ).strip()
            if not title:
                continue
            doi = self._normalize_doi(item.get("doi"))
            source_id_raw = str(item.get("id", "")).strip()
            year = str(item.get("publication_year", "") or "").strip()
            raw_citation_count = item.get("cited_by_count")
            try:
                citation_count: Optional[int] = (
                    int(raw_citation_count)
                    if raw_citation_count is not None
                    else None
                )
            except (TypeError, ValueError):
                citation_count = None
            source_id = (
                f"openalex:{doi}"
                if doi
                else f"openalex:{source_id_raw or title}"
            )
            records.append(
                LiteratureRecord(
                    title=title,
                    authors=self._extract_authors(item),
                    year=year,
                    doi=doi,
                    source_id=source_id,
                    provider="OpenAlex",
                    journal=self._extract_source(item),
                    url=self._extract_url(item),
                    abstract_available=bool(item.get("abstract_inverted_index")),
                    abstract_stored=False,
                    citation_count=citation_count,
                    subject_terms=self._extract_subject_terms(item),
                    source_query=query,
                    licence_note=_LICENCE_NOTE,
                )
            )
        return records

    def _make_evidence(
        self,
        query: str,
        endpoint: str,
        records: List[LiteratureRecord],
    ) -> List[SourceEvidence]:
        ts = datetime.now(timezone.utc).isoformat()
        evidence: List[SourceEvidence] = []
        for record in records:
            raw = (
                f"openalex|{query}|{record.doi}|{record.source_id}|"
                f"{record.title}|{ts}"
            )
            evidence.append(
                SourceEvidence(
                    record_id=record.source_id,
                    source_provider="OpenAlex",
                    retrieval_mode="live",
                    query=query,
                    api_endpoint_label=endpoint,
                    timestamp=ts,
                    confidence_score=0.9,
                    provenance_hash=hashlib.sha256(raw.encode()).hexdigest()[:16],
                )
            )
        return evidence

    def _request_json(self, url: str) -> Dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "morskamary-openalex-provider/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
        return cast(Dict[str, Any], payload)

    def _request_json_with_backoff(
        self,
        *,
        url: str,
        context_label: str,
    ) -> tuple[Dict[str, Any] | None, List[str], str | None, str | None]:
        warnings: List[str] = []
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            try:
                return self._request_json(url), warnings, None, None
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    retry_after = self._retry_after_seconds(
                        exc.headers.get("Retry-After", "") if exc.headers else ""
                    )
                    wait_seconds = (
                        retry_after
                        if retry_after is not None
                        else _BASE_BACKOFF_SECONDS * attempt
                    )
                    warnings.append(
                        "OpenAlex retry "
                        f"{context_label}: attempt={attempt} http_status=429 "
                        f"wait_seconds={round(wait_seconds, 3)}"
                    )
                    if attempt >= _MAX_RETRY_ATTEMPTS:
                        return (
                            None,
                            warnings,
                            "OpenAlex rate limited after retries",
                            "rate-limited",
                        )
                    time.sleep(max(wait_seconds, 0.0))
                    continue
                if exc.code not in _TRANSIENT_SERVER_HTTP_STATUSES:
                    return (
                        None,
                        warnings,
                        f"OpenAlex {context_label} failed (HTTP {exc.code})",
                        None,
                    )
                wait_seconds = _BASE_BACKOFF_SECONDS * attempt
                warnings.append(
                    "OpenAlex retry "
                    f"{context_label}: attempt={attempt} http_status={exc.code} "
                    f"wait_seconds={round(wait_seconds, 3)}"
                )
                if attempt >= _MAX_RETRY_ATTEMPTS:
                    return (
                        None,
                        warnings,
                        f"OpenAlex {context_label} failed after retries "
                        f"(HTTP {exc.code})",
                        None,
                    )
                time.sleep(max(wait_seconds, 0.0))
            except Exception as exc:  # pragma: no cover - provider boundary
                return (
                    None,
                    warnings,
                    f"OpenAlex {context_label} error: {exc}",
                    None,
                )
        return None, warnings, "OpenAlex retry loop exhausted", "rate-limited"

    @staticmethod
    def _time_window_filter(time_window: Dict[str, int] | None) -> str:
        if not time_window:
            return ""
        from_year = int(time_window.get("from_year", 0) or 0)
        to_year = int(time_window.get("to_year", 0) or 0)
        filters: List[str] = []
        if from_year:
            filters.append(f"from_publication_date:{from_year}-01-01")
        if to_year:
            filters.append(f"to_publication_date:{to_year}-12-31")
        return ",".join(filters)

    def _build_works_url(
        self,
        *,
        query: str,
        per_page: int,
        cursor: str,
        sort_strategy: str,
        time_window: Dict[str, int] | None,
    ) -> str:
        params: Dict[str, str] = {
            "api_key": self._api_key,
            "search": query,
            "per_page": str(per_page),
            "cursor": cursor,
        }
        filter_value = self._time_window_filter(time_window)
        if filter_value:
            params["filter"] = filter_value
        if sort_strategy in {"published-desc", "date-desc"}:
            params["sort"] = "publication_date:desc,relevance_score:desc"
        return f"{self._api_base}?{urllib.parse.urlencode(params)}"

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        if not self._api_key:
            return self._not_configured_result()
        return cast(
            ProviderResult,
            self.search_paginated(
                query,
                pages=1,
                rows_per_page=max_results,
                sort_strategy="date-desc",
                time_window=None,
            ),
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
        if not self._api_key:
            result = self._not_configured_result()
            return (
                (result, result.page_diagnostics)
                if logical_pages is not None
                else result
            )
        requested_pages = logical_pages if logical_pages is not None else pages
        safe_pages = max(1, int(requested_pages or 1))
        legacy_api = logical_pages is not None
        safe_rows = max(1, min(int(rows_per_page or 1), 100))
        cursor = "*"
        records: List[LiteratureRecord] = []
        provenance: List[SourceEvidence] = []
        warnings: List[str] = []
        page_diagnostics: List[Dict[str, Any]] = []
        retained_pages: List[Dict[str, Any]] = []

        for logical_page in range(1, safe_pages + 1):
            url = self._build_works_url(
                query=query,
                per_page=safe_rows,
                cursor=cursor,
                sort_strategy=sort_strategy,
                time_window=time_window,
            )
            payload, retry_warnings, terminal_error, rate_status = (
                self._request_json_with_backoff(
                    url=url,
                    context_label=f"search page {logical_page}",
                )
            )
            warnings.extend(retry_warnings)
            if terminal_error:
                page_diagnostics.append(
                    {
                        "provider": "openalex",
                        "query": query,
                        "logical_page": logical_page,
                        "physical_request_index": logical_page,
                        "cursor_or_offset": self._cursor_marker(cursor),
                        "requested_rows": safe_rows,
                        "returned_rows": 0,
                        "normalized_rows": 0,
                        "pagination_status": "failed",
                        "errors": terminal_error,
                    }
                )
                result = ProviderResult(
                    records=records,
                    errors=[terminal_error],
                    warnings=warnings,
                    rate_limit_status=rate_status,
                    provenance=provenance,
                    raw_payload=(
                        {"payload_kind": _PAYLOAD_KIND, "pages": retained_pages}
                        if retained_pages
                        else None
                    ),
                    page_diagnostics=page_diagnostics,
                )
                return (result, page_diagnostics) if legacy_api else result

            assert payload is not None
            items = payload.get("results", [])
            if not isinstance(items, list):
                items = []
            page_records = self._parse_items(
                [item for item in items if isinstance(item, dict)], query
            )
            records.extend(page_records)
            provenance.extend(
                self._make_evidence(query, "openalex/works", page_records)
            )
            retained_pages.append(
                {
                    "logical_page": logical_page,
                    "payload": self._safe_payload_envelope(payload),
                }
            )
            meta = payload.get("meta", {})
            if not isinstance(meta, dict):
                meta = {}
            next_cursor = str(meta.get("next_cursor", "") or "").strip()
            status = "end_of_results" if len(items) < safe_rows else "applied"
            page_diagnostics.append(
                {
                    "provider": "openalex",
                    "query": query,
                    "logical_page": logical_page,
                    "physical_request_index": logical_page,
                    "cursor_or_offset": self._cursor_marker(cursor),
                    "requested_rows": safe_rows,
                    "returned_rows": len(items),
                    "normalized_rows": len(page_records),
                    "pagination_status": status,
                }
            )
            if status == "end_of_results":
                break
            if not next_cursor or next_cursor == cursor:
                warnings.append(
                    "OpenAlex cursor pagination stopped: "
                    "missing_or_repeated_next_cursor"
                )
                break
            cursor = next_cursor

        result = ProviderResult(
            records=records,
            warnings=warnings,
            provenance=provenance,
            raw_payload={
                "payload_kind": _PAYLOAD_KIND,
                "pages": retained_pages,
            },
            page_diagnostics=page_diagnostics,
        )
        return (result, page_diagnostics) if legacy_api else result

    def verify_doi(self, doi: str) -> ProviderResult:
        if not self._api_key:
            return self._not_configured_result()
        normalized = self._normalize_doi(doi)
        url = (
            f"{self._api_base}/doi:{urllib.parse.quote(normalized)}"
            f"?api_key={urllib.parse.quote(self._api_key)}"
        )
        payload, warnings, terminal_error, rate_status = (
            self._request_json_with_backoff(
                url=url,
                context_label="DOI verification",
            )
        )
        if terminal_error:
            return ProviderResult(
                errors=[terminal_error],
                warnings=warnings,
                rate_limit_status=rate_status,
            )
        assert payload is not None
        records = self._parse_items([payload], doi)
        if records:
            records[0].source_query = doi
        return ProviderResult(
            records=records[:1],
            warnings=warnings,
            provenance=self._make_evidence(
                doi, "openalex/works/doi", records[:1]
            ),
            raw_payload={
                "payload_kind": _PAYLOAD_KIND,
                "payload": self._safe_work_envelope(payload),
            },
        )
