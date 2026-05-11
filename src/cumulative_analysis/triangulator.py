"""
Cumulative Triangulation Engine — Stage 1 / QMBD synthesis.

Merges the static University of Szczecin baseline (CSV) with dynamic
API ``LiteratureRecord`` outputs (Crossref, Scopus, WoS, SciVal, Drive,
Graph) into a single, deduplicated, strongly-provenanced record set
suitable for QMBD matrix construction.

Provenance typing
-----------------
Every record in the triangulated output carries a ``ClaimOrigin`` label
that identifies the specific provider that produced the evidence.  This
satisfies the data-lineage requirement of the ``DATA_GOVERNANCE.txt``
FAIR traceability rules and allows downstream analysis to distinguish
open (Crossref) from institutional (Scopus, WoS, SciVal) records.

Deduplication policy
--------------------
DOI takes chronological authority: if the same work appears in both the
static baseline and a live API output (matched by DOI or by normalised
title), the dynamic variant replaces the STATIC_BASELINE variant.  When
multiple live providers return the same DOI, the first dynamic record
ingested wins (insertion-order priority within the dynamic pool).  This
reflects the "DOI wins" principle described in
``docs/licensing_and_compliance.md`` (Category 1 — Open providers) and
the deduplication contract already established in
``scripts/export_live_research_records.py``.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from src.scientific_sources.models import LiteratureRecord


class ClaimOrigin(Enum):
    """Provenance label for a triangulated evidence claim.

    STATIC_BASELINE
        The record originated from the University of Szczecin baseline CSV
        (data/derived/Blue Social Competences Univ Szczecin - *.csv or
        equivalent static exports).  These records represent the curated,
        peer-reviewed starting point of the QMBD matrix.

    DYNAMIC_API_CROSSREF
        The record originated from a live Crossref API query mediated by
        ``src.scientific_sources.crossref.CrossrefProvider``.  These records
        are freely redistributable under Category 1 (Open providers) rules
        defined in ``docs/licensing_and_compliance.md``.

    DYNAMIC_API_SCOPUS
        The record originated from a live Elsevier Scopus API query mediated
        by ``src.scientific_sources.elsevier_scopus.ElsevierScopusProvider``.
        Subject to institutional licence constraints (Category 2).

    DYNAMIC_API_WOS
        The record originated from a live Clarivate Web of Science API query
        mediated by ``src.scientific_sources.web_of_science.WebOfScienceProvider``.
        Subject to institutional licence constraints (Category 2).

    DYNAMIC_API_SCIVAL
        The record originated from an Elsevier SciVal analytics query mediated
        by ``src.scientific_sources.scival.SciValProvider``.  SciVal records
        contain aggregated bibliometric indicators and topic labels only
        (Category 3 — restricted analytics).

    DYNAMIC_API_GOOGLE_DRIVE
        The record originated from a Google Drive metadata index mediated by
        ``src.scientific_sources.google_drive.GoogleDriveProvider``.  Only
        sanitised document metadata (title, year, DOI, file ID) is stored.

    DYNAMIC_API_MICROSOFT_GRAPH
        The record originated from a Microsoft Graph / OneDrive metadata index
        mediated by ``src.scientific_sources.microsoft_graph.MicrosoftGraphProvider``.
        Only sanitised document metadata is stored.
    """

    STATIC_BASELINE = "static_baseline"
    DYNAMIC_API_CROSSREF = "dynamic_api_crossref"
    DYNAMIC_API_SCOPUS = "dynamic_api_scopus"
    DYNAMIC_API_WOS = "dynamic_api_wos"
    DYNAMIC_API_SCIVAL = "dynamic_api_scival"
    DYNAMIC_API_GOOGLE_DRIVE = "dynamic_api_google_drive"
    DYNAMIC_API_MICROSOFT_GRAPH = "dynamic_api_microsoft_graph"


# ---------------------------------------------------------------------------
# Provider → ClaimOrigin mapping
# ---------------------------------------------------------------------------

# Maps normalised provider name strings (as set in LiteratureRecord.provider)
# to their ClaimOrigin enum member.  Matching is case-insensitive.
# Unknown providers default to DYNAMIC_API_CROSSREF (open, least-restrictive).
_PROVIDER_CLAIM_ORIGIN: Dict[str, ClaimOrigin] = {
    "crossref": ClaimOrigin.DYNAMIC_API_CROSSREF,
    "scopus": ClaimOrigin.DYNAMIC_API_SCOPUS,
    "elsevier / scopus": ClaimOrigin.DYNAMIC_API_SCOPUS,
    "web of science (clarivate)": ClaimOrigin.DYNAMIC_API_WOS,
    "elsevier scival": ClaimOrigin.DYNAMIC_API_SCIVAL,
    "google drive": ClaimOrigin.DYNAMIC_API_GOOGLE_DRIVE,
    "microsoft graph (onedrive/sharepoint)": ClaimOrigin.DYNAMIC_API_MICROSOFT_GRAPH,
}


def _claim_origin_for_provider(provider: str) -> ClaimOrigin:
    """Return the ClaimOrigin enum member for a given provider name string.

    Matching is case-insensitive.  Unknown providers default to
    DYNAMIC_API_CROSSREF so that the triangulator never crashes on a new
    provider added to the registry without a corresponding mapping entry.
    """
    return _PROVIDER_CLAIM_ORIGIN.get(provider.strip().lower(), ClaimOrigin.DYNAMIC_API_CROSSREF)


@dataclass
class TriangulatedRecord:
    """A single deduplicated, provenanced record in the cumulative QMBD matrix.

    This is the canonical output unit of ``CumulativeTriangulator``.  It
    carries only bibliographic-metadata fields that are safe to commit under
    the Stage 1 governance constraints of ``docs/licensing_and_compliance.md``
    ("What you are always allowed to store").

    Attributes:
        title:               Bibliographic title.
        authors:             Author string (bibliographic fact).
        year:                Publication year.
        doi:                 Digital Object Identifier — the primary dedup key.
        source:              Provenance label (``ClaimOrigin`` enum).
        provider:            Short provider name (e.g. "Crossref", "static").
        journal:             Journal or venue name (bibliographic fact).
        url:                 Persistent URL or DOI link (pointer, not content).
        subject_terms:       Aggregated classification terms, not full text.
        source_query:        Query that produced this record (internal metadata).
        retrieval_timestamp: ISO-8601 retrieval timestamp (internal metadata).
        licence_note:        Licence annotation (internal metadata).
    """

    title: str
    authors: str
    year: str
    doi: str
    source: ClaimOrigin
    provider: str
    journal: str = ""
    url: str = ""
    subject_terms: List[str] = field(default_factory=list)
    source_query: str = ""
    retrieval_timestamp: str = ""
    licence_note: str = ""

    def to_dict(self) -> Dict[str, object]:
        """Serialise to a plain dictionary (for JSON/CSV export)."""
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "doi": self.doi,
            "source": self.source.value,
            "provider": self.provider,
            "journal": self.journal,
            "url": self.url,
            "subject_terms": self.subject_terms,
            "source_query": self.source_query,
            "retrieval_timestamp": self.retrieval_timestamp,
            "licence_note": self.licence_note,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_doi(doi: str) -> str:
    """Lowercase and strip whitespace from a DOI string."""
    return doi.strip().lower()


def _normalize_title(title: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace — for title dedup."""
    t = title.lower()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _record_from_csv_row(row: Dict[str, str]) -> Optional[TriangulatedRecord]:
    """
    Convert a raw CSV row from the static baseline into a TriangulatedRecord.

    Expected columns (all optional except ``title``):
    title, authors, year, doi, provider, journal, url, subject_terms,
    source_query, retrieval_timestamp, licence_note.

    Returns ``None`` when the row lacks a usable title.
    """
    title = row.get("title", "").strip()
    if not title:
        return None

    subject_raw = row.get("subject_terms", "")
    subject_terms: List[str] = (
        [s.strip() for s in subject_raw.split(";") if s.strip()]
        if subject_raw
        else []
    )

    return TriangulatedRecord(
        title=title,
        authors=row.get("authors", "").strip(),
        year=row.get("year", "").strip(),
        doi=row.get("doi", "").strip(),
        source=ClaimOrigin.STATIC_BASELINE,
        provider=row.get("provider", "static").strip() or "static",
        journal=row.get("journal", "").strip(),
        url=row.get("url", "").strip(),
        subject_terms=subject_terms,
        source_query=row.get("source_query", "").strip(),
        retrieval_timestamp=row.get("retrieval_timestamp", "").strip(),
        licence_note=row.get("licence_note", "").strip(),
    )


def _record_from_literature_record(rec: LiteratureRecord) -> TriangulatedRecord:
    """
    Convert a live-API ``LiteratureRecord`` into a ``TriangulatedRecord``.

    The ``ClaimOrigin`` is derived from ``rec.provider`` via
    ``_claim_origin_for_provider`` so that records from Scopus, WoS, SciVal,
    Google Drive, and Microsoft Graph carry distinct provenance labels rather
    than being incorrectly marked as DYNAMIC_API_CROSSREF.

    Bibliographic metadata fields are copied directly; fields excluded by
    Stage 1 governance (citation_count, abstract_available, abstract_stored)
    are not forwarded (docs/licensing_and_compliance.md — Category 1/2/3).
    """
    return TriangulatedRecord(
        title=rec.title,
        authors=rec.authors,
        year=rec.year,
        doi=rec.doi,
        source=_claim_origin_for_provider(rec.provider),
        provider=rec.provider,
        journal=rec.journal,
        url=rec.url,
        subject_terms=list(rec.subject_terms),
        source_query=rec.source_query,
        retrieval_timestamp=rec.retrieval_timestamp,
        licence_note=rec.licence_note,
    )


# ---------------------------------------------------------------------------
# Main triangulator class
# ---------------------------------------------------------------------------


class CumulativeTriangulator:
    """
    Merge and deduplicate static baseline records with dynamic API records.

    Usage::

        triangulator = CumulativeTriangulator()
        triangulator.ingest_static_baseline(Path("data/derived/baseline.csv"))
        triangulator.ingest_dynamic_records(crossref_records)
        final_records = triangulator.triangulate()

    Deduplication rules
    -------------------
    1. **DOI-exact match** — a dynamic (Crossref) record whose DOI matches a
       previously ingested static record replaces it in-place.  This gives the
       live API record chronological authority while preserving the slot order.
    2. **Title-normalised match** — when no DOI is available, the normalised
       title is used.  A dynamic record that matches a static title replaces
       the static slot (DOI wins, i.e. the API-sourced variant is preferred).
    3. All remaining records are kept in ingestion order (static first, then
       dynamic additions).
    """

    def __init__(self) -> None:
        self._static: List[TriangulatedRecord] = []
        self._dynamic: List[TriangulatedRecord] = []

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_static_baseline(self, csv_path: Union[str, Path]) -> int:
        """
        Load static baseline records from a CSV file.

        Args:
            csv_path: Path to the CSV file (str or pathlib.Path).

        Returns:
            Number of records successfully loaded.

        Raises:
            FileNotFoundError: When ``csv_path`` does not exist.
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Static baseline not found: {path}")

        loaded = 0
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = _record_from_csv_row(row)
                if rec is not None:
                    self._static.append(rec)
                    loaded += 1
        return loaded

    def ingest_dynamic_records(self, records: List[LiteratureRecord]) -> int:
        """
        Load dynamic API records (``LiteratureRecord`` objects from any provider).

        The ``ClaimOrigin`` of each ingested record is determined automatically
        from its ``provider`` field via ``_claim_origin_for_provider``, so
        records from Crossref, Scopus, WoS, SciVal, Google Drive, and
        Microsoft Graph all carry distinct provenance labels.

        Args:
            records: List of ``LiteratureRecord`` objects from any configured
                     provider in ``src.scientific_sources``.

        Returns:
            Number of records ingested.
        """
        count = 0
        for rec in records:
            self._dynamic.append(_record_from_literature_record(rec))
            count += 1
        return count

    # ------------------------------------------------------------------
    # Triangulation / deduplication
    # ------------------------------------------------------------------

    def triangulate(self) -> List[TriangulatedRecord]:
        """
        Merge static and dynamic records into a single deduplicated list.

        DOI-bearing dynamic records take authority over static records with
        the same DOI or the same normalised title (DOI-wins policy).  This
        mirrors the deduplication contract used in
        ``scripts/export_live_research_records.py``.

        Returns:
            Deduplicated list of ``TriangulatedRecord`` objects, static
            records first, upgraded in-place where a dynamic record matches.
        """
        # Start with a mutable copy of the static pool.
        pool: List[TriangulatedRecord] = list(self._static)

        # Build lookup structures over the static pool.
        doi_to_idx: Dict[str, int] = {}
        title_to_idx: Dict[str, int] = {}
        for idx, rec in enumerate(pool):
            if rec.doi:
                doi_to_idx[_normalize_doi(rec.doi)] = idx
            norm = _normalize_title(rec.title)
            if norm:
                title_to_idx[norm] = idx

        # Track DOIs and normalised titles already in the pool to prevent
        # dynamic-only duplicates being appended twice.
        seen_dois: Set[str] = set(doi_to_idx.keys())
        seen_titles: Set[str] = set(title_to_idx.keys())

        # Integrate dynamic records.
        for dyn in self._dynamic:
            norm_doi = _normalize_doi(dyn.doi) if dyn.doi else ""
            norm_title = _normalize_title(dyn.title)

            # --- DOI-exact upgrade ------------------------------------------
            if norm_doi and norm_doi in doi_to_idx:
                idx = doi_to_idx[norm_doi]
                old_rec = pool[idx]
                # Preserve first-ingested dynamic provider priority.
                if old_rec.source != ClaimOrigin.STATIC_BASELINE:
                    continue
                # Remove stale title-index entry so a later dynamic record
                # matching the old static title does not overwrite this slot.
                old_norm_title = _normalize_title(old_rec.title)
                if (
                    old_norm_title
                    and title_to_idx.get(old_norm_title) == idx
                ):
                    del title_to_idx[old_norm_title]
                    seen_titles.discard(old_norm_title)
                # Replace the static slot with the first matching dynamic rec.
                pool[idx] = dyn
                # Register the new title so it is visible to subsequent records.
                if norm_title and norm_title not in seen_titles:
                    title_to_idx[norm_title] = idx
                    seen_titles.add(norm_title)
                continue

            # --- Title-normalised upgrade ------------------------------------
            if norm_title and norm_title in title_to_idx:
                idx = title_to_idx[norm_title]
                old_rec = pool[idx]
                # Preserve first-ingested dynamic provider priority.
                if old_rec.source != ClaimOrigin.STATIC_BASELINE:
                    continue
                # Replace static slot; first dynamic variant is authoritative.
                pool[idx] = dyn
                if norm_doi:
                    doi_to_idx[norm_doi] = idx
                    seen_dois.add(norm_doi)
                continue

            # --- New record (no collision) ------------------------------------
            if norm_doi and norm_doi in seen_dois:
                # Duplicate dynamic DOI — skip.
                continue
            if norm_title and norm_title in seen_titles:
                # Duplicate dynamic title (no DOI) — skip.
                continue

            # Append as a new entry.
            pool.append(dyn)
            if norm_doi:
                seen_dois.add(norm_doi)
            if norm_title:
                seen_titles.add(norm_title)

        return pool

    # ------------------------------------------------------------------
    # Convenience statistics
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, int]:
        """Return ingestion counts before triangulation."""
        return {
            "static_ingested": len(self._static),
            "dynamic_ingested": len(self._dynamic),
        }
