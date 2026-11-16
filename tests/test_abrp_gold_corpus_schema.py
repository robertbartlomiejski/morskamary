from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from scripts.validate_abrp_gold_corpus import validate_file, validate_payload


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "abrp_gold_corpus.schema.json"
FIXTURES = ROOT / "tests" / "fixtures"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_abrp_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_schema())


def test_valid_phase_a_fixture_passes() -> None:
    assert validate_file(FIXTURES / "abrp_gold_corpus_valid_phase_a.json") == []


def test_no_exact_action_span_fails_closed() -> None:
    errors = validate_file(FIXTURES / "abrp_gold_corpus_invalid_no_action.json")
    assert errors
    assert any("action" in item.lower() for item in errors)


def test_phase_a_rejects_axis_or_candidate_leakage() -> None:
    payload = json.loads(
        (FIXTURES / "abrp_gold_corpus_valid_phase_a.json").read_text(encoding="utf-8")
    )
    row = payload["records"][0]
    row["sector"] = "maritime_transport"
    row["qmbd_axis_group"] = "MARITIME"
    row["qmbd_axis_code"] = "T"
    errors = validate_payload(payload, _schema())
    assert errors


def test_qmbd_axis_name_code_pair_is_coupled() -> None:
    payload = json.loads(
        (FIXTURES / "abrp_gold_corpus_valid_phase_a.json").read_text(encoding="utf-8")
    )
    payload["annotation_phase"] = "B_REVEALED"
    row = payload["records"][0]
    row["sector"] = "maritime_transport"
    row["qmbd_axis_group"] = "MARINE"
    row["qmbd_axis_code"] = "H"
    row["axis_hidden_phase_A"] = True
    row["axis_revealed_phase_B"] = True
    row["axis_fit"] = "mismatch"
    row["candidate_capability"] = "inspect mooring equipment"
    row["canonicalization_level"] = "candidate"
    errors = validate_payload(payload, _schema())
    assert errors


def test_pilot_v7_seed_manifest_never_claims_gold_or_fabricated_ids() -> None:
    payload = json.loads(
        (
            ROOT
            / "docs"
            / "review_templates"
            / "abrp_pilot_v7_seed_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["case_count"] == 24
    assert payload["is_gold"] is False
    assert payload["evidence_ids_status"] == "unavailable_in_current_repository"
    assert payload["evidence_ids"] == []
    assert sum(payload["baseline_counts"].values()) == 24


def test_legacy_qmbd_gold_schema_rejects_mismatched_group_code() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "qmbd_gold_review_set.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    payload = [{
        "gold_set_version": "0.1.0",
        "review_case_id": "case-x",
        "evidence_scope": "sentence",
        "evidence_text": "example",
        "sector": "maritime_transport",
        "domain": "skills",
        "discipline": "sociology",
        "proposed_axis_group": "MARINE",
        "proposed_axis_code": "H",
        "uncertainty_typology": "ambiguous_context",
        "indicator_rule": "test",
        "review_status": "reviewed",
        "adjudication_note": ""
    }]
    assert list(validator.iter_errors(payload))


def test_validated_capability_requires_all_minimum_abrp_components() -> None:
    source = json.loads(
        (FIXTURES / "abrp_gold_corpus_valid_phase_a.json").read_text(encoding="utf-8")
    )
    source["annotation_phase"] = "ADJUDICATED"
    source["corpus_status"] = "adjudicated_gold"
    row = source["records"][0]
    row["validated_human_capability"] = True
    row["semantic_completeness"] = "complete_action_proposition"
    row["capability_content_gate"] = "PASS"
    row["is_gold"] = True
    for field in (
        "actor_span", "actor", "action_object_span", "action_object",
        "transformation_span", "transformation_driver", "affected_relation",
    ):
        payload = json.loads(json.dumps(source))
        payload["records"][0][field] = ""
        assert validate_payload(payload, _schema()), field


def test_legacy_qmbd_gold_schema_accepts_omitted_axis_pair() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "qmbd_gold_review_set.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    payload = [{
        "gold_set_version": "0.1.0",
        "review_case_id": "case-no-axis",
        "evidence_scope": "sentence",
        "evidence_text": "example",
        "sector": "maritime_transport",
        "domain": "skills",
        "discipline": "sociology",
        "uncertainty_typology": "boundary_threshold",
        "indicator_rule": "test",
        "review_status": "proposed",
        "adjudication_note": ""
    }]
    assert list(validator.iter_errors(payload)) == []


def test_governance_workflow_paginates_and_checks_renames() -> None:
    text = (
        ROOT / ".github" / "workflows" / "abrp-gold-corpus-governance.yml"
    ).read_text(encoding="utf-8")
    assert "def get_all(path):" in text
    assert "per_page=100&page={page}" in text
    assert "previous_filename" in text
    assert '"COMMENTED"' not in text.split("decision_states =", 1)[1].split("\n", 1)[0]
