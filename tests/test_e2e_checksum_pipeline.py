from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path
from typing import Any, Mapping

from src.scientific_sources.cumulative_scientific_database import (
    build_cumulative_scientific_database,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / "config" / "live_query_protocol.yml"
FROZEN_TS = "2026-07-23T00:00:00+00:00"
RUN_ID = "RUN-E2E-1"
BOUND_QUERY_TEXT = "marine biotechnology blue bioeconomy innovation governance"

_LAYER45_SPEC = importlib.util.spec_from_file_location(
    "build_layer4_5_scientific_analysis",
    str(REPO_ROOT / "scripts" / "build_layer4_5_scientific_analysis.py"),
)
assert _LAYER45_SPEC and _LAYER45_SPEC.loader
_LAYER45 = importlib.util.module_from_spec(_LAYER45_SPEC)
_LAYER45_SPEC.loader.exec_module(_LAYER45)
build_layer45_main = _LAYER45.main

_NOVELTY_SPEC = importlib.util.spec_from_file_location(
    "compute_live_novelty_metrics",
    str(REPO_ROOT / "scripts" / "compute_live_novelty_metrics.py"),
)
assert _NOVELTY_SPEC and _NOVELTY_SPEC.loader
_NOVELTY = importlib.util.module_from_spec(_NOVELTY_SPEC)
_NOVELTY_SPEC.loader.exec_module(_NOVELTY)
compute_novelty_main = _NOVELTY.main

_PACKAGE_SPEC = importlib.util.spec_from_file_location(
    "build_live_cumulative_release_package",
    str(REPO_ROOT / "scripts" / "build_live_cumulative_release_package.py"),
)
assert _PACKAGE_SPEC and _PACKAGE_SPEC.loader
_PACKAGE = importlib.util.module_from_spec(_PACKAGE_SPEC)
_PACKAGE_SPEC.loader.exec_module(_PACKAGE)
build_package_main = _PACKAGE.main


def _write_live_records(dir_path: Path, records: list[Mapping[str, Any]]) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "live_records.json").write_text(
        json.dumps(records, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_query_execution_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "query_id",
                "provider",
                "provider_canonical",
                "returned_record_count",
                "contributed_record_count",
                "execution_status",
                "errors",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
            {
                "query_id": "Q1",
                "provider": "Crossref",
                "provider_canonical": "crossref",
                "returned_record_count": "1",
                "contributed_record_count": "1",
                "execution_status": "ok",
                "errors": "",
            }
        )


def _write_layer1_index(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "query_id",
                "sector_slug",
                "sector_label",
                "axis_target",
                "axis_group",
                "axis_code",
                "query_family",
                "provider",
                "query_text",
                "raw_record_count",
                "normalized_record_count",
                "unique_source_ids",
                "coverage_record_count",
                "has_raw_payload_envelope",
                "raw_payload_sha256",
                "raw_payload_captured_at",
                "protocol_binding",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(
            {
                "query_id": "Q1",
                "sector_slug": "marine_biotech",
                "sector_label": "Marine biotechnology",
                "axis_target": "MARINE",
                "axis_group": "MARINE",
                "axis_code": "M",
                "query_family": "core_sector",
                "provider": "Crossref",
                "query_text": BOUND_QUERY_TEXT,
                "raw_record_count": "1",
                "normalized_record_count": "1",
                "unique_source_ids": "1",
                "coverage_record_count": "1",
                "has_raw_payload_envelope": "false",
                "raw_payload_sha256": "",
                "raw_payload_captured_at": "",
                "protocol_binding": "bound",
            }
        )


def _write_reports(reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    html = (
        "<html><body>"
        "Scientific hypothesis verification H1 H2 H3 "
        "Validity threats Reproducibility appendix"
        "</body></html>"
    )
    (reports_dir / "morskamary_statistical_report.html").write_text(
        html,
        encoding="utf-8",
    )
    (reports_dir / "morskamary_methodological_audit.html").write_text(
        html,
        encoding="utf-8",
    )
    (reports_dir / "morskamary_statistical_report.pdf").write_text(
        "PDF stub\n",
        encoding="utf-8",
    )


def _parse_checksum_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, relpath = line.split("  ", 1)
        entries[relpath] = digest
    return entries


def test_e2e_checksum_pipeline_produces_preflight_clean_release_zip(
    tmp_path: Path,
) -> None:
    outputs_root = tmp_path / "outputs"
    research_dir = outputs_root / "research_sources"
    live_runs_root = outputs_root / "live_runs"
    db_dir = outputs_root / "cumulative_database"
    stats_dir = outputs_root / "layer4_statistics"
    reports_dir = tmp_path / "reports"
    release_zip = outputs_root / "release_packages" / "morskamary_live_cumulative_latest.zip"
    raw_index_path = live_runs_root / RUN_ID / "raw" / "raw_acquisition_index.csv"
    projection_path = research_dir / "research_queries_from_protocol.yml"
    constraints_path = research_dir / "query_protocol_constraints.json"
    query_log_path = research_dir / "query_execution_log.csv"
    novelty_report_path = db_dir / "novelty_gate_report.json"
    provider_health_path = tmp_path / "research_api_health.json"

    _write_live_records(
        research_dir,
        [
            {
                "title": "Blue economy competences and workforce training",
                "doi": "10.1000/e2e.1",
                "source_id": "crossref:10.1000/e2e.1",
                "provider": "Crossref",
                "source_query": BOUND_QUERY_TEXT,
                "subject_terms": ["workforce training", "blue economy competences"],
                "retrieval_timestamp": FROZEN_TS,
            }
        ],
    )
    _write_query_execution_log(query_log_path)
    _write_layer1_index(raw_index_path)
    projection_path.write_text("query_groups: {}\n", encoding="utf-8")
    constraints_path.write_text("{}\n", encoding="utf-8")
    provider_health_path.write_text(
        json.dumps({"crossref": {"status": "ok"}}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_reports(reports_dir)

    cumulative = build_cumulative_scientific_database(
        current_run_dir=outputs_root,
        output_dir=db_dir,
        live_runs_root=live_runs_root,
        protocol_path=PROTOCOL_PATH,
        current_run_id=RUN_ID,
        built_at_utc=FROZEN_TS,
    )
    assert (db_dir / "run_novelty_metrics.json").is_file()
    assert cumulative.evidence_records
    assert cumulative.competence_demand_signals

    layer45_rc = build_layer45_main(
        [
            "--database-dir",
            str(db_dir),
            "--output-dir",
            str(db_dir),
            "--stats-dir",
            str(stats_dir),
            "--repository-root",
            str(REPO_ROOT),
            "--outputs-root",
            str(outputs_root),
            "--current-run-id",
            RUN_ID,
            "--analysis-timestamp-utc",
            FROZEN_TS,
        ]
    )
    assert layer45_rc == 0

    layer45_entries = _parse_checksum_manifest(db_dir / "_checksums_layer45.sha256")
    assert "../layer4_statistics/qmbd_cross_tables.csv" in layer45_entries
    assert "layer4_manifest.json" in layer45_entries
    assert "layer5_manifest.json" in layer45_entries

    novelty_rc = compute_novelty_main(
        [
            "--metrics",
            str(db_dir / "run_novelty_metrics.json"),
            "--provider-health",
            str(provider_health_path),
            "--current-run",
            str(outputs_root),
            "--output",
            str(novelty_report_path),
            "--strict",
        ]
    )
    assert novelty_rc == 0

    canonical_entries = _parse_checksum_manifest(db_dir / "_checksums.sha256")
    assert canonical_entries["novelty_gate_report.json"] == hashlib.sha256(
        novelty_report_path.read_bytes()
    ).hexdigest()

    package_rc = build_package_main(
        [
            "--database-dir",
            str(db_dir),
            "--reports-dir",
            str(reports_dir),
            "--stats-dir",
            str(stats_dir),
            "--protocol-path",
            str(PROTOCOL_PATH),
            "--projection-path",
            str(projection_path),
            "--constraints-path",
            str(constraints_path),
            "--query-execution-log",
            str(query_log_path),
            "--raw-acquisition-index",
            str(raw_index_path),
            "--current-run-id",
            RUN_ID,
            "--version-tag",
            "e2e-test",
            "--generated-at-utc",
            FROZEN_TS,
            "--output",
            str(release_zip),
        ]
    )
    assert package_rc == 0
    assert release_zip.is_file()

    with zipfile.ZipFile(release_zip) as archive:
        names = set(archive.namelist())
        checksums = archive.read("CHECKSUMS.sha256").decode("utf-8")

    assert "CHECKSUMS.sha256" in names
    assert "RELEASE_MANIFEST.json" in names
    assert "data/csv/derived_competence_demands.csv" in names
    assert "metadata/novelty_gate_report.json" in names
    assert "statistics/qmbd_cross_tables.csv" in names
    assert "  statistics/qmbd_cross_tables.csv\n" in checksums
