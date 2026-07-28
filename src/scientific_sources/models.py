"""Canonical data models for scientific-source providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class SourceCapability:
    """Describe one configured or unconfigured provider capability."""

    name: str
    provider: str
    requires_secret: bool
    configured: bool
    live_test_allowed: bool
    allowed_metadata_fields: List[str]
    licence_note: str


@dataclass
class LiteratureRecord:
    """Normalised bibliographic record produced by a provider."""

    title: str
    authors: str
    year: str
    doi: str
    source_id: str
    provider: str
    language: str = ""
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

    def to_dict(self, *, include_restricted: bool = False) -> Dict[str, Any]:
        """Serialise safe metadata, optionally including restricted fields."""

        payload: Dict[str, Any] = {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "doi": self.doi,
            "source_id": self.source_id,
            "provider": self.provider,
            "language": self.language,
            "journal": self.journal,
            "url": self.url,
            "subject_terms": self.subject_terms,
            "source_query": self.source_query,
            "retrieval_timestamp": self.retrieval_timestamp,
            "licence_note": self.licence_note,
        }
        if include_restricted:
            payload.update(
                {
                    "abstract": self.abstract,
                    "abstract_available": self.abstract_available,
                    "abstract_stored": self.abstract_stored,
                    "citation_count": self.citation_count,
                }
            )
        return payload


@dataclass
class SourceEvidence:
    """Provenance record for a single provider search result."""

    record_id: str
    source_provider: str
    retrieval_mode: str
    query: str
    api_endpoint_label: str
    timestamp: str
    confidence_score: float
    provenance_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
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
    """Result bundle returned by every provider search call.

    ``raw_payload`` may contain either a licence-safe verbatim provider payload
    or an explicitly declared redistribution-safe metadata envelope. Providers
    must remove fields that cannot be retained under licence, privacy, or
    repository governance rules. Consumers must inspect an envelope's
    ``payload_kind`` before assuming exact cold-cache replay is possible.
    """

    records: List[LiteratureRecord] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rate_limit_status: Optional[str] = None
    page_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    provenance: List[SourceEvidence] = field(default_factory=list)
    raw_payload: Optional[Dict[str, Any]] = field(default=None)

    @property
    def is_empty(self) -> bool:
        return len(self.records) == 0

    def to_dict(self, *, include_restricted: bool = False) -> Dict[str, Any]:
        return {
            "records": [
                record.to_dict(include_restricted=include_restricted)
                for record in self.records
            ],
            "errors": self.errors,
            "warnings": self.warnings,
            "rate_limit_status": self.rate_limit_status,
            "page_diagnostics": self.page_diagnostics,
            "provenance": [item.to_dict() for item in self.provenance],
        }
