"""
NLP reliability module for morskamary.

Provides tools for deduplication, coverage analysis, confidence scoring,
and triangulation across multiple scientific source providers.

All checks operate on normalized LiteratureRecord objects from the
scientific_sources package.
"""

from src.nlp_reliability.deduplication import deduplicate_records
from src.nlp_reliability.source_coverage import compute_coverage
from src.nlp_reliability.confidence import score_record_confidence
from src.nlp_reliability.triangulation import build_provider_overlap_matrix

__all__ = [
    "deduplicate_records",
    "compute_coverage",
    "score_record_confidence",
    "build_provider_overlap_matrix",
]
