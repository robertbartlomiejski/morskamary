"""
Elsevier / Scopus provider.

Requires ELSEVIER_API_KEY and/or SCOPUS_API_KEY.
Returns a structured "not configured" result when key is absent.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
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
    "citation_count",
    "subject_terms",
    "source_id",
    "provider",
    "source_query",
    "retrieval_timestamp",
]


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
            return json.loads(resp.read().decode())

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
                    terms = [t.strip() for t in raw_keywords.split(separator) if t.strip()]
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

    def _parse_items(self, items: List[Dict[str, Any]], query: str) -> List[LiteratureRecord]:
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
                citation_count_int = int(citation_count) if citation_count is not None else None
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

    def _make_evidence(
        self, query: str, endpoint: str, records: List[LiteratureRecord]
    ) -> List[SourceEvidence]:
        ts = datetime.now(timezone.utc).isoformat()
        evidence: List[SourceEvidence] = []
        for rec in records:
            raw = f"scopus|{query}|{rec.doi}|{ts}"
            evidence.append(
                SourceEvidence(
                    record_id=rec.source_id,
                    source_provider="Scopus",
                    retrieval_mode="live",
                    query=query,
                    api_endpoint_label=endpoint,
                    timestamp=ts,
                    confidence_score=0.85,
                    provenance_hash=hashlib.sha256(raw.encode()).hexdigest()[:16],
                )
            )
        return evidence

    @staticmethod
    def _http_error_result(action: str, exc: urllib.error.HTTPError) -> ProviderResult:
        if exc.code == 429:
            return ProviderResult(
                warnings=[f"Scopus {action} rate limited (HTTP 429)."],
                rate_limit_status="rate-limited",
            )
        if exc.code in (401, 403):
            return ProviderResult(errors=[f"Scopus {action} unauthorized (HTTP {exc.code})."])
        return ProviderResult(errors=[f"Scopus {action} failed (HTTP {exc.code})."])

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Scopus."""
        if not self._api_key:
            return self._not_configured_result()
        encoded_query = urllib.parse.quote(query)
        url = f"{self._api_base}?query={encoded_query}&count={max_results}&view=STANDARD"
        try:
            payload = self._request_json(url)
            items = payload.get("search-results", {}).get("entry", [])
            if not isinstance(items, list):
                items = []
            records = self._parse_items(items, query)
            return ProviderResult(
                records=records,
                provenance=self._make_evidence(query, "scopus/search", records),
            )
        except urllib.error.HTTPError as exc:
            return self._http_error_result("search", exc)
        except Exception as exc:
            return ProviderResult(errors=[f"Scopus search error: {exc}"])

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify DOI via Scopus."""
        if not self._api_key:
            return self._not_configured_result()
        query = f'DOI("{doi}")'
        encoded_query = urllib.parse.quote(query)
        url = f"{self._api_base}?query={encoded_query}&count=1&view=STANDARD"
        try:
            payload = self._request_json(url)
            items = payload.get("search-results", {}).get("entry", [])
            if not isinstance(items, list):
                items = []
            records = self._parse_items(items[:1], doi)
            if records:
                records[0].source_query = doi
            return ProviderResult(
                records=records,
                provenance=self._make_evidence(
                    doi, "scopus/search?query=DOI", records
                ),
            )
        except urllib.error.HTTPError as exc:
            return self._http_error_result("DOI verification", exc)
        except Exception as exc:
            return ProviderResult(errors=[f"Scopus DOI verification error: {exc}"])
