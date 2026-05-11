"""Regression tests for dynamic provider priority in triangulation."""

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
    assert providers == {"Crossref", "Scopus"}
