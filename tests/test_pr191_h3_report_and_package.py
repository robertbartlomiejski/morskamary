"""Final-cut regression tests for H3 reporting and Layer 4 ZIP contents."""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPORT = _load_module(
    "build_statistical_research_report",
    REPO_ROOT / "scripts" / "build_statistical_research_report.py",
)
PACKAGE = _load_module(
    "build_live_cumulative_release_package",
    REPO_ROOT / "scripts" / "build_live_cumulative_release_package.py",
)


def _h3_payload() -> dict:
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


def test_statistical_reports_serialize_h3(tmp_path: Path) -> None:
    database_dir = tmp_path / "database"
    reports_dir = tmp_path / "reports"
    database_dir.mkdir()
    (database_dir / "layer5_manifest.json").write_text(
        json.dumps({"hypothesis_results": {"H3": _h3_payload()}}),
        encoding="utf-8",
    )

    html_path = REPORT.build_html_report(
        database_dir=database_dir,
        reports_dir=reports_dir,
        generated_at="2026-07-14T00:00:00+00:00",
    )
    audit_path = REPORT.build_methodological_audit(
        database_dir=database_dir,
        reports_dir=reports_dir,
        generated_at="2026-07-14T00:00:00+00:00",
    )

    html_text = html_path.read_text(encoding="utf-8")
    audit_text = audit_path.read_text(encoding="utf-8")
    for text in (html_text, audit_text):
        assert "H3 — Omniocean Axis Translation" in text
        assert "marine_fragment_count" in text
        assert "semantic_bridge_count" in text
        assert "supported" in text


def _write_release_inputs(root: Path) -> tuple[Path, Path, Path]:
    database_dir = root / "database"
    reports_dir = root / "reports"
    stats_dir = root / "stats"
    database_dir.mkdir()
    reports_dir.mkdir()
    stats_dir.mkdir()

    for name in PACKAGE.CSV_FILES:
        (database_dir / name).write_text("column\nvalue\n", encoding="utf-8")
    for name in PACKAGE.JSONL_FILES:
        (database_dir / name).write_text("{}\n", encoding="utf-8")
    for name in PACKAGE.DATABASE_METADATA_FILES:
        if name == "layer5_manifest.json":
            payload = {"hypothesis_results": {"H3": _h3_payload()}}
            (database_dir / name).write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
        elif name.endswith(".json"):
            (database_dir / name).write_text("{}\n", encoding="utf-8")
        else:
            (database_dir / name).write_text(
                "fixture checksum\n",
                encoding="utf-8",
            )
    for name in ("VARIABLE_LABELS.csv", "VALUE_LABELS.csv"):
        (database_dir / name).write_text("column\nvalue\n", encoding="utf-8")
    for name in PACKAGE.REPORT_FILES:
        (reports_dir / name).write_text("report\n", encoding="utf-8")
    for name in PACKAGE.LAYER4_STAT_FILES:
        content = "{}\n" if name.endswith(".json") else "column\nvalue\n"
        (stats_dir / name).write_text(content, encoding="utf-8")

    (root / "protocol.yml").write_text("protocol_version: 1\n", encoding="utf-8")
    (root / "projection.yml").write_text("query_groups: {}\n", encoding="utf-8")
    (root / "constraints.json").write_text("{}\n", encoding="utf-8")
    (root / "query_execution_log.csv").write_text(
        "query_id,status\nQ1,completed\n",
        encoding="utf-8",
    )
    (root / "raw_acquisition_index.csv").write_text(
        "query_id,provider\nQ1,Crossref\n",
        encoding="utf-8",
    )
    return database_dir, reports_dir, stats_dir


def test_zip_contains_and_checksums_every_layer4_statistic(tmp_path: Path) -> None:
    database_dir, reports_dir, stats_dir = _write_release_inputs(tmp_path)
    output = tmp_path / "release.zip"
    rc = PACKAGE.main([
        "--database-dir", str(database_dir),
        "--reports-dir", str(reports_dir),
        "--stats-dir", str(stats_dir),
        "--protocol-path", str(tmp_path / "protocol.yml"),
        "--projection-path", str(tmp_path / "projection.yml"),
        "--constraints-path", str(tmp_path / "constraints.json"),
        "--query-execution-log", str(tmp_path / "query_execution_log.csv"),
        "--raw-acquisition-index", str(tmp_path / "raw_acquisition_index.csv"),
        "--generated-at-utc", "2026-07-14T00:00:00+00:00",
        "--output", str(output),
    ])
    assert rc == 0

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        checksums = archive.read("CHECKSUMS.sha256").decode("utf-8")
        packaged_layer5 = json.loads(
            archive.read("metadata/layer5_manifest.json")
        )

    for name in PACKAGE.LAYER4_STAT_FILES:
        archive_name = f"statistics/{name}"
        assert archive_name in names
        assert f"  {archive_name}\n" in checksums
    assert packaged_layer5["hypothesis_results"]["H3"]["hypothesis_id"] == "H3"
