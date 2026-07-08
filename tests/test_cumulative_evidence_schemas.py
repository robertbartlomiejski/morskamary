from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
CODEBOOK_PATH = REPO_ROOT / "docs" / "CROSS_RUN_EVIDENCE_CODEBOOK.md"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def test_cross_run_evidence_schema_validates_sample_payload() -> None:
    schema = _load_schema("cross_run_evidence.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = {
        "run_summary": [
            {
                "run_id": "run-1",
                "run_path": "runs/run-1",
                "timestamp_utc": "2026-07-07T00:00:00+00:00",
                "manifest_timestamp_utc": "2026-07-07T00:00:00+00:00",
                "live_records_count": "10",
                "triangulated_records_count": "9",
                "cumulative_qmbd_records_count": "25",
                "evidence_rows_total": "44",
                "evidence_rows_dedupable": "40",
                "unique_dedupe_values": "30",
            }
        ],
        "evidence_occurrences": [
            {
                "run_id": "run-1",
                "run_path": "runs/run-1",
                "timestamp_utc": "2026-07-07T00:00:00+00:00",
                "manifest_timestamp_utc": "2026-07-07T00:00:00+00:00",
                "dataset": "cumulative_qmbd_records",
                "record_index": "1",
                "dedupe_value": "10.1234/example",
                "dedupe_field_used": "doi",
                "doi": "10.1234/example",
                "source_id": "crossref:10.1234/example",
                "title": "Example evidence record",
                "record_origin": "LIVE_API",
                "axis_name": "OCEANIC",
            }
        ],
        "evidence_index": [
            {
                "dedupe_value": "10.1234/example",
                "first_seen_timestamp_utc": "2026-07-07T00:00:00+00:00",
                "first_seen_run_id": "run-1",
                "last_seen_timestamp_utc": "2026-07-07T00:00:00+00:00",
                "last_seen_run_id": "run-1",
                "run_count": "1",
                "occurrence_count": "1",
                "datasets": "cumulative_qmbd_records",
                "record_origins": "LIVE_API",
                "axis_names": "OCEANIC",
                "dois": "10.1234/example",
                "source_ids": "crossref:10.1234/example",
                "titles": "Example evidence record",
            }
        ],
        "build_report": {
            "archive_root": "outputs/run_archive",
            "output_dir": "outputs/run_archive",
            "runs_total": 1,
            "runs_processed": 1,
            "runs_skipped_invalid": 0,
            "dedupe_keys": ["doi", "source_id", "title"],
            "occurrences_total": 1,
            "manual_occurrences_total": 0,
            "dedupe_groups_total": 1,
        },
    }
    assert list(validator.iter_errors(payload)) == []


def test_manual_sources_ledger_schema_validates_sample_row() -> None:
    schema = _load_schema("manual_sources_ledger.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    row = {
        "source_id": "manual_src_0123456789abcdef",
        "ingested_at_utc": "2026-07-07T00:00:00+00:00",
        "source_kind": "manual_document",
        "file_name": "example.pdf",
        "extension": ".pdf",
        "size_bytes": "2048",
        "sha256": "a" * 64,
        "text_available": "no",
        "original_path": "C:/tmp/example.pdf",
        "zip_member_path": "",
        "stored_path": "outputs/manual_sources/files/manual_src_0123456789abcdef.pdf",
    }
    assert list(validator.iter_errors(row)) == []


def test_historical_revalidation_report_schema_validates_sample_payload() -> None:
    schema = _load_schema("historical_revalidation_report.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = {
        "captured_at_utc": "2026-07-07T00:00:00+00:00",
        "inputs_total": 4,
        "compatible_bundles": 3,
        "incompatible_bundles": 1,
        "records_scanned": 15111,
        "records_inserted": 0,
        "records_skipped_duplicates": 15111,
        "compatibility_csv": "outputs/manual_sources/historical_compatibility.csv",
        "historical_cumulative_jsonl": "outputs/manual_sources/historical_cumulative_records.jsonl",
    }
    assert list(validator.iter_errors(payload)) == []


def test_codebook_covers_required_entities() -> None:
    content = CODEBOOK_PATH.read_text(encoding="utf-8")
    required_sections = (
        "runs",
        "source_bundles",
        "evidence_records",
        "evidence_occurrences",
        "gap_clusters",
        "dynamic_credentials",
        "manual_sources",
        "historical_revalidation",
    )
    for token in required_sections:
        assert token in content
