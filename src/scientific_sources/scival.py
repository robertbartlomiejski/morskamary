"""
Elsevier SciVal provider stub.

Requires SCIVAL_API_KEY.  Returns a structured "not configured" result when
the key is absent.

SciVal provides institutional research analytics (FWCI, collaboration
indicators, topic clusters) rather than raw citation search.  Use this
provider only for bibliometric indicators, not as a replacement for Scopus.

Allowed metadata: aggregated indicators, topic labels, institutional
affiliation summaries — not restricted database payloads.

Live implementation notes (for institutional users):
  GET https://api.elsevier.com/analytics/scival/...
  Headers: X-ELS-APIKey: <key>
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
    "subject_terms",
    "source_id",
    "provider",
    "source_query",
    "retrieval_timestamp",
]


class SciValProvider(BaseProvider):
    """Elsevier SciVal provider (capability-gated; live impl requires key)."""

    def __init__(self) -> None:
        self._api_key: str = os.getenv("SCIVAL_API_KEY", "")

    @property
    def capability(self) -> SourceCapability:
        """Return capability descriptor for SciVal."""
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        return SourceCapability(
            name="scival",
            provider="Elsevier SciVal",
            requires_secret=True,
            configured=bool(self._api_key),
            live_test_allowed=live and bool(self._api_key),
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=(
                "SciVal analytics data: store only permitted aggregated "
                "indicators, not restricted database payloads."
            ),
        )

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search SciVal — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        return ProviderResult(
            warnings=[
                "SciVal live search not yet implemented. "
                "Set SCIVAL_API_KEY and implement the REST call in scival.py."
            ]
        )

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify DOI via SciVal — returns 'not configured' if key is absent."""
        if not self._api_key:
            return self._not_configured_result()
        return ProviderResult(
            warnings=[f"SciVal DOI verification not yet implemented for {doi}."]
        )
