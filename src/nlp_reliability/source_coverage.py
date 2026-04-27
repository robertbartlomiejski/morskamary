"""
Source coverage analysis for the NLP reliability module.

Computes coverage of literature records across:
- TMBD axes (Marine, Maritime, Oceanic)
- 12 Blue Economy sectors
- Providers

Results help identify gaps and guide targeted literature searches.
"""

from __future__ import annotations

from typing import Dict, List

from src.scientific_sources.models import LiteratureRecord

# The 12 canonical Blue Economy sectors from the University of Szczecin baseline.
BLUE_ECONOMY_SECTORS = [
    "Offshore Energy",
    "Ports",
    "Maritime Transport",
    "Fisheries",
    "Aquaculture",
    "Coastal Tourism",
    "Marine Biotechnology",
    "Ocean Governance",
    "Shipbuilding",
    "Marine Environmental Services",
    "Desalination",
    "Blue Carbon",
]

TMBD_AXES = ["Marine", "Maritime", "Oceanic"]


def compute_coverage(records: List[LiteratureRecord]) -> Dict[str, object]:
    """
    Compute coverage statistics for a list of LiteratureRecord objects.

    Args:
        records: Normalized literature records from any provider.

    Returns:
        Dictionary with:
        - provider_counts: records per provider
        - records_with_doi: count of records with a DOI
        - records_without_doi: count of records missing a DOI
        - subject_term_frequency: top subject terms across all records
        - low_confidence_count: records with no DOI and no journal
        - evidence_absent_flags: list of source_ids flagged as low-evidence
    """
    provider_counts: Dict[str, int] = {}
    records_with_doi = 0
    records_without_doi = 0
    term_freq: Dict[str, int] = {}
    low_confidence: List[str] = []

    for rec in records:
        provider_counts[rec.provider] = provider_counts.get(rec.provider, 0) + 1

        if rec.doi:
            records_with_doi += 1
        else:
            records_without_doi += 1

        for term in rec.subject_terms:
            term_freq[term] = term_freq.get(term, 0) + 1

        # Flag records without DOI and without journal as low-evidence
        if not rec.doi and not rec.journal:
            low_confidence.append(rec.source_id)

    # Sort subject terms by frequency
    sorted_terms = sorted(term_freq.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_records": len(records),
        "provider_counts": provider_counts,
        "records_with_doi": records_with_doi,
        "records_without_doi": records_without_doi,
        "subject_term_frequency": dict(sorted_terms[:20]),
        "low_confidence_count": len(low_confidence),
        "evidence_absent_flags": low_confidence,
    }
