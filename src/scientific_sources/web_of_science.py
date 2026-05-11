"""
Web of Science (Clarivate) provider.

Requires WOS_API_KEY.
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


class WebOfScienceProvider(BaseProvider):
    """Web of Science provider."""

    def __init__(self) -> None:
        self._api_key: str = os.getenv("WOS_API_KEY", "")
        self._api_base = "https://api.clarivate.com/apis/wos-starter/v1/documents"

    @property
    def capability(self) -> SourceCapability:
        """Return capability descriptor for Web of Science."""
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        return SourceCapability(
            name="wos",
            provider="Web of Science (Clarivate)",
            requires_secret=True,
            configured=bool(self._api_key),
            live_test_allowed=live and bool(self._api_key),
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=(
                "Store only permitted bibliographic fields; "
                "do not store full WoS database payloads."
            ),
        )

    def _request_json(self, url: str) -> Dict[str, Any]:
        req = urllib.request.Request(
            url, headers={"X-ApiKey": self._api_key, "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode())

    @staticmethod
    def _extract_authors(item: Dict[str, Any]) -> str:
        names = item.get("names", {})
        authors = names.get("authors")
        if isinstance(authors, list):
            parts = []
            for author in authors:
                if not isinstance(author, dict):
                    continue
                name = (
                    str(author.get("displayName", "")).strip()
                    or str(author.get("full_name", "")).strip()
                    or str(author.get("wosStandard", "")).strip()
                )
                if name:
                    parts.append(name)
            if parts:
                return ", ".join(parts)
        return str(item.get("authorString", "")).strip() or "Unknown"

    @staticmethod
    def _extract_subject_terms(item: Dict[str, Any]) -> List[str]:
        keywords = item.get("keywords", {})
        if not isinstance(keywords, dict):
            return []
        for key in ("authorKeywords", "keywordsPlus", "keyword"):
            value = keywords.get(key)
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
        return []

    @staticmethod
    def _extract_citation_count(item: Dict[str, Any]) -> int | None:
        value = item.get("timesCited")
        if isinstance(value, int):
            return value
        citations = item.get("citations")
        if isinstance(citations, list) and citations:
            first = citations[0]
            if isinstance(first, dict):
                raw = first.get("count")
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    return None
        return None

    def _parse_items(self, items: List[Dict[str, Any]], query: str) -> List[LiteratureRecord]:
        records: List[LiteratureRecord] = []
        for item in items:
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
            identifiers = (
                item.get("identifiers", {})
                if isinstance(item.get("identifiers"), dict)
                else {}
            )
            links = item.get("links", {}) if isinstance(item.get("links"), dict) else {}
            year_raw = source.get("publishYear", item.get("publishYear", ""))
            year = str(year_raw).strip()
            doi = str(identifiers.get("doi", item.get("doi", ""))).strip()
            url = str(links.get("record", item.get("url", ""))).strip()
            journal = str(source.get("sourceTitle", item.get("sourceTitle", ""))).strip()
            records.append(
                LiteratureRecord(
                    title=title,
                    authors=self._extract_authors(item),
                    year=year,
                    doi=doi,
                    source_id=f"wos:{doi}" if doi else f"wos:{url or title}",
                    provider="Web of Science",
                    journal=journal,
                    url=url,
                    citation_count=self._extract_citation_count(item),
                    subject_terms=self._extract_subject_terms(item),
                    source_query=query,
                    licence_note="Clarivate Web of Science bibliographic metadata",
                )
            )
        return records

    def _make_evidence(
        self, query: str, endpoint: str, records: List[LiteratureRecord]
    ) -> List[SourceEvidence]:
        ts = datetime.now(timezone.utc).isoformat()
        evidence: List[SourceEvidence] = []
        for rec in records:
            raw = f"wos|{query}|{rec.doi}|{ts}"
            evidence.append(
                SourceEvidence(
                    record_id=rec.source_id,
                    source_provider="Web of Science",
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
                warnings=[f"Web of Science {action} rate limited (HTTP 429)."],
                rate_limit_status="rate-limited",
            )
        if exc.code in (401, 403):
            return ProviderResult(
                errors=[f"Web of Science {action} unauthorized (HTTP {exc.code})."]
            )
        return ProviderResult(
            errors=[f"Web of Science {action} failed (HTTP {exc.code})."]
        )

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Web of Science."""
        if not self._api_key:
            return self._not_configured_result()
        wos_query = urllib.parse.quote(f"TS=({query})")
        url = f"{self._api_base}?q={wos_query}&limit={max_results}&page=1"
        try:
            payload = self._request_json(url)
            items = payload.get("hits", [])
            if not isinstance(items, list):
                items = []
            records = self._parse_items(items, query)
            return ProviderResult(
                records=records,
                provenance=self._make_evidence(query, "wos/documents", records),
            )
        except urllib.error.HTTPError as exc:
            return self._http_error_result("search", exc)
        except Exception as exc:
            return ProviderResult(errors=[f"Web of Science search error: {exc}"])

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify DOI via Web of Science."""
        if not self._api_key:
            return self._not_configured_result()
        wos_query = urllib.parse.quote(f"DO=({doi})")
        url = f"{self._api_base}?q={wos_query}&limit=1&page=1"
        try:
            payload = self._request_json(url)
            items = payload.get("hits", [])
            if not isinstance(items, list):
                items = []
            records = self._parse_items(items[:1], doi)
            if records:
                records[0].source_query = doi
            return ProviderResult(
                records=records,
                provenance=self._make_evidence(doi, "wos/documents?doi", records),
            )
        except urllib.error.HTTPError as exc:
            return self._http_error_result("DOI verification", exc)
        except Exception as exc:
            return ProviderResult(
                errors=[f"Web of Science DOI verification error: {exc}"]
            )
