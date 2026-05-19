"""
Confidence scoring for individual LiteratureRecord objects.

Assigns a confidence score (0.0–1.0) based on metadata completeness.
Records with DOI, authors, year, journal, and URL score highest.
Records with no DOI and no journal are flagged for manual review.

Never invent metadata to raise a score; use "evidence absent" flags.
"""

from __future__ import annotations

from src.scientific_sources.models import LiteratureRecord


def score_record_confidence(record: LiteratureRecord) -> float:
    """
    Compute a metadata-completeness confidence score for a LiteratureRecord.

    Scoring weights:
    - DOI present:     0.35
    - Authors known:   0.20
    - Year present:    0.15
    - Journal known:   0.15
    - URL present:     0.10
    - Subject terms:   0.05

    Args:
        record: The literature record to score.

    Returns:
        Float confidence score between 0.0 and 1.0.
    """
    score = 0.0

    if record.doi:
        score += 0.35
    if record.authors and record.authors.lower() != "unknown":
        score += 0.20
    if record.year:
        score += 0.15
    if record.journal:
        score += 0.15
    if record.url:
        score += 0.10
    if record.subject_terms:
        score += 0.05

    return round(min(score, 1.0), 4)


def is_low_confidence(record: LiteratureRecord, threshold: float = 0.5) -> bool:
    """
    Return True if the record's confidence score is below *threshold*.

    Low-confidence records should be queued for manual review rather than
    used directly in competence mapping or citation claims.

    Args:
        record: The record to evaluate.
        threshold: Confidence threshold (default 0.5).

    Returns:
        True if the record requires manual review.
    """
    return score_record_confidence(record) < threshold
