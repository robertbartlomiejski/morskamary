"""
Microsoft Graph (OneDrive / SharePoint) provider stub.

Requires MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID, and
MICROSOFT_CLIENT_SECRET for app-registration-based access.

This provider indexes sanitized, licence-compliant metadata from
OneDrive/SharePoint research folders.  Credentials must NEVER be
committed to the repository.

Only metadata (title, year, DOI, author, SharePoint URL) may be stored.

Live implementation notes:
  Authenticate via msal.ConfidentialClientApplication.
  Use Graph /v1.0/sites/{site}/drive/search API.
  Normalise items from value[] into LiteratureRecord.
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
    "url",
    "source_id",
    "provider",
    "source_query",
    "retrieval_timestamp",
]


class MicrosoftGraphProvider(BaseProvider):
    """Microsoft Graph / OneDrive provider (capability-gated; requires app reg)."""

    def __init__(self) -> None:
        self._tenant_id: str = os.getenv("MICROSOFT_TENANT_ID", "")
        self._client_id: str = os.getenv("MICROSOFT_CLIENT_ID", "")
        self._client_secret: str = os.getenv("MICROSOFT_CLIENT_SECRET", "")

    @property
    def capability(self) -> SourceCapability:
        """Return capability descriptor for Microsoft Graph."""
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        configured = bool(
            self._tenant_id and self._client_id and self._client_secret
        )
        return SourceCapability(
            name="microsoft_graph",
            provider="Microsoft Graph (OneDrive/SharePoint)",
            requires_secret=True,
            configured=configured,
            live_test_allowed=live and configured,
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=(
                "Store only sanitized metadata exported from OneDrive/SharePoint; "
                "never commit tenant IDs or app secrets to the repository."
            ),
        )

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Graph — returns 'not configured' if credentials are absent."""
        if not self.capability.configured:
            return self._not_configured_result()
        return ProviderResult(
            warnings=[
                "Microsoft Graph live search not yet implemented. "
                "Set MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID, "
                "MICROSOFT_CLIENT_SECRET and implement the Graph call "
                "in microsoft_graph.py."
            ]
        )

    def verify_doi(self, doi: str) -> ProviderResult:
        """DOI verification not applicable for Graph metadata."""
        return ProviderResult(
            warnings=[
                "Microsoft Graph provider does not support DOI verification."
            ]
        )
