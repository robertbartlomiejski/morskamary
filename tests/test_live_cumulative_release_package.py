"""Tests for the release package builder (PR-190 Task C)."""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "build_live_cumulative_release_package",
    str(REPO_ROOT / "scripts" / "build_live_cumulative_release_package.py"),
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
build_main = _MOD.main
DEMAND_STRENGTH_FORMULA = _MOD.DEMAND_STRENGTH_FORMULA
CSV_FILES = _MOD.CSV_FILES
JSONL_FILES = _MOD.JSONL_FILES
DATABASE_METADATA_FILES = _MOD.DATABASE_METADATA_FILES
LAYER4_STAT_FILES = _MOD.LAYER4_STAT_FILES
REPORT_FILES = _MOD.REPORT_FILES


def _required_source_args(db: Path) -> list[str]:
    root = db.parent
    return [
        "--stats-dir", str(root / "stats"),
        "--protocol-path", str(root / "protocol.yml"),
        "--projection-path", str(root / "projection.yml"),
        "--constraints-path", str(root / "constraints.json"),
        "--query-execution-log", str(root / "query_execution_log.csv"),
        "--raw-acquisition-index", str(root / "raw_acquisition_index.csv"),
    ]


def _write_min_bundle(db: Path, reports: Path) -> None:
    root = db.parent
    stats = root / "stats"
    db.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    stats.mkdir(parents=True, exist_ok=True)

    for name in CSV_FILES:
        (db / name).write_text("col_a\nval_1\n", encoding="utf-8")
    for name in JSONL_FILES:
        (db / name).write_text(
            json.dumps({"evidence_id": "E-0001"}) + "\n",
            encoding="utf-8",
        )
    for name in DATABASE_METADATA_FILES:
        if name.endswith(".json"):
            (db / name).write_text("{}\n", encoding="utf-8")
        else:
            (db / name).write_text("fixture checksum\n", encoding="utf-8")
    (db / "VARIABLE_LABELS.csv").write_text(
        "variable,label\nx,y\n",
        encoding="utf-8",
    )
    (db / "VALUE_LABELS.csv").write_text(
        "variable,value,label\n",
        encoding="utf-8",
    )
    for name in REPORT_FILES:
        (reports / name).write_bytes(b"<html>fixture</html>")
    for name in LAYER4_STAT_FILES:
        if name.endswith(".json"):
            (stats / name).write_text("{}\n", encoding="utf-8")
        else:
            (stats / name).write_text("col_a\nval_1\n", encoding="utf-8")

    (root / "protocol.yml").write_text("protocol_version: 1\n", encoding="utf-8")
    (root / "projection.yml").write_text("query_groups: {}\n", encoding="utf-8")
    (root / "constraints.json").write_text("{}\n", encoding="utf-8")
    (root / "query_execution_log.csv").write_text(
        "query_id,status\nQ1,applied\n",
        encoding="utf-8",
    )
    (root / "raw_acquisition_index.csv").write_text(
        "query_id,provider\nQ1,Crossref\n",
        encoding="utf-8",
    )


def test_package_is_deterministic(tmp_path: Path) -> None:
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    out1 = tmp_path / "pkg1.zip"
    out2 = tmp_path / "pkg2.zip"
    for out in (out1, out2):
        rc = build_main([
            "--database-dir", str(db),
            "--reports-dir", str(reports),
            "--output", str(out),
            "--version-tag", "test",
            "--generated-at-utc", "2026-07-10T00:00:00+00:00",
            *_required_source_args(db),
        ])
        assert rc == 0
    assert out1.read_bytes() == out2.read_bytes()


def test_package_contains_required_files(tmp_path: Path) -> None:
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    out = tmp_path / "pkg.zip"
    rc = build_main([
        "--database-dir", str(db),
        "--reports-dir", str(reports),
        "--output", str(out),
        "--version-tag", "test",
        "--generated-at-utc", "2026-07-10T00:00:00+00:00",
        *_required_source_args(db),
    ])
    assert rc == 0
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("RELEASE_MANIFEST.json"))
        checksums = zf.read("CHECKSUMS.sha256").decode("utf-8")
    for required in ("README_DATA_PACKAGE.md", "RELEASE_MANIFEST.json",
                     "CHECKSUMS.sha256", "CITATION_APA.txt",
                     "VARIABLE_LABELS.csv", "VALUE_LABELS.csv"):
        assert required in names, f"missing {required}"
    assert manifest["demand_strength_formula"] == DEMAND_STRENGTH_FORMULA
    assert manifest["version_tag"] == "test"
    assert "RELEASE_MANIFEST.json" in checksums
    assert "CHECKSUMS.sha256" not in checksums
    assert "protocol/live_query_protocol.yml" in names
    assert "provenance/raw_acquisition_index.csv" in names
    assert "statistics/qmbd_cross_tables.csv" in names
    assert "data/jsonl/hypothesis_semantic_fragments.jsonl" in names


def test_package_fails_when_required_csv_missing(tmp_path: Path) -> None:
    """Fix 4 regression test: missing required artifacts must fail non-zero."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    # Remove two required CSVs to simulate incomplete Layer 5 build.
    (db / "learning_outcomes.csv").unlink()
    (db / "credential_translation_eqf4_7.csv").unlink()
    out = tmp_path / "pkg_fail.zip"
    rc = build_main([
        "--database-dir", str(db),
        "--reports-dir", str(reports),
        "--output", str(out),
        "--version-tag", "test",
        "--generated-at-utc", "2026-07-10T00:00:00+00:00",
        *_required_source_args(db),
    ])
    assert rc == 1, "expected non-zero exit when required artifacts are missing"
    assert not out.exists(), "ZIP must not be written when pre-flight fails"
