"""
Source registry — central registry of all configured scientific providers.

Instantiates all providers and exposes aggregate search/verify-DOI operations
that fan out to configured providers and merge results.

Usage::

    from src.scientific_sources.source_registry import SourceRegistry

    registry = SourceRegistry()
    capabilities = registry.list_capabilities()
    results = registry.search("blue economy", max_results=5)
    doi_result = registry.verify_doi("10.1234/example")
"""

from __future__ import annotations

from typing import Dict, List

from src.scientific_sources.base import BaseProvider
from src.scientific_sources.crossref import CrossrefProvider
from src.scientific_sources.elsevier_scopus import ElsevierScopusProvider
from src.scientific_sources.google_drive import GoogleDriveProvider
from src.scientific_sources.microsoft_graph import MicrosoftGraphProvider
from src.scientific_sources.models import (
    LiteratureRecord,
    ProviderResult,
    SourceCapability,
)
from src.scientific_sources.scival import SciValProvider
from src.scientific_sources.web_of_science import WebOfScienceProvider


class SourceRegistry:
    """
    Registry of all scientific source providers.

    Instantiates every provider and delegates search/verify operations to
    those that are configured.  Crossref is always configured; proprietary
    providers silently return "not configured" results when keys are absent.
    """

    def __init__(self) -> None:
        self._providers: List[BaseProvider] = [
            CrossrefProvider(),
            ElsevierScopusProvider(),
            WebOfScienceProvider(),
            SciValProvider(),
            GoogleDriveProvider(),
            MicrosoftGraphProvider(),
        ]

    def list_capabilities(self) -> List[SourceCapability]:
        """Return capability descriptors for all registered providers."""
        return [p.capability for p in self._providers]

    def capabilities_dict(self) -> Dict[str, dict]:
        """
        Return capabilities as a serialisable dictionary keyed by provider name.
        """
        result: Dict[str, dict] = {}
        for cap in self.list_capabilities():
            result[cap.name] = {
                "provider": cap.provider,
                "requires_secret": cap.requires_secret,
                "configured": cap.configured,
                "live_test_allowed": cap.live_test_allowed,
                "allowed_metadata_fields": cap.allowed_metadata_fields,
                "licence_note": cap.licence_note,
            }
        return result

    def search(
        self,
        query: str,
        max_results: int = 5,
        providers: List[str] | None = None,
    ) -> List[ProviderResult]:
        """
        Search across all (or specified) providers.

        Args:
            query: Free-text search string.
            max_results: Maximum results per provider.
            providers: Optional list of provider names to query.
                       If None, all providers are queried.

        Returns:
            List of ProviderResult objects (one per provider).
        """
        targets = self._providers
        if providers is not None:
            targets = [
                p for p in self._providers if p.capability.name in providers
            ]
        return [p.search(query, max_results) for p in targets]

    def verify_doi(self, doi: str) -> List[ProviderResult]:
        """
        Verify a DOI across all configured providers.

        Args:
            doi: Digital Object Identifier to look up.

        Returns:
            List of ProviderResult objects (one per provider).
        """
        return [p.verify_doi(doi) for p in self._providers]

    def flat_records(self, results: List[ProviderResult]) -> List[LiteratureRecord]:
        """
        Flatten a list of ProviderResult objects into a single record list.

        Args:
            results: Results from search() or verify_doi().

        Returns:
            Deduplicated list of LiteratureRecord objects (DOI-exact dedup).
        """
        seen_dois: set = set()
        flat: List[LiteratureRecord] = []
        for result in results:
            for rec in result.records:
                key = rec.doi or rec.source_id
                if key not in seen_dois:
                    seen_dois.add(key)
                    flat.append(rec)
        return flat
