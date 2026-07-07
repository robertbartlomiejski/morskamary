from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_cross_run_evidence_index.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_cross_run_evidence_index", SCRIPT_PATH
    )
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


def _seed_run_archive(root: Path) -> None:
    archive_root = root / "outputs" / "run_archive"
    run_a = archive_root / "runs" / "run-a"
    run_b = archive_root / "runs" / "run-b"
    run_invalid = archive_root / "runs" / "run-invalid"

    _write_text(
        archive_root / "cumulative_runs_index.csv",
        (
            "timestamp_utc,run_id,run_path\n"
            "2026-06-01T00:00:00+00:00,run-a,runs/run-a\n"
            "2026-06-02T00:00:00+00:00,run-b,runs/run-b\n"
            "2026-06-03T00:00:00+00:00,run-invalid,runs/run-invalid\n"
        ),
    )

    for run_dir, ts in (
        (run_a, "2026-06-01T00:00:00+00:00"),
        (run_b, "2026-06-02T00:00:00+00:00"),
        (run_invalid, "2026-06-03T00:00:00+00:00"),
    ):
        _write_json(
            run_dir / "manifest.json",
            {"run_id": run_dir.name, "timestamp_utc": ts},
        )

    _write_json(
        run_a / "research_sources" / "live_records.json",
        [
            {
                "doi": "10.1000/abc",
                "source_id": "SRC-A-1",
                "title": "Alpha",
                "axis_name": "M",
            },
            {"source_id": "SRC-A-2", "title": "Beta", "record_origin": "live-crossref"},
        ],
    )
    _write_json(
        run_a / "research_sources" / "live_records_triangulated.json",
        {"records": [{"doi": "10.1000/abc", "title": "Alpha Tri"}]},
    )
    _write_json(
        run_a / "analysis_outputs" / "cumulative_qmbd_records.json",
        {"records": [{"source_id": "SRC-A-2", "title": "Beta Cumulative"}]},
    )

    _write_json(
        run_b / "research_sources" / "live_records.json",
        [{"doi": "10.1000/abc", "source_id": "SRC-B-1", "title": "Alpha B"}],
    )
    _write_json(
        run_b / "research_sources" / "live_records_triangulated.json",
        {"records": [{"title": "Gamma"}]},
    )
    _write_json(
        run_b / "analysis_outputs" / "cumulative_qmbd_records.json",
        {"records": [{"doi": "10.3000/qwe", "title": "Delta"}]},
    )

    _write_json(
        run_invalid / "research_sources" / "live_records.json",
        [{"doi": "10.5000/zzz", "title": "Invalid"}],
    )
    _write_json(
        run_invalid / "analysis_outputs" / "cumulative_qmbd_records.json",
        {"records": [{"doi": "10.5000/zzz", "title": "Invalid"}]},
    )
    _write_text(
        run_invalid / "research_sources" / "live_records_triangulated.json",
        "{this is invalid json}",
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_build_cross_run_evidence_index_builds_tables_and_skips_invalid_run(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _seed_run_archive(tmp_path)

    exit_code = module.main(
        [
            "--archive-root",
            str(tmp_path / "outputs" / "run_archive"),
            "--output-dir",
            str(tmp_path / "outputs" / "run_archive"),
            "--dedupe-key",
            "doi,source_id,title",
            "--fail-on-invalid",
            "false",
        ]
    )
    assert exit_code == 0

    output_dir = tmp_path / "outputs" / "run_archive"
    summary_rows = _read_csv(output_dir / "cross_run_run_summary.csv")
    occurrence_rows = _read_csv(output_dir / "cross_run_evidence_occurrences.csv")
    index_rows = _read_csv(output_dir / "cross_run_evidence_index.csv")
    report = json.loads(
        (output_dir / "cross_run_evidence_build_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert [row["run_id"] for row in summary_rows] == ["run-a", "run-b"]
    assert report["runs_total"] == 3
    assert report["runs_processed"] == 2
    assert report["runs_skipped_invalid"] == 1

    alpha_rows = [row for row in index_rows if row["dedupe_value"] == "10.1000/abc"]
    assert len(alpha_rows) == 1
    assert alpha_rows[0]["run_count"] == "2"
    assert alpha_rows[0]["occurrence_count"] == "3"

    assert any(
        row["dedupe_field_used"] == "title" and row["title"] == "Gamma"
        for row in occurrence_rows
    )


def test_build_cross_run_evidence_index_fails_on_invalid_when_enabled(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _seed_run_archive(tmp_path)

    exit_code = module.main(
        [
            "--archive-root",
            str(tmp_path / "outputs" / "run_archive"),
            "--output-dir",
            str(tmp_path / "outputs" / "run_archive"),
            "--fail-on-invalid",
            "true",
        ]
    )
    assert exit_code == 1


def test_build_cross_run_evidence_index_fails_when_cumulative_index_is_missing(
    tmp_path: Path,
) -> None:
    module = _load_module()
    output_dir = tmp_path / "outputs" / "run_archive"
    output_dir.mkdir(parents=True)

    exit_code = module.main(
        [
            "--archive-root",
            str(tmp_path / "outputs" / "run_archive"),
            "--output-dir",
            str(tmp_path / "outputs" / "run_archive"),
        ]
    )
    assert exit_code == 1


def test_build_cross_run_evidence_index_includes_manual_ledger_occurrences(
    tmp_path: Path,
) -> None:
    module = _load_module()
    _seed_run_archive(tmp_path)

    manual_dir = tmp_path / "outputs" / "manual_sources"
    _write_text(
        manual_dir / "manual_sources_ledger.jsonl",
        "\n".join(
            [
                json.dumps(
                    {
                        "source_id": "manual_src_abc123",
                        "file_name": "manual-report.pdf",
                        "title": "Manual Report",
                        "ingested_at_utc": "2026-07-01T00:00:00+00:00",
                    }
                ),
                json.dumps(
                    {
                        "source_id": "manual_src_def456",
                        "title": "Second Manual",
                        "ingested_at_utc": "2026-07-02T00:00:00+00:00",
                    }
                ),
            ]
        )
        + "\n",
    )

    exit_code = module.main(
        [
            "--archive-root",
            str(tmp_path / "outputs" / "run_archive"),
            "--output-dir",
            str(tmp_path / "outputs" / "run_archive"),
            "--fail-on-invalid",
            "false",
            "--manual-ledger",
            str(manual_dir / "manual_sources_ledger.jsonl"),
        ]
    )
    assert exit_code == 0

    rows = _read_csv(
        tmp_path / "outputs" / "run_archive" / "cross_run_evidence_occurrences.csv"
    )
    manual_rows = [row for row in rows if row["dataset"] == "manual_supporting_sources"]
    assert len(manual_rows) == 2
