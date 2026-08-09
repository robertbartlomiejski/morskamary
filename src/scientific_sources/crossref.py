"""
Crossref provider — the default open-access metadata source.

Uses the Crossref public REST API (no key required, but a contact email
in the User-Agent header is strongly recommended via CROSSREF_MAILTO).

Crossref data is open; DOI, title, author, journal, year, and URL may be
stored freely.  Abstracts are not returned by default from Crossref works
and must not be fabricated.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List

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
    "source_id",
    "provider",
    "source_query",
    "retrieval_timestamp",
]

_API_BASE = "https://api.crossref.org"
_MAX_RETRY_ATTEMPTS = 4
_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0
_MAX_RETRY_AFTER_SECONDS = 120.0
_TRANSIENT_SERVER_HTTP_STATUSES = frozenset({500, 502, 503, 504})


class CrossrefProvider(BaseProvider):
    """Crossref REST API provider (no key required)."""

    def __init__(self) -> None:
        self._mailto: str = os.getenv("CROSSREF_MAILTO", "")

    @property
    def capability(self) -> SourceCapability:
        """Return capability descriptor for Crossref."""
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        return SourceCapability(
            name="crossref",
            provider="Crossref",
            requires_secret=False,
            configured=True,
            live_test_allowed=live,
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=(
                "Crossref metadata is freely redistributable. "
                "Do not store restricted publisher full-text."
            ),
        )

    def _user_agent(self) -> str:
        """Build a polite User-Agent string."""
        base = (
            "morskamary-scientific-bridge/1.0 "
            "(https://github.com/robertbartlomiejski/morskamary"
        )
        if self._mailto:
            base += f"; mailto:{self._mailto}"
        return base + ")"

    @staticmethod
    def _clean_abstract(raw_abstract: Any) -> str:
        """Return normalized plain-text abstract from Crossref/JATS payload."""
        if not raw_abstract:
            return ""
        text = str(raw_abstract)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _parse_items(
        self, items: List[Dict[str, Any]], query: str
    ) -> List[LiteratureRecord]:
        """Convert raw Crossref items into LiteratureRecord objects."""
        records: List[LiteratureRecord] = []
        for item in items:
            authors_list: List[str] = []
            for author in item.get("author", []):
                family = author.get("family", "")
                given = author.get("given", "")
                if family:
                    authors_list.append(f"{given} {family}".strip())

            title_list = item.get("title", [])
            title = title_list[0] if title_list else "Unknown Title"

            container = item.get("container-title", [])
            journal = container[0] if container else ""

            published = item.get("published", {})
            year = ""
            if "date-parts" in published:
                parts = published["date-parts"][0]
                if parts:
                    year = str(parts[0])

            doi = item.get("DOI", "")
            url = item.get("URL", "")
            subject_terms = item.get("subject", [])
            if not isinstance(subject_terms, list):
                subject_terms = [str(subject_terms)] if subject_terms else []

            records.append(
                LiteratureRecord(
                    title=title,
                    authors=", ".join(authors_list) if authors_list else "Unknown",
                    year=year,
                    doi=doi,
                    source_id=f"crossref:{doi}" if doi else f"crossref:{url}",
                    provider="Crossref",
                    journal=journal,
                    url=url,
                    abstract="",
                    abstract_available=False,
                    abstract_stored=False,
                    subject_terms=[
                        str(term).strip() for term in subject_terms if str(term).strip()
                    ],
                    source_query=query,
                    licence_note="Crossref open metadata",
                )
            )
        return records

    def _make_evidence(
        self,
        query: str,
        endpoint: str,
        records: List[LiteratureRecord],
        mode: str = "live",
    ) -> List[SourceEvidence]:
        """Create provenance evidence entries for a search call."""
        ts = datetime.now(timezone.utc).isoformat()
        evidence: List[SourceEvidence] = []
        for rec in records:
            raw = f"crossref|{query}|{rec.doi}|{ts}"
            phash = hashlib.sha256(raw.encode()).hexdigest()[:16]
            evidence.append(
                SourceEvidence(
                    record_id=rec.source_id,
                    source_provider="Crossref",
                    retrieval_mode=mode,
                    query=query,
                    api_endpoint_label=endpoint,
                    timestamp=ts,
                    confidence_score=0.9,
                    provenance_hash=phash,
                )
            )
        return evidence

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
    def _deterministic_jitter_seconds(seed: str, attempt: int) -> float:
        digest = hashlib.sha256(f"{seed}|{attempt}".encode("utf-8")).hexdigest()
        jitter_unit = int(digest[:6], 16) / float(0xFFFFFF)
        return round(jitter_unit * 0.5, 3)

    def _request_json_with_backoff(
        self,
        *,
        url: str,
        context_label: str,
        jitter_seed: str,
    ) -> tuple[Dict[str, Any] | None, List[str], str | None, int]:
        """Fetch JSON with bounded retry and exact physical-attempt accounting."""
        warnings: List[str] = []
        physical_request_count = 0
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": self._user_agent()}
                )
                # Count immediately before urlopen so response-read, timeout, and
                # transport failures are retained as initiated HTTP attempts.
                physical_request_count += 1
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                if warnings:
                    warnings.append(
                        f"Crossref retry terminal_status=success attempt={attempt}"
                    )
                return data, warnings, None, physical_request_count
            except urllib.error.HTTPError as exc:
                if (
                    exc.code != 429
                    and exc.code not in _TRANSIENT_SERVER_HTTP_STATUSES
                ):
                    body_snippet = ""
                    try:
                        body_snippet = exc.read(240).decode(
                            "utf-8", errors="ignore"
                        ).strip()
                    except Exception:
                        body_snippet = ""
                    snippet = f" body={body_snippet[:180]!r}" if body_snippet else ""
                    terminal = (
                        f"Crossref {context_label} failed after attempt={attempt} "
                        f"(terminal_status=http_{exc.code}).{snippet}"
                    )
                    return None, warnings, terminal, physical_request_count
                retry_after_header = ""
                if exc.code == 429 and exc.headers:
                    retry_after_header = exc.headers.get("Retry-After", "")
                retry_after = self._retry_after_seconds(retry_after_header)
                backoff = min(
                    _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                    _MAX_BACKOFF_SECONDS,
                )
                jitter = self._deterministic_jitter_seconds(jitter_seed, attempt)
                wait_seconds = retry_after if retry_after is not None else backoff + jitter
                warnings.append(
                    f"Crossref retry {context_label}: attempt={attempt} http_status={exc.code} "
                    f"retry_after_seconds={retry_after!r} backoff_seconds={round(backoff, 3)} "
                    f"jitter_seconds={round(jitter, 3)} wait_seconds={round(wait_seconds, 3)}"
                )
                if attempt >= _MAX_RETRY_ATTEMPTS:
                    terminal_status = (
                        "rate_limited" if exc.code == 429 else f"http_{exc.code}"
                    )
                    terminal = (
                        f"Crossref {context_label} failed after {_MAX_RETRY_ATTEMPTS} attempts "
                        f"(terminal_status={terminal_status})"
                    )
                    return None, warnings, terminal, physical_request_count
                time.sleep(max(wait_seconds, 0.0))
            except (
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                OSError,
            ) as exc:
                backoff = min(
                    _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                    _MAX_BACKOFF_SECONDS,
                )
                jitter = self._deterministic_jitter_seconds(jitter_seed, attempt)
                wait_seconds = backoff + jitter
                warnings.append(
                    f"Crossref retry {context_label}: attempt={attempt} "
                    f"transport_error={type(exc).__name__} "
                    f"backoff_seconds={round(backoff, 3)} "
                    f"jitter_seconds={round(jitter, 3)} "
                    f"wait_seconds={round(wait_seconds, 3)}"
                )
                if attempt >= _MAX_RETRY_ATTEMPTS:
                    terminal = (
                        f"Crossref {context_label} failed after {_MAX_RETRY_ATTEMPTS} attempts "
                        "(terminal_status=transport_error)"
                    )
                    return None, warnings, terminal, physical_request_count
                time.sleep(max(wait_seconds, 0.0))
            except Exception:
                terminal = (
                    f"Crossref {context_label} failed after attempt={attempt} "
                    "(terminal_status=unexpected_error)"
                )
                return None, warnings, terminal, physical_request_count
        return None, warnings, (
            f"Crossref {context_label} failed after {_MAX_RETRY_ATTEMPTS} attempts "
            "(terminal_status=rate_limited)"
        ), physical_request_count

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Crossref for records matching *query*."""
        url = (
            f"{_API_BASE}/works"
            f"?query={urllib.parse.quote(query)}"
            f"&select=title,author,URL,DOI,published,container-title,subject"
            f"&rows={max_results}"
        )
        physical_request_count = 0
        try:
            (
                data,
                retry_warnings,
                terminal_error,
                physical_request_count,
            ) = self._request_json_with_backoff(
                url=url,
                context_label="search",
                jitter_seed=query,
            )
            if terminal_error:
                rate_limit_status = (
                    "rate-limited" if "terminal_status=rate_limited" in terminal_error else None
                )
                return ProviderResult(
                    errors=[terminal_error],
                    warnings=retry_warnings,
                    rate_limit_status=rate_limit_status,
                    physical_request_count=physical_request_count,
                )
            assert data is not None
            items = data.get("message", {}).get("items", [])
            records = self._parse_items(items, query)
            evidence = self._make_evidence(query, "crossref/works", records)
            return ProviderResult(
                records=records,
                warnings=retry_warnings,
                provenance=evidence,
                raw_payload=data,
                physical_request_count=physical_request_count,
            )
        except Exception as exc:
            return ProviderResult(
                errors=[f"Crossref search error: {exc}"],
                physical_request_count=physical_request_count,
            )

    @staticmethod
    def _cursor_marker(cursor: str) -> str:
        """Return a compact persisted marker for a Crossref cursor token."""
        if cursor == "*":
            return "*"
        digest = hashlib.sha256(cursor.encode("utf-8")).hexdigest()[:16]
        return f"sha256:{digest}"

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
        """Search Crossref using provider cursor paging."""
        legacy_api = logical_pages is not None
        requested_pages = logical_pages if logical_pages is not None else pages
        safe_pages = max(1, int(requested_pages or 1))
        safe_rows = max(1, min(int(rows_per_page or 1), 1000))
        cursor = "*"
        records: List[LiteratureRecord] = []
        provenance: List[SourceEvidence] = []
        warnings: List[str] = []
        page_diagnostics: List[Dict[str, Any]] = []
        raw_pages: List[Dict[str, Any]] = []
        physical_request_count = 0
        sort_clause = ""
        if sort_strategy == "published-desc":
            sort_clause = "&sort=published&order=desc"

        for logical_page in range(1, safe_pages + 1):
            endpoint = "crossref/works?offset" if legacy_api else "crossref/works?cursor"
            offset = (logical_page - 1) * safe_rows
            page_clause = (
                f"&offset={offset}"
                if legacy_api
                else f"&cursor={urllib.parse.quote(cursor, safe='')}"
            )
            url = (
                f"{_API_BASE}/works"
                f"?query={urllib.parse.quote(query)}"
                f"&select=title,author,URL,DOI,published,container-title,subject"
                f"&rows={safe_rows}"
                f"{page_clause}"
                f"{sort_clause}"
            )
            if time_window:
                from_year = int(time_window.get("from_year", 0) or 0)
                to_year = int(time_window.get("to_year", 9999) or 9999)
                filters: List[str] = []
                if from_year > 0:
                    filters.append(f"from-pub-date:{from_year:04d}-01-01")
                if to_year < 9999:
                    filters.append(f"until-pub-date:{to_year:04d}-12-31")
                if filters:
                    url += f"&filter={urllib.parse.quote(','.join(filters), safe=':,')}"
            (
                data,
                retry_warnings,
                terminal_error,
                page_physical_request_count,
            ) = self._request_json_with_backoff(
                url=url,
                context_label=f"search page {logical_page}",
                jitter_seed=f"{query}|{logical_page}",
            )
            physical_request_count += page_physical_request_count
            warnings.extend(retry_warnings)
            if terminal_error:
                rate_limit_status = (
                    "rate-limited" if "terminal_status=rate_limited" in terminal_error else None
                )
                page_diagnostics.append(
                    {
                        "provider": "crossref",
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
                    rate_limit_status=rate_limit_status,
                    provenance=provenance,
                    raw_payload={"pages": raw_pages} if raw_pages else None,
                    page_diagnostics=page_diagnostics,
                    physical_request_count=physical_request_count,
                )
                if legacy_api:
                    return result, page_diagnostics
                return result
            assert data is not None
            message = data.get("message", {})
            items = message.get("items", [])
            if not isinstance(items, list):
                items = []
            page_records = self._parse_items(items, query)
            records.extend(page_records)
            provenance.extend(self._make_evidence(query, endpoint, page_records))
            raw_pages.append({"logical_page": logical_page, "payload": data})
            next_cursor = str(message.get("next-cursor", "") or "").strip()
            status = "applied"
            if len(items) < safe_rows:
                status = "end_of_results"
            diagnostic = {
                "provider": "crossref",
                "query": query,
                "logical_page": logical_page,
                "physical_request_index": logical_page,
                "cursor_or_offset": str(offset) if legacy_api else self._cursor_marker(cursor),
                "requested_rows": safe_rows,
                "returned_rows": len(items),
                "normalized_rows": len(page_records),
                "pagination_status": status,
            }
            if legacy_api:
                diagnostic["offset"] = offset
                diagnostic["pagination_method"] = "crossref_offset"
            page_diagnostics.append(diagnostic)
            if status == "end_of_results":
                break
            if legacy_api:
                continue
            if not next_cursor or next_cursor == cursor:
                warnings.append("Crossref cursor pagination stopped: missing_or_repeated_next_cursor")
                break
            cursor = next_cursor

        result = ProviderResult(
            records=records,
            warnings=warnings,
            provenance=provenance,
            raw_payload={"pages": raw_pages},
            page_diagnostics=page_diagnostics,
            physical_request_count=physical_request_count,
        )
        if legacy_api:
            return result, page_diagnostics
        return result

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify a specific DOI via Crossref."""
        url = f"{_API_BASE}/works/{urllib.parse.quote(doi)}"
        physical_request_count = 0
        try:
            (
                data,
                retry_warnings,
                terminal_error,
                physical_request_count,
            ) = self._request_json_with_backoff(
                url=url,
                context_label="DOI verification",
                jitter_seed=doi,
            )
            if terminal_error:
                rate_limit_status = (
                    "rate-limited" if "terminal_status=rate_limited" in terminal_error else None
                )
                return ProviderResult(
                    errors=[terminal_error],
                    warnings=retry_warnings,
                    rate_limit_status=rate_limit_status,
                    physical_request_count=physical_request_count,
                )
            assert data is not None
            item = data.get("message", {})
            records = self._parse_items([item], doi)
            evidence = self._make_evidence(doi, f"crossref/works/{doi}", records)
            return ProviderResult(
                records=records,
                warnings=retry_warnings,
                provenance=evidence,
                raw_payload=data,
                physical_request_count=physical_request_count,
            )
        except Exception as exc:
            return ProviderResult(
                errors=[f"Crossref DOI verification error: {exc}"],
                physical_request_count=physical_request_count,
            )
