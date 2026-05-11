"""Regression tests for first-ingested dynamic priority in triangulation."""

from __future__ import annotations

import csv
from pathlib import Path

from src.cumulative_analysis.triangulator import (
    ClaimOrigin,
    CumulativeTriangulator,
)
from src.scientific_sources.models import LiteratureRecord


def _write_static_csv(tmp_path: Path, *, title: str, doi: str) -> Path:
    path = tmp_path / "baseline.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "title",
                "authors",
                "year",
                "doi",
                "journal",
                "url",
                "subject_terms",
                "source_query",
                "retrieval_timestamp",
                "licence_note",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "title": title,
                "authors": "Static Author",
                "year": "2024",
                "doi": doi,
                "journal": "Static Journal",
                "url": "https://example.org/static",
                "subject_terms": "governance",
                "source_query": "",
                "retrieval_timestamp": "",
                "licence_note": "",
            }
        )
    return path


def _record(*, provider: str, title: str, doi: str, source_id: str) -> LiteratureRecord:
    return LiteratureRecord(
        title=title,
        authors=f"{provider} Author",
        year="2025",
        doi=doi,
        source_id=source_id,
        provider=provider,
        journal=f"{provider} Journal",
        url=f"https://example.org/{source_id}",
    )


def test_first_dynamic_doi_match_preserved_after_static_upgrade(tmp_path):
    """Later dynamic DOI duplicates must not overwrite the first dynamic upgrade."""
    doi = "10.1234/shared"
    baseline = _write_static_csv(tmp_path, title="Static Title", doi=doi)

    triangulator = CumulativeTriangulator()
    triangulator.ingest_static_baseline(baseline)
    triangulator.ingest_dynamic_records(
        [
            _record(
                provider="Crossref",
                title="Crossref Dynamic Title",
                doi=doi,
                source_id="crossref:10.1234/shared",
            ),
            _record(
                provider="Scopus",
                title="Scopus Dynamic Title",
                doi=doi,
                source_id="scopus:10.1234/shared",
            ),
        ]
    )

    result = triangulator.triangulate()

    assert len(result) == 1
    assert result[0].title == "Crossref Dynamic Title"
    assert result[0].provider == "Crossref"
    assert result[0].source == ClaimOrigin.DYNAMIC_API_CROSSREF


def test_first_dynamic_title_match_preserved_after_static_upgrade(tmp_path):
    """Later dynamic title duplicates must not overwrite the first dynamic upgrade."""
    baseline = _write_static_csv(tmp_path, title="Shared Dynamic Title", doi="")

    triangulator = CumulativeTriangulator()
    triangulator.ingest_static_baseline(baseline)
    triangulator.ingest_dynamic_records(
        [
            _record(
                provider="Crossref",
                title="Shared Dynamic Title",
                doi="10.1234/crossref",
                source_id="crossref:10.1234/crossref",
            ),
            _record(
                provider="Scopus",
                title="Shared: Dynamic Title!",
                doi="10.1234/scopus",
                source_id="scopus:10.1234/scopus",
            ),
        ]
    )

    result = triangulator.triangulate()

    assert len(result) == 1
    assert result[0].doi == "10.1234/crossref"
    assert result[0].provider == "Crossref"
    assert result[0].source == ClaimOrigin.DYNAMIC_API_CROSSREF
