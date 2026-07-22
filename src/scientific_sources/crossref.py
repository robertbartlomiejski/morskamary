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
    ) -> tuple[Dict[str, Any] | None, List[str], str | None]:
        warnings: List[str] = []
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            req = urllib.request.Request(url, headers={"User-Agent": self._user_agent()})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                if warnings:
                    warnings.append(
                        f"Crossref retry terminal_status=success attempt={attempt}"
                    )
                return data, warnings, None
            except urllib.error.HTTPError as exc:
                if exc.code != 429:
                    raise
                retry_after = self._retry_after_seconds(exc.headers.get("Retry-After", ""))
                backoff = min(
                    _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                    _MAX_BACKOFF_SECONDS,
                )
                jitter = self._deterministic_jitter_seconds(jitter_seed, attempt)
                wait_seconds = retry_after if retry_after is not None else backoff + jitter
                warnings.append(
                    f"Crossref retry {context_label}: attempt={attempt} http_status=429 "
                    f"retry_after_seconds={retry_after!r} backoff_seconds={round(backoff, 3)} "
                    f"jitter_seconds={round(jitter, 3)} wait_seconds={round(wait_seconds, 3)}"
                )
                if attempt >= _MAX_RETRY_ATTEMPTS:
                    terminal = (
                        f"Crossref {context_label} failed after {_MAX_RETRY_ATTEMPTS} attempts "
                        "(terminal_status=rate_limited)"
                    )
                    return None, warnings, terminal
                time.sleep(max(wait_seconds, 0.0))

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Crossref for records matching *query*."""
        url = (
            f"{_API_BASE}/works"
            f"?query={urllib.parse.quote(query)}"
            f"&select=title,author,URL,DOI,published,container-title,subject"
            f"&rows={max_results}"
        )
        try:
            data, retry_warnings, terminal_error = self._request_json_with_backoff(
                url=url,
                context_label="search",
                jitter_seed=query,
            )
            if terminal_error:
                return ProviderResult(
                    errors=[terminal_error],
                    warnings=retry_warnings,
                    rate_limit_status="rate-limited",
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
            )
        except Exception as exc:
            return ProviderResult(errors=[f"Crossref search error: {exc}"])

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify a specific DOI via Crossref."""
        url = f"{_API_BASE}/works/{urllib.parse.quote(doi)}"
        try:
            data, retry_warnings, terminal_error = self._request_json_with_backoff(
                url=url,
                context_label="DOI verification",
                jitter_seed=doi,
            )
            if terminal_error:
                return ProviderResult(
                    errors=[terminal_error],
                    warnings=retry_warnings,
                    rate_limit_status="rate-limited",
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
            )
        except Exception as exc:
            return ProviderResult(errors=[f"Crossref DOI verification error: {exc}"])
