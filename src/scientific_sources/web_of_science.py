"""
Web of Science (Clarivate) provider stub.

Requires WOS_API_KEY.  Returns a structured "not configured" result when
the key is absent so that the bridge and registry never crash.

Allowed metadata fields (per Clarivate API licence):
- title, authors, year, doi, journal, url, citation_count, subject_terms
Do NOT store full abstracts or restricted WoS database payloads unless
your institutional licence explicitly permits redistribution.

Live implementation notes (for institutional users):
  GET https://api.clarivate.com/apis/wos-starter/v1/documents
  Headers: X-ApiKey: <key>
  Normalise items from hits[] into LiteratureRecord.
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

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search WoS — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        return ProviderResult(
            warnings=[
                "Web of Science live search not yet implemented. "
                "Set WOS_API_KEY and implement the REST call in web_of_science.py."
            ]
        )

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify DOI via WoS — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        return ProviderResult(
            warnings=[f"WoS DOI verification not yet implemented for {doi}."]
        )
