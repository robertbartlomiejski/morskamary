from __future__ import annotations

import csv
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
            "crossref,scopus,wos",
            "--max-results-per-query",
            "50",
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
    assert (run_dir / "analysis_outputs" / "cumulative_qmbd_records.json").exists()
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
    assert manifest["manifest_schema"] == "schemas/run_archive_manifest.schema.json"
    assert manifest["workflow"]["name"] == "Full Live-Enriched Analysis"
    assert manifest["workflow"]["inputs"]["providers"] == "crossref,scopus,wos"
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
