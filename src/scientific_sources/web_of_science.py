"""
Web of Science (Clarivate) provider.

Requires WOS_API_KEY.  Returns a structured "not configured" result when
the key is absent so that the bridge and registry never crash.

Allowed metadata fields (per Clarivate API licence):
- title, authors, year, doi, journal, url, citation_count, subject_terms
Do NOT store full abstracts or restricted WoS database payloads unless
your institutional licence explicitly permits redistribution.

REST endpoint used (WoS Starter API v1):
  GET https://api.clarivate.com/apis/wos-starter/v1/documents
  Headers: X-ApiKey: <key>, Accept: application/json
  Response: hits[] — each hit maps to a LiteratureRecord.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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

_WOS_API_BASE = "https://api.clarivate.com/apis/wos-starter/v1/documents"

_LICENCE_NOTE = (
    "Clarivate Web of Science institutional metadata (Stage 1 compliant). "
    "Do not store full abstracts or restricted WoS database payloads."
)


class WebOfScienceProvider(BaseProvider):
    """Web of Science provider (capability-gated; live impl requires key)."""

    def __init__(self) -> None:
        self._api_key: str = os.getenv("WOS_API_KEY", "")

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        """Return WoS API request headers."""
        return {"X-ApiKey": self._api_key, "Accept": "application/json"}

    def _parse_hit(self, hit: Dict[str, Any], query: str) -> LiteratureRecord:
        """Convert a single WoS Starter API hit into a LiteratureRecord.

        Field mapping (WoS Starter v1 JSON → LiteratureRecord):
          title                               → title
          names.authors[].displayName         → authors (comma-joined)
          source.publishYear                  → year
          identifiers.doi                     → doi
          source.sourceTitle                  → journal
          links.record                        → url
          citations[0].count                  → citation_count (transient)
          keywords.authorKeywords + keywordsPlus → subject_terms
          uid                                 → source_id prefix

        Abstract and full-text fields are intentionally excluded.
        """
        title = (hit.get("title") or "Unknown Title").strip()

        # Authors: WoS Starter uses names.authors; some older versions use authors.authors.
        author_objs = (
            hit.get("names", {}).get("authors", [])
            or hit.get("authors", {}).get("authors", [])
        )
        authors_list: List[str] = []
        for author in author_objs:
            name = (author.get("displayName") or author.get("fullName") or author.get("wosStandard") or "").strip()
            if name:
                authors_list.append(name)
        authors = ", ".join(authors_list) if authors_list else "Unknown"

        source = hit.get("source", {})
        year_raw = source.get("publishYear")
        year = str(year_raw) if year_raw is not None else ""

        identifiers = hit.get("identifiers", {})
        doi = (identifiers.get("doi") or "").strip()

        journal = (source.get("sourceTitle") or "").strip()

        links = hit.get("links", {})
        url = (links.get("record") or "").strip()

        # Citation count (transient — Stage 1 compliance filter drops it from exports).
        citation_count: Optional[int] = None
        citations = hit.get("citations", [])
        if citations and isinstance(citations, list):
            raw_count = citations[0].get("count")
            if raw_count is not None:
                try:
                    citation_count = int(raw_count)
                except (ValueError, TypeError):
                    pass

        # Subject terms: union of author keywords and KeyWords Plus.
        keywords = hit.get("keywords", {})
        author_kws: List[str] = keywords.get("authorKeywords", []) or []
        plus_kws: List[str] = keywords.get("keywordsPlus", []) or []
        subject_terms = [k for k in (author_kws + plus_kws) if k]

        uid = (hit.get("uid") or "").strip()
        if doi:
            source_id = f"wos:{doi}"
        elif uid:
            source_id = f"wos:{uid}"
        else:
            source_id = f"wos:{title[:40]}"

        ts = datetime.now(timezone.utc).isoformat()
        return LiteratureRecord(
            title=title,
            authors=authors,
            year=year,
            doi=doi,
            source_id=source_id,
            provider="Web of Science (Clarivate)",
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

    def _parse_hits(self, hits: List[Dict[str, Any]], query: str) -> List[LiteratureRecord]:
        """Parse a list of WoS hit dicts into LiteratureRecord objects."""
        return [self._parse_hit(h, query) for h in hits if isinstance(h, dict)]

    def _make_evidence(
        self, query: str, endpoint: str, records: List[LiteratureRecord]
    ) -> List[SourceEvidence]:
        """Create provenance evidence entries for a WoS search call."""
        ts = datetime.now(timezone.utc).isoformat()
        evidence: List[SourceEvidence] = []
        for rec in records:
            raw = f"wos|{query}|{rec.doi}|{ts}"
            phash = hashlib.sha256(raw.encode()).hexdigest()[:16]
            evidence.append(
                SourceEvidence(
                    record_id=rec.source_id,
                    source_provider="Web of Science (Clarivate)",
                    retrieval_mode="live",
                    query=query,
                    api_endpoint_label=endpoint,
                    timestamp=ts,
                    confidence_score=0.9,
                    provenance_hash=phash,
                )
            )
        return evidence

    # ------------------------------------------------------------------
    # Public API (BaseProvider contract)
    # ------------------------------------------------------------------

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search WoS — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        params = urllib.parse.urlencode({"q": query, "limit": max_results, "page": 1})
        url = f"{_WOS_API_BASE}?{params}"
        try:
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            hits = data.get("hits", [])
            records = self._parse_hits(hits, query)
            evidence = self._make_evidence(query, "wos-starter/documents", records)
            return ProviderResult(records=records, provenance=evidence)
        except Exception as exc:
            return ProviderResult(errors=[f"Web of Science search error: {exc}"])

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify DOI via WoS — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        params = urllib.parse.urlencode({"q": f"DO={doi}", "limit": 1, "page": 1})
        url = f"{_WOS_API_BASE}?{params}"
        try:
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            hits = data.get("hits", [])
            records = self._parse_hits(hits, doi)
            evidence = self._make_evidence(doi, f"wos-starter/documents/doi/{doi}", records)
            return ProviderResult(records=records, provenance=evidence)
        except Exception as exc:
            return ProviderResult(errors=[f"Web of Science DOI verification error: {exc}"])
