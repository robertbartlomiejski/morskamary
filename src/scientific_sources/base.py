"""
Abstract base class for all scientific source providers.

Every concrete provider must implement:
- ``capability`` property returning a ``SourceCapability``
- ``search(query, max_results)`` returning a ``ProviderResult``
- ``verify_doi(doi)`` returning a ``ProviderResult`` with at most one record

Providers must NEVER fabricate metadata (title, DOI, citation count, journal,
abstract) and must return a structured "not configured" result instead of
raising an exception when a required secret is absent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.scientific_sources.models import ProviderResult, SourceCapability

_PAGINATION_UNSUPPORTED = "pagination_not_supported_by_provider"


class BaseProvider(ABC):
    """Abstract base for scientific database providers."""

    @property
    @abstractmethod
    def capability(self) -> SourceCapability:
        """Return a SourceCapability describing this provider's runtime state."""

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """
        Search for literature records matching *query*.

        Args:
            query: Free-text search string.
            max_results: Maximum number of results to return.

        Returns:
            ProviderResult with normalized LiteratureRecord objects.
            If the provider is not configured, returns an empty result
            with an explanatory warning rather than raising.
        """

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
        """Search using protocol-defined logical pages when supported.

        The default implementation preserves the historical provider contract by
        delegating to ``search(query, max_results)``. Providers with native
        pagination override this method. Multi-page scientific acquisitions must
        inspect ``page_diagnostics`` before claiming the sampling strategy was
        applied.
        """
        del sort_strategy, time_window
        legacy_api = logical_pages is not None
        requested_pages = logical_pages if logical_pages is not None else pages
        safe_pages = max(1, int(requested_pages or 1))
        safe_rows = max(1, int(rows_per_page or 1))
        result = self.search(query, safe_pages * safe_rows)
        result.page_diagnostics.append(
            {
                "provider": self.capability.name,
                "query": query,
                "logical_page": 1,
                "physical_request_index": 1,
                "cursor_or_offset": "single_request_fallback",
                "requested_rows": safe_pages * safe_rows,
                "returned_rows": len(result.records),
                "normalized_rows": len(result.records),
                "pagination_status": (
                    "single_page_fallback"
                    if safe_pages == 1
                    else _PAGINATION_UNSUPPORTED
                ),
            }
        )
        if safe_pages > 1:
            result.warnings.append(_PAGINATION_UNSUPPORTED)
        if legacy_api:
            diagnostic = dict(result.page_diagnostics[0])
            diagnostic["pagination_method"] = "single_request_fallback"
            return result, [diagnostic]
        return result

    @abstractmethod
    def verify_doi(self, doi: str) -> ProviderResult:
        """
        Look up a specific DOI and return its metadata.

        Args:
            doi: The Digital Object Identifier to verify.

        Returns:
            ProviderResult with at most one LiteratureRecord.
        """

    def _not_configured_result(self) -> ProviderResult:
        """Return a standard "provider not configured" result."""
        cap = self.capability
        env_vars = [
            v
            for v in [
                "CROSSREF_MAILTO",
                "ELSEVIER_API_KEY",
                "SCOPUS_API_KEY",
                "OPENALEX_API_KEY",
                "WOS_API_KEY",
                "SCIVAL_API_KEY",
                "GOOGLE_DRIVE_OAUTH_CREDENTIALS",
                "MICROSOFT_TENANT_ID",
            ]
            if cap.name.lower() in v.lower()
        ]
        hint = (
            f"Set the {env_vars[0]} environment variable to enable."
            if env_vars
            else "Configure the required credential to enable this provider."
        )
        return ProviderResult(
            warnings=[
                f"Provider '{cap.name}' is not configured. {hint} "
                "No live API call was made."
            ]
        )
