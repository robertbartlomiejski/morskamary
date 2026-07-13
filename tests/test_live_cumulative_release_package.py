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


def _write_min_bundle(db: Path, reports: Path) -> None:
    db.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    # Write all required CSV files so the pre-flight check passes.
    for name in CSV_FILES:
        (db / name).write_text("col_a\nval_1\n", encoding="utf-8")
    (db / "evidence_records.jsonl").write_text(
        json.dumps({"evidence_id": "E-0001"}) + "\n", encoding="utf-8"
    )
    (db / "VARIABLE_LABELS.csv").write_text("variable,label\nx,y\n", encoding="utf-8")
    (db / "VALUE_LABELS.csv").write_text("variable,value,label\n", encoding="utf-8")
    (reports / "morskamary_statistical_report.html").write_text(
        "<html></html>", encoding="utf-8"
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
    ])
    assert rc == 0
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("RELEASE_MANIFEST.json"))
    for required in ("README_DATA_PACKAGE.md", "RELEASE_MANIFEST.json",
                     "CHECKSUMS.sha256", "CITATION_APA.txt",
                     "VARIABLE_LABELS.csv", "VALUE_LABELS.csv"):
        assert required in names, f"missing {required}"
    assert manifest["demand_strength_formula"] == DEMAND_STRENGTH_FORMULA
    assert manifest["version_tag"] == "test"


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
    ])
    assert rc == 1, "expected non-zero exit when required artifacts are missing"
    assert not out.exists(), "ZIP must not be written when pre-flight fails"
