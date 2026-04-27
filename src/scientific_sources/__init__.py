"""
Scientific sources provider package for morskamary.

Provides a modular, capability-gated interface to multiple scientific databases
(Crossref, Elsevier/Scopus, Web of Science, SciVal, Google Drive, Microsoft Graph).

All providers normalize results into LiteratureRecord. Proprietary providers
return a structured "not configured" result when the required secret is absent.

Usage::

    from src.scientific_sources import SourceRegistry
    registry = SourceRegistry()
    results = registry.search("blue economy sociology", max_results=5)
"""

from src.scientific_sources.models import (
    LiteratureRecord,
    SourceCapability,
    SourceEvidence,
    ProviderResult,
)
from src.scientific_sources.source_registry import SourceRegistry

__all__ = [
    "LiteratureRecord",
    "SourceCapability",
    "SourceEvidence",
    "ProviderResult",
    "SourceRegistry",
]
