"""
Provenance utilities for the scientific sources package.

Provides helpers for hashing and serialising provenance metadata so that
every derived output can be traced back to its source provider and query.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from src.scientific_sources.models import LiteratureRecord, ProviderResult


def compute_record_hash(record: LiteratureRecord) -> str:
    """
    Compute a deterministic SHA-256 hash for a LiteratureRecord.

    The hash covers title, doi, provider, and source_query to allow
    deduplication across provider results.

    Args:
        record: The literature record to hash.

    Returns:
        Hex-encoded 16-character hash prefix (collision-resistant for this use).
    """
    raw = f"{record.title}|{record.doi}|{record.provider}|{record.source_query}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def build_provenance_summary(results: List[ProviderResult]) -> Dict[str, Any]:
    """
    Build a provenance summary dictionary from a list of ProviderResult objects.

    Args:
        results: Results from one or more providers.

    Returns:
        Dictionary with provider counts, error list, warning list,
        and per-record provenance hashes.
    """
    total_records = 0
    all_errors: List[str] = []
    all_warnings: List[str] = []
    provider_counts: Dict[str, int] = {}
    record_hashes: List[str] = []

    for result in results:
        for rec in result.records:
            total_records += 1
            provider_counts[rec.provider] = provider_counts.get(rec.provider, 0) + 1
            record_hashes.append(compute_record_hash(rec))
        all_errors.extend(result.errors)
        all_warnings.extend(result.warnings)

    return {
        "total_records": total_records,
        "provider_counts": provider_counts,
        "errors": all_errors,
        "warnings": all_warnings,
        "record_hashes": record_hashes,
    }


def export_provenance_json(results: List[ProviderResult]) -> str:
    """
    Serialize the provenance summary of a list of ProviderResult objects to JSON.

    Args:
        results: Results from one or more providers.

    Returns:
        JSON string of the provenance summary.
    """
    summary = build_provenance_summary(results)
    return json.dumps(summary, indent=2, ensure_ascii=False)
