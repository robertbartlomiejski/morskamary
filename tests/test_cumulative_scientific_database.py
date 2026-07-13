"""Unit tests for the Layer 2 + 3 cumulative scientific database builder.

Covers PR-190 Task B:

* Layer 2: deduplication order (DOI → normalized title → source_id),
  first_seen / latest_seen computation, novelty status classification,
  jaccard grouping of near-duplicate titles, byte-identical determinism.
* Layer 3: rule-based semantic competence-demand signal extraction,
  ``review_required`` gating on weak/metadata-only evidence, and
  cross-linking with Layer 2 evidence rows.

The tests use minimal on-disk fixtures written into ``tmp_path`` and reuse
the shipped Layer 0 protocol at ``config/live_query_protocol.yml`` so the
protocol-binding path is exercised end-to-end.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pytest

from src.scientific_sources.cumulative_scientific_database import (
    ALLOWED_MANUAL_REVIEW_STATUSES,
    ALLOWED_RECORD_NOVELTY_STATUS,
    ALLOWED_SIGNAL_TYPES,
    CLASSIFIER_VERSION,
    COMPETENCE_DEMAND_SIGNALS_CSV,
    COMPETENCE_DEMAND_SIGNALS_JSONL,
    COMPETENCE_DEMAND_SIGNAL_COLUMNS,
    DATABASE_CHECKSUMS_FILENAME,
    DATABASE_MANIFEST_FILENAME,
    EVIDENCE_RECORDS_CSV,
    EVIDENCE_RECORDS_JSONL,
    EVIDENCE_RECORD_COLUMNS,
    RUN_NOVELTY_METRICS_CSV,
    RUN_NOVELTY_METRICS_JSON,
    build_cumulative_scientific_database,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / "config" / "live_query_protocol.yml"

FROZEN_TS = "2026-07-09T00:00:00+00:00"

# A query text that is guaranteed to exist in `config/live_query_protocol.yml`
# (verified during the smoke run above).
BOUND_QUERY_TEXT = (
    "marine biotechnology blue bioeconomy innovation governance"
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_live_records(dir_path: Path, records: List[Mapping[str, Any]]) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "live_records.json").write_text(
        json.dumps(records, indent=2, sort_keys=True), encoding="utf-8"
    )


def _write_run_archive(
    archive_root: Path, runs: List[Dict[str, Any]]
) -> None:
    """Materialize a synthetic run archive with cumulative_runs_index.csv."""
    archive_root.mkdir(parents=True, exist_ok=True)
    index_path = archive_root / "cumulative_runs_index.csv"
    columns = ["timestamp_utc", "run_id", "run_path"]
    with index_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for run in runs:
            writer.writerow(
                {
                    "timestamp_utc": run["timestamp_utc"],
                    "run_id": run["run_id"],
                    "run_path": f"runs/{run['run_id']}",
                }
            )
            run_dir = archive_root / "runs" / run["run_id"]
            research_dir = run_dir / "research_sources"
            _write_live_records(research_dir, run["records"])


def _write_current_run(run_dir: Path, records: List[Mapping[str, Any]]) -> None:
    _write_live_records(run_dir / "research_sources", records)


def _write_layer1_audit(
    live_runs_root: Path, run_id: str, rows: List[Dict[str, str]]
) -> None:
    bundle_raw = live_runs_root / run_id / "raw"
    bundle_raw.mkdir(parents=True, exist_ok=True)
    csv_path = bundle_raw / "raw_acquisition_index.csv"
    columns = [
        "query_id",
        "sector_slug",
        "sector_label",
        "axis_target",
        "query_family",
        "provider",
        "query_text",
        "raw_record_count",
        "normalized_record_count",
        "unique_source_ids",
        "coverage_record_count",
        "has_raw_payload_envelope",
        "raw_payload_sha256",
        "raw_payload_captured_at",
        "protocol_binding",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


# ---------------------------------------------------------------------------
# Bundle shape
# ---------------------------------------------------------------------------


class TestBundleShape:
    def test_writes_expected_files(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        output = tmp_path / "cumulative_database"
        _write_current_run(
            current,
            [
                {
                    "title": "Blue economy skills gap",
                    "doi": "10.1000/aa.1",
                    "source_id": "crossref:10.1000/aa.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )

        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=output,
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )

        expected = {
            EVIDENCE_RECORDS_CSV,
            EVIDENCE_RECORDS_JSONL,
            COMPETENCE_DEMAND_SIGNALS_CSV,
            COMPETENCE_DEMAND_SIGNALS_JSONL,
            RUN_NOVELTY_METRICS_CSV,
            RUN_NOVELTY_METRICS_JSON,
            DATABASE_MANIFEST_FILENAME,
            DATABASE_CHECKSUMS_FILENAME,
        }
        assert {p.name for p in result.files} == expected
        for name in expected:
            assert (output / name).is_file()

    def test_manifest_records_allowed_vocabularies(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "Only record",
                    "doi": "10.1000/aa.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        manifest = json.loads(
            (tmp_path / "out" / DATABASE_MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert manifest["allowed_record_novelty_status"] == list(
            ALLOWED_RECORD_NOVELTY_STATUS
        )
        assert manifest["allowed_signal_types"] == list(ALLOWED_SIGNAL_TYPES)
        assert manifest["allowed_manual_review_statuses"] == list(
            ALLOWED_MANUAL_REVIEW_STATUSES
        )
        assert manifest["classifier_version"] == CLASSIFIER_VERSION


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_doi_identical_records_dedupe_across_runs(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        archive = tmp_path / "archive"
        record_a = {
            "title": "Sample paper A",
            "doi": "10.1000/aa.1",
            "source_id": "crossref:10.1000/aa.1",
            "provider": "Crossref",
            "source_query": BOUND_QUERY_TEXT,
            "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
        }
        _write_run_archive(
            archive,
            [
                {
                    "run_id": "prev",
                    "timestamp_utc": "2026-06-01T00:00:00+00:00",
                    "records": [record_a],
                }
            ],
        )
        _write_current_run(current, [dict(record_a, retrieval_timestamp="2026-07-02T00:00:00+00:00")])

        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            archive_root=archive,
            protocol_path=PROTOCOL_PATH,
            current_run_id="R2",
            built_at_utc=FROZEN_TS,
        )

        assert len(result.evidence_records) == 1
        row = result.evidence_records[0]
        assert row.canonical_doi == "10.1000/aa.1"
        assert row.first_seen_run_id == "prev"
        assert row.latest_seen_run_id == "R2"
        assert row.first_seen_at_utc == "2026-07-01T00:00:00+00:00"
        assert row.latest_seen_at_utc == "2026-07-02T00:00:00+00:00"
        assert row.record_recurrence_count == 2

    def test_title_identical_records_without_doi_dedupe(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        archive = tmp_path / "archive"
        _write_run_archive(
            archive,
            [
                {
                    "run_id": "prev",
                    "timestamp_utc": "2026-06-01T00:00:00+00:00",
                    "records": [
                        {
                            "title": "  A Blue Economy Skills Gap  ",
                            "provider": "Crossref",
                            "source_query": BOUND_QUERY_TEXT,
                            "retrieval_timestamp": "2026-06-01T00:00:00+00:00",
                        }
                    ],
                }
            ],
        )
        _write_current_run(
            current,
            [
                {
                    "title": "A blue-economy   skills gap",
                    "provider": "Scopus",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-02T00:00:00+00:00",
                }
            ],
        )

        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            archive_root=archive,
            protocol_path=PROTOCOL_PATH,
            current_run_id="R2",
            built_at_utc=FROZEN_TS,
        )

        assert len(result.evidence_records) == 1
        row = result.evidence_records[0]
        assert row.canonical_doi == ""
        assert row.normalized_title_hash != ""
        assert row.provider_count == 2
        assert row.record_recurrence_count == 2

    def test_source_id_dedupe_when_no_doi_or_title(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        archive = tmp_path / "archive"
        _write_run_archive(
            archive,
            [
                {
                    "run_id": "prev",
                    "timestamp_utc": "2026-06-01T00:00:00+00:00",
                    "records": [
                        {
                            "source_id": "wos:AB1234",
                            "provider": "WoS",
                            "source_query": BOUND_QUERY_TEXT,
                            "retrieval_timestamp": "2026-06-01T00:00:00+00:00",
                        }
                    ],
                }
            ],
        )
        _write_current_run(
            current,
            [
                {
                    "source_id": "WoS:AB1234",
                    "provider": "WoS",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-02T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            archive_root=archive,
            protocol_path=PROTOCOL_PATH,
            current_run_id="R2",
            built_at_utc=FROZEN_TS,
        )
        assert len(result.evidence_records) == 1
        row = result.evidence_records[0]
        # With no DOI or title, the review_required status is emitted.
        assert row.record_novelty_status == "review_required"
        assert row.validity_warning == "no_stable_dedupe_key"

    def test_distinct_dois_stay_separate(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "P1",
                    "doi": "10.1000/aa.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                },
                {
                    "title": "P2",
                    "doi": "10.1000/aa.2",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                },
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        ids = {r.evidence_id for r in result.evidence_records}
        assert ids == {"evidence:doi:10.1000/aa.1", "evidence:doi:10.1000/aa.2"}


# ---------------------------------------------------------------------------
# Novelty
# ---------------------------------------------------------------------------


class TestNovelty:
    def test_new_record_status_for_first_appearance(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "Brand new",
                    "doi": "10.1000/new.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        assert result.evidence_records[0].record_novelty_status == "new_record"

    def test_repeated_record_when_not_current_run(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        archive = tmp_path / "archive"
        record = {
            "title": "Older paper",
            "doi": "10.1000/old.1",
            "provider": "Crossref",
            "source_query": BOUND_QUERY_TEXT,
            "retrieval_timestamp": "2026-06-01T00:00:00+00:00",
        }
        _write_run_archive(
            archive,
            [
                {
                    "run_id": "prev",
                    "timestamp_utc": "2026-06-01T00:00:00+00:00",
                    "records": [record],
                }
            ],
        )
        # Current run has an unrelated record; the old one is only in archive.
        _write_current_run(
            current,
            [
                {
                    "title": "Unrelated new",
                    "doi": "10.1000/unrelated.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            archive_root=archive,
            protocol_path=PROTOCOL_PATH,
            current_run_id="R2",
            built_at_utc=FROZEN_TS,
        )
        statuses = {r.evidence_id: r.record_novelty_status for r in result.evidence_records}
        assert statuses["evidence:doi:10.1000/old.1"] == "repeated_record"
        assert statuses["evidence:doi:10.1000/unrelated.1"] == "new_record"

    def test_provider_enriched_when_current_adds_provider(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        archive = tmp_path / "archive"
        _write_run_archive(
            archive,
            [
                {
                    "run_id": "prev",
                    "timestamp_utc": "2026-06-01T00:00:00+00:00",
                    "records": [
                        {
                            "title": "Multi-provider",
                            "doi": "10.1000/multi.1",
                            "provider": "Crossref",
                            "source_query": BOUND_QUERY_TEXT,
                            "retrieval_timestamp": "2026-06-01T00:00:00+00:00",
                        }
                    ],
                }
            ],
        )
        _write_current_run(
            current,
            [
                {
                    "title": "Multi-provider",
                    "doi": "10.1000/multi.1",
                    "provider": "Scopus",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            archive_root=archive,
            protocol_path=PROTOCOL_PATH,
            current_run_id="R2",
            built_at_utc=FROZEN_TS,
        )
        row = result.evidence_records[0]
        assert row.record_novelty_status == "provider_enriched"
        assert row.provider_count == 2

    def test_repeated_records_not_counted_as_new(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        archive = tmp_path / "archive"
        # Use a title/source_query pair that does NOT match any semantic
        # signal pattern so the record stays classified as ``repeated_record``
        # instead of being upgraded to ``semantic_enriched``. The chosen query
        # is a bound protocol query that contains no signal keywords.
        neutral_bound_query = "bioprospecting marine genetic resources benefit sharing"
        record = {
            "title": "A neutral observational study of coastal water salinity",
            "doi": "10.1000/old.1",
            "provider": "Crossref",
            "source_query": neutral_bound_query,
            "retrieval_timestamp": "2026-06-01T00:00:00+00:00",
        }
        _write_run_archive(
            archive,
            [
                {
                    "run_id": "prev",
                    "timestamp_utc": "2026-06-01T00:00:00+00:00",
                    "records": [record],
                }
            ],
        )
        _write_current_run(current, [dict(record, retrieval_timestamp="2026-07-01T00:00:00+00:00")])
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            archive_root=archive,
            protocol_path=PROTOCOL_PATH,
            current_run_id="R2",
            built_at_utc=FROZEN_TS,
        )
        metrics = result.run_novelty_metrics.to_dict()
        # The same DOI appears in both runs; new_unique_doi_count must stay 0.
        assert metrics["new_unique_doi_count"] == 0
        # When no semantic signals are emitted the record is not upgraded to
        # ``semantic_enriched`` and stays as ``repeated_record``.
        statuses = {r.record_novelty_status for r in result.evidence_records}
        assert statuses == {"repeated_record"}
        assert metrics["repeated_doi_count"] == 1
        assert metrics["semantic_new_signal_count"] == 0


# ---------------------------------------------------------------------------
# Layer 1 binding
# ---------------------------------------------------------------------------


class TestLayer1Binding:
    def test_layer1_bindings_populate_query_id(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        live_runs = tmp_path / "live_runs"
        _write_current_run(
            current,
            [
                {
                    "title": "Bindable paper",
                    "doi": "10.1000/bind.1",
                    "provider": "Crossref",
                    "source_query": "custom bound query text",
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        _write_layer1_audit(
            live_runs,
            run_id="R1",
            rows=[
                {
                    "query_id": "Q_TEST_001",
                    "sector_slug": "test_sector",
                    "sector_label": "Test Sector",
                    "axis_target": "MARITIME",
                    "query_family": "core_sector",
                    "provider": "Crossref",
                    "query_text": "custom bound query text",
                    "raw_record_count": "1",
                    "normalized_record_count": "1",
                    "unique_source_ids": "1",
                    "coverage_record_count": "1",
                    "has_raw_payload_envelope": "false",
                    "raw_payload_sha256": "",
                    "raw_payload_captured_at": "",
                    "protocol_binding": "bound",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            live_runs_root=live_runs,
            protocol_path=None,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        row = result.evidence_records[0]
        assert row.query_ids_seen == "Q_TEST_001"
        assert row.query_families_seen == "core_sector"
        assert row.sector_candidates == "test_sector"
        assert row.axis_candidates == "T"

    def test_layer1_unbound_rows_do_not_bind(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        live_runs = tmp_path / "live_runs"
        _write_current_run(
            current,
            [
                {
                    "title": "Unbindable paper",
                    "doi": "10.1000/unbind.1",
                    "provider": "Crossref",
                    "source_query": "custom unbound query text",
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        _write_layer1_audit(
            live_runs,
            run_id="R1",
            rows=[
                {
                    "query_id": "",
                    "sector_slug": "",
                    "sector_label": "",
                    "axis_target": "",
                    "query_family": "",
                    "provider": "Crossref",
                    "query_text": "custom unbound query text",
                    "raw_record_count": "1",
                    "normalized_record_count": "1",
                    "unique_source_ids": "1",
                    "coverage_record_count": "1",
                    "has_raw_payload_envelope": "false",
                    "raw_payload_sha256": "",
                    "raw_payload_captured_at": "",
                    "protocol_binding": "unbound",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            live_runs_root=live_runs,
            protocol_path=None,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        row = result.evidence_records[0]
        assert row.query_ids_seen == ""
        assert row.sector_candidates == ""
        assert row.axis_candidates == ""


# ---------------------------------------------------------------------------
# Semantic (Layer 3)
# ---------------------------------------------------------------------------


class TestSemanticSignals:
    def test_explicit_competence_demand_signal(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "Blue economy competences and workforce training",
                    "doi": "10.1000/sem.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        signal_types = {s.signal_type for s in result.competence_demand_signals}
        assert "explicit_competence_demand" in signal_types
        assert "workforce_skill" in signal_types
        assert "education_training_signal" in signal_types

    def test_no_signals_for_records_without_matches(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "A paper about barnacle taxonomy",
                    "doi": "10.1000/none.1",
                    "provider": "Crossref",
                    "source_query": "barnacle taxonomy morphology",
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        assert result.competence_demand_signals == []

    def test_source_query_only_match_produces_no_signals(self, tmp_path: Path) -> None:
        """Regression test: source_query is provenance metadata only.

        A record whose title and subject_terms do NOT match any semantic
        pattern must produce zero competence signals even if the source_query
        text would match — query intent is not empirical evidence.
        """
        current = tmp_path / "outputs"
        # Only source_query mentions "governance" (no title / subject term match).
        _write_current_run(
            current,
            [
                {
                    "title": "Unrelated title with no signals",
                    "doi": "10.1000/weak.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,  # protocol query mentions governance
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        gov_signals = [
            s for s in result.competence_demand_signals if s.signal_type == "governance_skill"
        ]
        # source_query-only matches must never produce signals.
        assert gov_signals == [], (
            "source_query-only records must not produce semantic signals; "
            f"got {gov_signals}"
        )

    def test_metadata_only_flag_absent_when_abstract_present(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "Governance training programme evaluation",
                    "abstract": "Full abstract text present here.",
                    "doi": "10.1000/abs.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        for s in result.competence_demand_signals:
            assert s.validity_warning == ""

    def test_signal_types_are_allowed(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": (
                        "Digital competences, workforce upskilling, and safety training "
                        "for a sustainable blue economy"
                    ),
                    "doi": "10.1000/many.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        for s in result.competence_demand_signals:
            assert s.signal_type in ALLOWED_SIGNAL_TYPES
            assert s.manual_review_status in ALLOWED_MANUAL_REVIEW_STATUSES
            assert 0.0 < s.confidence_score <= 1.0

    def test_semantic_enriched_upgrade_for_repeated_records(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        archive = tmp_path / "archive"
        record = {
            "title": "Governance training for maritime workforce",
            "doi": "10.1000/gov.1",
            "provider": "Crossref",
            "source_query": BOUND_QUERY_TEXT,
            "retrieval_timestamp": "2026-06-01T00:00:00+00:00",
        }
        _write_run_archive(
            archive,
            [
                {
                    "run_id": "prev",
                    "timestamp_utc": "2026-06-01T00:00:00+00:00",
                    "records": [record],
                }
            ],
        )
        _write_current_run(current, [dict(record, retrieval_timestamp="2026-07-01T00:00:00+00:00")])
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            archive_root=archive,
            protocol_path=PROTOCOL_PATH,
            current_run_id="R2",
            built_at_utc=FROZEN_TS,
        )
        row = result.evidence_records[0]
        assert row.record_novelty_status == "semantic_enriched"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_two_runs_are_byte_identical(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "Blue skills governance",
                    "doi": "10.1000/det.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                },
                {
                    "title": "Digital training in maritime workforce",
                    "doi": "10.1000/det.2",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                },
            ],
        )
        out1 = tmp_path / "out1"
        out2 = tmp_path / "out2"
        for out in (out1, out2):
            build_cumulative_scientific_database(
                current_run_dir=current,
                output_dir=out,
                protocol_path=PROTOCOL_PATH,
                current_run_id="R1",
                built_at_utc=FROZEN_TS,
            )
        for name in (
            EVIDENCE_RECORDS_CSV,
            EVIDENCE_RECORDS_JSONL,
            COMPETENCE_DEMAND_SIGNALS_CSV,
            COMPETENCE_DEMAND_SIGNALS_JSONL,
            RUN_NOVELTY_METRICS_CSV,
            RUN_NOVELTY_METRICS_JSON,
            DATABASE_MANIFEST_FILENAME,
            DATABASE_CHECKSUMS_FILENAME,
        ):
            assert (out1 / name).read_bytes() == (out2 / name).read_bytes(), (
                f"file {name} is not byte-identical across two runs"
            )

    def test_csv_column_order_stable(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "P1",
                    "doi": "10.1000/aa.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        with (tmp_path / "out" / EVIDENCE_RECORDS_CSV).open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            header = next(csv.reader(handle))
        assert tuple(header) == EVIDENCE_RECORD_COLUMNS

        with (tmp_path / "out" / COMPETENCE_DEMAND_SIGNALS_CSV).open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            header = next(csv.reader(handle))
        assert tuple(header) == COMPETENCE_DEMAND_SIGNAL_COLUMNS


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestNoveltyMetrics:
    def test_metrics_expose_all_required_fields(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "P1",
                    "doi": "10.1000/m.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        d = result.run_novelty_metrics.to_dict()
        for field_name in (
            "new_unique_doi_count",
            "repeated_doi_count",
            "updated_metadata_count",
            "provider_enriched_count",
            "semantic_new_signal_count",
            "provider_record_count_by_provider",
            "provider_health_ok_zero_records",
            "jaccard_similarity_with_previous_run",
            "provider_diversity_score",
            "query_diversity_score",
            "crossref_dominance_ratio",
            "validity_warnings",
        ):
            assert field_name in d

    def test_jaccard_zero_when_no_previous(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "P1",
                    "doi": "10.1000/first.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        d = result.run_novelty_metrics.to_dict()
        assert d["jaccard_similarity_with_previous_run"] == 0.0
        assert d["previous_run_id"] == ""


# ---------------------------------------------------------------------------
# Optional inputs
# ---------------------------------------------------------------------------


class TestOptionalInputs:
    def test_missing_archive_root_ok(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "Only current",
                    "doi": "10.1000/only.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            archive_root=None,
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        assert len(result.evidence_records) == 1

    def test_missing_protocol_uses_unbound(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(
            current,
            [
                {
                    "title": "Only current",
                    "doi": "10.1000/only.1",
                    "provider": "Crossref",
                    "source_query": BOUND_QUERY_TEXT,
                    "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=None,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        row = result.evidence_records[0]
        assert row.query_ids_seen == ""
        assert row.sector_candidates == ""

    def test_current_run_with_no_records_produces_warning(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        _write_current_run(current, [])
        result = build_cumulative_scientific_database(
            current_run_dir=current,
            output_dir=tmp_path / "out",
            protocol_path=PROTOCOL_PATH,
            current_run_id="R1",
            built_at_utc=FROZEN_TS,
        )
        assert result.evidence_records == []
        metrics = result.run_novelty_metrics.to_dict()
        assert "current_run_no_records" in metrics["validity_warnings"]


# ---------------------------------------------------------------------------
# CLI wrapper smoke test
# ---------------------------------------------------------------------------


class TestCliWrapper:
    @pytest.mark.integration
    def test_cli_help_runs(self) -> None:
        import subprocess

        script = REPO_ROOT / "scripts" / "build_cumulative_scientific_database.py"
        proc = subprocess.run(
            ["python", str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert "Build the PR-190 live cumulative scientific database" in proc.stdout


# ---------------------------------------------------------------------------
# Regression tests for hardening fixes (PR-191)
# ---------------------------------------------------------------------------


class TestDOICanonicalization:
    """Fix 5: URL-form and bare-form DOIs must collapse to the same evidence_id."""

    def test_url_and_bare_doi_dedupe_to_one_record(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        output = tmp_path / "cumulative_database"
        # One record with a URL-form DOI, another with the bare form of the same DOI.
        _write_current_run(
            current,
            [
                {
                    "title": "Same paper via URL doi",
                    "doi": "https://doi.org/10.1234/test.2026",
                    "provider": "crossref",
                    "source_id": "url-form",
                },
                {
                    "title": "Same paper via bare doi",
                    "doi": "10.1234/test.2026",
                    "provider": "scopus",
                    "source_id": "bare-form",
                },
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=str(current),
            output_dir=str(output),
            current_run_id="RUN-DOI-001",
        )
        # Both forms must resolve to a single evidence record.
        assert len(result.evidence_records) == 1, (
            f"expected 1 evidence record, got {len(result.evidence_records)}: "
            f"{[r.evidence_id for r in result.evidence_records]}"
        )
        record = result.evidence_records[0]
        # Canonical DOI must be the bare lowercased form.
        assert record.canonical_doi == "10.1234/test.2026"
        # Both providers must be listed.
        assert "crossref" in record.providers_seen
        assert "scopus" in record.providers_seen

    def test_dx_doi_prefix_stripped(self, tmp_path: Path) -> None:
        """https://dx.doi.org/ prefix must also be stripped."""
        current = tmp_path / "outputs"
        output = tmp_path / "cumulative_database"
        _write_current_run(
            current,
            [
                {"doi": "https://dx.doi.org/10.9999/dx.form", "provider": "crossref"},
                {"doi": "10.9999/dx.form", "provider": "wos"},
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=str(current),
            output_dir=str(output),
            current_run_id="RUN-DOI-002",
        )
        assert len(result.evidence_records) == 1
        assert result.evidence_records[0].canonical_doi == "10.9999/dx.form"

    def test_doi_prefix_stripped(self, tmp_path: Path) -> None:
        """'doi:' prefix must be stripped."""
        current = tmp_path / "outputs"
        output = tmp_path / "cumulative_database"
        _write_current_run(
            current,
            [
                {"doi": "doi:10.5678/prefix.test", "provider": "crossref"},
                {"doi": "10.5678/prefix.test", "provider": "scopus"},
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=str(current),
            output_dir=str(output),
            current_run_id="RUN-DOI-003",
        )
        assert len(result.evidence_records) == 1
        assert result.evidence_records[0].canonical_doi == "10.5678/prefix.test"


class TestLatestEnrichedMetadata:
    """Fix 6: year/journal/citation_count use the latest non-empty value."""

    def test_latest_enriched_year_preferred_over_sparse_first(
        self, tmp_path: Path
    ) -> None:
        """An older sparse record followed by a richer later record must use
        the later year and journal, while first_seen timestamps reflect the
        earliest observation.
        """
        archive = tmp_path / "archive"
        current = tmp_path / "outputs"
        output = tmp_path / "cumulative_database"

        # Run 1: sparse metadata (no year/journal).
        _write_run_archive(
            archive,
            [
                {
                    "timestamp_utc": "2026-01-01T00:00:00+00:00",
                    "run_id": "RUN-ENRICH-001",
                    "records": [
                        {
                            "doi": "10.4321/enrich.test",
                            "title": "Enrichment test paper",
                            "year": "",
                            "journal": "",
                            "citation_count": 0,
                            "provider": "crossref",
                        }
                    ],
                }
            ],
        )
        # Current run: same DOI, richer metadata.
        _write_current_run(
            current,
            [
                {
                    "doi": "10.4321/enrich.test",
                    "title": "Enrichment test paper",
                    "year": "2025",
                    "journal": "Ocean Science Journal",
                    "citation_count": 42,
                    "provider": "scopus",
                }
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=str(current),
            output_dir=str(output),
            archive_root=archive,
            current_run_id="RUN-ENRICH-002",
        )
        assert len(result.evidence_records) == 1
        rec = result.evidence_records[0]
        # Latest enriched values must be preferred.
        assert rec.year == "2025", f"expected '2025', got {rec.year!r}"
        assert rec.journal == "Ocean Science Journal", f"got {rec.journal!r}"
        assert rec.citation_count == 42, f"got {rec.citation_count!r}"
        # First-seen provenance must still reflect run 1.
        assert rec.first_seen_run_id == "RUN-ENRICH-001"


class TestJaccardDuplicateOnly:
    """Fix 7: Jaccard non-root members receive duplicate_only status."""

    def test_near_duplicate_titles_non_root_marked_duplicate_only(
        self, tmp_path: Path
    ) -> None:
        current = tmp_path / "outputs"
        output = tmp_path / "cumulative_database"
        # Two records without DOI but very similar titles (high Jaccard sim.).
        title_a = "maritime blue economy competence development skills training"
        title_b = "maritime blue economy competence development skills training review"
        _write_current_run(
            current,
            [
                {"title": title_a, "provider": "crossref"},
                {"title": title_b, "provider": "scopus"},
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=str(current),
            output_dir=str(output),
            current_run_id="RUN-JACCARD-001",
        )
        statuses = {r.record_novelty_status for r in result.evidence_records}
        # At least one record should be duplicate_only (the non-root member).
        assert "duplicate_only" in statuses, (
            f"expected at least one duplicate_only record; got statuses: {statuses}"
        )
        # The root record should NOT be duplicate_only.
        non_duplicate = [
            r for r in result.evidence_records
            if r.record_novelty_status != "duplicate_only"
        ]
        assert non_duplicate, "expected at least one non-duplicate_only record"
        # Crosswalk: non-root members must have jaccard_group_id equal to root.
        for rec in result.evidence_records:
            if rec.record_novelty_status == "duplicate_only":
                assert rec.jaccard_group_id, (
                    "duplicate_only record must have a jaccard_group_id for audit"
                )
                assert rec.jaccard_group_id != rec.evidence_id, (
                    "non-root member's jaccard_group_id must differ from its own evidence_id"
                )

    def test_dissimilar_titles_not_marked_duplicate(self, tmp_path: Path) -> None:
        current = tmp_path / "outputs"
        output = tmp_path / "cumulative_database"
        _write_current_run(
            current,
            [
                {"title": "ocean governance hydrosocial theory", "provider": "crossref"},
                {"title": "marine biotechnology blue bioeconomy innovation", "provider": "scopus"},
            ],
        )
        result = build_cumulative_scientific_database(
            current_run_dir=str(current),
            output_dir=str(output),
            current_run_id="RUN-JACCARD-002",
        )
        # Dissimilar titles must not be merged.
        statuses = {r.record_novelty_status for r in result.evidence_records}
        assert "duplicate_only" not in statuses, (
            f"dissimilar titles should not produce duplicate_only records; got {statuses}"
        )
