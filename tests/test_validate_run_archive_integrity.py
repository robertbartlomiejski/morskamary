from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


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
            "metadata": {
                "analysis_input_mode": "live-enriched",
                "is_static_recovery_mode": False,
                "static_recovery_reason": "",
                "allow_static_recovery_mode_env": "ALLOW_STATIC_RECOVERY_MODE",
                "provider_set": "crossref",
                "github_run_id": "",
                "github_run_attempt": "",
                "commit_sha": "abc123",
                "timestamp_utc": "2026-07-07T00:00:00+00:00",
                "warnings": [],
            },
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


def _refresh_archived_file_integrity(run_dir: Path, relative_path: str) -> None:
    archived_path = run_dir / relative_path
    digest = hashlib.sha256(archived_path.read_bytes()).hexdigest()
    size_bytes = archived_path.stat().st_size

    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for descriptor in manifest["files"]:
        if descriptor["path"] == relative_path:
            descriptor["sha256"] = digest
            descriptor["size_bytes"] = size_bytes
            break
    manifest["total_bytes"] = sum(item["size_bytes"] for item in manifest["files"])
    _write_json(manifest_path, manifest)
    _write_json(run_dir / "run_manifest.json", manifest)

    checksums_path = run_dir / "_checksums.sha256"
    checksum_lines = checksums_path.read_text(encoding="utf-8").splitlines()
    checksum_lines = [
        f"{digest}  {relative_path}"
        if line.endswith(f"  {relative_path}")
        else line
        for line in checksum_lines
    ]
    _write_text(checksums_path, "\n".join(checksum_lines) + "\n")


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


@pytest.mark.parametrize("field", ["file_count", "total_bytes"])
def test_validate_run_archive_integrity_rejects_stale_cumulative_csv_total(
    tmp_path: Path, field: str,
) -> None:
    _create_archive(tmp_path, run_id="run-csv-stale-total")
    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())

    rows[-1][field] = str(int(rows[-1][field]) + 1)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    assert _validate_archive(tmp_path) == 1


@pytest.mark.parametrize("field", ["file_count", "total_bytes"])
def test_validate_run_archive_integrity_rejects_stale_jsonl_total(
    tmp_path: Path, field: str,
) -> None:
    _create_archive(tmp_path, run_id="run-jsonl-stale-total")
    index_path = tmp_path / "outputs" / "run_archive" / "_index" / "runs_index.jsonl"
    entries = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entries[-1][field] += 1
    _write_text(
        index_path,
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in entries),
    )

    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_rejects_phantom_csv_run(
    tmp_path: Path,
) -> None:
    _create_archive(tmp_path, run_id="run-csv-present")
    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())

    phantom_row = dict(rows[-1])
    phantom_row["run_id"] = "run-csv-phantom"
    phantom_row["run_path"] = "runs/run-csv-phantom"
    rows.append(phantom_row)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_rejects_phantom_jsonl_run(
    tmp_path: Path,
) -> None:
    _create_archive(tmp_path, run_id="run-jsonl-present")
    index_path = tmp_path / "outputs" / "run_archive" / "_index" / "runs_index.jsonl"
    entry = json.loads(index_path.read_text(encoding="utf-8").strip())
    phantom_entry = dict(entry)
    phantom_entry["run_id"] = "run-jsonl-phantom"
    phantom_entry["run_path"] = "runs/run-jsonl-phantom"
    _write_text(
        index_path,
        json.dumps(entry, sort_keys=True)
        + "\n"
        + json.dumps(phantom_entry, sort_keys=True)
        + "\n",
    )

    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_rejects_arbitrary_absolute_cumulative_csv_run_path(
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

    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_accepts_fingerprinted_legacy_absolute_csv_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run-csv-fingerprinted-legacy"
    run_dir = _create_archive(tmp_path, run_id=run_id)
    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())

    rows[-1]["run_path"] = run_dir.resolve().as_posix()
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH,
        "validate_run_archive_integrity_fingerprinted_legacy_csv_test",
    )
    manifest_path = run_dir / "manifest.json"
    monkeypatch.setitem(
        validate_module.LEGACY_PATH_METADATA_MANIFEST_SHA256,
        run_id,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )
    assert (
        validate_module.main(
            [
                "--repo-root",
                str(tmp_path),
                "--archive-root",
                "outputs/run_archive",
                "--require-present",
            ]
        )
        == 0
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timestamp_utc", ""),
        ("timestamp_utc", "not-a-timestamp"),
        ("timestamp_utc", "2025-01-01T00:00:00+00:00"),
        ("analysis_timestamp_utc", ""),
        ("analysis_timestamp_utc", "not-a-timestamp"),
        ("analysis_timestamp_utc", "2025-01-01T00:00:00+00:00"),
    ],
)
def test_validate_run_archive_integrity_rejects_invalid_or_stale_csv_timestamp(
    tmp_path: Path, field: str, value: str
) -> None:
    _create_archive(tmp_path, run_id="run-csv-timestamp")
    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())

    rows[-1][field] = value
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    assert _validate_archive(tmp_path) == 1


@pytest.mark.parametrize(
    "archived_at",
    ["", "not-a-timestamp", "2025-01-01T00:00:00+00:00"],
)
def test_validate_run_archive_integrity_rejects_invalid_or_stale_jsonl_timestamp(
    tmp_path: Path, archived_at: str
) -> None:
    _create_archive(tmp_path, run_id="run-jsonl-timestamp")
    index_path = tmp_path / "outputs" / "run_archive" / "_index" / "runs_index.jsonl"
    entry = json.loads(index_path.read_text(encoding="utf-8").strip())
    entry["archived_at"] = archived_at
    _write_text(index_path, json.dumps(entry, sort_keys=True) + "\n")

    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_rejects_absolute_archive_root_fields(
    tmp_path: Path,
) -> None:
    run_dir = _create_archive(tmp_path, run_id="run-abs-archive-root")
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["archive_root"] = "/home/runner/work/morskamary/morskamary/outputs/run_archive"
    _write_json(manifest_path, manifest)
    _write_json(run_dir / "run_manifest.json", manifest)

    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())
    rows[-1]["archive_root"] = manifest["archive_root"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_rejects_windows_absolute_archive_root_fields(
    tmp_path: Path,
) -> None:
    run_dir = _create_archive(tmp_path, run_id="run-win-archive-root")
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["archive_root"] = r"C:\Users\runner\work\morskamary\outputs\run_archive"
    _write_json(manifest_path, manifest)
    _write_json(run_dir / "run_manifest.json", manifest)

    csv_path = tmp_path / "outputs" / "run_archive" / "cumulative_runs_index.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())
    rows[-1]["archive_root"] = manifest["archive_root"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    assert _validate_archive(tmp_path) == 1


def test_validate_run_archive_integrity_rejects_public_runner_path_leaks(
    tmp_path: Path,
) -> None:
    run_dir = _create_archive(tmp_path, run_id="run-public-path-leak")
    leaked_path = run_dir / "analysis_outputs" / "literature_integration.html"
    leaked_path.write_text(
        (
            "<a href='https://github.com/robertbartlomiejski/morskamary/"
            "blob/main//home/runner/work/morskamary/morskamary/outputs/"
            "report_index.html'>bad</a>\n"
        ),
        encoding="utf-8",
    )
    _refresh_archived_file_integrity(
        run_dir,
        "analysis_outputs/literature_integration.html",
    )

    assert _validate_archive(tmp_path) == 1


@pytest.mark.parametrize(
    "leaked_path",
    [
        "/Users/researcher/work/morskamary/output.json",
        "/opt/build/morskamary/output.json",
        "/data/custom-root/morskamary/output.json",
        r"C:\Users\researcher\work\morskamary\output.json",
        r"\\build-server\research\morskamary\output.json",
    ],
)
def test_absolute_path_leak_detection_is_platform_independent(
    tmp_path: Path, leaked_path: str
) -> None:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH,
        "validate_run_archive_integrity_portable_path_test",
    )

    assert (
        validate_module._count_absolute_path_leaks(
            json.dumps({"source_path": leaked_path}),
            repo_root=tmp_path,
        )
        == 1
    )


def test_absolute_path_leak_detection_does_not_treat_url_host_as_path(
    tmp_path: Path,
) -> None:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH,
        "validate_run_archive_integrity_url_path_test",
    )

    assert (
        validate_module._count_absolute_path_leaks(
            "https://github.com/example/project/blob/main/report.json",
            repo_root=tmp_path,
        )
        == 0
    )


def test_legacy_path_grandfathering_is_bound_to_manifest_bytes(tmp_path: Path) -> None:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH,
        "validate_run_archive_integrity_legacy_fingerprint_test",
    )
    run_id = "28967267944.2"
    manifest_path = (
        REPO_ROOT / "outputs" / "run_archive" / "runs" / run_id / "manifest.json"
    )

    assert validate_module._is_grandfathered_legacy_run(run_id, manifest_path)

    changed_manifest = tmp_path / "manifest.json"
    changed_manifest.write_bytes(manifest_path.read_bytes() + b"\n")
    assert not validate_module._is_grandfathered_legacy_run(run_id, changed_manifest)


def test_legacy_index_totals_are_limited_to_fingerprinted_exact_values(
    tmp_path: Path,
) -> None:
    validate_module = _load_module(
        VALIDATE_SCRIPT_PATH,
        "validate_run_archive_integrity_legacy_index_test",
    )
    run_id = "28967267944.2"
    expected_totals = (64, 46631770)
    index_path = tmp_path / "runs_index.jsonl"
    archive_root = REPO_ROOT / "outputs" / "run_archive"
    legacy_entry = {
        "file_count": 64,
        "total_bytes": 45636058,
    }
    legacy_totals = validate_module._legacy_index_totals(run_id, archive_root)

    assert legacy_totals == (64, 45636058)
    assert (
        validate_module._validate_index_totals(
            index_path,
            "line 1",
            run_id,
            legacy_entry,
            expected_totals,
            legacy_totals,
        )
        == []
    )

    legacy_entry["total_bytes"] += 1
    errors = validate_module._validate_index_totals(
        index_path,
        "line 1",
        run_id,
        legacy_entry,
        expected_totals,
        legacy_totals,
    )

    assert len(errors) == 1
    assert "expected 46631770, got 45636059" in errors[0]


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
