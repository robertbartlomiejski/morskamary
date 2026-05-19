"""
Google Drive metadata provider stub.

Requires GOOGLE_DRIVE_OAUTH_CREDENTIALS (path to local OAuth JSON).

This provider indexes sanitized, licence-compliant metadata from a user's
Google Drive research folder.  OAuth credentials must NEVER be committed
to the repository.

Only metadata (title, year, DOI, author, file ID) may be stored —
not full document text unless explicitly permitted.

Live implementation notes:
  Authenticate via google-auth and googleapiclient.
  Use Drive files.list API with q="mimeType='application/pdf'" etc.
  Extract metadata from document properties or linked reference managers.
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


class GoogleDriveProvider(BaseProvider):
    """Google Drive metadata provider (capability-gated; requires OAuth)."""

    def __init__(self) -> None:
        self._credentials_path: str = os.getenv(
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS", ""
        )

    @property
    def capability(self) -> SourceCapability:
        """Return capability descriptor for Google Drive."""
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        configured = bool(
            self._credentials_path and os.path.isfile(self._credentials_path)
        )
        return SourceCapability(
            name="google_drive",
            provider="Google Drive",
            requires_secret=True,
            configured=configured,
            live_test_allowed=live and configured,
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=(
                "Store only sanitized metadata exported from Drive; "
                "never commit OAuth credentials to the repository."
            ),
        )

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Drive — returns 'not configured' if credentials are absent."""
        if not self.capability.configured:
            return self._not_configured_result()
        return ProviderResult(
            warnings=[
                "Google Drive live search not yet implemented. "
                "Set GOOGLE_DRIVE_OAUTH_CREDENTIALS path and implement "
                "the Drive API call in google_drive.py."
            ]
        )

    def verify_doi(self, doi: str) -> ProviderResult:
        """DOI verification not applicable for Drive metadata."""
        return ProviderResult(
            warnings=["Google Drive provider does not support DOI verification."]
        )
