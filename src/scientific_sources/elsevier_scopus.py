"""
Elsevier / Scopus provider stub.

This provider requires an institutional Elsevier API key (ELSEVIER_API_KEY
and/or SCOPUS_API_KEY).  When the key is absent the provider returns a
structured "not configured" result without making any network call.

Allowed metadata fields (per Elsevier Text and Data Mining policy):
- title, authors, year, doi, journal, url, citation_count, subject_terms
Do NOT store full abstracts or restricted database payloads unless your
institutional licence explicitly permits it.

Live implementation notes (for institutional users):
  POST https://api.elsevier.com/content/search/scopus
  Headers: X-ELS-APIKey: <key>, Accept: application/json
  Normalise items from search.results[] into LiteratureRecord.
"""

from __future__ import annotations

import os

from src.scientific_sources.base import BaseProvider
from src.scientific_sources.models import (
    ProviderResult,
    SourceCapability,
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

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Scopus — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        # Live implementation: make Scopus REST call here.
        # Placeholder until institutional access is configured.
        return ProviderResult(
            warnings=[
                "Elsevier/Scopus live search not yet implemented. "
                "Set ELSEVIER_API_KEY or SCOPUS_API_KEY and implement "
                "the REST call in elsevier_scopus.py."
            ]
        )

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify DOI via Scopus — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        return ProviderResult(
            warnings=[
                f"Elsevier/Scopus DOI verification not yet implemented for {doi}."
            ]
        )
