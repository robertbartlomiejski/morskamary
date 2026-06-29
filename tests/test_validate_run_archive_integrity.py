from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SCRIPT_PATH = REPO_ROOT / "scripts" / "archive_run_outputs.py"
VALIDATE_SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_run_archive_integrity.py"


def _load_module(script_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def _seed_manifest_schema(base_dir: Path) -> None:
    schema_source = REPO_ROOT / "schemas" / "run_archive_manifest.schema.json"
    schema_target = base_dir / "schemas" / "run_archive_manifest.schema.json"
    schema_target.parent.mkdir(parents=True, exist_ok=True)
    schema_target.write_text(schema_source.read_text(encoding="utf-8"), encoding="utf-8")


def _create_archive(tmp_path: Path, run_id: str = "run-ok") -> Path:
    archive_module = _load_module(ARCHIVE_SCRIPT_PATH, "archive_run_outputs_validate_tests")
    _seed_required_targets(tmp_path)
    _seed_manifest_schema(tmp_path)
    _write_text(tmp_path / "outputs/validation_state.json", '{"status":"passed"}\n')
    exit_code = archive_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            run_id,
        ]
    )
    assert exit_code == 0
    return tmp_path / "outputs" / "run_archive" / "runs" / run_id


def test_validate_run_archive_integrity_passes_for_valid_archive(tmp_path: Path) -> None:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH, "validate_run_archive_integrity_pass_test"
    )
    _create_archive(tmp_path)

    result = validate_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--require-present",
        ]
    )
    assert result == 0


def test_validate_run_archive_integrity_detects_checksum_tampering(tmp_path: Path) -> None:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH, "validate_run_archive_integrity_tamper_test"
    )
    run_dir = _create_archive(tmp_path, run_id="run-tampered")
    _write_text(run_dir / "outputs" / "gaps_summary.csv", "tampered\n")

    result = validate_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--require-present",
        ]
    )
    assert result == 1


def test_validate_run_archive_integrity_skips_missing_archive_by_default(
    tmp_path: Path,
) -> None:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH, "validate_run_archive_integrity_skip_test"
    )

    result = validate_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
        ]
    )
    assert result == 0


def test_validate_run_archive_integrity_can_require_archive_presence(
    tmp_path: Path,
) -> None:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH, "validate_run_archive_integrity_require_test"
    )

    result = validate_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--require-present",
        ]
    )
    assert result == 1


def test_validate_run_archive_integrity_requires_index_file(tmp_path: Path) -> None:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH, "validate_run_archive_integrity_index_test"
    )
    _create_archive(tmp_path, run_id="run-index")
    index_path = tmp_path / "outputs" / "run_archive" / "_index" / "runs_index.jsonl"
    index_path.unlink()

    result = validate_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--require-present",
        ]
    )
    assert result == 1
