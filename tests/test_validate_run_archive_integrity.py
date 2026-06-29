from __future__ import annotations

import csv
import importlib.util
import json
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


def _write_json(path: Path, payload: object) -> None:
    _write_text(path, json.dumps(payload, indent=2) + "\n")


def _seed_required_targets(base_dir: Path) -> None:
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
    _write_text(base_dir / "outputs/gaps_summary.csv", "sector,gap_count\nports,1\n")
    _write_json(
        base_dir / "outputs/credentials_database.json",
        {
            "credentials": [{"id": "cred-1"}, {"id": "cred-2"}],
            "items": [{"id": "ignore-me"}],
        },
    )
    _write_json(
        base_dir / "outputs/competences_full_database.json",
        {
            "baseline": [{"id": "b-1"}],
            "literature": [{"id": "l-1"}],
        },
    )
    _write_json(
        base_dir / "outputs/cumulative_qmbd_records.json",
        {
            "records": [
                {"id": "q-1", "record_origin": "live-crossref"},
                {"id": "q-2", "record_origin": "baseline"},
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


def _seed_manifest_schema(base_dir: Path) -> None:
    schema_source = REPO_ROOT / "schemas" / "run_archive_manifest.schema.json"
    schema_target = base_dir / "schemas" / "run_archive_manifest.schema.json"
    schema_target.parent.mkdir(parents=True, exist_ok=True)
    schema_target.write_text(schema_source.read_text(encoding="utf-8"), encoding="utf-8")


def _create_archive(tmp_path: Path, run_id: str = "run-ok") -> Path:
    archive_module = _load_module(ARCHIVE_SCRIPT_PATH, "archive_run_outputs_validate_tests")
    _seed_required_targets(tmp_path)
    _seed_manifest_schema(tmp_path)
    _write_json(tmp_path / "outputs/validation_state.json", {"status": "passed"})
    exit_code = archive_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--run-id",
            run_id,
            "--query-file",
            "config/research_queries.yml",
        ]
    )
    assert exit_code == 0
    return tmp_path / "outputs" / "run_archive" / "runs" / run_id


def _validate_archive(tmp_path: Path) -> int:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH,
        "validate_run_archive_integrity_tests",
    )
    return validate_module.main(
        [
            "--repo-root",
            str(tmp_path),
            "--archive-root",
            "outputs/run_archive",
            "--require-present",
        ]
    )


def test_validate_run_archive_integrity_passes_for_valid_archive(tmp_path: Path) -> None:
    _create_archive(tmp_path)
    assert _validate_archive(tmp_path) == 0


def test_validate_run_archive_integrity_detects_checksum_tampering(tmp_path: Path) -> None:
    run_dir = _create_archive(tmp_path, run_id="run-tampered")
    _write_text(run_dir / "outputs" / "gaps_summary.csv", "tampered\n")
    assert _validate_archive(tmp_path) == 1


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
    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_requires_jsonl_index_file(tmp_path: Path) -> None:
    _create_archive(tmp_path, run_id="run-index-jsonl")
    index_path = tmp_path / "outputs" / "run_archive" / "_index" / "runs_index.jsonl"
    index_path.unlink()
    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_requires_cumulative_csv_index(tmp_path: Path) -> None:
    _create_archive(tmp_path, run_id="run-index-csv")
    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    csv_path.unlink()
    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_requires_cumulative_csv_columns(
    tmp_path: Path,
) -> None:
    _create_archive(tmp_path, run_id="run-csv-columns")
    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    _write_text(csv_path, "run_id,run_path\nrun-csv-columns,/tmp/path\n")
    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_requires_archived_run_in_cumulative_csv(
    tmp_path: Path,
) -> None:
    _create_archive(tmp_path, run_id="run-csv-missing")
    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({"run_id": "different-run", "run_path": "runs/different-run"})

    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_requires_consistent_cumulative_csv_run_path(
    tmp_path: Path,
) -> None:
    _create_archive(tmp_path, run_id="run-csv-path")
    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())

    rows[-1]["run_path"] = "runs/not-the-real-path"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_accepts_legacy_absolute_cumulative_csv_run_path(
    tmp_path: Path,
) -> None:
    run_dir = _create_archive(tmp_path, run_id="run-csv-legacy-abs")
    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())

    rows[-1]["run_path"] = run_dir.resolve().as_posix()
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    assert _validate_archive(tmp_path) == 0


def test_validate_run_archive_integrity_accepts_legacy_manifest_filename(
    tmp_path: Path,
) -> None:
    run_dir = _create_archive(tmp_path, run_id="run-legacy")
    canonical_manifest = run_dir / "manifest.json"
    compat_manifest = run_dir / "run_manifest.json"
    legacy_manifest = run_dir / "_run_manifest.json"
    compat_manifest.unlink()
    canonical_manifest.rename(legacy_manifest)

    assert _validate_archive(tmp_path) == 0


def test_validate_run_archive_integrity_prefers_canonical_manifest_over_compat(
    tmp_path: Path,
) -> None:
    run_dir = _create_archive(tmp_path, run_id="run-canonical")
    _write_text(run_dir / "run_manifest.json", "this is not valid json\n")

    assert _validate_archive(tmp_path) == 0
