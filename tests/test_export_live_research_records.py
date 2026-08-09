"""
Tests for scripts/export_live_research_records.py.

All tests use mocked Crossref responses — no network access required.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml
from unittest.mock import MagicMock, patch

from scripts.export_live_research_records import (
    LiveContextClassificationRepository,
    PhysicalRequestCountContractError,
    QUERY_EXECUTION_FIELDS,
    PROTOCOL_PROJECTED_QUERY_FILE_NAME,
    STAGE1_CSV_FIELDS,
    _apply_query_constraint,
    _lookup_provider_sort_strategy_full,
    _normalise_page_diagnostics,
    _resolve_effective_sampling_request,
    _resolve_provider_sort_strategies,
    _search_registry_paginated,
    _to_stage1_compliant_dict,
    _validate_provider_physical_request_count,
    build_thematic_loop_audit,
    build_coverage_report,
    deduplicate_records,
    export_coverage_csv,
    export_provenance_json,
    export_records_csv,
    export_records_json,
    main,
    normalize_title,
    triangulate_identity_loop,
)
from src.scientific_sources.live_query_protocol import load_live_query_protocol
from src.scientific_sources.models import (
    LiteratureRecord,
    ProviderResult,
    SourceEvidence,
)

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


def _make_capability(*names: str) -> list:
    """Return a list of mock SourceCapability objects for the given provider names."""
    caps = []
    for name in names:
        cap = MagicMock()
        cap.name = name
        cap.configured = True
        caps.append(cap)
    return caps


def _adapt_legacy_search_for_paginated_dispatch(legacy_search):
    """Adapt a synthetic legacy fixture without exercising the legacy path."""

    def search_paginated(
        query,
        *,
        pages,
        rows_per_page,
        providers,
        sort_strategy_by_provider,
        time_window,
    ):
        del sort_strategy_by_provider, time_window
        results = legacy_search(
            query,
            max_results=pages * rows_per_page,
            providers=providers,
        )
        return results

    return search_paginated


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestNormalizeTitle:
    def test_lowercases_title(self):
        assert normalize_title("BLUE Economy") == "blue economy"

    def test_removes_punctuation(self):
        assert normalize_title("Blue Economy: Governance!") == "blue economy governance"

    def test_collapses_whitespace(self):
        assert (
            normalize_title("Blue   Economy    Governance") == "blue economy governance"
        )

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

    def test_removes_title_duplicate_when_only_one_record_has_doi(self):
        """Title dedup must still run when one variant has DOI and one does not."""
        rec1 = _make_record(doi="10.1234/x", title="Blue Economy Governance")
        rec2 = _make_record(doi="", title="BLUE ECONOMY: GOVERNANCE!")
        deduped, stats = deduplicate_records([rec1, rec2])
        assert len(deduped) == 1
        assert stats["doi_duplicates"] == 0
        assert stats["title_duplicates"] == 1

    def test_prefers_doi_record_when_no_doi_variant_comes_first(self):
        """On title collision, DOI-bearing record should replace no-DOI record."""
        rec1 = _make_record(doi="", title="Blue Economy Governance", source_id="no-doi")
        rec2 = _make_record(
            doi="10.1234/x",
            title="BLUE ECONOMY: GOVERNANCE!",
            source_id="with-doi",
        )
        deduped, stats = deduplicate_records([rec1, rec2])
        assert len(deduped) == 1
        assert deduped[0].doi == "10.1234/x"
        assert deduped[0].source_id == "with-doi"
        assert stats["doi_duplicates"] == 0
        assert stats["title_duplicates"] == 1

    def test_doi_title_dedup_is_order_independent(self):
        """The DOI-bearing variant must win regardless of input order."""
        title_only = _make_record(doi="", title="Blue Economy Governance")
        with_doi = _make_record(doi="10.1234/order", title="BLUE ECONOMY: GOVERNANCE!")

        first_pass, _ = deduplicate_records([title_only, with_doi])
        second_pass, _ = deduplicate_records([with_doi, title_only])

        assert len(first_pass) == 1
        assert len(second_pass) == 1
        assert first_pass[0].doi == "10.1234/order"
        assert second_pass[0].doi == "10.1234/order"

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

    def test_preserves_language_on_doi_winner_from_duplicate_candidate(self):
        rec1 = _make_record(doi="10.1234/lang", language="")
        rec2 = _make_record(doi="10.1234/lang", language="en", title="Other title")
        deduped, stats = deduplicate_records([rec1, rec2])
        assert len(deduped) == 1
        assert stats["doi_duplicates"] == 1
        assert deduped[0].language == "en"

    def test_preserves_language_when_upgrading_title_only_to_doi_record(self):
        title_only = _make_record(doi="", language="fr", source_id="no-doi")
        doi_record = _make_record(
            doi="10.1234/upgrade",
            language="",
            title=title_only.title,
            source_id="with-doi",
        )
        deduped, stats = deduplicate_records([title_only, doi_record])
        assert len(deduped) == 1
        assert stats["title_duplicates"] == 1
        assert deduped[0].doi == "10.1234/upgrade"
        assert deduped[0].language == "fr"


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


class TestApplyQueryConstraint:
    def test_missing_year_kept_without_time_window(self):
        records = [
            _make_record(year=""),
            _make_record(year="2024", doi="10.1234/y", source_id="crossref:y"),
        ]
        accepted, audit = _apply_query_constraint(
            records=records,
            constraint={"time_window": {}},
            provider_name="Crossref",
            max_results=10,
            physical_request_count=1,
        )
        assert len(accepted) == 2
        assert audit["excluded_missing_year_count"] == 0

    def test_missing_year_excluded_when_time_window_declared(self):
        records = [
            _make_record(year=""),
            _make_record(year="2024", doi="10.1234/y", source_id="crossref:y"),
        ]
        accepted, audit = _apply_query_constraint(
            records=records,
            constraint={"time_window": {"from_year": 2020, "to_year": 2026}},
            provider_name="Crossref",
            max_results=10,
            physical_request_count=1,
        )
        assert len(accepted) == 1
        assert accepted[0].year == "2024"
        assert audit["excluded_missing_year_count"] == 1

    def test_records_actual_attempted_pages_when_max_results_caps_sampling(self):
        accepted, audit = _apply_query_constraint(
            records=[_make_record(year="2024") for _ in range(60)],
            constraint={
                "time_window": {"from_year": 2020, "to_year": 2026},
                "sampling_strategy": {
                    "mode": "stratified",
                    "pages": 3,
                    "rows_per_page": 50,
                },
            },
            provider_name="Crossref",
            max_results=20,
            physical_request_count=1,
            attempted_logical_pages=1,
        )

        assert len(accepted) == 20
        assert audit["logical_pages_attempted"] == 1

    def test_malformed_page_diagnostics_do_not_abort_constraint_audit(self):
        accepted, audit = _apply_query_constraint(
            records=[_make_record(year="2024")],
            constraint={
                "time_window": {"from_year": 2020, "to_year": 2026},
                "sampling_strategy": {
                    "mode": "stratified",
                    "pages": 2,
                    "rows_per_page": 50,
                },
            },
            provider_name="Crossref",
            max_results=10,
            physical_request_count=1,
            page_diagnostics=[
                {
                    "logical_page": {"malformed": True},
                    "pagination_status": "applied",
                    "errors": "",
                    "warnings": "provider returned malformed page index",
                }
            ],
            attempted_logical_pages=2,
        )

        assert len(accepted) == 1
        assert audit["logical_pages_completed"] == 0
        assert audit["sampling_status"] == "partially_applied_pagination_incomplete"
        assert "filter_not_applied:multi_page_sampling" in audit["validity_warnings"]

    def test_normalise_page_diagnostics_converts_non_mapping_entries(self):
        diagnostics = _normalise_page_diagnostics(
            [None, "bad-diagnostic"],
            provider_name="Crossref",
            query="offshore wind",
        )

        assert len(diagnostics) == 2
        for idx, row in enumerate(diagnostics, start=1):
            assert row["provider"] == "crossref"
            assert row["query"] == "offshore wind"
            assert row["pagination_status"] == "failed"
            assert row["errors"] == "malformed_page_diagnostic_non_mapping"
            assert row["warnings"] == f"malformed_page_diagnostic_index:{idx}"

    def test_physical_request_count_uses_provider_result_not_diagnostics(self):
        """The provider count wins even when diagnostic rows disagree."""
        _, audit = _apply_query_constraint(
            records=[_make_record(year="2024")],
            constraint={
                "time_window": {"from_year": 2020, "to_year": 2026},
                "sampling_strategy": {"mode": "paginated", "pages": 1, "rows_per_page": 50},
            },
            provider_name="wos",
            max_results=100,
            physical_request_count=7,
            page_diagnostics=[
                {
                    "provider": "wos",
                    "logical_page": 1,
                    "physical_requests": 2,
                    "pagination_status": "applied",
                    "errors": "",
                }
            ],
            attempted_logical_pages=1,
        )
        assert audit["physical_request_count"] == 7

    def test_physical_request_count_never_falls_back_to_diagnostics(self):
        """Diagnostic indexes cannot create a provider request count."""
        _, audit = _apply_query_constraint(
            records=[_make_record(year="2024")],
            constraint={
                "time_window": {"from_year": 2020, "to_year": 2026},
                "sampling_strategy": {"mode": "paginated", "pages": 2, "rows_per_page": 50},
            },
            provider_name="openalex",
            max_results=100,
            physical_request_count=3,
            page_diagnostics=[
                {
                    "provider": "openalex",
                    "logical_page": 1,
                    "physical_request_index": 1,
                    "pagination_status": "applied",
                    "errors": "",
                },
                {
                    "provider": "openalex",
                    "logical_page": 2,
                    "physical_request_index": 2,
                    "pagination_status": "applied",
                    "errors": "",
                },
            ],
            attempted_logical_pages=2,
        )
        assert audit["physical_request_count"] == 3


def test_resolve_provider_sort_strategies_uses_declared_openalex_sort() -> None:
    resolved = _resolve_provider_sort_strategies(
        {"crossref": "published-desc", "scopus": "date-desc", "openalex": "date-desc"},
        ["Crossref", "OpenAlex"],
    )

    assert resolved == {
        "crossref": "published-desc",
        "openalex": "date-desc",
    }


def test_resolve_provider_sort_strategies_openalex_undeclared_returns_empty() -> None:
    resolved = _resolve_provider_sort_strategies(
        {"crossref": "published-desc", "scopus": "date-desc"},
        ["Crossref", "OpenAlex"],
    )

    assert resolved == {
        "crossref": "published-desc",
        "openalex": "",
    }


def test_provider_sort_strategy_source_uses_canonical_audit_values() -> None:
    assert _lookup_provider_sort_strategy_full(
        {"crossref": "published-desc"},
        "crossref",
    ) == ("published-desc", "published-desc", "declared")
    assert _lookup_provider_sort_strategy_full(
        {"scopus": "date-desc"},
        "openalex",
    ) == ("", "", "not_declared")
    assert _lookup_provider_sort_strategy_full({}, "wos") == (
        "",
        "",
        "not_declared",
    )


def test_effective_sampling_uses_complete_pages_or_one_reduced_page() -> None:
    assert _resolve_effective_sampling_request(
        declared_pages=3,
        declared_rows_per_page=50,
        max_results=120,
    ) == (2, 50)
    assert _resolve_effective_sampling_request(
        declared_pages=3,
        declared_rows_per_page=50,
        max_results=20,
    ) == (1, 20)


def test_search_registry_paginated_propagates_provider_typeerror() -> None:
    class Registry:
        def search_paginated(
            self,
            query: str,
            *,
            pages: int,
            rows_per_page: int,
            providers: list[str],
            sort_strategy_by_provider: dict[str, str],
            time_window: dict[str, int],
        ):
            del (
                query,
                pages,
                rows_per_page,
                providers,
                sort_strategy_by_provider,
                time_window,
            )
            raise TypeError("provider-side failure")

    try:
        _search_registry_paginated(
            Registry(),
            query="blue economy",
            pages=2,
            rows_per_page=50,
            providers=["crossref"],
            sort_strategy_by_provider={"crossref": "published-desc"},
            time_window={"from_year": 2020, "to_year": 2026},
        )
    except TypeError as exc:
        assert "provider-side failure" in str(exc)
    else:
        raise AssertionError(
            "provider TypeError must not be masked as legacy signature handling"
        )


class TestSentenceLevelClassification:
    def test_build_thematic_loop_audit_emits_sentence_classifications(self):
        rec = _make_record(
            title="Port logistics and maritime labour transitions",
            subject_terms=["shipping", "seafarer welfare"],
            source_id="crossref:10.1234/ctx",
        )
        provenance = [
            _make_evidence(record_id="crossref:10.1234/ctx", confidence_score=0.91)
        ]
        audit = build_thematic_loop_audit(
            records=[rec],
            provenance=provenance,
            support_by_identity={"doi:10.1234/blue": ["crossref"]},
            provider_classes={"crossref": "bibliographic"},
        )
        assert audit["records"]
        row = audit["records"][0]
        assert isinstance(row["sentence_classifications"], list)
        assert row["sentence_classifications"]
        assert row["sentence_classifications"][0]["text_scope"].startswith("live_api_")
        assert "sentence" not in row["sentence_classifications"][0]
        assert row["sentence_classifications"][0]["sentence_hash"]
        assert row["sentence_classifications"][0]["sentence_length"] > 0

    def test_classification_repository_caches_sentence_analysis(self):
        repo = LiveContextClassificationRepository()
        rec = _make_record(
            title="Port logistics and maritime labour transitions",
            subject_terms=["shipping", "seafarer welfare"],
            source_id="crossref:10.1234/cache",
        )
        classify_context = MagicMock(
            return_value={
                "axis": "MARITIME",
                "axis_code": "T",
                "text_scope": "live_api_title_sentence",
                "sentence": "Port logistics and maritime labour transitions",
                "matched_keywords": ["port"],
                "confidence_score": 0.95,
            }
        )
        repo._classifier.classify_context = classify_context  # type: ignore[method-assign]

        first = repo.classify_record_sentences(rec)
        second = repo.classify_record_sentences(rec)

        assert classify_context.call_count == 1
        assert first == second
        assert first is not second


class TestTriangulationPolicy:
    def test_keeps_unique_non_primary_records_and_supports_overlap(self):
        crossref_shared = _make_record(
            doi="10.1234/shared",
            source_id="crossref:10.1234/shared",
            provider="Crossref",
            title="Shared title",
        )
        scival_shared = _make_record(
            doi="10.1234/shared",
            source_id="scival:10.1234/shared",
            provider="SciVal",
            title="Shared title",
        )
        scival_unique = _make_record(
            doi="10.9999/unique",
            source_id="scival:10.9999/unique",
            provider="SciVal",
            title="Unique scival record",
        )

        policy = {
            "precedence": ["crossref", "scopus", "wos", "scival"],
            "primary_identity_providers": ["crossref", "scopus", "wos"],
        }
        merged_records, _, _, _, support_by_identity = triangulate_identity_loop(
            [crossref_shared, scival_shared, scival_unique], policy
        )

        dois = {r.doi for r in merged_records}
        assert "10.1234/shared" in dois
        assert "10.9999/unique" in dois
        assert any(
            r.provider == "SciVal" and r.doi == "10.9999/unique" for r in merged_records
        )
        assert set(support_by_identity["doi:10.1234/shared"]) == {"crossref", "scival"}

    def test_preserves_language_from_non_identity_candidate_on_winner(self, tmp_path):
        crossref_shared = _make_record(
            doi="10.1234/shared",
            source_id="crossref:10.1234/shared",
            provider="Crossref",
            title="Shared title",
            language="",
        )
        scival_shared = _make_record(
            doi="10.1234/shared",
            source_id="scival:10.1234/shared",
            provider="SciVal",
            title="Shared title",
            language="en",
        )
        policy = {
            "precedence": ["crossref", "scopus", "wos", "scival"],
            "primary_identity_providers": ["crossref", "scopus", "wos"],
        }
        merged_records, _, _, _, _ = triangulate_identity_loop(
            [crossref_shared, scival_shared], policy
        )
        assert len(merged_records) == 1
        assert merged_records[0].doi == "10.1234/shared"
        assert merged_records[0].language == "en"

        output_path = tmp_path / "live_records.json"
        export_records_json(merged_records, output_path)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload[0]["language"] == "en"

        stage1_row = _to_stage1_compliant_dict(merged_records[0])
        assert stage1_row["language"] == "en"

    def test_non_doi_source_id_fallback_preserves_language(self, tmp_path):
        record = _make_record(
            doi="",
            title="",
            source_id="drive:abc123",
            provider="Google Drive",
            language="pl",
        )
        policy = {
            "precedence": ["crossref", "scopus", "wos", "scival", "google_drive"],
            "primary_identity_providers": ["crossref", "scopus", "wos"],
        }
        merged_records, _, _, _, _ = triangulate_identity_loop([record], policy)
        assert len(merged_records) == 1
        assert merged_records[0].language == "pl"

        output_path = tmp_path / "live_records.json"
        export_records_json(merged_records, output_path)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload[0]["language"] == "pl"


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

    def test_export_raw_api_payloads_writes_envelope(self, tmp_path):
        """export_raw_api_payloads writes one file per (provider, query) pair."""
        from scripts.export_live_research_records import export_raw_api_payloads

        triples = [
            {
                "provider": "crossref",
                "query": "offshore wind",
                "raw_payload": {"message": {"items": [{"DOI": "10.1234/x"}]}},
            }
        ]
        count = export_raw_api_payloads(triples, tmp_path)
        assert count == 1
        raw_dir = tmp_path / "raw_api_payloads"
        assert raw_dir.is_dir()
        files = list(raw_dir.glob("*.json"))
        assert len(files) == 1
        envelope = json.loads(files[0].read_text())
        assert envelope["provider"] == "crossref"
        assert envelope["query"] == "offshore wind"
        assert "payload_sha256" in envelope
        assert len(envelope["payload_sha256"]) == 64
        assert envelope["payload"]["message"]["items"][0]["DOI"] == "10.1234/x"

    def test_export_raw_api_payloads_empty_triples(self, tmp_path):
        """export_raw_api_payloads returns 0 when no payloads are provided."""
        from scripts.export_live_research_records import export_raw_api_payloads

        count = export_raw_api_payloads([], tmp_path)
        assert count == 0
        assert not (tmp_path / "raw_api_payloads").exists()

    def test_export_raw_api_payloads_skips_none_payload(self, tmp_path):
        """Triples with raw_payload=None are silently skipped."""
        from scripts.export_live_research_records import export_raw_api_payloads

        triples = [{"provider": "crossref", "query": "test", "raw_payload": None}]
        count = export_raw_api_payloads(triples, tmp_path)
        assert count == 0


# ---------------------------------------------------------------------------
# Integration tests for main()
# ---------------------------------------------------------------------------


class TestMainIntegration:
    def test_legacy_default_query_file_falls_back_to_ad_hoc_constraints(
        self, tmp_path, monkeypatch
    ):
        """Legacy research_queries.yml should trigger ad-hoc constraints fallback."""
        query_file = tmp_path / "config" / "research_queries.yml"
        query_file.parent.mkdir(parents=True, exist_ok=True)
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test Sector"
    queries:
      - "test query"
""")
        constraints_file = (
            tmp_path
            / "outputs"
            / "research_sources"
            / "query_protocol_constraints.json"
        )
        constraints_file.parent.mkdir(parents=True, exist_ok=True)
        constraints_file.write_text(
            json.dumps(
                {
                    "query_count": 1,
                    "queries": [
                        {
                            "query_id": "OTHER",
                            "query_text": "other query",
                            "sector_slug": "other_sector",
                            "query_family": "discovery",
                        }
                    ],
                }
            )
        )
        output_dir = tmp_path / "out"
        fallback_called = False

        def _spy_build_ad_hoc_constraints(query_groups):
            nonlocal fallback_called
            fallback_called = True
            return {
                query_text.lower(): {
                    "query_id": f"{group_name}_Q{idx + 1}",
                    "sector_slug": group_name,
                    "query_family": "legacy_projection",
                }
                for group_name, sector_data in query_groups.items()
                for idx, query_text in enumerate(sector_data["queries"])
            }

        monkeypatch.setattr(
            "scripts.export_live_research_records._build_ad_hoc_constraints_from_query_groups",
            _spy_build_ad_hoc_constraints,
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "sys.argv",
            [
                "export_live_research_records.py",
                "--output-dir",
                str(output_dir),
                "--offline",
                "true",
            ],
        )

        result = main()

        assert result == 0
        assert fallback_called

    def test_protocol_projected_query_never_falls_back_to_ad_hoc_constraints(
        self, tmp_path, monkeypatch, capsys
    ):
        """Protocol projections must fail on constraints mismatch instead of fallback."""
        query_file = (
            tmp_path
            / "outputs"
            / "research_sources"
            / "research_queries_from_protocol.yml"
        )
        query_file.parent.mkdir(parents=True, exist_ok=True)
        query_file.write_text("""
query_groups:
  maritime_transport:
    label: "Maritime Transport"
    queries:
      - "port decarbonization maritime workforce"
""")
        constraints_file = (
            tmp_path
            / "outputs"
            / "research_sources"
            / "query_protocol_constraints.json"
        )
        constraints_file.parent.mkdir(parents=True, exist_ok=True)
        constraints_file.write_text(
            json.dumps(
                {
                    "query_count": 1,
                    "queries": [
                        {
                            "query_id": "OTHER",
                            "query_text": "other query",
                            "sector_slug": "other_sector",
                            "query_family": "discovery",
                        }
                    ],
                }
            )
        )
        output_dir = tmp_path / "out"

        monkeypatch.chdir(tmp_path)
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

        result = main()
        captured = capsys.readouterr()

        assert result == 1
        assert (
            "authoritative protocol projection and constraints differ" in captured.err
        )

    def test_offline_mode_skips_network_calls(self, tmp_path, monkeypatch):
        """Test that offline mode produces empty outputs without network calls."""
        # Create minimal query file
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test Sector"
    queries:
      - "test query"
""")

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
        assert (output_dir / "live_records_triangulated.json").exists()
        assert (output_dir / "live_records.csv").exists()
        assert (output_dir / "crossref_records.json").exists()
        assert (output_dir / "raw_provider_records.json").exists()
        assert (output_dir / "enrichment_records.json").exists()
        assert (output_dir / "live_provenance.json").exists()
        assert (output_dir / "live_source_coverage.csv").exists()
        assert (output_dir / "low_confidence_live_records.json").exists()
        assert (output_dir / "triangulation_identity_loop.json").exists()
        assert (output_dir / "triangulation_thematic_loop.json").exists()

        # Check that outputs are empty
        records = json.loads((output_dir / "live_records.json").read_text())
        assert len(records) == 0

    def test_protocol_projection_119_queries_fails_before_provider_setup(
        self, tmp_path, monkeypatch, capsys
    ):
        repo_root = Path(__file__).resolve().parents[1]
        protocol_path = repo_root / "config" / "live_query_protocol.yml"
        protocol = load_live_query_protocol(protocol_path)
        constraints = protocol.to_query_constraints()[:-1]
        dropped_query_text = protocol.to_query_constraints()[-1]["query_text"]
        legacy_projection = protocol.to_legacy_query_groups()
        for group in legacy_projection["query_groups"].values():
            group["queries"] = [
                query for query in group["queries"] if query != dropped_query_text
            ]
        query_file = tmp_path / PROTOCOL_PROJECTED_QUERY_FILE_NAME
        query_file.write_text(
            yaml.safe_dump(legacy_projection, sort_keys=False), encoding="utf-8"
        )
        constraints_file = tmp_path / "query_protocol_constraints.json"
        constraints_file.write_text(
            json.dumps(
                {
                    "protocol_version": protocol.protocol_version,
                    "query_count": len(constraints),
                    "queries": constraints,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        with patch("scripts.export_live_research_records.SourceRegistry") as registry:
            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--query-constraints-file",
                    str(constraints_file),
                    "--protocol-path",
                    str(protocol_path),
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--offline",
                    "false",
                    "--providers",
                    "crossref",
                ],
            )

            result = main()

        captured = capsys.readouterr()
        assert result == 1
        registry.assert_not_called()
        assert "exactly 120 queries" in captured.err

    @pytest.mark.parametrize(
        "field_name",
        [
            "query_text",
            "sector_slug",
            "query_family",
            "axis_target",
            "evidence_intent",
            "time_window",
            "sort_strategy",
            "sampling_strategy",
            "protocol_version",
        ],
    )
    def test_protocol_projection_field_mismatch_fails_before_provider_setup(
        self, field_name, tmp_path, monkeypatch
    ):
        repo_root = Path(__file__).resolve().parents[1]
        protocol_path = repo_root / "config" / "live_query_protocol.yml"
        protocol = load_live_query_protocol(protocol_path)
        constraints = json.loads(json.dumps(protocol.to_query_constraints()))
        first = constraints[0]
        payload = {
            "protocol_version": protocol.protocol_version,
            "query_count": len(constraints),
            "queries": constraints,
        }
        if field_name == "query_text":
            first["query_text"] = f"{first['query_text']} stale"
        elif field_name == "sector_slug":
            first["sector_slug"] = "wrong_sector"
        elif field_name == "query_family":
            first["query_family"] = "wrong_family"
        elif field_name == "axis_target":
            first["axis_target"] = (
                "MARITIME" if first["axis_target"] != "MARITIME" else "OCEANIC"
            )
        elif field_name == "evidence_intent":
            first["evidence_intent"] = "wrong_intent"
        elif field_name == "time_window":
            first["time_window"] = {"from_year": 1900, "to_year": 1901}
        elif field_name == "sort_strategy":
            first["sort_strategy"] = {
                "crossref": "relevance",
                "scopus": "relevance",
                "wos": "relevance",
            }
        elif field_name == "sampling_strategy":
            first["sampling_strategy"] = {
                "mode": "stratified",
                "pages": int(first["sampling_strategy"]["pages"]) + 1,
                "rows_per_page": first["sampling_strategy"]["rows_per_page"],
                "dedupe_key": first["sampling_strategy"]["dedupe_key"],
            }
        elif field_name == "protocol_version":
            payload["protocol_version"] = "0.0.0"
        query_file = tmp_path / PROTOCOL_PROJECTED_QUERY_FILE_NAME
        query_file.write_text(
            yaml.safe_dump(protocol.to_legacy_query_groups(), sort_keys=False),
            encoding="utf-8",
        )
        constraints_file = tmp_path / "query_protocol_constraints.json"
        constraints_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        with patch("scripts.export_live_research_records.SourceRegistry") as registry:
            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--query-constraints-file",
                    str(constraints_file),
                    "--protocol-path",
                    str(protocol_path),
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--offline",
                    "false",
                    "--providers",
                    "crossref",
                ],
            )

            result = main()

        assert result == 1
        registry.assert_not_called()

    def test_live_mode_uses_paginated_registry_search(self, tmp_path, monkeypatch):
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  offshore_energy:
    label: "Offshore Energy"
    queries:
      - "offshore wind"
""",
            encoding="utf-8",
        )
        constraints_file = tmp_path / "constraints.json"
        constraints_file.write_text(
            json.dumps(
                {
                    "query_count": 1,
                    "queries": [
                        {
                            "query_id": "Q_TEST_001",
                            "query_text": "offshore wind",
                            "sector_slug": "offshore_energy",
                            "query_family": "core_sector",
                            "time_window": {"from_year": 2019, "to_year": 2026},
                            "sort_strategy": {"crossref": "published-desc"},
                            "sampling_strategy": {
                                "mode": "stratified",
                                "pages": 3,
                                "rows_per_page": 1,
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        output_dir = tmp_path / "outputs"
        mock_record = _make_record(
            title="Offshore Wind Energy",
            doi="10.1234/wind",
            source_id="crossref:10.1234/wind",
        )
        mock_evidence = _make_evidence(
            record_id="crossref:10.1234/wind", query="offshore wind"
        )
        mock_result = ProviderResult(
            records=[mock_record],
            provenance=[mock_evidence],
            physical_request_count=7,
            page_diagnostics=[
                {
                    "provider": "crossref",
                    "query": "offshore wind",
                    "logical_page": 1,
                    "physical_request_index": 1,
                    "cursor_or_offset": "*",
                    "requested_rows": 1,
                    "returned_rows": 1,
                    "normalized_rows": 1,
                    "pagination_status": "applied",
                },
                {
                    "provider": "crossref",
                    "query": "offshore wind",
                    "logical_page": 2,
                    "physical_request_index": 2,
                    "cursor_or_offset": "sha256:two",
                    "requested_rows": 1,
                    "returned_rows": 1,
                    "normalized_rows": 1,
                    "pagination_status": "applied",
                },
                {
                    "provider": "crossref",
                    "query": "offshore wind",
                    "logical_page": 3,
                    "physical_request_index": 3,
                    "cursor_or_offset": "sha256:three",
                    "requested_rows": 1,
                    "returned_rows": 1,
                    "normalized_rows": 1,
                    "pagination_status": "applied",
                },
            ],
        )
        seen: dict[str, object] = {}

        def mock_search_paginated(
            query,
            *,
            pages,
            rows_per_page,
            providers,
            sort_strategy_by_provider,
            time_window,
        ):
            seen.update(
                {
                    "query": query,
                    "pages": pages,
                    "rows_per_page": rows_per_page,
                    "providers": providers,
                    "sort_strategy_by_provider": sort_strategy_by_provider,
                    "time_window": time_window,
                }
            )
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = mock_search_paginated
            mock_instance.search.side_effect = AssertionError("old search path used")
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
            MockRegistry.return_value = mock_instance
            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--query-constraints-file",
                    str(constraints_file),
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
        assert seen["pages"] == 3
        assert seen["rows_per_page"] == 1
        assert seen["providers"] == ["crossref"]
        rows = json.loads(
            (output_dir / "provider_pagination_diagnostics.json").read_text()
        )
        assert [row["logical_page"] for row in rows] == [1, 2, 3]
        execution_rows = list(
            csv.DictReader(
                (output_dir / "query_execution_log.csv").read_text().splitlines()
            )
        )
        assert execution_rows[0]["sampling_status"] == "applied_logical_pagination"
        assert execution_rows[0]["physical_request_count"] == "7"

    def test_empty_paginated_result_fails_without_publishing_or_registry_fallback(
        self, tmp_path, monkeypatch
    ):
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "empty-result query"
""",
            encoding="utf-8",
        )
        output_dir = tmp_path / "outputs"
        paginated_calls = 0

        def mock_search_paginated(
            query,
            *,
            pages,
            rows_per_page,
            providers,
            sort_strategy_by_provider,
            time_window,
        ):
            nonlocal paginated_calls
            del (
                query,
                pages,
                rows_per_page,
                providers,
                sort_strategy_by_provider,
                time_window,
            )
            paginated_calls += 1
            return []

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = mock_search_paginated
            mock_instance.search.side_effect = AssertionError("unpaginated fallback used")
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
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

            assert main() == 1

        assert paginated_calls == 1
        mock_instance.search.assert_not_called()
        assert not output_dir.exists()

    @pytest.mark.parametrize("invalid_count", [True, 1.0, -1, "1"])
    def test_main_fails_closed_for_invalid_provider_request_count(
        self, invalid_count, tmp_path, monkeypatch, capsys
    ):
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "invalid-count query"
""",
            encoding="utf-8",
        )
        mock_result = ProviderResult(physical_request_count=invalid_count)
        paginated_calls = 0

        def mock_search_paginated(
            query,
            *,
            pages,
            rows_per_page,
            providers,
            sort_strategy_by_provider,
            time_window,
        ):
            nonlocal paginated_calls
            del (
                query,
                pages,
                rows_per_page,
                providers,
                sort_strategy_by_provider,
                time_window,
            )
            paginated_calls += 1
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = mock_search_paginated
            mock_instance.search.side_effect = AssertionError("unpaginated fallback used")
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
            MockRegistry.return_value = mock_instance
            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--output-dir",
                    str(tmp_path / "outputs"),
                    "--offline",
                    "false",
                    "--providers",
                    "crossref",
                ],
            )

            assert main() == 1

        assert paginated_calls == 1
        mock_instance.search.assert_not_called()
        assert "provider result contract failed" in capsys.readouterr().err

    @pytest.mark.parametrize("invalid_diagnostics", [{}, ["not-a-mapping"]])
    def test_main_fails_closed_for_malformed_page_diagnostics(
        self, invalid_diagnostics, tmp_path, monkeypatch, capsys
    ):
        query_file = tmp_path / "queries.yml"
        query_file.write_text(
            """
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "malformed-diagnostic query"
""",
            encoding="utf-8",
        )
        mock_result = ProviderResult(
            physical_request_count=1,
            page_diagnostics=invalid_diagnostics,
        )
        paginated_calls = 0

        def mock_search_paginated(
            query,
            *,
            pages,
            rows_per_page,
            providers,
            sort_strategy_by_provider,
            time_window,
        ):
            nonlocal paginated_calls
            del (
                query,
                pages,
                rows_per_page,
                providers,
                sort_strategy_by_provider,
                time_window,
            )
            paginated_calls += 1
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = mock_search_paginated
            mock_instance.search.side_effect = AssertionError("unpaginated fallback used")
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
            MockRegistry.return_value = mock_instance
            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--output-dir",
                    str(tmp_path / "outputs"),
                    "--offline",
                    "false",
                    "--providers",
                    "crossref",
                ],
            )

            assert main() == 1

        assert paginated_calls == 1
        mock_instance.search.assert_not_called()
        assert "provider result contract failed" in capsys.readouterr().err

    def test_apply_query_constraint_rejects_replayed_page_tokens(self):
        records = [
            _make_record(title=f"Record {idx}", doi=f"10.1234/{idx}")
            for idx in range(3)
        ]
        constraint = {
            "time_window": {"from_year": 2019, "to_year": 2026},
            "sort_strategy": {"crossref": "published-desc"},
            "sampling_strategy": {
                "mode": "stratified",
                "pages": 3,
                "rows_per_page": 1,
            },
        }
        page_diagnostics = [
            {
                "logical_page": page,
                "physical_request_index": page,
                "cursor_or_offset": "*",
                "requested_rows": 1,
                "returned_rows": 1,
                "normalized_rows": 1,
                "pagination_status": "applied",
            }
            for page in (1, 2, 3)
        ]

        _accepted, audit = _apply_query_constraint(
            records,
            constraint,
            "crossref",
            max_results=50,
            physical_request_count=3,
            page_diagnostics=page_diagnostics,
        )

        assert audit["sampling_status"] == "invalid_replayed_page"
        assert "invalid_sampling:replayed_page" in audit["validity_warnings"]
        assert "sampling_strategy" in audit["unapplied_constraint_filters"]

    def test_live_mode_with_mocked_registry(self, tmp_path, monkeypatch):
        """Test live mode with mocked SourceRegistry returning synthetic records."""
        # Create minimal query file
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  offshore_energy:
    label: "Offshore Energy"
    queries:
      - "offshore wind"
""")

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
            records=[mock_record], provenance=[mock_evidence], physical_request_count=1
        )

        def mock_search(query, max_results, providers):
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
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

            triangulated = json.loads(
                (output_dir / "live_records_triangulated.json").read_text()
            )
            assert len(triangulated) == 1
            assert triangulated[0]["sentence_classifications"]
            assert triangulated[0]["sentence_classifications"][0][
                "text_scope"
            ].startswith("live_api_")
            assert "sentence" not in triangulated[0]["sentence_classifications"][0]
            assert triangulated[0]["sentence_classifications"][0]["sentence_hash"]

            provenance = json.loads((output_dir / "live_provenance.json").read_text())
            assert len(provenance) == 1

    def test_live_mode_cold_cache_writes_raw_payloads(self, tmp_path, monkeypatch):
        """When providers return raw_payload, raw_api_payloads/ directory is created."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  offshore_energy:
    label: "Offshore Energy"
    queries:
      - "offshore wind"
""")
        output_dir = tmp_path / "outputs"

        mock_record = _make_record(
            title="Offshore Wind Energy",
            doi="10.1234/wind",
            source_id="crossref:10.1234/wind",
        )
        mock_evidence = _make_evidence(
            record_id="crossref:10.1234/wind", query="offshore wind"
        )
        raw_payload = {
            "message": {
                "items": [{"DOI": "10.1234/wind", "title": ["Offshore Wind Energy"]}]
            }
        }
        mock_result = ProviderResult(
            records=[mock_record],
            provenance=[mock_evidence],
            raw_payload=raw_payload,
            physical_request_count=1,
        )

        def mock_search(query, max_results, providers):
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
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

            result = main()
            assert result == 0

        raw_dir = output_dir / "raw_api_payloads"
        assert raw_dir.is_dir(), "raw_api_payloads/ directory must be created"
        payload_files = list(raw_dir.glob("*.json"))
        assert len(payload_files) >= 1, "At least one raw payload file must be written"
        envelope = json.loads(payload_files[0].read_text())
        assert envelope["provider"] == "crossref"
        assert envelope["query"] == "offshore wind"
        assert "payload_sha256" in envelope
        assert envelope["payload"] == raw_payload

    def test_live_records_triangulated_keeps_unique_non_primary_records(
        self, tmp_path, monkeypatch
    ):
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  offshore_energy:
    label: "Offshore Energy"
    queries:
      - "offshore wind"
""")

        output_dir = tmp_path / "outputs"

        crossref_record = _make_record(
            title="Crossref shared",
            doi="10.1234/shared",
            source_id="crossref:10.1234/shared",
            provider="Crossref",
        )
        scival_record = _make_record(
            title="SciVal unique",
            doi="10.9999/unique",
            source_id="scival:10.9999/unique",
            provider="SciVal",
        )
        crossref_ev = _make_evidence(
            record_id="crossref:10.1234/shared",
            source_provider="Crossref",
        )
        scival_ev = _make_evidence(
            record_id="scival:10.9999/unique",
            source_provider="SciVal",
        )
        mock_crossref_result = ProviderResult(
            records=[crossref_record],
            provenance=[crossref_ev],
            physical_request_count=1,
        )
        mock_scival_result = ProviderResult(
            records=[scival_record],
            provenance=[scival_ev],
            physical_request_count=1,
        )

        def mock_search(query, max_results, providers):
            return [mock_crossref_result, mock_scival_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability(
                "crossref", "scival"
            )
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
                    "crossref,scival",
                ],
            )

            result = main()
            assert result == 0

            live_triangulated = json.loads(
                (output_dir / "live_records_triangulated.json").read_text()
            )
            assert len(live_triangulated) == 2
            assert any(
                row["provider"] == "SciVal" and row["doi"] == "10.9999/unique"
                for row in live_triangulated
            )

    def test_deduplication_in_main(self, tmp_path, monkeypatch):
        """Test that duplicate records are removed in main."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
      - "query2"
""")

        output_dir = tmp_path / "outputs"

        # Mock two identical records from different queries
        mock_record = _make_record(doi="10.1234/same")
        mock_evidence = _make_evidence()
        mock_result = ProviderResult(
            records=[mock_record], provenance=[mock_evidence], physical_request_count=1
        )

        def mock_search(query, max_results, providers):
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
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
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
""")

        output_dir = tmp_path / "outputs"

        # Mock record with low-confidence provenance
        mock_record = _make_record(doi="10.1234/low", source_id="crossref:10.1234/low")
        mock_evidence = _make_evidence(
            record_id="crossref:10.1234/low", confidence_score=0.5
        )
        mock_result = ProviderResult(
            records=[mock_record], provenance=[mock_evidence], physical_request_count=1
        )

        def mock_search(query, max_results, providers):
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
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
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
""")

        output_dir = tmp_path / "outputs"

        # Mock records from different providers
        crossref_rec = _make_record(provider="Crossref", doi="10.1234/cr")
        scopus_rec = _make_record(
            provider="Scopus", doi="10.1234/sc", source_id="scopus:10.1234/sc"
        )
        mock_evidence = _make_evidence()
        mock_result_cr = ProviderResult(
            records=[crossref_rec], provenance=[mock_evidence], physical_request_count=1
        )
        mock_result_sc = ProviderResult(
            records=[scopus_rec], provenance=[mock_evidence], physical_request_count=1
        )

        def mock_search(query, max_results, providers):
            return [mock_result_cr, mock_result_sc]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability(
                "crossref", "scopus"
            )
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
                    "crossref,scopus",
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

            # Verify live_records.json applies provider-priority triangulation
            all_records = json.loads((output_dir / "live_records.json").read_text())
            assert len(all_records) == 1
            assert all_records[0]["provider"] == "Crossref"
            assert (output_dir / "triangulation_identity_loop.json").exists()
            assert (output_dir / "triangulation_thematic_loop.json").exists()

    def test_empty_query_file_returns_error(self, tmp_path, monkeypatch, capsys):
        """An empty YAML file must return error code 1 with a user-facing message."""
        query_file = tmp_path / "empty.yml"
        query_file.write_text("")

        output_dir = tmp_path / "outputs"

        monkeypatch.setattr(
            "sys.argv",
            [
                "export_live_research_records.py",
                "--query-file",
                str(query_file),
                "--output-dir",
                str(output_dir),
            ],
        )

        result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "is empty or not a valid YAML mapping" in captured.err

    def test_comment_only_query_file_returns_error(self, tmp_path, monkeypatch, capsys):
        """A comment-only YAML file (yaml.safe_load returns None) must return error code 1."""
        query_file = tmp_path / "comments.yml"
        query_file.write_text("# just a comment\n# no data here\n")

        output_dir = tmp_path / "outputs"

        monkeypatch.setattr(
            "sys.argv",
            [
                "export_live_research_records.py",
                "--query-file",
                str(query_file),
                "--output-dir",
                str(output_dir),
            ],
        )

        result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "is empty or not a valid YAML mapping" in captured.err

    def test_invalid_yaml_syntax_returns_parse_error(
        self, tmp_path, monkeypatch, capsys
    ):
        """A YAML file with a syntax error must return error code 1 with a parse error."""
        query_file = tmp_path / "bad_syntax.yml"
        query_file.write_text("query_groups:\n- [unclosed list\n  key: value\n")

        output_dir = tmp_path / "outputs"

        monkeypatch.setattr(
            "sys.argv",
            [
                "export_live_research_records.py",
                "--query-file",
                str(query_file),
                "--output-dir",
                str(output_dir),
            ],
        )

        result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Failed to parse" in captured.err
        assert "Syntactically invalid YAML" in captured.err
        assert str(query_file) in captured.err

    def test_scalar_query_file_returns_error(self, tmp_path, monkeypatch, capsys):
        """A YAML file containing only a scalar (not a dict) must return error code 1."""
        query_file = tmp_path / "scalar.yml"
        query_file.write_text("just a string\n")

        output_dir = tmp_path / "outputs"

        monkeypatch.setattr(
            "sys.argv",
            [
                "export_live_research_records.py",
                "--query-file",
                str(query_file),
                "--output-dir",
                str(output_dir),
            ],
        )

        result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "is empty or not a valid YAML mapping" in captured.err

    def test_zero_record_provider_identity_in_coverage(self, tmp_path, monkeypatch):
        """Zero-record provider results must preserve provider identity in coverage CSV."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test Sector"
    queries:
      - "blue economy"
""")

        output_dir = tmp_path / "outputs"

        # Provider returns an empty ProviderResult (zero records, zero provenance)
        empty_result = ProviderResult(
            records=[], provenance=[], physical_request_count=1
        )

        def mock_search(query, max_results, providers):
            return [empty_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
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

    def test_legacy_adapter_preserves_canonical_skipped_zero_request_count(
        self, tmp_path, monkeypatch
    ):
        """A valid pre-network zero remains provider-owned through export."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test Sector"
    queries:
      - "blue economy"
""")
        output_dir = tmp_path / "outputs"
        skipped_result = ProviderResult(
            records=[],
            provenance=[],
            physical_request_count=0,
            page_diagnostics=[{"pagination_status": "skipped"}],
        )

        def mock_search(query, max_results, providers):
            return [skipped_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
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

            assert main() == 0

        execution_rows = list(
            csv.DictReader(
                (output_dir / "query_execution_log.csv").read_text().splitlines()
            )
        )
        assert skipped_result.physical_request_count == 0
        assert execution_rows[0]["physical_request_count"] == "0"

    def test_reversed_cli_provider_order_uses_registry_order_in_coverage(
        self, tmp_path, monkeypatch
    ):
        """Coverage provider labels must follow registry order, not raw CLI order."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test Sector"
    queries:
      - "blue economy"
""")

        output_dir = tmp_path / "outputs"
        crossref_rec = _make_record(
            provider="Crossref",
            doi="10.1111/crossref",
            source_id="crossref:10.1111/c",
        )
        scopus_rec = _make_record(
            provider="Scopus",
            doi="10.2222/scopus",
            source_id="scopus:10.2222/s",
        )
        crossref_result = ProviderResult(
            records=[crossref_rec], provenance=[], physical_request_count=1
        )
        scopus_result = ProviderResult(
            records=[scopus_rec], provenance=[], physical_request_count=1
        )

        def mock_search(query, max_results, providers):
            assert providers == ["scopus", "crossref"]
            return [crossref_result, scopus_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability(
                "crossref", "scopus"
            )
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
                    "scopus,crossref",
                ],
            )

            result = main()
            assert result == 0

            import csv as csv_module

            with open(output_dir / "live_source_coverage.csv", newline="") as f:
                rows = list(csv_module.DictReader(f))

            assert len(rows) == 2
            assert rows[0]["provider"] == "crossref"
            assert rows[1]["provider"] == "scopus"

    def test_query_execution_log_includes_scopus_diagnostics_columns(
        self, tmp_path, monkeypatch
    ):
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test Sector"
    queries:
      - "blue economy"
""")
        output_dir = tmp_path / "outputs"
        scopus_rec = _make_record(
            provider="Scopus",
            doi="10.1000/scopus.1",
            source_id="scopus:10.1000/scopus.1",
        )
        scopus_result = ProviderResult(
            records=[scopus_rec], provenance=[], physical_request_count=1
        )

        def mock_search(query, max_results, providers):
            assert providers == ["scopus"]
            return [scopus_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability("scopus")
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
                    "scopus",
                ],
            )
            result = main()
            assert result == 0

        import csv as csv_module

        with open(output_dir / "query_execution_log.csv", newline="") as f:
            rows = list(csv_module.DictReader(f))
        assert rows
        row = rows[0]
        for field in (
            "provider_canonical",
            "returned_record_count",
            "normalized_record_count",
            "contributed_record_count",
            "requested_constraint_filters",
            "applied_constraint_filters",
            "unsupported_constraint_filters",
            "unapplied_constraint_filters",
        ):
            assert field in QUERY_EXECUTION_FIELDS
            assert field in row
        assert row["provider_canonical"] == "scopus"
        assert row["returned_record_count"] == "1"
        assert row["normalized_record_count"] == "1"
        assert row["contributed_record_count"] == "1"
        assert "time_window" in row["requested_constraint_filters"]
        assert "sampling_strategy" in row["requested_constraint_filters"]
        assert "time_window" in row["applied_constraint_filters"]
        assert row["unsupported_constraint_filters"] == ""
        assert "sort_strategy" in row["unapplied_constraint_filters"]

        diagnostics = json.loads(
            (output_dir / "scopus_query_diagnostics.json").read_text()
        )
        assert len(diagnostics) == 1
        assert diagnostics[0]["provider_canonical"] == "scopus"
        assert diagnostics[0]["contributed_record_count"] == 1

    def test_unknown_provider_returns_error(self, tmp_path, monkeypatch, capsys):
        """An unrecognised provider name must return error code 1 with a clear message."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
""")

        output_dir = tmp_path / "outputs"

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.list_capabilities.return_value = _make_capability(
                "crossref", "scopus"
            )
            MockRegistry.return_value = mock_instance

            monkeypatch.setattr(
                "sys.argv",
                [
                    "export_live_research_records.py",
                    "--query-file",
                    str(query_file),
                    "--output-dir",
                    str(output_dir),
                    "--providers",
                    "crossreff",
                ],
            )

            result = main()
            assert result == 1
            captured = capsys.readouterr()
            assert "Unknown provider" in captured.err
            assert "crossreff" in captured.err

    def test_mixed_case_provider_is_normalised(self, tmp_path, monkeypatch):
        """Provider names like 'Crossref' should be normalised to lowercase and accepted."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
""")

        output_dir = tmp_path / "outputs"
        mock_result = ProviderResult(records=[], provenance=[], physical_request_count=1)

        def mock_search(query, max_results, providers):
            assert providers == ["crossref"]
            return [mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability("crossref")
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
                    "Crossref",
                ],
            )

            result = main()
            assert result == 0

    def test_all_provider_token_expands_to_registry_providers(
        self, tmp_path, monkeypatch
    ):
        """--providers all should query all known providers in registry order."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test Sector"
    queries:
      - "blue economy"
""")

        output_dir = tmp_path / "outputs"
        mock_result = ProviderResult(records=[], provenance=[], physical_request_count=1)
        seen_providers = []

        def mock_search(query, max_results, providers):
            seen_providers.append(providers)
            return [mock_result, mock_result]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability(
                "crossref", "scopus"
            )
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
                    "all",
                ],
            )

            result = main()
            assert result == 0
            assert seen_providers == [["crossref", "scopus"]]

    def test_comma_separated_providers_are_trimmed_and_normalised(
        self, tmp_path, monkeypatch
    ):
        """Comma-separated providers with spaces should be lowercased before search."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
""")

        output_dir = tmp_path / "outputs"
        mock_result_crossref = ProviderResult(
            records=[], provenance=[], physical_request_count=1
        )
        mock_result_scopus = ProviderResult(
            records=[], provenance=[], physical_request_count=1
        )

        def mock_search(query, max_results, providers):
            assert providers == ["crossref", "scopus"]
            return [mock_result_crossref, mock_result_scopus]

        with patch(
            "scripts.export_live_research_records.SourceRegistry"
        ) as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.search_paginated = _adapt_legacy_search_for_paginated_dispatch(
                mock_search
            )
            mock_instance.list_capabilities.return_value = _make_capability(
                "crossref", "scopus"
            )
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
                    " Crossref, Scopus ",
                ],
            )

            result = main()
            assert result == 0

    def test_empty_providers_string_returns_error(self, tmp_path, monkeypatch, capsys):
        """Passing an empty string for --providers must return error code 1."""
        query_file = tmp_path / "queries.yml"
        query_file.write_text("""
query_groups:
  test_sector:
    label: "Test"
    queries:
      - "query1"
""")

        output_dir = tmp_path / "outputs"

        monkeypatch.setattr(
            "sys.argv",
            [
                "export_live_research_records.py",
                "--query-file",
                str(query_file),
                "--output-dir",
                str(output_dir),
                "--providers",
                "",
            ],
        )

        result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "--providers must not be empty" in captured.err


# ---------------------------------------------------------------------------
# Stage 1 governance compliance tests
# ---------------------------------------------------------------------------


class TestStage1ComplianceFilter:
    """Verify that _to_stage1_compliant_dict enforces Stage 1 metadata rules.

    Rules sourced from docs/licensing_and_compliance.md:
    - Retained: title, authors, year, doi, source_id, provider, journal,
      language, url, subject_terms, source_query, retrieval_timestamp, licence_note.
    - Dropped: citation_count (institutional-provider restriction),
      abstract_available, abstract_stored (misleading flags for 3rd parties).
    """

    def _make_full_record(self, **kwargs) -> LiteratureRecord:
        """Return a LiteratureRecord with all fields populated."""
        defaults = dict(
            title="Maritime Governance Study",
            authors="J. Smith",
            year="2024",
            doi="10.0001/test",
            source_id="crossref:10.0001/test",
            provider="Crossref",
            journal="Ocean Studies",
            url="https://doi.org/10.0001/test",
            abstract_available=True,
            abstract_stored=False,
            citation_count=42,
            subject_terms=["governance", "blue economy"],
            source_query="maritime governance",
            retrieval_timestamp="2024-01-01T00:00:00Z",
            licence_note="Crossref — freely redistributable",
        )
        defaults.update(kwargs)
        return LiteratureRecord(**defaults)

    def test_permitted_fields_are_present(self):
        """All Stage 1 permitted bibliographic fields must appear in the output."""
        rec = self._make_full_record()
        result = _to_stage1_compliant_dict(rec)
        for field in (
            "title",
            "authors",
            "year",
            "doi",
            "source_id",
            "provider",
            "language",
            "journal",
            "url",
            "subject_terms",
            "source_query",
            "retrieval_timestamp",
            "licence_note",
        ):
            assert field in result, f"Expected permitted field '{field}' to be present"

    def test_citation_count_is_dropped(self):
        """citation_count must not appear — restricted for institutional providers."""
        rec = self._make_full_record(citation_count=99)
        result = _to_stage1_compliant_dict(rec)
        assert "citation_count" not in result, (
            "citation_count must be dropped per docs/licensing_and_compliance.md "
            "Category 2/3 institutional-provider restrictions"
        )

    def test_abstract_available_flag_is_dropped(self):
        """abstract_available flag must not be exported — could mislead redistributors."""
        rec = self._make_full_record(abstract_available=True)
        result = _to_stage1_compliant_dict(rec)
        assert "abstract_available" not in result, (
            "abstract_available must be dropped per Stage 1 compliance "
            "(docs/licensing_and_compliance.md — never store abstract content signals)"
        )

    def test_abstract_stored_flag_is_dropped(self):
        """abstract_stored flag must not be exported."""
        rec = self._make_full_record(abstract_stored=True)
        result = _to_stage1_compliant_dict(rec)
        assert "abstract_stored" not in result

    def test_compliant_dict_field_values_match_record(self):
        """Retained field values must match the source record exactly."""
        rec = self._make_full_record(
            title="Test Title",
            authors="A. Author",
            doi="10.9999/x",
            language="pl",
            subject_terms=["fisheries"],
            licence_note="open",
        )
        result = _to_stage1_compliant_dict(rec)
        assert result["title"] == "Test Title"
        assert result["authors"] == "A. Author"
        assert result["doi"] == "10.9999/x"
        assert result["language"] == "pl"
        assert result["subject_terms"] == ["fisheries"]
        assert result["licence_note"] == "open"

    def test_json_export_omits_restricted_fields(self, tmp_path):
        """JSON export must not contain citation_count or abstract fields."""
        rec = self._make_full_record(citation_count=10, abstract_available=True)
        output_path = tmp_path / "out.json"
        export_records_json([rec], output_path)
        import json as _json

        data = _json.loads(output_path.read_text())
        assert len(data) == 1
        row = data[0]
        assert "citation_count" not in row
        assert "abstract_available" not in row
        assert "abstract_stored" not in row

    def test_csv_export_omits_restricted_fields(self, tmp_path):
        """CSV export must not contain citation_count or abstract field columns."""
        import csv as _csv

        rec = self._make_full_record(citation_count=7, abstract_stored=True)
        output_path = tmp_path / "out.csv"
        export_records_csv([rec], output_path)
        with open(output_path, newline="") as f:
            reader = _csv.DictReader(f)
            headers = reader.fieldnames or []
        assert "citation_count" not in headers
        assert "abstract_available" not in headers
        assert "abstract_stored" not in headers

    def test_csv_export_includes_licence_note(self, tmp_path):
        """CSV export must include licence_note column (added by Stage 1 compliance)."""
        import csv as _csv

        rec = self._make_full_record(licence_note="Crossref open")
        output_path = tmp_path / "out.csv"
        export_records_csv([rec], output_path)
        with open(output_path, newline="") as f:
            reader = _csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["licence_note"] == "Crossref open"

    def test_stage1_csv_fields_excludes_restricted_columns(self):
        """STAGE1_CSV_FIELDS must not include any restricted metadata fields."""
        restricted = {"citation_count", "abstract_available", "abstract_stored"}
        overlap = restricted & set(STAGE1_CSV_FIELDS)
        assert not overlap, (
            f"STAGE1_CSV_FIELDS contains restricted fields: {overlap}. "
            "These must be dropped per docs/licensing_and_compliance.md."
        )

    def test_stage1_csv_fields_includes_licence_note(self):
        """STAGE1_CSV_FIELDS must include licence_note (mandatory Stage 1 field)."""
        assert "licence_note" in STAGE1_CSV_FIELDS, (
            "licence_note must be in STAGE1_CSV_FIELDS — it is required by "
            "docs/licensing_and_compliance.md Stage 1 export rules."
        )


class TestProviderOwnedPhysicalRequestCount:
    """The exporter accepts only the provider's exact attempt count."""

    @pytest.mark.parametrize("invalid_count", [True, 1.0, -1, "1", None])
    def test_rejects_noncanonical_count_values(self, invalid_count):
        result = ProviderResult(physical_request_count=invalid_count)

        with pytest.raises(PhysicalRequestCountContractError):
            _validate_provider_physical_request_count(
                result,
                provider_name="crossref",
                provider_configured=True,
                page_diagnostics=[{"pagination_status": "applied"}],
            )

    def test_configured_provider_requires_count_above_zero_after_acquisition(self):
        result = ProviderResult(physical_request_count=0)

        with pytest.raises(PhysicalRequestCountContractError, match="configured provider"):
            _validate_provider_physical_request_count(
                result,
                provider_name="crossref",
                provider_configured=True,
                page_diagnostics=[],
            )

    def test_zero_is_allowed_for_explicit_pre_network_skip(self):
        result = ProviderResult(physical_request_count=0)

        assert (
            _validate_provider_physical_request_count(
                result,
                provider_name="scopus",
                provider_configured=True,
                page_diagnostics=[{"pagination_status": "skipped"}],
            )
            == 0
        )

    def test_unconfigured_provider_requires_exact_zero(self):
        assert (
            _validate_provider_physical_request_count(
                ProviderResult(physical_request_count=0),
                provider_name="openalex",
                provider_configured=False,
                page_diagnostics=[],
            )
            == 0
        )
        with pytest.raises(PhysicalRequestCountContractError, match="unconfigured provider"):
            _validate_provider_physical_request_count(
                ProviderResult(physical_request_count=1),
                provider_name="openalex",
                provider_configured=False,
                page_diagnostics=[],
            )
