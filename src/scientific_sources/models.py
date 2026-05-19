"""
Data models for the scientific sources provider package.

All providers normalize their responses into these canonical models so that
downstream analysis code is decoupled from provider-specific API formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class SourceCapability:
    """Describes one configured (or unconfigured) provider capability."""

    name: str
    """Short identifier, e.g. 'crossref', 'scopus'."""

    provider: str
    """Human-readable provider name."""

    requires_secret: bool
    """True when an API key or OAuth credential is needed."""

    configured: bool
    """True when the required secret/credential is available at runtime."""

    live_test_allowed: bool
    """True when LIVE_RESEARCH_API_TESTS env var is set to 'true'."""

    allowed_metadata_fields: List[str]
    """Fields that may be stored under licence / open-access rules."""

    licence_note: str
    """Short note on storage/redistribution constraints."""


@dataclass
class LiteratureRecord:
    """
    Normalized bibliographic record produced by any provider.

    Only the fields listed in the provider's ``allowed_metadata_fields``
    should be populated; all others must be left as None/empty.
    """

    title: str
    authors: str
    year: str
    doi: str
    source_id: str
    provider: str
    journal: str = ""
    url: str = ""
    abstract: str = ""
    abstract_available: bool = False
    abstract_stored: bool = False
    citation_count: Optional[int] = None
    subject_terms: List[str] = field(default_factory=list)
    source_query: str = ""
    retrieval_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    licence_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary (for JSON export)."""
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "doi": self.doi,
            "source_id": self.source_id,
            "provider": self.provider,
            "journal": self.journal,
            "url": self.url,
            "abstract": self.abstract,
            "abstract_available": self.abstract_available,
            "abstract_stored": self.abstract_stored,
            "citation_count": self.citation_count,
            "subject_terms": self.subject_terms,
            "source_query": self.source_query,
            "retrieval_timestamp": self.retrieval_timestamp,
            "licence_note": self.licence_note,
        }


@dataclass
class SourceEvidence:
    """Provenance record for a single search call."""

    record_id: str
    source_provider: str
    retrieval_mode: str
    """'live', 'mocked', or 'offline'."""
    query: str
    api_endpoint_label: str
    timestamp: str
    confidence_score: float
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "record_id": self.record_id,
            "source_provider": self.source_provider,
            "retrieval_mode": self.retrieval_mode,
            "query": self.query,
            "api_endpoint_label": self.api_endpoint_label,
            "timestamp": self.timestamp,
            "confidence_score": self.confidence_score,
            "provenance_hash": self.provenance_hash,
        }


@dataclass
class ProviderResult:
    """
    Result bundle returned by every provider search call.

    Always contains *records* (possibly empty), *errors*, *warnings*, and
    *provenance* metadata.  Callers must never crash when *records* is empty.
    """

    records: List[LiteratureRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rate_limit_status: Optional[str] = None
    provenance: List[SourceEvidence] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Return True when no records were returned."""
        return len(self.records) == 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dictionary (for JSON export)."""
        return {
            "records": [r.to_dict() for r in self.records],
            "errors": self.errors,
            "warnings": self.warnings,
            "rate_limit_status": self.rate_limit_status,
            "provenance": [p.to_dict() for p in self.provenance],
        }
