from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _seed_required_targets(base_dir: Path) -> None:
    required_targets = [
        "outputs/research_sources/live_records_triangulated.json",
        "outputs/research_sources/live_source_coverage.csv",
        "outputs/gaps_summary.csv",
        "outputs/credentials_database.json",
        "outputs/competences_full_database.json",
        "outputs/cumulative_qmbd_records.json",
        "outputs/report_index.html",
        "outputs/gaps_by_sector.html",
        "outputs/credentials_matrix.html",
        "outputs/literature_integration.html",
        "outputs/sector_dictionaries/blue_biotech_tmbd_dictionary.json",
        "MANIFEST_SOURCES.csv",
    ]
    for rel in required_targets:
        _write_text(base_dir / rel, f"content for {rel}\n")


def test_archive_run_outputs_creates_full_run_archive(tmp_path: Path) -> None:
    module = _load_archive_module()
    _seed_required_targets(tmp_path)
    _write_text(tmp_path / "outputs/research_api_health.json", '{"status":"ok"}\n')
    _write_text(tmp_path / "outputs/validation_state.json", '{"status":"passed"}\n')

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
            "crossref,scopus,wos",
            "--max-results-per-query",
            "50",
            "--offline",
            "false",
            "--require-live-records",
            "true",
        ]
    )
    assert exit_code == 0

    run_dir = tmp_path / "outputs" / "run_archive" / "runs" / "run-123-1"
    assert run_dir.exists()
    assert (run_dir / "outputs" / "gaps_summary.csv").exists()
    assert (
        run_dir / "outputs" / "research_sources" / "live_records_triangulated.json"
    ).exists()
    assert (run_dir / "MANIFEST_SOURCES.csv").exists()
    assert (run_dir / "_checksums.sha256").exists()

    manifest = json.loads((run_dir / "_run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "run-123-1"
    assert manifest["requested_run_id"] == "run-123-1"
    assert manifest["manifest_schema"] == "schemas/run_archive_manifest.schema.json"
    assert manifest["workflow"]["name"] == "Full Live-Enriched Analysis"
    assert manifest["workflow"]["inputs"]["providers"] == "crossref,scopus,wos"

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


def test_manifest_matches_json_schema(tmp_path: Path) -> None:
    module = _load_archive_module()
    _seed_required_targets(tmp_path)
    _write_text(tmp_path / "outputs/validation_state.json", '{"status":"passed"}\n')

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
        tmp_path / "outputs" / "run_archive" / "runs" / "run-schema" / "_run_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_path = REPO_ROOT / "schemas" / "run_archive_manifest.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda item: item.path)
    assert not errors


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

    _write_text(tmp_path / "outputs/gaps_summary.csv", "mutated snapshot content\n")
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


def test_archive_does_not_modify_latest_snapshot_outputs(tmp_path: Path) -> None:
    module = _load_archive_module()
    _seed_required_targets(tmp_path)

    tracked_latest = [
        tmp_path / "outputs" / "gaps_summary.csv",
        tmp_path / "outputs" / "credentials_database.json",
        tmp_path / "outputs" / "competences_full_database.json",
        tmp_path / "outputs" / "cumulative_qmbd_records.json",
        tmp_path / "outputs" / "report_index.html",
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
