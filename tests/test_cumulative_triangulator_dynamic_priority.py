"""Regression tests for dynamic provider priority in triangulation."""

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


def test_same_doi_first_dynamic_provider_wins():
    t = CumulativeTriangulator()
    t.ingest_dynamic_records(
        [
            _record("Shared DOI title", "10.1000/shared", "Crossref", "crossref:10.1000/shared"),
            _record("Shared DOI title", "10.1000/shared", "Scopus", "scopus:10.1000/shared"),
        ]
    )

    out = t.triangulate()

    assert len(out) == 1
    assert out[0].provider == "Crossref"


def test_same_normalized_title_first_dynamic_provider_wins():
    t = CumulativeTriangulator()
    t.ingest_dynamic_records(
        [
            _record("Maritime Transport: Resilience", "", "Crossref", "crossref:1"),
            _record("maritime transport resilience", "", "Scopus", "scopus:1"),
        ]
    )

    out = t.triangulate()

    assert len(out) == 1
    assert out[0].provider == "Crossref"
