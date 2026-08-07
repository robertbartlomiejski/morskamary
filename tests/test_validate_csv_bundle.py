"""Regression coverage for the standalone schema-v2 bundle preflight."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = REPO_ROOT / "scripts" / "validate_csv_bundle.py"
_PACKAGE_PATH = REPO_ROOT / "scripts" / "build_live_cumulative_release_package.py"


def _load_package_module() -> Any:
    """Load the production validator for its deterministic fixture preimages."""
    spec = importlib.util.spec_from_file_location(
        "build_live_cumulative_release_package_fixture", _PACKAGE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PACKAGE = _load_package_module()


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
    """Build one fully linked schema-v2 decision chain from live preimages."""
    fragment: dict[str, object] = {
        "fragment_id": "",
        "evidence_id": "E-0001",
        "run_id": "RUN-1",
        "source_provenance_id": "",
        "source_provider": "Crossref",
        "source_provider_id": "source:fixture",
        "source_retrieved_at_utc": "2026-07-10T00:00:00+00:00",
        "source_query_id": "Q1",
        "source_query_text": "fixture query",
        "source_field": "title",
        "language": "en",
        "fragment_text": "marine skill",
        "span_start_offset": 0,
        "span_end_offset": 12,
        "surface_text_hash": "",
        "provenance_hash": "",
    }
    provenance_id = _PACKAGE._expected_fragment_provenance_id(fragment)
    fragment["source_provenance_id"] = provenance_id
    fragment["surface_text_hash"] = _PACKAGE._normalized_text_hash(
        fragment["fragment_text"]
    )
    fragment["provenance_hash"] = hashlib.sha256(
        provenance_id.encode("utf-8")
    ).hexdigest()

    signal: dict[str, object] = {
        "signal_id": "",
        "fragment_id": "",
        "evidence_id": "E-0001",
        "run_id": "RUN-1",
        "source_provenance_id": provenance_id,
        "sector": "ports",
        "axis_group": "MARINE",
        "axis_code": "M",
        "query_id": "Q1",
        "query_family": "core_sector",
        "signal_type": "governance_skill",
        "signal_category_label": "Marine skill",
        "signal_category_description": "Fixture semantic signal.",
        "matched_phrase": "marine",
        "confidence_score": 0.8,
        "classifier_version": "fixture-v1",
        "negation_status": "not_detected",
        "speculation_status": "not_detected",
        "actor_text": "",
        "action_text": "",
        "object_text": "",
        "context_text": "marine skill",
        "evidence_text_hash": hashlib.sha256(
            b"fixture evidence scope"
        ).hexdigest(),
        "manual_review_status": "auto_accepted",
        "validity_warning": "",
    }
    signal["signal_id"] = _PACKAGE._expected_signal_id(signal)
    fragment_id = _PACKAGE._expected_fragment_id(fragment, signal)
    fragment["fragment_id"] = fragment_id
    signal["fragment_id"] = fragment_id

    candidate: dict[str, object] = {
        "candidate_id": "",
        "signal_id": signal["signal_id"],
        "fragment_id": fragment_id,
        "evidence_id": "E-0001",
        "run_id": "RUN-1",
        "sector": "ports",
        "axis_group": "MARINE",
        "axis_code": "M",
        "source_provenance_ids": provenance_id,
        "fragment_ids": fragment_id,
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
    }
    candidate["candidate_id"] = _PACKAGE._expected_candidate_id(candidate)

    decision: dict[str, object] = {
        "validation_decision_id": "decision:fixture",
        "target_candidate_id": candidate["candidate_id"],
        "canonical_label": "Marine skill",
        "decision_status": "accepted",
        "reviewer": "reviewer-fixture",
        "decision_at_utc": "2026-07-10T00:00:00+00:00",
        "decision_reason": "Fixture acceptance.",
        "evidence_ids": "E-0001",
        "fragment_ids": fragment_id,
        "source_provenance_ids": provenance_id,
        "superseded_validation_decision_id": "",
    }
    canonical: dict[str, object] = {
        "canonical_competence_id": "",
        "validation_decision_id": decision["validation_decision_id"],
        "source_candidate_id": candidate["candidate_id"],
        "preferred_label": "Marine skill",
        "canonical_definition": "Fixture candidate definition.",
        "aliases": "",
        "validation_status": "accepted",
        "schema_version": "2.0.0",
        "provenance_guard_status": "passed",
    }
    canonical["canonical_competence_id"] = (
        _PACKAGE._expected_canonical_competence_id(canonical)
    )
    assignment: dict[str, object] = {
        "assignment_id": "assignment:fixture",
        "canonical_competence_id": canonical["canonical_competence_id"],
        "validation_decision_id": decision["validation_decision_id"],
        "source_candidate_id": candidate["candidate_id"],
        "sector": "ports",
        "axis_group": "MARINE",
        "axis_code": "M",
        "evidence_ids": "E-0001",
    }
    return {
        "evidence_fragments": fragment,
        "semantic_signals": signal,
        "competence_candidates": candidate,
        "canonical_competences": canonical,
        "sector_competence_assignments": assignment,
        "validation_decisions": decision,
    }


def _fields_for(entity_name: str) -> tuple[str, ...]:
    if entity_name == "evidence_records":
        return cast(
            tuple[str, ...],
            _PACKAGE.CSV_REQUIRED_COLUMNS["evidence_records.csv"],
        )
    return cast(
        tuple[str, ...], _PACKAGE.SCHEMA_V2_REQUIRED_COLUMNS[entity_name]
    )


def _write_projection(
    bundle_dir: Path,
    entity_name: str,
    rows: list[dict[str, object]],
) -> None:
    fields = _fields_for(entity_name)
    _write_csv_rows(bundle_dir / f"{entity_name}.csv", fields, rows)
    (bundle_dir / f"{entity_name}.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_valid_bundle(bundle_dir: Path) -> None:
    bundle_dir.mkdir()
    evidence_record: dict[str, object] = {
        field_name: "fixture" for field_name in _fields_for("evidence_records")
    }
    evidence_record.update(
        {
            "evidence_id": "E-0001",
            "canonical_doi": "10.1000/fixture",
            "canonical_title": "Fixture source title",
            "first_seen_run_id": "RUN-1",
            "latest_seen_run_id": "RUN-1",
            "providers_seen": "crossref",
            "record_novelty_status": "new_record",
        }
    )
    _write_projection(bundle_dir, "evidence_records", [evidence_record])
    rows = _schema_v2_rows()
    for entity_name in _PACKAGE.SCHEMA_V2_ENTITY_NAMES:
        _write_projection(bundle_dir, entity_name, [rows[entity_name]])
    (bundle_dir / "cumulative_database_manifest.json").write_text(
        json.dumps(
            {
                "counts": {
                    entity_name: 1
                    for entity_name in _PACKAGE.SCHEMA_V2_ENTITY_NAMES
                }
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _read_projection_rows(
    bundle_dir: Path, entity_name: str
) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (bundle_dir / f"{entity_name}.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]


def _replace_projection_rows(
    bundle_dir: Path,
    entity_name: str,
    rows: list[dict[str, object]],
) -> None:
    _write_projection(bundle_dir, entity_name, rows)


def _update_projection(
    bundle_dir: Path, entity_name: str, updates: dict[str, object]
) -> None:
    rows = _read_projection_rows(bundle_dir, entity_name)
    assert rows
    rows[0].update(updates)
    _replace_projection_rows(bundle_dir, entity_name, rows)


def _run_validator(bundle_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR_PATH), "--bundle-dir", str(bundle_dir)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_accepts_a_fully_linked_clean_bundle(tmp_path: Path) -> None:
    """The offline gate accepts a current-contract CSV/JSONL projection."""
    bundle_dir = tmp_path / "clean"
    _write_valid_bundle(bundle_dir)

    completed = _run_validator(bundle_dir)

    assert completed.returncode == 0, completed.stderr
    assert "[OK] Schema-v2 bundle preflight passed." in completed.stdout


def test_cli_rejects_forged_canonical_competence_identity(tmp_path: Path) -> None:
    """Both projections must retain the canonical ID derived from its label."""
    bundle_dir = tmp_path / "forged-canonical-id"
    _write_valid_bundle(bundle_dir)
    forged_id = "canonical:" + "f" * 64
    _update_projection(
        bundle_dir,
        "canonical_competences",
        {"canonical_competence_id": forged_id},
    )
    # Keep the assignment foreign key internally consistent.  The failure
    # must come from canonical identity recomputation, not a broken reference.
    _update_projection(
        bundle_dir,
        "sector_competence_assignments",
        {"canonical_competence_id": forged_id},
    )

    completed = _run_validator(bundle_dir)
    output = completed.stdout + completed.stderr

    assert completed.returncode == 1
    assert (
        "schema_v2_lineage_mismatch:"
        "canonical_competences.csv:L2:canonical_competence_id"
    ) in output
    assert (
        "schema_v2_lineage_mismatch:"
        "canonical_competences.jsonl:L1:canonical_competence_id"
    ) in output


def test_cli_rejects_superseding_decision_that_is_not_later(
    tmp_path: Path,
) -> None:
    """Both projections reject equal-time validation-decision replacements."""
    bundle_dir = tmp_path / "equal-time-supersession"
    _write_valid_bundle(bundle_dir)
    decisions = _read_projection_rows(bundle_dir, "validation_decisions")
    replacement = dict(decisions[0])
    replacement.update(
        {
            "validation_decision_id": "decision:replacement",
            "canonical_label": "",
            "decision_status": "review_required",
            "decision_reason": "Equal-time replacement is invalid.",
            "superseded_validation_decision_id": "decision:fixture",
        }
    )
    _replace_projection_rows(
        bundle_dir, "validation_decisions", [*decisions, replacement]
    )
    manifest_path = bundle_dir / "cumulative_database_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["validation_decisions"] = 2
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
    )

    completed = _run_validator(bundle_dir)
    output = completed.stdout + completed.stderr

    assert completed.returncode == 1
    assert (
        "schema_v2_lineage_mismatch:validation_decisions.csv:L3:"
        "superseding_validation_decision_not_later"
    ) in output
    assert (
        "schema_v2_lineage_mismatch:validation_decisions.jsonl:L2:"
        "superseding_validation_decision_not_later"
    ) in output


def test_cli_rejects_every_appendix_corruption_class(tmp_path: Path) -> None:
    """One corrupt fixture proves the preflight is a fail-closed gate."""
    bundle_dir = tmp_path / "invalid"
    _write_valid_bundle(bundle_dir)
    _update_projection(
        bundle_dir,
        "evidence_fragments",
        {
            "evidence_id": "E-999",
            "source_field": "invalid_field",
            "span_start_offset": -5,
        },
    )
    _update_projection(
        bundle_dir,
        "semantic_signals",
        {
            "axis_group": "MARINE",
            "axis_code": "O",
            "confidence_score": "not_a_float",
            "manual_review_status": "invalid_status_enum",
        },
    )
    _update_projection(
        bundle_dir,
        "validation_decisions",
        {
            "canonical_label": "",
            "decision_at_utc": "2026/08/07 12:00:00",
            "reviewer": "reviewer@example.org",
        },
    )
    _update_projection(
        bundle_dir,
        "sector_competence_assignments",
        {"evidence_ids": "E-999"},
    )
    candidates = _read_projection_rows(bundle_dir, "competence_candidates")
    _replace_projection_rows(bundle_dir, "competence_candidates", candidates * 2)

    completed = _run_validator(bundle_dir)
    output = completed.stdout + completed.stderr

    assert completed.returncode == 1
    expected_errors = (
        "schema_v2_schema_validation:evidence_fragments.csv:L2:source_field:enum",
        "schema_v2_schema_validation:evidence_fragments.csv:L2:span_start_offset:minimum",
        "schema_v2_schema_validation:semantic_signals.csv:L2:confidence_score:type",
        "schema_v2_schema_validation:semantic_signals.csv:L2:manual_review_status:enum",
        "schema_v2_schema_validation:semantic_signals.csv:L2:$:anyOf",
        "schema_v2_duplicate_primary_key:competence_candidates.csv:L3:candidate_id",
        "schema_v2_schema_validation:validation_decisions.csv:L2:canonical_label:minLength",
        "schema_v2_schema_validation:validation_decisions.csv:L2:reviewer:pattern",
        "schema_v2_invalid_decision_at_utc:validation_decisions.csv:L2:decision_at_utc",
        "schema_v2_broken_foreign_key:evidence_fragments.csv:L2:evidence_id",
        "schema_v2_broken_foreign_key:sector_competence_assignments.csv:L2:evidence_ids:E-999",
    )
    for expected_error in expected_errors:
        assert expected_error in output
    assert "[ERROR] Schema-v2 bundle preflight failed" in output


def test_cli_rejects_zero_byte_csv_instead_of_weakening_headers(
    tmp_path: Path,
) -> None:
    """Allowed-empty entities still require a CSV header for schema checking."""
    bundle_dir = tmp_path / "zero-byte"
    _write_valid_bundle(bundle_dir)
    (bundle_dir / "canonical_competences.csv").write_bytes(b"")

    completed = _run_validator(bundle_dir)

    assert completed.returncode == 1
    assert "empty_csv:canonical_competences.csv" in completed.stderr


def test_cli_rejects_a_bundle_that_predates_schema_v2(tmp_path: Path) -> None:
    """A legacy-only bundle cannot be silently accepted as a v2 projection."""
    bundle_dir = tmp_path / "legacy-only"
    bundle_dir.mkdir()

    completed = _run_validator(bundle_dir)

    assert completed.returncode == 1
    assert "schema_v2_missing_required_file:evidence_fragments.csv" in completed.stderr
    assert "schema_v2_missing_required_file:validation_decisions.jsonl" in completed.stderr


def test_cli_rejects_incomplete_evidence_record_jsonl_projection(
    tmp_path: Path,
) -> None:
    """Evidence records cannot bypass required-field or parity validation."""
    bundle_dir = tmp_path / "incomplete-evidence-records"
    _write_valid_bundle(bundle_dir)
    (bundle_dir / "evidence_records.jsonl").write_text(
        '{"evidence_id":"E-0001"}\n', encoding="utf-8"
    )

    completed = _run_validator(bundle_dir)

    assert completed.returncode == 1
    assert (
        "evidence_records_missing_required_field:"
        "evidence_records.jsonl:L1:canonical_title"
    ) in completed.stderr
    assert (
        "evidence_records_cross_projection_value_mismatch:"
        "canonical_title:csv:L2:jsonl:L1"
    ) in completed.stderr


def test_cli_rejects_nonfinite_jsonl_number(tmp_path: Path) -> None:
    """The standalone path retains the production NaN/Infinity rejection."""
    bundle_dir = tmp_path / "nonfinite"
    _write_valid_bundle(bundle_dir)
    signal_path = bundle_dir / "semantic_signals.jsonl"
    signal_path.write_text(
        signal_path.read_text(encoding="utf-8").replace(
            '"confidence_score": 0.8', '"confidence_score": NaN'
        ),
        encoding="utf-8",
    )

    completed = _run_validator(bundle_dir)

    assert completed.returncode == 1
    assert "nonfinite_jsonl_number:semantic_signals.jsonl:L1:NaN" in completed.stderr
