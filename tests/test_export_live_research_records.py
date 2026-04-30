"""
Tests for scripts/export_live_research_records.py.

All tests use mocked Crossref responses — no network access required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.export_live_research_records import (
    build_coverage_report,
    deduplicate_records,
    export_coverage_csv,
    export_provenance_json,
    export_records_csv,
    export_records_json,
    main,
    normalize_title,
)
from src.scientific_sources.models import LiteratureRecord, ProviderResult, SourceEvidence


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_record(**kwargs) -> LiteratureRecord:
    """Return a minimal LiteratureRecord with overridable fields."""
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


def _make_evidence(**kwargs) -> SourceEvidence:
    """Return a minimal SourceEvidence with overridable fields."""
    defaults = dict(
        record_id="crossref:10.1234/blue",
        source_provider="Crossref",
        retrieval_mode="live",
        query="blue economy",
        api_endpoint_label="crossref/works",
        timestamp="2024-01-01T00:00:00Z",
        confidence_score=0.9,
        provenance_hash="abc123",
    )
    defaults.update(kwargs)
    return SourceEvidence(**defaults)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestNormalizeTitle:
    def test_lowercases_title(self):
        assert normalize_title("BLUE Economy") == "blue economy"

    def test_removes_punctuation(self):
        assert normalize_title("Blue Economy: Governance!") == "blue economy governance"

    def test_collapses_whitespace(self):
        assert normalize_title("Blue   Economy    Governance") == "blue economy governance"

    def test_strips_leading_trailing_whitespace(self):
        assert normalize_title("  Blue Economy  ") == "blue economy"


class TestDeduplicateRecords:
    def test_removes_doi_duplicates(self):
        rec1 = _make_record(doi="10.1234/x", title="Title A")
        rec2 = _make_record(doi="10.1234/x", title="Title B")
        deduped, stats = deduplicate_records([rec1, rec2])
        assert len(deduped) == 1
        assert stats["doi_duplicates"] == 1
        assert stats["title_duplicates"] == 0

    def test_removes_title_duplicates_when_no_doi(self):
        rec1 = _make_record(doi="", title="Blue Economy Governance")
        rec2 = _make_record(doi="", title="BLUE ECONOMY: GOVERNANCE!")
        deduped, stats = deduplicate_records([rec1, rec2])
        assert len(deduped) == 1
        assert stats["doi_duplicates"] == 0
        assert stats["title_duplicates"] == 1

    def test_keeps_distinct_dois(self):
        rec1 = _make_record(doi="10.1234/a")
        rec2 = _make_record(doi="10.1234/b")
        deduped, stats = deduplicate_records([rec1, rec2])
        assert len(deduped) == 2

    def test_keeps_distinct_titles_when_no_doi(self):
        rec1 = _make_record(doi="", title="Fisheries")
        rec2 = _make_record(doi="", title="Aquaculture")
        deduped, stats = deduplicate_records([rec1, rec2])
        assert len(deduped) == 2

    def test_doi_normalization_case_and_whitespace(self):
        """DOI dedup must be case- and whitespace-insensitive."""
        rec1 = _make_record(doi="10.1234/X", title="Title A")
        rec2 = _make_record(doi="10.1234/x", title="Title B")
        rec3 = _make_record(doi=" 10.1234/x ", title="Title C")
        deduped, stats = deduplicate_records([rec1, rec2, rec3])
        assert len(deduped) == 1
        assert stats["doi_duplicates"] == 2

    def test_deduplicates_later_doi_record_against_earlier_title_only_match(self):
        """
        A later DOI-bearing record with the same normalized title must not leak
        through when a title-only record was accepted first.
        """
        rec1 = _make_record(doi="", title="Blue Economy Governance")
        rec2 = _make_record(doi="10.1234/x", title="BLUE ECONOMY: GOVERNANCE!")
        deduped, stats = deduplicate_records([rec1, rec2])
        assert len(deduped) == 1
        assert deduped[0].doi == "10.1234/x"
        assert stats["doi_duplicates"] + stats["title_duplicates"] == 1


class TestBuildCoverageReport:
    def test_builds_coverage_rows(self):
        items = [
            {
                "sector": "Offshore Energy",
                "provider": "Crossref",
                "query": "offshore wind",
                "record_count": 10,
            },
            {
                "sector": "Ports",
                "provider": "Crossref",
                "query": "port governance",
                "record_count": 5,
            },
        ]
        coverage = build_coverage_report(items)
        assert len(coverage) == 2
        assert coverage[0]["sector"] == "Offshore Energy"
        assert coverage[1]["record_count"] == 5


# ---------------------------------------------------------------------------
# Export function tests
# ---------------------------------------------------------------------------


class TestExportFunctions:
    def test_export_records_json(self, tmp_path):
        records = [_make_record()]
        output_path = tmp_path / "test.json"
        export_records_json(records, output_path)
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert len(data) == 1
        assert data[0]["title"] == "Blue Economy Governance"

    def test_export_records_csv(self, tmp_path):
        records = [_make_record()]
        output_path = tmp_path / "test.csv"
        export_records_csv(records, output_path)
        assert output_path.exists()
        content = output_path.read_text()
        assert "title,authors,year" in content
        assert "Blue Economy Governance" in content

    def test_export_records_csv_empty(self, tmp_path):
        records = []
        output_path = tmp_path / "empty.csv"
        export_records_csv(records, output_path)
        assert output_path.exists()
        content = output_path.read_text()
        assert "title,authors,year" in content
        assert len(content.strip().split("\n")) == 1  # header only

    def test_export_provenance_json(self, tmp_path):
        provenance = [_make_evidence()]
        output_path = tmp_path / "prov.json"
        export_provenance_json(provenance, output_path)
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert len(data) == 1
        assert data[0]["source_provider"] == "Crossref"

    def test_export_coverage_csv(self, tmp_path):
        coverage = [
            {
                "sector": "Offshore Energy",
                "provider": "Crossref",
                "query": "offshore wind",
                "record_count": 10,
            }
        ]
        output_path = tmp_path / "coverage.csv"
        export_coverage_csv(coverage, output_path)
        assert output_path.exists()
        content = output_path.read_text()
        assert "sector,provider,query,record_count" in content
        assert "Offshore Energy" in content


# ---------------------------------------------------------------------------
# Integration tests for main()
# ---------------------------------------------------------------------------


class TestMainIntegration:
    def test_offline_mode_skips_network_calls(self, tmp_path, monkeypatch):
        """Test that offline mode produces empty outputs without network calls."""
        # Create minimal query file
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  test_sector:
    label: "Test Sector"
    queries:
      - "test query"
"""
        )

        output_dir = tmp_path / "outputs"

        # Mock sys.argv
        monkeypatch.setattr(
            "sys.argv",
            [
                "export_live_research_records.py",
                "--query-file",
                str(query_file),
                "--output-dir",
                str(output_dir),
                "--offline",
                "true",
            ],
        )

        # Run main
        result = main()
        assert result == 0

        # Verify outputs exist and are empty/minimal
        assert (output_dir / "live_records.json").exists()
        assert (output_dir / "live_records.csv").exists()
        assert (output_dir / "crossref_records.json").exists()
        assert (output_dir / "live_provenance.json").exists()
        assert (output_dir / "live_source_coverage.csv").exists()
        assert (output_dir / "low_confidence_live_records.json").exists()

        # Check that outputs are empty
        records = json.loads((output_dir / "live_records.json").read_text())
        assert len(records) == 0

    def test_live_mode_with_mocked_registry(self, tmp_path, monkeypatch):
        """Test live mode with mocked SourceRegistry returning synthetic records."""
        # Create minimal query file
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  offshore_energy:
    label: "Offshore Energy"
    queries:
      - "offshore wind"
"""
        )

        output_dir = tmp_path / "outputs"

        # Mock SourceRegistry.search to return synthetic records
        mock_record = _make_record(
            title="Offshore Wind Energy",
            doi="10.1234/wind",
            source_id="crossref:10.1234/wind",
        )
        mock_evidence = _make_evidence(
            record_id="crossref:10.1234/wind", query="offshore wind"
        )
        mock_result = ProviderResult(
            records=[mock_record], provenance=[mock_evidence]
        )

        def mock_search(query, max_results, providers):
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search = mock_search
            MockRegistry.return_value = mock_instance

            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--output-dir",
                    str(output_dir),
                    "--offline",
                    "false",
                    "--providers",
                    "crossref",
                    "--max-results-per-query",
                    "10",
                ],
            )

            # Run main
            result = main()
            assert result == 0

            # Verify outputs
            records = json.loads((output_dir / "live_records.json").read_text())
            assert len(records) == 1
            assert records[0]["title"] == "Offshore Wind Energy"

            provenance = json.loads((output_dir / "live_provenance.json").read_text())
            assert len(provenance) == 1

    def test_deduplication_in_main(self, tmp_path, monkeypatch):
        """Test that duplicate records are removed in main."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
      - "query2"
"""
        )

        output_dir = tmp_path / "outputs"

        # Mock two identical records from different queries
        mock_record = _make_record(doi="10.1234/same")
        mock_evidence = _make_evidence()
        mock_result = ProviderResult(
            records=[mock_record], provenance=[mock_evidence]
        )

        def mock_search(query, max_results, providers):
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search = mock_search
            MockRegistry.return_value = mock_instance

            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--output-dir",
                    str(output_dir),
                    "--offline",
                    "false",
                ],
            )

            result = main()
            assert result == 0

            # Verify only one record (deduped)
            records = json.loads((output_dir / "live_records.json").read_text())
            assert len(records) == 1

    def test_low_confidence_filtering(self, tmp_path, monkeypatch):
        """Test that low-confidence records are exported separately."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
"""
        )

        output_dir = tmp_path / "outputs"

        # Mock record with low-confidence provenance
        mock_record = _make_record(doi="10.1234/low", source_id="crossref:10.1234/low")
        mock_evidence = _make_evidence(
            record_id="crossref:10.1234/low", confidence_score=0.5
        )
        mock_result = ProviderResult(
            records=[mock_record], provenance=[mock_evidence]
        )

        def mock_search(query, max_results, providers):
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search = mock_search
            MockRegistry.return_value = mock_instance

            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--output-dir",
                    str(output_dir),
                    "--offline",
                    "false",
                ],
            )

            result = main()
            assert result == 0

            # Verify low-confidence record is in separate file
            low_conf = json.loads(
                (output_dir / "low_confidence_live_records.json").read_text()
            )
            assert len(low_conf) == 1
            assert low_conf[0]["doi"] == "10.1234/low"

    def test_missing_query_file_returns_error(self, tmp_path, monkeypatch, capsys):
        """Test that missing query file returns error code."""
        output_dir = tmp_path / "outputs"

        monkeypatch.setattr(
            "sys.argv",
            [
                "export_live_research_records.py",
                "--query-file",
                "nonexistent.yml",
                "--output-dir",
                str(output_dir),
            ],
        )

        result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Query file not found" in captured.err

    def test_crossref_records_json_contains_only_crossref(self, tmp_path, monkeypatch):
        """Test that crossref_records.json contains only Crossref records."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
"""
        )

        output_dir = tmp_path / "outputs"

        # Mock records from different providers
        crossref_rec = _make_record(provider="Crossref", doi="10.1234/cr")
        scopus_rec = _make_record(
            provider="Scopus", doi="10.1234/sc", source_id="scopus:10.1234/sc"
        )
        mock_evidence = _make_evidence()
        mock_result_cr = ProviderResult(records=[crossref_rec], provenance=[mock_evidence])
        mock_result_sc = ProviderResult(records=[scopus_rec], provenance=[mock_evidence])

        def mock_search(query, max_results, providers):
            return [mock_result_cr, mock_result_sc]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search = mock_search
            MockRegistry.return_value = mock_instance

            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--output-dir",
                    str(output_dir),
                    "--offline",
                    "false",
                ],
            )

            result = main()
            assert result == 0

            # Verify crossref_records.json contains only Crossref
            crossref_only = json.loads(
                (output_dir / "crossref_records.json").read_text()
            )
            assert len(crossref_only) == 1
            assert crossref_only[0]["provider"] == "Crossref"

            # Verify live_records.json contains both
            all_records = json.loads((output_dir / "live_records.json").read_text())
            assert len(all_records) == 2

    def test_zero_record_provider_identity_in_coverage(self, tmp_path, monkeypatch):
        """Zero-record provider results must preserve provider identity in coverage CSV."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  test_sector:
    label: "Test Sector"
    queries:
      - "blue economy"
"""
        )

        output_dir = tmp_path / "outputs"

        # Provider returns an empty ProviderResult (zero records, zero provenance)
        empty_result = ProviderResult(records=[], provenance=[])

        def mock_search(query, max_results, providers):
            return [empty_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search = mock_search
            MockRegistry.return_value = mock_instance

            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--output-dir",
                    str(output_dir),
                    "--offline",
                    "false",
                    "--providers",
                    "crossref",
                ],
            )

            result = main()
            assert result == 0

            # Verify that coverage CSV contains a row for the provider with zero records
            import csv as csv_module

            with open(output_dir / "live_source_coverage.csv", newline="") as f:
                rows = list(csv_module.DictReader(f))

            assert len(rows) == 1
            assert rows[0]["provider"] == "crossref"
            assert rows[0]["record_count"] == "0"
            assert rows[0]["sector"] == "Test Sector"
