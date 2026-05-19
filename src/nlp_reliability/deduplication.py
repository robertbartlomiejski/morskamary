"""
Deduplication utilities for LiteratureRecord collections.

Provides DOI-exact and title-normalised fuzzy deduplication to prevent
the same publication from being counted multiple times when retrieved from
different providers (Crossref, Scopus, WoS, SciVal).

Thresholds are deterministic and documented so results are reproducible.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from src.scientific_sources.models import LiteratureRecord

# Fuzzy title similarity threshold (Jaccard on word tokens, range 0–1).
# Records with similarity >= this threshold are considered duplicates.
TITLE_SIMILARITY_THRESHOLD = 0.85


def _normalize_title(title: str) -> str:
    """
    Lowercase, remove punctuation, and collapse whitespace for comparison.

    Args:
        title: Raw title string.

    Returns:
        Normalized title string.
    """
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _jaccard_similarity(a: str, b: str) -> float:
    """
    Compute Jaccard similarity between two strings as sets of word tokens.

    Args:
        a: First normalized string.
        b: Second normalized string.

    Returns:
        Similarity score between 0.0 and 1.0.
    """
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def deduplicate_records(
    records: List[LiteratureRecord],
    threshold: float = TITLE_SIMILARITY_THRESHOLD,
) -> Tuple[List[LiteratureRecord], List[Tuple[LiteratureRecord, LiteratureRecord]]]:
    """
    Deduplicate a list of LiteratureRecord objects.

    Strategy:
    1. DOI-exact deduplication: records sharing a non-empty DOI are merged.
    2. Title fuzzy deduplication: records with normalized-title Jaccard
       similarity >= ``threshold`` are considered duplicates; the first
       occurrence (by list order) is kept.

    Args:
        records: Input records (may come from multiple providers).
        threshold: Jaccard similarity threshold for title deduplication.

    Returns:
        Tuple of (unique_records, duplicate_pairs) where each pair is
        (kept_record, removed_duplicate).
    """
    unique: List[LiteratureRecord] = []
    duplicate_pairs: List[Tuple[LiteratureRecord, LiteratureRecord]] = []
    seen_dois: set = set()
    normalized_titles: List[str] = []

    for rec in records:
        # Step 1: DOI-exact dedup
        if rec.doi:
            if rec.doi in seen_dois:
                # Find the original record for reporting
                orig = next((u for u in unique if u.doi == rec.doi), unique[0])
                duplicate_pairs.append((orig, rec))
                continue
            seen_dois.add(rec.doi)

        # Step 2: Title fuzzy dedup
        norm = _normalize_title(rec.title)
        is_dup = False
        for i, existing_norm in enumerate(normalized_titles):
            if _jaccard_similarity(norm, existing_norm) >= threshold:
                duplicate_pairs.append((unique[i], rec))
                is_dup = True
                break

        if not is_dup:
            unique.append(rec)
            normalized_titles.append(norm)

    return unique, duplicate_pairs
