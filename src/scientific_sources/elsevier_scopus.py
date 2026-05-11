"""
Elsevier / Scopus provider.

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

_SCOPUS_API_BASE = "https://api.elsevier.com/content/search/scopus"

# Fields requested from the Scopus API — deliberately excludes abstract/full-text.
_SCOPUS_FIELDS = (
    "dc:title,dc:creator,author,prism:doi,prism:coverDate,"
    "prism:publicationName,prism:url,citedby-count,authkeywords,eid"
)

_LICENCE_NOTE = (
    "Elsevier/Scopus institutional metadata (Stage 1 compliant). "
    "Do not store full abstracts or restricted database payloads."
)


class ElsevierScopusProvider(BaseProvider):
    """Elsevier Scopus provider (capability-gated; live impl requires key)."""

    def __init__(self) -> None:
        self._api_key: str = os.getenv("ELSEVIER_API_KEY", "") or os.getenv(
            "SCOPUS_API_KEY", ""
        )

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

    def _parse_entries(self, entries: List[Dict[str, Any]], query: str) -> List[LiteratureRecord]:
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
            raw = f"scopus|{query}|{rec.doi}|{ts}"
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

    # ------------------------------------------------------------------
    # Public API (BaseProvider contract)
    # ------------------------------------------------------------------

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Scopus — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        params = urllib.parse.urlencode(
            {"query": query, "count": max_results, "field": _SCOPUS_FIELDS}
        )
        url = f"{_SCOPUS_API_BASE}?{params}"
        try:
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            entries = data.get("search-results", {}).get("entry", [])
            records = self._parse_entries(entries, query)
            evidence = self._make_evidence(query, "scopus/search", records)
            return ProviderResult(records=records, provenance=evidence)
        except Exception as exc:
            return ProviderResult(errors=[f"Scopus search error: {exc}"])

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify DOI via Scopus — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        params = urllib.parse.urlencode(
            {"query": f"DOI({doi})", "count": 1, "field": _SCOPUS_FIELDS}
        )
        url = f"{_SCOPUS_API_BASE}?{params}"
        try:
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            entries = data.get("search-results", {}).get("entry", [])
            records = self._parse_entries(entries, doi)
            evidence = self._make_evidence(doi, f"scopus/doi/{doi}", records)
            return ProviderResult(records=records, provenance=evidence)
        except Exception as exc:
            return ProviderResult(errors=[f"Scopus DOI verification error: {exc}"])
