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
from typing import Any

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

    def search_paginated(
        self,
        query: str,
        *,
        pages: int = 1,
        logical_pages: int | None = None,
        rows_per_page: int = 50,
        sort_strategy: str = "",
        time_window: dict[str, int] | None = None,
    ) -> Any:
        """Return an explicit zero-attempt pagination result until Drive dispatch exists."""
        del sort_strategy, time_window
        legacy_api = logical_pages is not None
        requested_pages = logical_pages if logical_pages is not None else pages
        safe_pages = max(1, int(requested_pages or 1))
        safe_rows = max(1, int(rows_per_page or 1))
        result = self.search(query, safe_pages * safe_rows)
        configured = self.capability.configured
        pagination_status = "skipped" if configured else "provider_not_configured"
        diagnostic = {
            "provider": self.capability.name,
            "query": query,
            "logical_page": 1,
            "physical_request_index": 0,
            "cursor_or_offset": (
                "not_implemented" if configured else "not_configured"
            ),
            "requested_rows": safe_pages * safe_rows,
            "returned_rows": 0,
            "normalized_rows": 0,
            "pagination_status": pagination_status,
            "errors": "not_implemented" if configured else "provider_not_configured",
        }
        result.page_diagnostics = [diagnostic]
        if legacy_api:
            legacy_diagnostic = dict(diagnostic)
            legacy_diagnostic["pagination_method"] = "no_dispatch"
            return result, [legacy_diagnostic]
        return result

    def verify_doi(self, doi: str) -> ProviderResult:
        """DOI verification not applicable for Drive metadata."""
        return ProviderResult(
            warnings=["Google Drive provider does not support DOI verification."]
        )
