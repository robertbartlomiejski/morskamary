from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from unittest.mock import Mock
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "archive_run_outputs.py"


def _load_archive_module():
    spec = importlib.util.spec_from_file_location("archive_run_outputs", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    _write_text(path, json.dumps(payload, indent=2) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _seed_required_targets(base_dir: Path) -> dict[str, int | str]:
    _write_json(
        base_dir / "outputs/research_sources/live_records.json",
        [{"id": "lr-1"}, {"id": "lr-2"}],
    )
    _write_json(
        base_dir / "outputs/research_sources/live_records_triangulated.json",
        {"records": [{"id": "tri-1"}, {"id": "tri-2"}, {"id": "tri-3"}]},
    )
    _write_text(
        base_dir / "outputs/research_sources/live_source_coverage.csv",
        "provider,records\ncrossref,2\n",
    )
    _write_text(
        base_dir / "outputs/gaps_summary.csv",
        "sector,gap_count\nports,1\n",
    )
    _write_json(
        base_dir / "outputs/credentials_database.json",
        {
            "credentials": [
                {"id": "cred-1"},
                {"id": "cred-2"},
                {"id": "cred-3"},
                {"id": "cred-4"},
            ],
            "items": [{"id": "ignored-items-entry"}],
        },
    )
    _write_json(
        base_dir / "outputs/competences_full_database.json",
        {
            "baseline": [{"id": "b-1"}, {"id": "b-2"}],
            "literature": [{"id": "l-1"}],
        },
    )
    _write_json(
        base_dir / "outputs/cumulative_qmbd_records.json",
        {
            "metadata": {
                "analysis_input_mode": "static",
                "is_static_recovery_mode": True,
                "static_recovery_reason": "offline-ci",
                "allow_static_recovery_mode_env": "ALLOW_STATIC_RECOVERY_MODE",
                "provider_set": "crossref,scopus,openalex",
                "github_run_id": "1001",
                "commit_sha": "abc123",
                "timestamp_utc": "2026-07-07T00:00:00+00:00",
                "warnings": [
                    "STATIC recovery mode active: deterministic recovery artifacts only; not cumulative live evidence."
                ],
            },
            "records": [
                {"id": "q-1", "record_origin": "live-crossref"},
                {"id": "q-2", "record_origin": "baseline"},
                {"id": "q-3", "record_origin": "live-scopus"},
                {"id": "q-4", "record_origin": "literature"},
            ]
        },
    )
    _write_text(base_dir / "outputs/report_index.html", "<html>report</html>\n")
    _write_text(base_dir / "outputs/gaps_by_sector.html", "<html>gaps</html>\n")
    _write_text(
        base_dir / "outputs/credentials_matrix.html", "<html>credentials</html>\n"
    )
    _write_text(
        base_dir / "outputs/literature_integration.html", "<html>literature</html>\n"
    )
    _write_json(
        base_dir / "outputs/sector_dictionaries/blue_biotech_tmbd_dictionary.json",
        {"sector": "blue_biotech", "axis": "M"},
    )
    _write_text(
        base_dir / "MANIFEST_SOURCES.csv",
        "path,type\ndata/raw/source.csv,dataset\n",
    )
    _write_text(
        base_dir / "config/research_queries.yml",
        "queries:\n  - id: q1\n    text: marine governance\n",
    )

    query_file_path = base_dir / "config/research_queries.yml"
    return {
        "query_file_sha256": _sha256(query_file_path),
        "live_records_count": 2,
        "triangulated_records_count": 3,
        "cumulative_qmbd_records_count": 4,
        "competences_total": 3,
        "baseline_count": 2,
        "static_literature_count": 1,
        "live_enrichment_count": 2,
        "credentials_count": 4,
    }


def test_archive_run_outputs_creates_full_run_archive(tmp_path: Path) -> None:
    module = _load_archive_module()
    expected_metrics = _seed_required_targets(tmp_path)
    _write_json(tmp_path / "outputs/research_api_health.json", {"status": "ok"})
    _write_json(tmp_path / "outputs/validation_state.json", {"status": "passed"})

    exit_code = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            "run-123-1",
            "--workflow-name",
            "Full Live-Enriched Analysis",
            "--event-name",
            "workflow_dispatch",
            "--git-sha",
            "abc123",
            "--git-ref",
            "refs/heads/main",
            "--providers",
            "crossref,scopus,openalex",
            "--max-results-per-query",
            "150",
            "--offline",
            "false",
            "--require-live-records",
            "true",
            "--github-run-id",
            "1001",
            "--github-run-attempt",
            "2",
            "--github-run-number",
            "77",
            "--github-job",
            "live-analysis",
            "--query-file",
            "config/research_queries.yml",
        ]
    )
    assert exit_code == 0

    run_dir = tmp_path / "outputs" / "run_archive" / "runs" / "run-123-1"
    assert run_dir.exists()

    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "run_manifest.json").exists()
    assert (run_dir / "analysis_outputs").is_dir()
    assert (run_dir / "analysis_outputs" / "gaps_summary.csv").exists()
    assert (run_dir / "analysis_outputs" / "credentials_database.json").exists()
    assert (run_dir / "analysis_outputs" / "cumulative_qmbd_records.json").exists()
    assert (run_dir / "outputs" / "credentials_database.json").exists()
    assert (run_dir / "research_sources").is_dir()
    assert (run_dir / "research_sources" / "live_records.json").exists()
    assert (run_dir / "MANIFEST_SOURCES.csv").exists()
    assert (run_dir / "_checksums.sha256").exists()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    compat_manifest = json.loads(
        (run_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == compat_manifest

    assert manifest["run_id"] == "run-123-1"
    assert manifest["requested_run_id"] == "run-123-1"
    assert manifest["run_path"] == "runs/run-123-1"
    assert manifest["archive_root"] == "outputs/run_archive"
    assert manifest["manifest_schema"] == "schemas/run_archive_manifest.schema.json"
    assert manifest["analysis_input_mode"] == "static"
    assert manifest["is_static_recovery_mode"] is True
    assert manifest["static_recovery_reason"] == "offline-ci"
    assert manifest["allow_static_recovery_mode_env"] == "ALLOW_STATIC_RECOVERY_MODE"
    assert manifest["provider_set"] == "crossref,scopus,openalex"
    assert manifest["analysis_timestamp_utc"] == "2026-07-07T00:00:00+00:00"
    assert manifest["warnings"]
    assert manifest["workflow"]["name"] == "Full Live-Enriched Analysis"
    assert manifest["workflow"]["inputs"]["providers"] == "crossref,scopus,openalex"
    assert manifest["query_file_sha256"] == expected_metrics["query_file_sha256"]
    assert manifest["live_records_count"] == expected_metrics["live_records_count"]
    assert (
        manifest["triangulated_records_count"]
        == expected_metrics["triangulated_records_count"]
    )
    assert (
        manifest["cumulative_qmbd_records_count"]
        == expected_metrics["cumulative_qmbd_records_count"]
    )
    assert manifest["competences_total"] == expected_metrics["competences_total"]
    assert manifest["baseline_count"] == expected_metrics["baseline_count"]
    assert (
        manifest["static_literature_count"]
        == expected_metrics["static_literature_count"]
    )
    assert manifest["live_enrichment_count"] == expected_metrics["live_enrichment_count"]
    assert manifest["credentials_count"] == expected_metrics["credentials_count"]

    checksum_lines = (run_dir / "_checksums.sha256").read_text(encoding="utf-8")
    assert "outputs/gaps_summary.csv" in checksum_lines

    index_file = tmp_path / "outputs" / "run_archive" / "_index" / "runs_index.jsonl"
    lines = [
        line for line in index_file.read_text(encoding="utf-8").splitlines() if line
    ]
    assert lines
    latest = json.loads(lines[-1])
    assert latest["run_id"] == "run-123-1"
    assert latest["run_path"] == "runs/run-123-1"

    csv_index = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    assert csv_index.exists()
    with csv_index.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    csv_latest = rows[-1]
    assert csv_latest["run_id"] == "run-123-1"
    assert csv_latest["run_path"] == "runs/run-123-1"
    assert csv_latest["analysis_input_mode"] == "static"
    assert csv_latest["is_static_recovery_mode"] == "true"
    assert csv_latest["provider_set"] == "crossref,scopus,openalex"
    assert csv_latest["query_file_sha256"] == expected_metrics["query_file_sha256"]
    assert csv_latest["credentials_count"] == str(expected_metrics["credentials_count"])


def test_manifest_matches_json_schema(tmp_path: Path) -> None:
    module = _load_archive_module()
    _seed_required_targets(tmp_path)
    _write_json(tmp_path / "outputs/validation_state.json", {"status": "passed"})

    result = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            "run-schema",
        ]
    )
    assert result == 0

    manifest_path = (
        tmp_path / "outputs" / "run_archive" / "runs" / "run-schema" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_path = REPO_ROOT / "schemas" / "run_archive_manifest.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda item: item.path)
    assert not errors


def test_archive_reuses_manifest_timestamp_for_jsonl_index(tmp_path: Path) -> None:
    module = _load_archive_module()
    _seed_required_targets(tmp_path)
    first_timestamp = "2026-08-09T15:39:59+00:00"
    next_second = "2026-08-09T15:40:00+00:00"
    module._now_utc_iso = Mock(side_effect=[first_timestamp, next_second])

    result = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            "run-timestamp-boundary",
        ]
    )

    assert result == 0
    run_dir = (
        tmp_path
        / "outputs"
        / "run_archive"
        / "runs"
        / "run-timestamp-boundary"
    )
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    index_path = tmp_path / "outputs" / "run_archive" / "_index" / "runs_index.jsonl"
    index_entry = json.loads(index_path.read_text(encoding="utf-8").strip())
    assert manifest["timestamp_utc"] == first_timestamp
    assert index_entry["archived_at"] == manifest["timestamp_utc"]
    assert index_entry["archived_at"] != next_second
    assert module._now_utc_iso.call_count == 1


def test_archive_checksums_match_archived_files(tmp_path: Path) -> None:
    module = _load_archive_module()
    _seed_required_targets(tmp_path)

    result = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            "run-checksum",
        ]
    )
    assert result == 0

    run_dir = tmp_path / "outputs" / "run_archive" / "runs" / "run-checksum"
    checksum_file = run_dir / "_checksums.sha256"
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", maxsplit=1)
        archived_path = run_dir / rel
        assert archived_path.exists()
        assert digest == _sha256(archived_path)


def test_archive_excludes_raw_api_payloads_from_committed_run_archive(
    tmp_path: Path,
) -> None:
    module = _load_archive_module()
    _seed_required_targets(tmp_path)
    _write_json(
        tmp_path / "outputs/research_sources/raw_api_payloads/crossref_query_01.json",
        {"provider": "crossref", "query": "marine governance"},
    )

    result = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            "run-no-raw-payloads",
        ]
    )
    assert result == 0

    run_dir = tmp_path / "outputs" / "run_archive" / "runs" / "run-no-raw-payloads"
    assert not (run_dir / "outputs" / "research_sources" / "raw_api_payloads").exists()
    assert not (run_dir / "research_sources" / "raw_api_payloads").exists()

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert all("raw_api_payloads/" not in item["path"] for item in manifest["files"])


def test_repeated_archive_creation_does_not_overwrite_previous_run(tmp_path: Path) -> None:
    module = _load_archive_module()
    _seed_required_targets(tmp_path)

    first_result = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            "run-repeat",
        ]
    )
    assert first_result == 0
    first_run_dir = tmp_path / "outputs" / "run_archive" / "runs" / "run-repeat"
    first_checksum = _sha256(first_run_dir / "outputs" / "gaps_summary.csv")

    _write_text(tmp_path / "outputs/gaps_summary.csv", "sector,gap_count\nports,2\n")
    second_result = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            "run-repeat",
        ]
    )
    assert second_result == 0
    second_run_dir = tmp_path / "outputs" / "run_archive" / "runs" / "run-repeat.2"
    second_checksum = _sha256(second_run_dir / "outputs" / "gaps_summary.csv")

    assert first_run_dir.exists()
    assert second_run_dir.exists()
    assert first_checksum != second_checksum
    assert _sha256(first_run_dir / "outputs" / "gaps_summary.csv") == first_checksum

    csv_index = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_index.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row_map = {row["run_id"]: row for row in rows}
    assert "run-repeat" in row_map
    assert "run-repeat.2" in row_map


def test_archive_does_not_modify_latest_snapshot_outputs(tmp_path: Path) -> None:
    module = _load_archive_module()
    _seed_required_targets(tmp_path)

    tracked_latest = [
        tmp_path / "outputs" / "gaps_summary.csv",
        tmp_path / "outputs" / "credentials_database.json",
        tmp_path / "outputs" / "competences_full_database.json",
        tmp_path / "outputs" / "cumulative_qmbd_records.json",
        tmp_path / "outputs" / "report_index.html",
        tmp_path / "outputs" / "research_sources" / "live_records.json",
        tmp_path / "outputs" / "research_sources" / "live_records_triangulated.json",
    ]
    before = {path.as_posix(): _sha256(path) for path in tracked_latest}

    result = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            "run-snapshot",
        ]
    )
    assert result == 0

    after = {path.as_posix(): _sha256(path) for path in tracked_latest}
    assert before == after


def test_archive_run_outputs_fails_when_required_targets_are_missing(tmp_path: Path) -> None:
    module = _load_archive_module()
    _write_text(tmp_path / "outputs/gaps_summary.csv", "header\n")
    _write_text(tmp_path / "MANIFEST_SOURCES.csv", "manifest\n")

    exit_code = module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            "run-999",
        ]
    )

    assert exit_code == 1
    assert not (tmp_path / "outputs" / "run_archive" / "runs" / "run-999").exists()


def test_repo_relative_posix_uses_redaction_sentinel_for_out_of_tree_path(
    tmp_path: Path,
) -> None:
    """_repo_relative_posix must return the sentinel for paths outside the repo root."""
    module = _load_archive_module()
    import tempfile

    with tempfile.TemporaryDirectory() as out_of_tree_dir:
        out_of_tree_path = Path(out_of_tree_dir) / "some_archive"
        repo_root = tmp_path
        result = module._repo_relative_posix(out_of_tree_path, repo_root)
        assert result == "[redacted-out-of-tree-path]", (
            f"Expected sentinel for out-of-tree path, got: {result!r}"
        )


def test_out_of_tree_archive_root_is_redacted_in_manifest_and_csv(
    tmp_path: Path,
) -> None:
    """When --archive-root is outside --repo-root, both manifest.json and
    cumulative_runs_index.csv must record exactly '[redacted-out-of-tree-path]',
    never an absolute path or a bare basename."""
    import tempfile

    module = _load_archive_module()

    with tempfile.TemporaryDirectory() as out_of_tree_dir:
        archive_root = Path(out_of_tree_dir) / "run_archive"
        archive_root.mkdir(parents=True, exist_ok=True)

        _seed_required_targets(tmp_path)

        result = module.main(
            [
                "--repo-root",
                str(tmp_path),
                "--archive-root",
                str(archive_root),
                "--run-id",
                "run-oot-1",
            ]
        )
        assert result == 0, "archive with out-of-tree root must succeed"

        run_dir = archive_root / "runs" / "run-oot-1"
        manifest_path = run_dir / "manifest.json"
        assert manifest_path.exists(), "manifest must be written"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # manifest must redact the absolute path
        assert manifest["archive_root"] == "[redacted-out-of-tree-path]", (
            f"manifest archive_root must be sentinel, got: {manifest['archive_root']!r}"
        )
        assert str(out_of_tree_dir) not in manifest["archive_root"]

        csv_index = archive_root / "cumulative_runs_index.csv"
        assert csv_index.exists(), "cumulative CSV index must be written"
        with csv_index.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows, "CSV index must have at least one row"
        row = rows[-1]

        assert row["archive_root"] == "[redacted-out-of-tree-path]", (
            f"CSV archive_root must be sentinel, got: {row['archive_root']!r}"
        )
        assert str(out_of_tree_dir) not in row["archive_root"]


def test_append_csv_index_migrates_legacy_header(tmp_path: Path) -> None:
    """Appending to a CSV with a legacy (narrower) schema must rewrite the header
    and fill missing columns with empty strings rather than corrupting alignment."""
    module = _load_archive_module()

    archive_root = tmp_path / "archive"
    archive_root.mkdir(parents=True)
    csv_path = archive_root / "cumulative_runs_index.csv"

    # Write a legacy CSV that is missing the 'archive_root' column.
    legacy_columns = [
        c for c in module.INDEX_CSV_COLUMNS if c != "archive_root"
    ]
    legacy_row = {col: f"v-{col}" for col in legacy_columns}
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=legacy_columns)
        writer.writeheader()
        writer.writerow(legacy_row)

    # Build a minimal manifest that can drive _append_csv_index.
    manifest: dict = {col: "" for col in module.INDEX_CSV_COLUMNS}
    manifest.update(
        {
            "run_id": "test-run-1",
            "run_path": "runs/test-run-1",
            "archive_root": "outputs/run_archive",
            "timestamp_utc": "2025-01-01T00:00:00+00:00",
            "analysis_timestamp_utc": "2025-01-01T00:00:00+00:00",
            "is_static_recovery_mode": False,
            "gaps_summary_available": False,
            "live_records_count": 0,
            "triangulated_records_count": 0,
            "cumulative_qmbd_records_count": 0,
            "competences_total": 0,
            "baseline_count": 0,
            "static_literature_count": 0,
            "live_enrichment_count": 0,
            "credentials_count": 0,
            "file_count": 0,
            "total_bytes": 0,
        }
    )

    module._append_csv_index(archive_root, manifest)

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2, "legacy row plus new row"
    # Both rows must now have an 'archive_root' key (migrated).
    for row in rows:
        assert "archive_root" in row, "archive_root column must be present after migration"
    # The legacy row should have an empty archive_root (filled in during migration).
    assert rows[0]["archive_root"] == "", (
        "legacy row should have empty archive_root after migration"
    )
    # The new row should have the correct value.
    assert rows[1]["archive_root"] == "outputs/run_archive"


def test_append_csv_index_does_not_rewrite_when_schema_matches(tmp_path: Path) -> None:
    """When the existing CSV header already matches INDEX_CSV_COLUMNS, appending
    must not rewrite the file (no migration needed)."""
    module = _load_archive_module()

    archive_root = tmp_path / "archive"
    archive_root.mkdir(parents=True)
    csv_path = archive_root / "cumulative_runs_index.csv"

    # Write a CSV with the current full schema.
    first_row = {col: f"orig-{col}" for col in module.INDEX_CSV_COLUMNS}
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(module.INDEX_CSV_COLUMNS))
        writer.writeheader()
        writer.writerow(first_row)

    manifest: dict = {col: "" for col in module.INDEX_CSV_COLUMNS}
    manifest.update(
        {
            "run_id": "test-run-2",
            "is_static_recovery_mode": False,
            "gaps_summary_available": False,
            "live_records_count": 0,
            "triangulated_records_count": 0,
            "cumulative_qmbd_records_count": 0,
            "competences_total": 0,
            "baseline_count": 0,
            "static_literature_count": 0,
            "live_enrichment_count": 0,
            "credentials_count": 0,
            "file_count": 0,
            "total_bytes": 0,
        }
    )

    module._append_csv_index(archive_root, manifest)

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2, "original row plus new row"
    assert rows[0]["run_id"] == "orig-run_id", "original row must be preserved"


def test_append_csv_index_rejects_unknown_header_without_rewriting(tmp_path: Path) -> None:
    """An unrecognized index schema must fail closed and preserve existing bytes."""
    module = _load_archive_module()
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    csv_path = archive_root / "cumulative_runs_index.csv"
    original = b"run_id,unexpected\nlegacy,value\n"
    csv_path.write_bytes(original)
    manifest = {column: "" for column in module.INDEX_CSV_COLUMNS}
    manifest.update(
        {
            "is_static_recovery_mode": False,
            "gaps_summary_available": False,
            "live_records_count": 0,
            "triangulated_records_count": 0,
            "cumulative_qmbd_records_count": 0,
            "competences_total": 0,
            "baseline_count": 0,
            "static_literature_count": 0,
            "live_enrichment_count": 0,
            "credentials_count": 0,
            "file_count": 0,
            "total_bytes": 0,
        }
    )
    with pytest.raises(ValueError, match="incompatible"):
        module._append_csv_index(archive_root, manifest)
    assert csv_path.read_bytes() == original
