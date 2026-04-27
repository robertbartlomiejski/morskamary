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

from src.scientific_sources.models import ProviderResult, SourceCapability


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
