"""
Literature extractor: parse combined_*.csv files and build Competence objects.

Reads all combined_*.csv files from data/raw/ and maps each paper row to a
Competence object using TMBD axis classification based on title/abstract
keyword matching.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pandas as pd  # type: ignore[import-untyped]

from src.core import BlueDynamicsAxis, Competence, CompetenceLevel

# ---------------------------------------------------------------------------
# Keyword sets for axis classification
# ---------------------------------------------------------------------------

_MARINE_KEYWORDS = {
    "ecosystem",
    "biodiversity",
    "marine biology",
    "fisheries",
    "aquaculture",
    "biophysical",
    "species",
    "habitat",
    "ecological",
    "ocean ecology",
    "marine life",
    "reef",
    "wetland",
}

_OCEANIC_KEYWORDS = {
    "governance",
    "policy",
    "international",
    "transboundary",
    "planetary",
    "ocean pact",
    "sovereignty",
    "hydrosocial",
    "ocean literacy",
    "sustainability framework",
    "climate change",
    "multilevel",
    "global",
}

_MARITIME_KEYWORDS = {
    "port",
    "shipping",
    "transport",
    "infrastructure",
    "digital",
    "technology",
    "labor",
    "labour",
    "workforce",
    "economy",
    "industry",
    "trade",
    "logistics",
}


def load_literature_sources(data_dir: Path) -> List[Path]:
    """Return all combined_*.csv paths found inside *data_dir*.

    Args:
        data_dir: Directory to search (usually ``data/raw/``).

    Returns:
        Sorted list of matching :class:`Path` objects.
    """
    return sorted(data_dir.glob("combined_*.csv"))


def map_theme_to_axis(text: str) -> BlueDynamicsAxis:
    """Map free-text (title + abstract) to the closest TMBD axis.

    Precedence: MARINE > OCEANIC > MARITIME (default).

    Args:
        text: Concatenated title and abstract string.

    Returns:
        The best-matching :class:`BlueDynamicsAxis`.
    """
    lower = text.lower()

    marine_hits = sum(1 for kw in _MARINE_KEYWORDS if kw in lower)
    oceanic_hits = sum(1 for kw in _OCEANIC_KEYWORDS if kw in lower)
    maritime_hits = sum(1 for kw in _MARITIME_KEYWORDS if kw in lower)

    if marine_hits >= oceanic_hits and marine_hits >= maritime_hits and marine_hits > 0:
        return BlueDynamicsAxis.MARINE
    if oceanic_hits >= maritime_hits and oceanic_hits > 0:
        return BlueDynamicsAxis.OCEANIC
    return BlueDynamicsAxis.MARITIME


def _sanitize_stem(stem: str) -> str:
    """Replace spaces and non-alphanumeric characters with underscores."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", stem).strip("_")


def _extract_keywords(title: str) -> List[str]:
    """Extract up to 8 unique lowercase words of length >= 4 from *title*."""
    words = re.findall(r"[a-zA-Z]{4,}", title.lower())
    seen: List[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
        if len(seen) == 8:
            break
    return seen


def extract_competences_from_literature(
    csv_paths: List[Path],
    max_per_file: int = 80,
) -> List[Competence]:
    """Read each CSV and create one :class:`Competence` per valid paper row.

    Args:
        csv_paths: List of CSV file paths to process.
        max_per_file: Maximum rows to process per file (prevents bloat).

    Returns:
        Flat list of :class:`Competence` objects (may contain duplicates).
    """
    competences: List[Competence] = []

    for csv_path in csv_paths:
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(csv_path, dtype=str)
        except Exception:
            continue

        stem = _sanitize_stem(csv_path.stem)
        count = 0

        for row_index, row in df.iterrows():
            if count >= max_per_file:
                break

            title = str(row.get("Paper Title", "") or "").strip()
            abstract = str(row.get("Abstract", "") or "").strip()

            if (
                pd.isna(row.get("Paper Title"))
                or pd.isna(row.get("Abstract"))
                or not title
                or not abstract
            ):
                continue

            # --- metadata fields ---
            authors = str(row.get("Author Names", "") or "").strip()
            doi = str(row.get("DOI", "") or "").strip()
            paper_link = str(row.get("Paper Link", "") or "").strip()

            raw_year = str(row.get("Publication Year", "") or "").strip()
            try:
                year = int(float(raw_year))
            except (ValueError, TypeError):
                year = 0

            # --- level from year ---
            if year >= 2022:
                level = CompetenceLevel.ADVANCED
            elif year >= 2019:
                level = CompetenceLevel.INTERMEDIATE
            else:
                level = CompetenceLevel.FOUNDATIONAL

            combined_text = title + " " + abstract
            axis = map_theme_to_axis(combined_text)

            comp_id = f"lit_{stem}_{row_index:03d}"
            competences.append(
                Competence(
                    id=comp_id,
                    name=title[:80],
                    description=abstract[:300],
                    axis=axis,
                    level=level,
                    keywords=_extract_keywords(title),
                    source_metadata={
                        "file": csv_path.name,
                        "row": int(row_index) + 2,
                        "authors": authors,
                        "year": year,
                        "doi": doi,
                        "paper_link": paper_link,
                    },
                )
            )
            count += 1

    return competences


def deduplicate_competences(competences: List[Competence]) -> List[Competence]:
    """Remove duplicate competences by normalised name, keeping first occurrence.

    Args:
        competences: Input list (may contain duplicates).

    Returns:
        Deduplicated list preserving original order.
    """
    seen: set[str] = set()
    unique: List[Competence] = []
    for comp in competences:
        key = comp.name.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(comp)
    return unique


def extract_literature_competences(data_raw_dir: Path) -> List[Competence]:
    """Orchestrate the full literature extraction pipeline.

    Loads all ``combined_*.csv`` sources, extracts competences, deduplicates
    and returns the final list.

    Args:
        data_raw_dir: Directory containing the ``combined_*.csv`` files.

    Returns:
        Deduplicated list of :class:`Competence` objects extracted from
        literature.
    """
    paths = load_literature_sources(data_raw_dir)
    raw = extract_competences_from_literature(paths)
    return deduplicate_competences(raw)
