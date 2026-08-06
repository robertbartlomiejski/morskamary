"""Tests for the release package builder and final H3 report contract."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest

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
CSV_REQUIRED_COLUMNS = _PACKAGE.CSV_REQUIRED_COLUMNS
JSONL_FILES = _PACKAGE.JSONL_FILES
ALLOW_EMPTY_JSONL = _PACKAGE.ALLOW_EMPTY_JSONL
DATABASE_METADATA_FILES = _PACKAGE.DATABASE_METADATA_FILES
LAYER4_STAT_FILES = _PACKAGE.LAYER4_STAT_FILES
REPORT_FILES = _PACKAGE.REPORT_FILES
SCHEMA_V2_SCHEMA_FILENAMES = _PACKAGE.SCHEMA_V2_SCHEMA_FILENAMES

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
        "sample_size_maritime": 7,
        "sample_size_oceanic": 6,
        "effect_size_cohens_d": 0.3,
        "interpretation": "partially_supported_maritime",
        "validity_warning": "",
    }


def _h2_payload() -> dict[str, object]:
    return {
        "hypothesis_id": "H2",
        "hypothesis_label": "Hydronization Lag",
        "hydronization_demand_count": 8,
        "validated_covered_demand_count": 2,
        "validated_missing_demand_count": 6,
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


def _write_csv_rows(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _schema_v2_rows() -> dict[str, dict[str, object]]:
    source_provenance_id = (
        "prov:35e99358e7ea05bc9630930eab4cd3228b215cabd6de9984c6dbba75525367d3"
    )
    surface_text_hash = (
        "b300492f352a9fb63eb3282fb2ce0abcecde517e668f13636ec2cbe428d1cd2e"
    )
    provenance_hash = (
        "ae6f862b5bdaa0aa6aaf222d6d4015529bc08efd04dda15945c121ccb1f6566a"
    )
    return {
        "evidence_fragments": {
            "fragment_id": "fragment:test",
            "evidence_id": "E-0001",
            "run_id": "RUN-1",
            "source_provenance_id": source_provenance_id,
            "source_provider": "Crossref",
            "source_provider_id": "source:test",
            "source_retrieved_at_utc": "2026-07-10T00:00:00+00:00",
            "source_query_id": "Q1",
            "source_query_text": "fixture query",
            "source_field": "title",
            "language": "en",
            "fragment_text": "marine skill",
            "span_start_offset": 0,
            "span_end_offset": 12,
            "surface_text_hash": surface_text_hash,
            "provenance_hash": provenance_hash,
        },
        "semantic_signals": {
            "signal_id": "S-0001",
            "fragment_id": "fragment:test",
            "evidence_id": "E-0001",
            "run_id": "RUN-1",
            "source_provenance_id": source_provenance_id,
            "sector": "ports",
            "axis_group": "MARINE",
            "axis_code": "M",
            "query_id": "Q1",
            "query_family": "core_sector",
            "signal_type": "governance_skill",
            "signal_category_label": "marine skill",
            "signal_category_description": "Fixture semantic signal.",
            "matched_phrase": "marine",
            "confidence_score": 0.8,
            "classifier_version": "v1",
            "negation_status": "not_detected",
            "speculation_status": "not_detected",
            "actor_text": "",
            "action_text": "",
            "object_text": "",
            "context_text": "marine skill",
            "manual_review_status": "auto_accepted",
            "validity_warning": "",
        },
        "competence_candidates": {
            "candidate_id": "candidate:test",
            "signal_id": "S-0001",
            "fragment_id": "fragment:test",
            "evidence_id": "E-0001",
            "run_id": "RUN-1",
            "sector": "ports",
            "axis_group": "MARINE",
            "axis_code": "M",
            "source_provenance_ids": source_provenance_id,
            "fragment_ids": "fragment:test",
            "candidate_label": "Marine skill",
            "candidate_definition": "Fixture candidate definition.",
            "capability_proposition": "Apply marine skill.",
            "knowledge_dimension": "marine knowledge",
            "skill_dimension": "marine skill",
            "responsibility_autonomy_dimension": "independent practice",
            "candidate_status": "candidate",
            "review_status": "auto_accepted",
            "exact_evidence_span": "marine skill",
            "exact_span_start_offset": 0,
            "exact_span_end_offset": 12,
        },
        "validation_decisions": {
            "validation_decision_id": "decision:test",
            "target_candidate_id": "candidate:test",
            "canonical_label": "Marine skill",
            "decision_status": "accepted",
            "reviewer": "reviewer-fixture",
            "decision_at_utc": "2026-07-10T00:00:00+00:00",
            "decision_reason": "Fixture acceptance.",
            "evidence_ids": "E-0001",
            "fragment_ids": "fragment:test",
            "source_provenance_ids": source_provenance_id,
            "superseded_validation_decision_id": "",
        },
        "canonical_competences": {
            "canonical_competence_id": "canonical:test",
            "validation_decision_id": "decision:test",
            "source_candidate_id": "candidate:test",
            "preferred_label": "Marine skill",
            "canonical_definition": "Fixture candidate definition.",
            "aliases": "",
            "validation_status": "accepted",
            "schema_version": "2.0.0",
            "provenance_guard_status": "passed",
        },
        "sector_competence_assignments": {
            "assignment_id": "assignment:test",
            "canonical_competence_id": "canonical:test",
            "validation_decision_id": "decision:test",
            "source_candidate_id": "candidate:test",
            "sector": "ports",
            "axis_group": "MARINE",
            "axis_code": "M",
            "evidence_ids": "E-0001",
        },
    }


def _refresh_fragment_integrity(
    fragment: dict[str, object], *, source_provider_id: str
) -> str:
    """Refresh fixture hashes from the published source-occurrence preimage."""
    fragment["source_provider_id"] = source_provider_id
    source_query_text = re.sub(
        r"\s+", " ", str(fragment["source_query_text"])
    ).strip().lower()
    payload = "\x1f".join(
        (
            str(fragment["run_id"]),
            str(fragment["evidence_id"]),
            str(fragment["source_retrieved_at_utc"]),
            str(fragment["source_provider"]),
            source_provider_id.strip().lower(),
            str(fragment["source_query_id"]),
            source_query_text,
        )
    )
    provenance_id = "prov:" + hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()
    fragment["source_provenance_id"] = provenance_id
    fragment["provenance_hash"] = hashlib.sha256(
        provenance_id.encode("utf-8")
    ).hexdigest()
    normalized_context = re.sub(
        r"\s+", " ", str(fragment["fragment_text"])
    ).strip().lower()
    fragment["surface_text_hash"] = hashlib.sha256(
        normalized_context.encode("utf-8")
    ).hexdigest()
    return provenance_id


def _write_min_bundle(db: Path, reports: Path) -> None:
    root = db.parent
    stats = root / "stats"
    db.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    stats.mkdir(parents=True, exist_ok=True)

    schema_rows = _schema_v2_rows()
    empty_by_default = {
        "canonical_competences",
        "sector_competence_assignments",
        "validation_decisions",
    }
    derived_demand: dict[str, object] = {
        "competence_demand_id": "cd:test",
        "competence_label": "marine skill",
        "view_kind": "legacy_category_aggregate_compatibility_view",
        "scientific_status": "legacy_not_validated_canonical_competence",
        "sector": "ports",
        "axis_group": "MARINE",
        "demand_strength_score": "0.55",
        "evidence_ids": "E-0001",
    }
    for name in CSV_FILES:
        required_columns = CSV_REQUIRED_COLUMNS.get(name)
        if not required_columns:
            (db / name).write_text("col_a\nval_1\n", encoding="utf-8")
            continue
        entity_name = name.removesuffix(".csv")
        if entity_name in empty_by_default:
            _write_csv_rows(db / name, required_columns, [])
        elif entity_name == "evidence_records":
            row: dict[str, object] = {
                field_name: "x" for field_name in required_columns
            }
            row["evidence_id"] = "E-0001"
            _write_csv_rows(db / name, required_columns, [row])
        elif entity_name in schema_rows:
            _write_csv_rows(
                db / name, required_columns, [schema_rows[entity_name]]
            )
        else:
            _write_csv_rows(
                db / name,
                required_columns,
                [{field_name: "x" for field_name in required_columns}],
            )

    _write_csv_rows(
        db / "derived_competence_demands.csv",
        CSV_REQUIRED_COLUMNS["derived_competence_demands.csv"],
        [derived_demand],
    )
    _write_csv_rows(
        db / "learning_outcomes.csv",
        CSV_REQUIRED_COLUMNS["learning_outcomes.csv"],
        [{
            "outcome_id": "lo:test",
            "credential_id": "cred:test",
            "sector": "ports",
            "eqf_level": "6",
            "outcome_statement": "Outcome statement",
            "competence_demand_id": "cd:test",
            "evidence_id": "E-0001",
        }],
    )

    for name in JSONL_FILES:
        if name.removesuffix(".jsonl") in empty_by_default:
            (db / name).write_text("", encoding="utf-8")
            continue
        jsonl_payload: dict[str, object]
        if name == "hypothesis_semantic_fragments.jsonl":
            jsonl_payload = {
                "fragment_id": "fragment:S-0001:H3:test",
                "hypothesis_id": "H3",
                "hypothesis_ids": "H3",
                "signal_id": "S-0001",
                "evidence_id": "E-0001",
                "run_id": "RUN-1",
                "sector": "ports",
                "axis_group": "MARINE",
                "axis_code": "M",
                "signal_type": "competence_demand",
                "demand_phrase": "marine",
                "matched_hypothesis_phrase": "marine",
                "theory_term_family": "bridge_semantics",
                "indicator_family": "marine_ecological",
                "semantic_fragment": "marine",
                "evidence_surface": "title+subject",
                "semantic_scope": "title+subject",
                "evidence_text_hash": "abc",
                "classifier_version": "v1",
                "manual_review_status": "auto_accepted",
                "validity_warning": "",
            }
        elif name == "derived_competence_demands.jsonl":
            jsonl_payload = derived_demand
        elif name.removesuffix(".jsonl") in schema_rows:
            jsonl_payload = schema_rows[name.removesuffix(".jsonl")]
        elif name == "competence_demand_signals.jsonl":
            jsonl_payload = {"signal_id": "S-0001", "evidence_id": "E-0001"}
        else:
            jsonl_payload = {"evidence_id": "E-0001"}
        (db / name).write_text(
            json.dumps(jsonl_payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # Write all metadata files except _checksums.sha256 first, so we can
    # compute real SHA-256 digests for the checksum file.
    for name in DATABASE_METADATA_FILES:
        if name.endswith(".sha256"):
            continue
        if name == "layer5_manifest.json":
            metadata_payload = {"hypothesis_results": _all_hypotheses()}
            (db / name).write_text(
                json.dumps(metadata_payload, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif name.endswith(".json"):
            (db / name).write_text("{}\n", encoding="utf-8")
        else:
            (db / name).write_text("fixture data\n", encoding="utf-8")
    # Build a real _checksums.sha256 with actual digests.
    checksum_lines: list[str] = []
    for name in sorted(
        list(CSV_FILES) + list(JSONL_FILES)
        + [n for n in DATABASE_METADATA_FILES if not n.endswith(".sha256")]
    ):
        fp = db / name
        if fp.is_file():
            digest = hashlib.sha256(fp.read_bytes()).hexdigest()
            checksum_lines.append(f"{digest}  {name}")
    (db / "_checksums.sha256").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    (db / "VARIABLE_LABELS.csv").write_text(
        "variable,label\nx,y\n",
        encoding="utf-8",
    )
    (db / "VALUE_LABELS.csv").write_text(
        "variable,value,label\n",
        encoding="utf-8",
    )
    for name in REPORT_FILES:
        (reports / name).write_text(
            (
                "<html><body>"
                "Scientific hypothesis verification H1 H2 H3 "
                "Validity threats Reproducibility appendix"
                "</body></html>"
            ),
            encoding="utf-8",
        )
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


def _build_fixture_package(db: Path, reports: Path, output: Path) -> int:
    return int(build_main([
        "--database-dir", str(db),
        "--reports-dir", str(reports),
        "--output", str(output),
        "--version-tag", "test",
        "--generated-at-utc", "2026-07-10T00:00:00+00:00",
        *_required_source_args(db),
    ]))


def _append_schema_v2_row(
    db: Path,
    entity_name: str,
    row: dict[str, object],
) -> None:
    csv_path = db / f"{entity_name}.csv"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        csv_rows: list[dict[str, object]] = [
            {
                str(key): value
                for key, value in parsed_row.items()
                if key is not None
            }
            for parsed_row in csv.DictReader(handle)
        ]
    csv_rows.append(row)
    _write_csv_rows(csv_path, CSV_REQUIRED_COLUMNS[csv_path.name], csv_rows)
    jsonl_path = db / f"{entity_name}.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_schema_v2_decision_chain(db: Path) -> None:
    """Populate the accepted fixture chain in both package projections."""
    rows = _schema_v2_rows()
    for entity_name in (
        "validation_decisions",
        "canonical_competences",
        "sector_competence_assignments",
    ):
        row = rows[entity_name]
        _write_csv_rows(
            db / f"{entity_name}.csv",
            CSV_REQUIRED_COLUMNS[f"{entity_name}.csv"],
            [row],
        )
        (db / f"{entity_name}.jsonl").write_text(
            json.dumps(row, sort_keys=True) + "\n", encoding="utf-8"
        )


def _update_schema_v2_first_row(
    db: Path, entity_name: str, updates: dict[str, object]
) -> None:
    """Apply the same field mutation to one schema-v2 CSV/JSONL row."""
    csv_path = db / f"{entity_name}.csv"
    csv_rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert csv_rows
    csv_rows[0].update(updates)
    _write_csv_rows(
        csv_path,
        CSV_REQUIRED_COLUMNS[csv_path.name],
        [dict(row) for row in csv_rows],
    )
    jsonl_path = db / f"{entity_name}.jsonl"
    jsonl_row = json.loads(jsonl_path.read_text(encoding="utf-8"))
    jsonl_row.update(updates)
    jsonl_path.write_text(
        json.dumps(jsonl_row, sort_keys=True) + "\n", encoding="utf-8"
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

    for schema_name in SCHEMA_V2_SCHEMA_FILENAMES:
        archive_name = f"schemas/{schema_name}"
        assert archive_name in names
        assert f"  {archive_name}\n" in checksums

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


def test_package_rejects_false_checksum(tmp_path: Path) -> None:
    """A syntactically valid but incorrect checksum must fail preflight."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    # Corrupt the checksum file with a wrong digest.
    (db / "_checksums.sha256").write_text(
        "0" * 64 + "  evidence_records.csv\n", encoding="utf-8"
    )
    out = tmp_path / "pkg.zip"
    rc = build_main([
        "--database-dir", str(db),
        "--reports-dir", str(reports),
        "--output", str(out),
        "--version-tag", "test",
        "--generated-at-utc", "2026-07-10T00:00:00+00:00",
        *_required_source_args(db),
    ])
    assert rc == 1
    assert not out.exists()


def test_package_rejects_missing_csv_columns(tmp_path: Path) -> None:
    """CSVs with wrong headers must fail preflight."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    # Overwrite a required CSV with a wrong header and recompute checksums.
    (db / "evidence_records.csv").write_text(
        "wrong_col\nval\n", encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    rc = build_main([
        "--database-dir", str(db),
        "--reports-dir", str(reports),
        "--output", str(out),
        "--version-tag", "test",
        "--generated-at-utc", "2026-07-10T00:00:00+00:00",
        *_required_source_args(db),
    ])
    assert rc == 1
    assert not out.exists()


def test_package_allows_byte_empty_null_result_jsonl_tables(
    tmp_path: Path,
) -> None:
    """Null-result projections are valid only when their JSONL is byte-empty."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    for name in ALLOW_EMPTY_JSONL:
        (db / name).write_text("", encoding="utf-8")
        csv_name = name.removesuffix(".jsonl") + ".csv"
        if csv_name in CSV_REQUIRED_COLUMNS:
            _write_csv_rows(
                db / csv_name,
                CSV_REQUIRED_COLUMNS[csv_name],
                [],
            )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 0
    assert out.exists()


def test_package_rejects_whitespace_only_allowed_empty_jsonl(
    tmp_path: Path,
) -> None:
    """An allowed-empty projection must hold zero bytes, not blank lines."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    (db / "canonical_competences.jsonl").write_text(
        "\n   \n", encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()


def test_package_rejects_schema_v2_row_missing_required_field(
    tmp_path: Path,
) -> None:
    """A partially populated v2 row cannot bypass required-field validation."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    jsonl_path = db / "competence_candidates.jsonl"
    payload = json.loads(jsonl_path.read_text(encoding="utf-8"))
    del payload["candidate_definition"]
    jsonl_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()


def test_package_reports_physical_csv_line_for_schema_failure(
    tmp_path: Path, capsys: object
) -> None:
    """Schema diagnostics retain the physical CSV line after blank records."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    candidate_path = db / "competence_candidates.csv"
    rows = list(csv.DictReader(candidate_path.open(encoding="utf-8")))
    assert rows
    rows[0]["candidate_definition"] = ""
    _write_csv_rows(
        candidate_path,
        CSV_REQUIRED_COLUMNS[candidate_path.name],
        [dict(rows[0])],
    )
    header, separator, payload = candidate_path.read_text(
        encoding="utf-8"
    ).partition("\n")
    assert separator
    candidate_path.write_text(
        f"{header}\n\n{payload}", encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_empty_required_field:"
        "competence_candidates.csv:L3:candidate_definition"
    ) in captured.err


def test_package_rejects_surplus_csv_values_with_physical_line(
    tmp_path: Path, capsys: object
) -> None:
    """CSV values without a header are rejected instead of being discarded."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    candidate_path = db / "competence_candidates.csv"
    candidate_path.write_text(
        candidate_path.read_text(encoding="utf-8").rstrip("\n")
        + ",surplus-value\n",
        encoding="utf-8",
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "csv_surplus_values:competence_candidates.csv:L2" in captured.err


def test_package_rejects_duplicate_csv_headers_on_header_line(
    tmp_path: Path, capsys: object
) -> None:
    """Duplicate header names cannot be silently overwritten by DictReader."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    candidate_path = db / "competence_candidates.csv"
    header, separator, payload = candidate_path.read_text(
        encoding="utf-8"
    ).partition("\n")
    assert separator
    headers = next(csv.reader([header]))
    headers[1] = headers[0]
    candidate_path.write_text(
        ",".join(headers) + "\n" + payload, encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "csv_duplicate_headers:competence_candidates.csv:L1:candidate_id"
    ) in captured.err


def test_package_applies_full_draft_schema_to_jsonl_rows(
    tmp_path: Path, capsys: object
) -> None:
    """A JSONL scalar type error cannot pass the required-column checks."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    jsonl_path = db / "competence_candidates.jsonl"
    payload = json.loads(jsonl_path.read_text(encoding="utf-8"))
    payload["exact_span_start_offset"] = "not-an-integer"
    jsonl_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_schema_validation:competence_candidates.jsonl:L1:"
        "exact_span_start_offset:type"
    ) in captured.err


def test_package_rejects_blank_reason_and_non_utc_decision_time(
    tmp_path: Path, capsys: object
) -> None:
    """Published decisions retain the runtime audit-field requirements."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _write_schema_v2_decision_chain(db)
    _update_schema_v2_first_row(
        db,
        "validation_decisions",
        {
            "decision_reason": "",
            "decision_at_utc": "2026-07-10T01:00:00+01:00",
        },
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_empty_required_field:"
        "validation_decisions.csv:L2:decision_reason"
    ) in captured.err
    assert (
        "schema_v2_invalid_decision_at_utc:"
        "validation_decisions.csv:L2:decision_at_utc"
    ) in captured.err


def test_package_rejects_broken_schema_v2_foreign_keys(
    tmp_path: Path,
) -> None:
    """Both package projections must retain the fragment-to-signal link."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    csv_path = db / "semantic_signals.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows
    rows[0]["fragment_id"] = "fragment:missing"
    _write_csv_rows(
        csv_path,
        CSV_REQUIRED_COLUMNS[csv_path.name],
        [dict(row) for row in rows],
    )
    jsonl_path = db / "semantic_signals.jsonl"
    payload = json.loads(jsonl_path.read_text(encoding="utf-8"))
    payload["fragment_id"] = "fragment:missing"
    jsonl_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()


def test_package_rejects_schema_v2_projection_key_mismatch(
    tmp_path: Path, capsys: object
) -> None:
    """Every schema-v2 primary key is retained in both package projections."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    candidate_path = db / "competence_candidates.csv"
    rows = list(csv.DictReader(candidate_path.open(encoding="utf-8")))
    assert rows
    second_candidate = dict(rows[0])
    second_candidate["candidate_id"] = "candidate:csv-only"
    _write_csv_rows(
        candidate_path,
        CSV_REQUIRED_COLUMNS[candidate_path.name],
        [dict(rows[0]), second_candidate],
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_cross_projection_missing_jsonl_key:"
        "competence_candidates:csv:L3"
    ) in captured.err


def test_package_rejects_projection_evidence_ids_mismatch(
    tmp_path: Path, capsys: object
) -> None:
    """Decision evidence IDs cannot differ between CSV and JSONL projections."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _write_schema_v2_decision_chain(db)
    decision_path = db / "validation_decisions.jsonl"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["evidence_ids"] = "E-0001|"
    decision_path.write_text(
        json.dumps(decision, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_cross_projection_value_mismatch:"
        "validation_decisions:evidence_ids:csv:L2:jsonl:L1"
    ) in captured.err


def test_package_rejects_canonical_rows_without_validation_decisions(
    tmp_path: Path,
) -> None:
    """Canonical promotion cannot bypass a retained validation decision."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    canonical = _schema_v2_rows()["canonical_competences"]
    _write_csv_rows(
        db / "canonical_competences.csv",
        CSV_REQUIRED_COLUMNS["canonical_competences.csv"],
        [canonical],
    )
    (db / "canonical_competences.jsonl").write_text(
        json.dumps(canonical) + "\n", encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()


def test_package_requires_canonical_label_to_match_decision(
    tmp_path: Path, capsys: object
) -> None:
    """An accepted decision's label binds the promoted canonical row."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _write_schema_v2_decision_chain(db)
    canonical_path = db / "canonical_competences.csv"
    canonical_rows = list(csv.DictReader(canonical_path.open(encoding="utf-8")))
    assert canonical_rows
    canonical_rows[0]["preferred_label"] = "A different competence"
    _write_csv_rows(
        canonical_path,
        CSV_REQUIRED_COLUMNS[canonical_path.name],
        [dict(canonical_rows[0])],
    )
    canonical_jsonl_path = db / "canonical_competences.jsonl"
    canonical = json.loads(canonical_jsonl_path.read_text(encoding="utf-8"))
    canonical["preferred_label"] = "A different competence"
    canonical_jsonl_path.write_text(
        json.dumps(canonical, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_lineage_mismatch:"
        "canonical_competences.csv:L2:canonical_label"
    ) in captured.err


def test_package_requires_semantic_phrase_to_remain_in_fragment(
    tmp_path: Path, capsys: object
) -> None:
    """A semantic signal remains bound to the retained fragment content."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    semantic_path = db / "semantic_signals.csv"
    semantic_rows = list(csv.DictReader(semantic_path.open(encoding="utf-8")))
    assert semantic_rows
    semantic_rows[0]["matched_phrase"] = "unlinked phrase"
    _write_csv_rows(
        semantic_path,
        CSV_REQUIRED_COLUMNS[semantic_path.name],
        [dict(semantic_rows[0])],
    )
    semantic_jsonl_path = db / "semantic_signals.jsonl"
    semantic = json.loads(semantic_jsonl_path.read_text(encoding="utf-8"))
    semantic["matched_phrase"] = "unlinked phrase"
    semantic_jsonl_path.write_text(
        json.dumps(semantic, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_lineage_mismatch:"
        "semantic_signals.csv:L2:matched_phrase"
    ) in captured.err


def test_package_requires_fragment_context_offsets_and_surface_hash(
    tmp_path: Path, capsys: object
) -> None:
    """Fragment coordinates and surface hash remain bound to semantic context."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _update_schema_v2_first_row(
        db,
        "evidence_fragments",
        {"span_end_offset": 13},
    )
    _update_schema_v2_first_row(
        db,
        "competence_candidates",
        {"exact_span_end_offset": 13},
    )
    _update_schema_v2_first_row(
        db,
        "semantic_signals",
        {"context_text": "marine craft"},
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_lineage_mismatch:"
        "semantic_signals.csv:L2:fragment_context_offsets"
    ) in captured.err
    assert (
        "schema_v2_lineage_mismatch:"
        "semantic_signals.csv:L2:surface_text_hash"
    ) in captured.err


def test_package_recomputes_fragment_provenance_preimage_and_hash(
    tmp_path: Path, capsys: object
) -> None:
    """Direct provenance fields cannot diverge from published identifiers."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _update_schema_v2_first_row(
        db,
        "evidence_fragments",
        {
            "source_provider_id": "tampered-source-id",
            "provenance_hash": "0" * 64,
        },
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_lineage_mismatch:"
        "evidence_fragments.csv:L2:source_provenance_id"
    ) in captured.err
    assert (
        "schema_v2_lineage_mismatch:"
        "evidence_fragments.csv:L2:provenance_hash"
    ) in captured.err


def test_package_requires_assignment_semantic_context_and_label_guard(
    tmp_path: Path, capsys: object
) -> None:
    """Assignments and canonical labels remain grounded in semantic evidence."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _write_schema_v2_decision_chain(db)
    _update_schema_v2_first_row(
        db,
        "sector_competence_assignments",
        {"sector": "not-in-signal"},
    )
    _update_schema_v2_first_row(
        db,
        "validation_decisions",
        {"canonical_label": "Crossref: marine skill"},
    )
    _update_schema_v2_first_row(
        db,
        "canonical_competences",
        {"preferred_label": "Crossref: marine skill"},
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_lineage_mismatch:"
        "sector_competence_assignments.csv:L2:semantic_context"
    ) in captured.err
    assert (
        "schema_v2_lineage_mismatch:"
        "canonical_competences.csv:L2:canonical_label_guard:"
        "provider_metadata_prefix"
    ) in captured.err


def test_package_requires_all_candidate_fragments_and_bound_assignments(
    tmp_path: Path, capsys: object
) -> None:
    """Candidate aggregates and active decisions retain every bound context."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    rows = _schema_v2_rows()
    second_fragment = dict(rows["evidence_fragments"])
    second_fragment["fragment_id"] = "fragment:second"
    second_provenance_id = _refresh_fragment_integrity(
        second_fragment, source_provider_id="source:second"
    )
    second_signal = dict(rows["semantic_signals"])
    second_signal.update(
        {
            "fragment_id": "fragment:second",
            "source_provenance_id": second_provenance_id,
            "sector": "shipping",
            "axis_group": "MARITIME",
            "axis_code": "T",
        }
    )
    _append_schema_v2_row(db, "evidence_fragments", second_fragment)
    _append_schema_v2_row(db, "semantic_signals", second_signal)
    _rewrite_checksums(db)

    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_lineage_mismatch:"
        "competence_candidates.csv:L2:fragment_ids"
    ) in captured.err

    references = "fragment:test|fragment:second"
    provenance_ids = "|".join(
        sorted(
            {
                str(rows["evidence_fragments"]["source_provenance_id"]),
                second_provenance_id,
            }
        )
    )
    _update_schema_v2_first_row(
        db,
        "competence_candidates",
        {
            "fragment_ids": references,
            "source_provenance_ids": provenance_ids,
        },
    )
    _write_schema_v2_decision_chain(db)
    _update_schema_v2_first_row(
        db,
        "validation_decisions",
        {
            "fragment_ids": references,
            "source_provenance_ids": provenance_ids,
        },
    )
    _rewrite_checksums(db)
    assert _build_fixture_package(db, reports, out) == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_lineage_mismatch:"
        "validation_decisions.csv:L2:sector_competence_assignments"
    ) in captured.err


def test_package_rejects_promotions_from_superseded_decisions(
    tmp_path: Path, capsys: object
) -> None:
    """Canonical rows and assignments cannot retain inactive decisions."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _write_schema_v2_decision_chain(db)
    superseding = dict(_schema_v2_rows()["validation_decisions"])
    superseding.update(
        {
            "validation_decision_id": "decision:replacement",
            "decision_status": "review_required",
            "superseded_validation_decision_id": "decision:test",
            "decision_reason": "Replaces the earlier decision.",
        }
    )
    _append_schema_v2_row(db, "validation_decisions", superseding)
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_lineage_mismatch:"
        "canonical_competences.csv:L2:inactive_validation_decision_id"
    ) in captured.err
    assert (
        "schema_v2_lineage_mismatch:"
        "sector_competence_assignments.csv:L2:inactive_validation_decision_id"
    ) in captured.err


def test_package_rejects_invalid_supersession_links(
    tmp_path: Path, capsys: object
) -> None:
    """Supersession cannot self-reference or cross candidate lineage."""
    scenarios = (
        (
            "self",
            "superseded_validation_decision_self_reference",
        ),
        (
            "cross-candidate",
            "superseded_validation_decision_target_candidate",
        ),
    )
    for scenario, expected_issue in scenarios:
        db = tmp_path / f"db-{scenario}"
        reports = tmp_path / f"reports-{scenario}"
        _write_min_bundle(db, reports)
        _write_schema_v2_decision_chain(db)
        if scenario == "self":
            _update_schema_v2_first_row(
                db,
                "validation_decisions",
                {"superseded_validation_decision_id": "decision:test"},
            )
        else:
            cross_candidate = dict(_schema_v2_rows()["validation_decisions"])
            cross_candidate.update(
                {
                    "validation_decision_id": "decision:cross-candidate",
                    "target_candidate_id": "candidate:other",
                    "decision_status": "review_required",
                    "superseded_validation_decision_id": "decision:test",
                    "decision_reason": "Invalid cross-candidate fixture.",
                }
            )
            _append_schema_v2_row(db, "validation_decisions", cross_candidate)
        _rewrite_checksums(db)
        out = tmp_path / f"pkg-{scenario}.zip"
        assert _build_fixture_package(db, reports, out) == 1
        assert not out.exists()
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert (
            "schema_v2_lineage_mismatch:validation_decisions.csv:"
            f"L{2 if scenario == 'self' else 3}:{expected_issue}"
        ) in captured.err


@pytest.mark.parametrize("suffix", ("csv", "jsonl"))
@pytest.mark.parametrize("evidence_ids", ("E-OTHER", "E-0001|E-OTHER", "|"))
def test_package_rejects_assignment_evidence_unlinked_from_candidate(
    tmp_path: Path,
    suffix: str,
    evidence_ids: str,
) -> None:
    """Assignments retain their source candidate's nonempty evidence lineage."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    rows = _schema_v2_rows()
    for entity_name in (
        "validation_decisions",
        "canonical_competences",
        "sector_competence_assignments",
    ):
        row = rows[entity_name]
        _write_csv_rows(
            db / f"{entity_name}.csv",
            CSV_REQUIRED_COLUMNS[f"{entity_name}.csv"],
            [row],
        )
        (db / f"{entity_name}.jsonl").write_text(
            json.dumps(row) + "\n", encoding="utf-8"
        )

    evidence_csv_path = db / "evidence_records.csv"
    evidence_rows = list(
        csv.DictReader(evidence_csv_path.open(encoding="utf-8"))
    )
    assert evidence_rows
    other_evidence = dict(evidence_rows[0])
    other_evidence["evidence_id"] = "E-OTHER"
    _write_csv_rows(
        evidence_csv_path,
        CSV_REQUIRED_COLUMNS[evidence_csv_path.name],
        [dict(evidence_rows[0]), other_evidence],
    )
    with (db / "evidence_records.jsonl").open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write(json.dumps({"evidence_id": "E-OTHER"}) + "\n")

    assignment_path = db / f"sector_competence_assignments.{suffix}"
    if suffix == "csv":
        assignments = list(
            csv.DictReader(assignment_path.open(encoding="utf-8"))
        )
        assignments[0]["evidence_ids"] = evidence_ids
        _write_csv_rows(
            assignment_path,
            CSV_REQUIRED_COLUMNS[assignment_path.name],
            [dict(assignments[0])],
        )
    else:
        assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
        assignment["evidence_ids"] = evidence_ids
        assignment_path.write_text(
            json.dumps(assignment) + "\n", encoding="utf-8"
        )

    _rewrite_checksums(db)
    out = tmp_path / f"pkg-{suffix}-{evidence_ids.replace('|', 'pipe')}.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()


def test_package_requires_decision_to_retain_full_candidate_reference_sets(
    tmp_path: Path, capsys: object
) -> None:
    """Decisions retain every fragment and source provenance of their candidate."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    rows = _schema_v2_rows()
    second_fragment = dict(rows["evidence_fragments"])
    second_fragment.update(
        {
            "fragment_id": "fragment:second",
        }
    )
    second_provenance_id = _refresh_fragment_integrity(
        second_fragment, source_provider_id="source:second"
    )
    second_signal = dict(rows["semantic_signals"])
    second_signal.update(
        {
            "fragment_id": "fragment:second",
            "source_provenance_id": second_provenance_id,
        }
    )
    _append_schema_v2_row(db, "evidence_fragments", second_fragment)
    _append_schema_v2_row(db, "semantic_signals", second_signal)

    candidate_path = db / "competence_candidates.csv"
    candidate_rows = list(csv.DictReader(candidate_path.open(encoding="utf-8")))
    assert candidate_rows
    candidate_rows[0]["fragment_ids"] = "fragment:test|fragment:second"
    candidate_rows[0]["source_provenance_ids"] = "|".join(
        sorted(
            {
                str(rows["evidence_fragments"]["source_provenance_id"]),
                second_provenance_id,
            }
        )
    )
    _write_csv_rows(
        candidate_path,
        CSV_REQUIRED_COLUMNS[candidate_path.name],
        [dict(candidate_rows[0])],
    )
    candidate_jsonl_path = db / "competence_candidates.jsonl"
    candidate = json.loads(candidate_jsonl_path.read_text(encoding="utf-8"))
    candidate["fragment_ids"] = "fragment:test|fragment:second"
    candidate["source_provenance_ids"] = candidate_rows[0][
        "source_provenance_ids"
    ]
    candidate_jsonl_path.write_text(
        json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_schema_v2_decision_chain(db)
    _rewrite_checksums(db)

    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert (
        "schema_v2_lineage_mismatch:"
        "validation_decisions.csv:L2:fragment_ids"
    ) in captured.err
    assert (
        "schema_v2_lineage_mismatch:"
        "validation_decisions.csv:L2:source_provenance_ids"
    ) in captured.err

    for suffix in ("csv", "jsonl"):
        decision_path = db / f"validation_decisions.{suffix}"
        if suffix == "csv":
            decision_rows = list(csv.DictReader(decision_path.open(encoding="utf-8")))
            decision_rows[0]["fragment_ids"] = "fragment:test|fragment:second"
            decision_rows[0]["source_provenance_ids"] = candidate_rows[0][
                "source_provenance_ids"
            ]
            _write_csv_rows(
                decision_path,
                CSV_REQUIRED_COLUMNS[decision_path.name],
                [dict(decision_rows[0])],
            )
        else:
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            decision["fragment_ids"] = "fragment:test|fragment:second"
            decision["source_provenance_ids"] = candidate_rows[0][
                "source_provenance_ids"
            ]
            decision_path.write_text(
                json.dumps(decision, sort_keys=True) + "\n", encoding="utf-8"
            )
    _rewrite_checksums(db)
    assert _build_fixture_package(db, reports, out) == 0
    assert out.exists()


def test_package_rejects_legacy_metadata_projection_mismatch(
    tmp_path: Path,
) -> None:
    """The CSV and JSONL compatibility views share ID-keyed metadata."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    jsonl_path = db / "derived_competence_demands.jsonl"
    payload = json.loads(jsonl_path.read_text(encoding="utf-8"))
    payload["evidence_ids"] = "E-OTHER"
    jsonl_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()


def test_package_allows_shared_signal_id_for_distinct_fragments(
    tmp_path: Path,
) -> None:
    """One candidate aggregates all fragment pairs for its shared signal ID."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    rows = _schema_v2_rows()
    second_fragment = dict(rows["evidence_fragments"])
    second_fragment.update({
        "fragment_id": "fragment:second",
    })
    second_provenance_id = _refresh_fragment_integrity(
        second_fragment, source_provider_id="source:second"
    )
    second_signal = dict(rows["semantic_signals"])
    second_signal.update({
        "fragment_id": "fragment:second",
        "source_provenance_id": second_provenance_id,
    })
    for entity_name, row in (
        ("evidence_fragments", second_fragment),
        ("semantic_signals", second_signal),
    ):
        _append_schema_v2_row(db, entity_name, row)
    candidate_path = db / "competence_candidates.csv"
    candidate_rows = list(csv.DictReader(candidate_path.open(encoding="utf-8")))
    assert candidate_rows
    candidate_rows[0]["fragment_ids"] = "fragment:test|fragment:second"
    candidate_rows[0]["source_provenance_ids"] = "|".join(
        sorted(
            {
                str(rows["evidence_fragments"]["source_provenance_id"]),
                second_provenance_id,
            }
        )
    )
    _write_csv_rows(
        candidate_path,
        CSV_REQUIRED_COLUMNS[candidate_path.name],
        [dict(candidate_rows[0])],
    )
    candidate_jsonl_path = db / "competence_candidates.jsonl"
    candidate = json.loads(candidate_jsonl_path.read_text(encoding="utf-8"))
    candidate["fragment_ids"] = candidate_rows[0]["fragment_ids"]
    candidate["source_provenance_ids"] = candidate_rows[0][
        "source_provenance_ids"
    ]
    candidate_jsonl_path.write_text(
        json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 0
    assert out.exists()


def test_package_rejects_unknown_superseded_validation_decision(
    tmp_path: Path,
) -> None:
    """A populated superseded-decision reference is a validation-decision FK."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    decision = _schema_v2_rows()["validation_decisions"]
    decision["superseded_validation_decision_id"] = "decision:missing"
    _write_csv_rows(
        db / "validation_decisions.csv",
        CSV_REQUIRED_COLUMNS["validation_decisions.csv"],
        [decision],
    )
    (db / "validation_decisions.jsonl").write_text(
        json.dumps(decision) + "\n", encoding="utf-8"
    )
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()


def test_package_rejects_demand_without_supporting_evidence_ids(tmp_path: Path) -> None:
    """Derived demands without supporting evidence IDs must fail preflight."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    rows = list(csv.DictReader((db / "derived_competence_demands.csv").open(encoding="utf-8")))
    assert rows
    rows[0]["evidence_ids"] = ""
    with (db / "derived_competence_demands.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    rc = build_main([
        "--database-dir", str(db),
        "--reports-dir", str(reports),
        "--output", str(out),
        "--version-tag", "test",
        "--generated-at-utc", "2026-07-10T00:00:00+00:00",
        *_required_source_args(db),
    ])
    assert rc == 1
    assert not out.exists()


def test_package_rejects_jsonl_demand_without_supporting_evidence_ids(
    tmp_path: Path,
) -> None:
    """The JSONL compatibility view must retain supporting evidence IDs."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    path = db / "derived_competence_demands.jsonl"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evidence_ids"] = ""
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    _rewrite_checksums(db)
    out = tmp_path / "pkg.zip"
    assert _build_fixture_package(db, reports, out) == 1
    assert not out.exists()


def test_package_allows_non_hypothesis_demand_evidence_not_in_fragments(
    tmp_path: Path,
) -> None:
    """Non-hypothesis demand rows should not require fragment-backed evidence."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    rows = list(
        csv.DictReader((db / "derived_competence_demands.csv").open(encoding="utf-8"))
    )
    assert rows
    rows[0]["evidence_ids"] = "E-NONH"
    rows[0]["hypothesis_ids"] = ""
    fieldnames = list(rows[0].keys())
    if "hypothesis_ids" not in fieldnames:
        fieldnames.append("hypothesis_ids")
    with (db / "derived_competence_demands.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    demand_jsonl_path = db / "derived_competence_demands.jsonl"
    demand_jsonl = json.loads(demand_jsonl_path.read_text(encoding="utf-8"))
    demand_jsonl["evidence_ids"] = "E-NONH"
    demand_jsonl_path.write_text(
        json.dumps(demand_jsonl) + "\n", encoding="utf-8"
    )
    learning_rows = list(csv.DictReader((db / "learning_outcomes.csv").open(encoding="utf-8")))
    assert learning_rows
    learning_rows[0]["evidence_id"] = "E-NONH"
    with (db / "learning_outcomes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(learning_rows[0].keys()))
        writer.writeheader()
        writer.writerows(learning_rows)
    _rewrite_checksums(db)
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
    assert out.exists()


def test_package_rejects_wrong_path_contract(tmp_path: Path) -> None:
    """A raw-acquisition-index path that doesn't match the contract fails."""
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    _write_min_bundle(db, reports)
    _stamp_current_run_id(db, "RUN-NEW")
    # Create a path that has run ID as a substring but wrong structure.
    bad_path = tmp_path / "live_runs" / "RUN-NEW-old" / "raw"
    bad_path.mkdir(parents=True)
    idx = bad_path / "raw_acquisition_index.csv"
    idx.write_text("query_id,provider\nQ1,Crossref\n", encoding="utf-8")
    out = tmp_path / "pkg.zip"
    rc = build_main([
        "--database-dir", str(db),
        "--reports-dir", str(reports),
        "--output", str(out),
        "--version-tag", "test",
        "--generated-at-utc", "2026-07-10T00:00:00+00:00",
        "--current-run-id", "RUN-NEW",
        "--stats-dir", str(tmp_path / "stats"),
        "--protocol-path", str(tmp_path / "protocol.yml"),
        "--projection-path", str(tmp_path / "projection.yml"),
        "--constraints-path", str(tmp_path / "constraints.json"),
        "--query-execution-log", str(tmp_path / "query_execution_log.csv"),
        "--raw-acquisition-index", str(idx),
    ])
    assert rc == 1
    assert not out.exists()


def _rewrite_checksums(db: Path) -> None:
    """Recompute _checksums.sha256 from current file contents."""
    checksum_lines: list[str] = []
    for name in sorted(
        list(CSV_FILES) + list(JSONL_FILES)
        + [n for n in DATABASE_METADATA_FILES if not n.endswith(".sha256")]
    ):
        fp = db / name
        if fp.is_file():
            digest = hashlib.sha256(fp.read_bytes()).hexdigest()
            checksum_lines.append(f"{digest}  {name}")
    (db / "_checksums.sha256").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )


def test_report_rejects_missing_declared_hypothesis_required_fields(tmp_path: Path) -> None:
    db = tmp_path / "db"
    reports = tmp_path / "reports"
    db.mkdir()
    (db / "layer5_manifest.json").write_text(
        json.dumps(
            {
                "hypothesis_results": {
                    "H1": {"hypothesis_id": "H1", "hypothesis_label": "Maritimisation Shift"},
                    "H2": _h2_payload(),
                    "H3": _h3_payload(),
                }
            }
        ),
        encoding="utf-8",
    )
    try:
        _REPORT.build_html_report(
            database_dir=db,
            reports_dir=reports,
            generated_at="2026-07-14T00:00:00+00:00",
        )
    except ValueError as exc:
        assert "Declared hypothesis result fields missing" in str(exc)
    else:
        raise AssertionError("Expected report build to fail on missing required hypothesis fields")
