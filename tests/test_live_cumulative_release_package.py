"""Tests for the release package builder and final H3 report contract."""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_PACKAGE_SPEC = importlib.util.spec_from_file_location(
    "build_live_cumulative_release_package",
    str(REPO_ROOT / "scripts" / "build_live_cumulative_release_package.py"),
)
assert _PACKAGE_SPEC and _PACKAGE_SPEC.loader
_PACKAGE = importlib.util.module_from_spec(_PACKAGE_SPEC)
_PACKAGE_SPEC.loader.exec_module(_PACKAGE)
build_main = _PACKAGE.main
DEMAND_STRENGTH_FORMULA = _PACKAGE.DEMAND_STRENGTH_FORMULA
CSV_FILES = _PACKAGE.CSV_FILES
JSONL_FILES = _PACKAGE.JSONL_FILES
DATABASE_METADATA_FILES = _PACKAGE.DATABASE_METADATA_FILES
LAYER4_STAT_FILES = _PACKAGE.LAYER4_STAT_FILES
REPORT_FILES = _PACKAGE.REPORT_FILES

_REPORT_SPEC = importlib.util.spec_from_file_location(
    "build_statistical_research_report",
    str(REPO_ROOT / "scripts" / "build_statistical_research_report.py"),
)
assert _REPORT_SPEC and _REPORT_SPEC.loader
_REPORT = importlib.util.module_from_spec(_REPORT_SPEC)
_REPORT_SPEC.loader.exec_module(_REPORT)


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


def _h1_payload() -> dict[str, object]:
    return {
        "hypothesis_id": "H1",
        "hypothesis_label": "Maritimisation Shift",
        "effect_size_cohens_d": 0.3,
        "interpretation": "partially_supported_maritime",
        "validity_warning": "",
    }


def _h2_payload() -> dict[str, object]:
    return {
        "hypothesis_id": "H2",
        "hypothesis_label": "Hydronization Lag",
        "missing_ratio": 0.5,
        "interpretation": "not_computable",
        "validity_warning": "no_validated_supply_map",
    }


def _h3_payload() -> dict[str, object]:
    return {
        "hypothesis_id": "H3",
        "hypothesis_label": "MARINE vs OCEANIC Differential Coverage",
        "marine_fragment_count": 7,
        "oceanic_fragment_count": 5,
        "balance_score": 0.833333,
        "semantic_bridge_count": 2,
        "interpretation": "supported",
        "validity_warning": "",
    }


def _all_hypotheses() -> dict[str, object]:
    return {"H1": _h1_payload(), "H2": _h2_payload(), "H3": _h3_payload()}


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
        if name == "layer5_manifest.json":
            payload = {"hypothesis_results": _all_hypotheses()}
            (db / name).write_text(
                json.dumps(payload, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif name.endswith(".json"):
            (db / name).write_text("{}\n", encoding="utf-8")
        elif name.endswith(".sha256"):
            dummy_hash = "a" * 64
            (db / name).write_text(
                f"{dummy_hash}  evidence_records.csv\n", encoding="utf-8"
            )
        else:
            (db / name).write_text("fixture data\n", encoding="utf-8")
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


def _stamp_current_run_id(db: Path, run_id: str) -> None:
    for name in ("run_novelty_metrics.json", "layer4_manifest.json", "layer5_manifest.json"):
        path = db / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
        payload["current_run_id"] = run_id
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


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
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
        checksums = archive.read("CHECKSUMS.sha256").decode("utf-8")
        packaged_layer5 = json.loads(
            archive.read("metadata/layer5_manifest.json")
        )

    for required in (
        "README_DATA_PACKAGE.md",
        "RELEASE_MANIFEST.json",
        "CHECKSUMS.sha256",
        "CITATION_APA.txt",
        "VARIABLE_LABELS.csv",
        "VALUE_LABELS.csv",
    ):
        assert required in names, f"missing {required}"
    assert manifest["demand_strength_formula"] == DEMAND_STRENGTH_FORMULA
    assert manifest["version_tag"] == "test"
    assert "RELEASE_MANIFEST.json" in checksums
    assert "CHECKSUMS.sha256" not in checksums
    assert "protocol/live_query_protocol.yml" in names
    assert "provenance/raw_acquisition_index.csv" in names
    assert "data/jsonl/hypothesis_semantic_fragments.jsonl" in names

    for name in LAYER4_STAT_FILES:
        archive_name = f"statistics/{name}"
        assert archive_name in names
        assert f"  {archive_name}\n" in checksums

    assert packaged_layer5["hypothesis_results"]["H3"]["hypothesis_id"] == "H3"


def test_reports_render_executable_h3(tmp_path: Path) -> None:
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    db.mkdir()
    (db / "layer5_manifest.json").write_text(
        json.dumps({"hypothesis_results": _all_hypotheses()}),
        encoding="utf-8",
    )

    html_path = _REPORT.build_html_report(
        database_dir=db,
        reports_dir=reports,
        generated_at="2026-07-14T00:00:00+00:00",
    )
    audit_path = _REPORT.build_methodological_audit(
        database_dir=db,
        reports_dir=reports,
        generated_at="2026-07-14T00:00:00+00:00",
    )

    for path in (html_path, audit_path):
        text = path.read_text(encoding="utf-8")
        assert "H3 — Omniocean Axis Translation" in text
        assert "marine_fragment_count" in text
        assert "semantic_bridge_count" in text
        assert "supported" in text


def test_package_fails_when_required_csv_missing(tmp_path: Path) -> None:
    """Missing required Layer 5 artifacts must fail non-zero."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
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


def test_package_rejects_stale_current_run_id(tmp_path: Path) -> None:
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _stamp_current_run_id(db, "RUN-OLDER")
    out = tmp_path / "pkg.zip"
    rc = build_main([
        "--database-dir", str(db),
        "--reports-dir", str(reports),
        "--output", str(out),
        "--version-tag", "test",
        "--generated-at-utc", "2026-07-10T00:00:00+00:00",
        "--current-run-id", "RUN-NEW",
        *_required_source_args(db),
    ])
    assert rc == 1
    assert not out.exists()


def test_report_rejects_stale_current_run_id(tmp_path: Path) -> None:
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _stamp_current_run_id(db, "RUN-OLDER")
    rc = _REPORT.main([
        "--database-dir", str(db),
        "--output-dir", str(reports),
        "--formats", "html",
        "--current-run-id", "RUN-NEW",
    ])
    assert rc == 1
