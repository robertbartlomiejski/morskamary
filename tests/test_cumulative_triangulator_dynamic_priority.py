"""Regression tests for dynamic provider priority in triangulation."""
"""Regression tests for first-ingested dynamic priority in triangulation."""

from __future__ import annotations

import csv
from pathlib import Path

from src.cumulative_analysis.triangulator import CumulativeTriangulator
from src.scientific_sources.models import LiteratureRecord


def _record(title: str, doi: str, provider: str, source_id: str) -> LiteratureRecord:
    return LiteratureRecord(
        title=title,
        authors="A. Author",
        year="2024",
        doi=doi,
        source_id=source_id,
        provider=provider,
        journal="Journal",
        url="https://example.org",
    )


def _baseline_csv(tmp_path: Path, title: str, doi: str) -> Path:
    csv_path = tmp_path / "baseline.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["title", "authors", "year", "doi", "provider", "journal", "url"])
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
                "year": "2023",
                "doi": doi,
                "provider": "static",
                "journal": "Static Journal",
                "url": "https://example.org/static",
            }
        )
    return csv_path


def test_same_doi_first_dynamic_provider_wins_after_static_upgrade(tmp_path: Path):
    t = CumulativeTriangulator()
    t.ingest_static_baseline(_baseline_csv(tmp_path, "Shared DOI title", "10.1000/shared"))
    t.ingest_dynamic_records(
        [
            _record("Shared DOI title", "10.1000/shared", "Crossref", "crossref:10.1000/shared"),
            _record("Shared DOI title", "10.1000/shared", "Scopus", "scopus:10.1000/shared"),
        ]
    )

    out = t.triangulate()

    assert len(out) == 1
    assert out[0].provider == "Crossref"


def test_same_normalized_title_first_dynamic_provider_wins_after_static_upgrade(tmp_path: Path):
    t = CumulativeTriangulator()
    t.ingest_static_baseline(_baseline_csv(tmp_path, "Maritime Transport: Resilience", ""))
    t.ingest_dynamic_records(
        [
            _record("Maritime Transport: Resilience", "", "Crossref", "crossref:1"),
            _record("maritime transport resilience", "", "Scopus", "scopus:1"),
        ]
    )

    out = t.triangulate()

    assert len(out) == 1
    assert out[0].provider == "Crossref"


def test_title_upgrade_removes_old_static_doi_index(tmp_path: Path):
    t = CumulativeTriangulator()
    t.ingest_static_baseline(
        _baseline_csv(tmp_path, "Shared Normalized Title", "10.1000/static-doi")
    )
    t.ingest_dynamic_records(
        [
            _record(
                "Shared Normalized Title",
                "10.1000/crossref-doi",
                "Crossref",
                "crossref:10.1000/crossref-doi",
            ),
            _record(
                "A distinct Scopus record",
                "10.1000/static-doi",
                "Scopus",
                "scopus:10.1000/static-doi",
            ),
        ]
    )

    out = t.triangulate()

    assert len(out) == 2
    providers = {rec.provider for rec in out}
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


def test_title_upgrade_removes_old_static_doi_index(tmp_path):
    """Title-based static upgrade must clear stale DOI index for later dynamics."""
    triangulator = CumulativeTriangulator()
    triangulator.ingest_static_baseline(
        _write_static_csv(
            tmp_path, title="Shared Normalized Title", doi="10.1000/static-doi"
        )
    )
    triangulator.ingest_dynamic_records(
        [
            _record(
                provider="Crossref",
                title="Shared Normalized Title",
                doi="10.1000/crossref-doi",
                source_id="crossref:10.1000/crossref-doi",
            ),
            _record(
                provider="Scopus",
                title="A distinct Scopus record",
                doi="10.1000/static-doi",
                source_id="scopus:10.1000/static-doi",
            ),
        ]
    )

    result = triangulator.triangulate()

    assert len(result) == 2
    providers = {rec.provider for rec in result}
    assert providers == {"Crossref", "Scopus"}
