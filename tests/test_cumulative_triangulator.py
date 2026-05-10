"""
Tests for src/cumulative_analysis/triangulator.py.

Verifies:
- ClaimOrigin provenance typing (STATIC_BASELINE vs DYNAMIC_API_CROSSREF)
- Static baseline CSV ingestion
- Dynamic LiteratureRecord ingestion
- Triangulation / deduplication with DOI-first chronological authority
- Title-normalised fallback deduplication
- TriangulatedRecord.to_dict() serialisation
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from src.cumulative_analysis.triangulator import (
    ClaimOrigin,
    CumulativeTriangulator,
    TriangulatedRecord,
    _normalize_doi,
    _normalize_title,
)
from src.scientific_sources.models import LiteratureRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _csv_file(tmp_path: Path, rows: list[dict]) -> Path:
    """Write a CSV file containing the given rows and return its path."""
    if not rows:
        p = tmp_path / "baseline.csv"
        p.write_text("title,authors,year,doi,journal,url,subject_terms,source_query,retrieval_timestamp,licence_note\n")
        return p
    p = tmp_path / "baseline.csv"
    fieldnames = list(rows[0].keys())
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return p


def _static_row(**kwargs) -> dict:
    defaults = dict(
        title="Blue Economy Governance",
        authors="Ada Lovelace",
        year="2024",
        doi="10.1234/blue",
        journal="Ocean Studies",
        url="https://example.org/paper",
        subject_terms="governance;policy",
        source_query="",
        retrieval_timestamp="",
        licence_note="",
    )
    defaults.update(kwargs)
    return defaults


def _lit_record(**kwargs) -> LiteratureRecord:
    defaults = dict(
        title="Blue Economy Governance",
        authors="Ada Lovelace",
        year="2024",
        doi="10.1234/blue",
        source_id="crossref:10.1234/blue",
        provider="Crossref",
        journal="Ocean Studies",
        url="https://example.org/paper",
    )
    defaults.update(kwargs)
    return LiteratureRecord(**defaults)


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------


class TestNormalizeHelpers:
    def test_normalize_doi_lowercases(self):
        assert _normalize_doi("10.1234/BLUE") == "10.1234/blue"

    def test_normalize_doi_strips_whitespace(self):
        assert _normalize_doi("  10.1234/x  ") == "10.1234/x"

    def test_normalize_title_lowercases_removes_punctuation(self):
        result = _normalize_title("Blue Economy: Governance!")
        assert result == "blue economy governance"

    def test_normalize_title_collapses_whitespace(self):
        assert _normalize_title("Blue   Economy") == "blue economy"


# ---------------------------------------------------------------------------
# Unit tests: ClaimOrigin enum
# ---------------------------------------------------------------------------


class TestClaimOrigin:
    def test_static_baseline_value(self):
        assert ClaimOrigin.STATIC_BASELINE.value == "static_baseline"

    def test_dynamic_api_crossref_value(self):
        assert ClaimOrigin.DYNAMIC_API_CROSSREF.value == "dynamic_api_crossref"

    def test_two_members(self):
        assert len(list(ClaimOrigin)) == 2


# ---------------------------------------------------------------------------
# Unit tests: TriangulatedRecord
# ---------------------------------------------------------------------------


class TestTriangulatedRecord:
    def test_to_dict_contains_source_value(self):
        rec = TriangulatedRecord(
            title="Test",
            authors="A. Author",
            year="2024",
            doi="10.0/x",
            source=ClaimOrigin.STATIC_BASELINE,
            provider="static",
        )
        d = rec.to_dict()
        assert d["source"] == "static_baseline"

    def test_to_dict_excludes_citation_count(self):
        rec = TriangulatedRecord(
            title="T",
            authors="A",
            year="2024",
            doi="",
            source=ClaimOrigin.DYNAMIC_API_CROSSREF,
            provider="Crossref",
        )
        d = rec.to_dict()
        assert "citation_count" not in d

    def test_to_dict_excludes_abstract_flags(self):
        rec = TriangulatedRecord(
            title="T",
            authors="A",
            year="2024",
            doi="",
            source=ClaimOrigin.STATIC_BASELINE,
            provider="static",
        )
        d = rec.to_dict()
        assert "abstract_available" not in d
        assert "abstract_stored" not in d


# ---------------------------------------------------------------------------
# Unit tests: CumulativeTriangulator ingestion
# ---------------------------------------------------------------------------


class TestIngestStaticBaseline:
    def test_ingest_returns_count(self, tmp_path):
        csv_path = _csv_file(tmp_path, [_static_row(), _static_row(doi="10.2/b", title="Other")])
        t = CumulativeTriangulator()
        n = t.ingest_static_baseline(csv_path)
        assert n == 2

    def test_ingest_sets_static_origin(self, tmp_path):
        csv_path = _csv_file(tmp_path, [_static_row()])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        records = t.triangulate()
        assert records[0].source == ClaimOrigin.STATIC_BASELINE

    def test_ingest_missing_file_raises(self):
        t = CumulativeTriangulator()
        with pytest.raises(FileNotFoundError):
            t.ingest_static_baseline(Path("/nonexistent/path/baseline.csv"))

    def test_ingest_skips_rows_without_title(self, tmp_path):
        csv_path = _csv_file(
            tmp_path,
            [_static_row(), _static_row(title="", doi="10.0/x")],
        )
        t = CumulativeTriangulator()
        n = t.ingest_static_baseline(csv_path)
        assert n == 1

    def test_subject_terms_parsed_from_semicolons(self, tmp_path):
        csv_path = _csv_file(tmp_path, [_static_row(subject_terms="governance;policy;blue")])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        records = t.triangulate()
        assert records[0].subject_terms == ["governance", "policy", "blue"]

    def test_subject_terms_parsed_from_pipes(self, tmp_path):
        csv_path = _csv_file(tmp_path, [_static_row(subject_terms="governance|policy|blue")])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        records = t.triangulate()
        assert records[0].subject_terms == ["governance", "policy", "blue"]


class TestIngestDynamicRecords:
    def test_ingest_returns_count(self):
        t = CumulativeTriangulator()
        n = t.ingest_dynamic_records([_lit_record(), _lit_record(doi="10.2/b", title="Other")])
        assert n == 2

    def test_ingest_sets_dynamic_origin(self):
        t = CumulativeTriangulator()
        t.ingest_dynamic_records([_lit_record()])
        records = t.triangulate()
        assert records[0].source == ClaimOrigin.DYNAMIC_API_CROSSREF

    def test_dynamic_records_preserve_provider(self):
        t = CumulativeTriangulator()
        t.ingest_dynamic_records([_lit_record(provider="Crossref")])
        records = t.triangulate()
        assert records[0].provider == "Crossref"


# ---------------------------------------------------------------------------
# Unit tests: Triangulation / deduplication
# ---------------------------------------------------------------------------


class TestTriangulate:
    def test_no_overlap_returns_all_records(self, tmp_path):
        """Static and dynamic records with no common DOI or title are all kept."""
        csv_path = _csv_file(tmp_path, [_static_row(doi="10.1/a", title="Alpha")])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        t.ingest_dynamic_records([_lit_record(doi="10.2/b", title="Beta")])
        result = t.triangulate()
        assert len(result) == 2

    def test_doi_match_dynamic_replaces_static(self, tmp_path):
        """DOI-bearing dynamic record must replace matching static record."""
        doi = "10.1234/shared"
        csv_path = _csv_file(tmp_path, [_static_row(doi=doi, title="Static Title")])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        t.ingest_dynamic_records([_lit_record(doi=doi, title="Dynamic Title")])
        result = t.triangulate()
        assert len(result) == 1
        assert result[0].source == ClaimOrigin.DYNAMIC_API_CROSSREF
        assert result[0].title == "Dynamic Title"

    def test_title_match_dynamic_replaces_static_when_no_doi(self, tmp_path):
        """Title-normalised match must allow dynamic to replace static (DOI-wins)."""
        csv_path = _csv_file(
            tmp_path,
            [_static_row(doi="", title="Blue Economy Governance")],
        )
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        t.ingest_dynamic_records(
            [_lit_record(doi="10.99/x", title="BLUE ECONOMY: GOVERNANCE!")]
        )
        result = t.triangulate()
        assert len(result) == 1
        assert result[0].source == ClaimOrigin.DYNAMIC_API_CROSSREF
        assert result[0].doi == "10.99/x"

    def test_duplicate_dynamic_dois_deduplicated(self, tmp_path):
        """Two dynamic records with the same DOI must produce only one entry."""
        csv_path = _csv_file(tmp_path, [])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        t.ingest_dynamic_records(
            [
                _lit_record(doi="10.1/same", title="First"),
                _lit_record(doi="10.1/same", title="Second"),
            ]
        )
        result = t.triangulate()
        assert len(result) == 1

    def test_duplicate_dynamic_titles_deduplicated(self, tmp_path):
        """Two no-DOI dynamic records with the same title produce one entry."""
        csv_path = _csv_file(tmp_path, [])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        t.ingest_dynamic_records(
            [
                _lit_record(doi="", title="Blue Economy", source_id="x1"),
                _lit_record(doi="", title="BLUE ECONOMY!", source_id="x2"),
            ]
        )
        result = t.triangulate()
        assert len(result) == 1

    def test_static_first_in_output_order(self, tmp_path):
        """Static records appear before newly-appended dynamic records."""
        csv_path = _csv_file(tmp_path, [_static_row(doi="10.1/a", title="Alpha")])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        t.ingest_dynamic_records([_lit_record(doi="10.2/b", title="Beta")])
        result = t.triangulate()
        assert result[0].doi == "10.1/a"
        assert result[1].doi == "10.2/b"

    def test_doi_case_insensitive_match(self, tmp_path):
        """DOI matching must be case-insensitive."""
        csv_path = _csv_file(tmp_path, [_static_row(doi="10.1/UPPER")])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        t.ingest_dynamic_records([_lit_record(doi="10.1/upper", title="New")])
        result = t.triangulate()
        assert len(result) == 1
        assert result[0].source == ClaimOrigin.DYNAMIC_API_CROSSREF

    def test_stats_before_triangulate(self, tmp_path):
        csv_path = _csv_file(tmp_path, [_static_row()])
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        t.ingest_dynamic_records([_lit_record(doi="10.2/b", title="Beta")])
        s = t.stats()
        assert s["static_ingested"] == 1
        assert s["dynamic_ingested"] == 1

    def test_empty_triangulator_returns_empty_list(self):
        t = CumulativeTriangulator()
        assert t.triangulate() == []

    def test_doi_upgrade_does_not_leave_stale_title_index(self, tmp_path):
        """A DOI-upgraded slot must not be overwritten by a later dynamic record
        that matches the *old* static title.

        Regression guard for the stale title_to_idx bug: after upgrading a
        static record via DOI match, the old title must be removed from the
        title index so a subsequent dynamic record with the same old title is
        treated as a new (separate) record rather than silently replacing the
        already-upgraded slot.
        """
        # Static record: doi="10.1/a", title="OldTitle"
        csv_path = _csv_file(
            tmp_path, [_static_row(doi="10.1/a", title="OldTitle")]
        )
        t = CumulativeTriangulator()
        t.ingest_static_baseline(csv_path)
        # First dynamic record upgrades via DOI; it has a different title.
        dyn_upgraded = _lit_record(
            doi="10.1/a", title="NewTitle", source_id="x1"
        )
        # Second dynamic record shares the *old* static title but no DOI —
        # it must NOT overwrite the already-upgraded slot.
        dyn_old_title = _lit_record(
            doi="", title="OldTitle", source_id="x2"
        )
        t.ingest_dynamic_records([dyn_upgraded, dyn_old_title])
        result = t.triangulate()
        # Should have two records: the upgraded slot + the second dynamic record.
        assert len(result) == 2, (
            f"Expected 2 records (upgraded + separate old-title), got {len(result)}"
        )
        # The first slot must hold the DOI-upgraded record (dyn_upgraded).
        doi_upgraded_result = next(
            (r for r in result if r.doi == "10.1/a"), None
        )
        assert doi_upgraded_result is not None
        assert doi_upgraded_result.title == "NewTitle"
        assert doi_upgraded_result.source == ClaimOrigin.DYNAMIC_API_CROSSREF
