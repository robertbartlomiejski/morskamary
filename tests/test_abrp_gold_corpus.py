from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.validate_abrp_gold_corpus import (
    validate_document,
    validate_pilot_seed,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "abrp_gold_annotation.schema.json"
PILOT_SEED = ROOT / "tests" / "fixtures" / "pilot_v7_phase_a_seed.csv"
PILOT_META = ROOT / "tests" / "fixtures" / "pilot_v7_phase_a_seed_metadata.json"
QMBD_SCHEMA = ROOT / "schemas" / "qmbd_gold_review_set.schema.json"


def _span(text: str, token: str) -> dict[str, object]:
    start = text.index(token)
    return {"text": token, "start": start, "end": start + len(token)}


def _complete_phase_b() -> dict[str, object]:
    text = "Port planners adapt infrastructure because sea-level rise changes access."
    return {
        "schema_version": "abrp_gold_annotation/1",
        "corpus_status": "coder_blind",
        "coding_phase": "B",
        "method_contract": {
            "empirical_unit": "Action-Bearing Relational Proposition (ABRP)",
            "phase_a_blindness": True,
            "no_action_span_rule": "no_exact_action_span_no_validated_human_capability",
        },
        "annotations": [{
            "annotation_id": "a-1",
            "evidence_id": "e-1",
            "fragment_id": "f-1",
            "source_surface": "abstract",
            "evidence_text": text,
            "exact_evidence_span": {"text": text, "start": 0, "end": len(text)},
            "actor_span": _span(text, "Port planners"),
            "actor": "port planners",
            "action_span": _span(text, "adapt"),
            "primary_action": "adapt",
            "action_object_span": _span(text, "infrastructure"),
            "action_object": "infrastructure",
            "transformation_span": _span(text, "sea-level rise"),
            "transformation_driver": "sea-level rise",
            "affected_relation": "port infrastructure ↔ access",
            "effect_span": None,
            "intended_effect": None,
            "qualifier": None,
            "qualifier_basis": None,
            "semantic_completeness": "complete_action_proposition",
            "capability_content_gate": "PASS",
            "ocean_relationality": "conditioning",
            "sector": "maritime_transport",
            "qmbd_axis": "MARITIME",
            "axis_hidden_phase_A": True,
            "axis_revealed_phase_B": True,
            "axis_fit": "congruent",
            "candidate_capability": "adapt port infrastructure to sea-level change",
            "canonicalization_level": "event_capability",
            "translation_candidate": "none",
            "supply_relevance": "requires_independent_supply_check",
            "coder_decision": "accept_candidate",
            "reviewer": "coder-a",
            "confidence": "high",
            "adjudication": "pending",
        }],
    }


def test_valid_complete_phase_b_package() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert validate_document(_complete_phase_b(), schema) == []


def test_no_action_span_cannot_validate_capability() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = _complete_phase_b()
    row = payload["annotations"][0]
    row["action_span"] = None
    errors = validate_document(payload, schema)
    assert any("PASS requires an exact action_span" in error for error in errors)


def test_span_text_must_match_offsets() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = _complete_phase_b()
    payload["annotations"][0]["action_span"]["start"] = 0
    errors = validate_document(payload, schema)
    assert any("span text does not equal" in error for error in errors)


def test_phase_a_fails_closed_on_axis_leakage() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = _complete_phase_b()
    payload["coding_phase"] = "A"
    row = payload["annotations"][0]
    row["axis_revealed_phase_B"] = False
    errors = validate_document(payload, schema)
    assert any("Phase A requires hidden sector=null" in error for error in errors)


def test_pilot_v7_seed_is_exactly_24_non_gold_title_cases() -> None:
    assert validate_pilot_seed(PILOT_SEED, PILOT_META) == []


def _valid_qmbd_gold_row(group: str, code: str) -> dict[str, str]:
    return {
        "gold_set_version": "v1",
        "review_case_id": "R-1",
        "evidence_scope": "title",
        "evidence_text": "Example evidence",
        "sector": "maritime_transport",
        "domain": "governance",
        "discipline": "sociology",
        "proposed_axis_group": group,
        "proposed_axis_code": code,
        "uncertainty_typology": "boundary_threshold",
        "indicator_rule": "explicit test fixture",
        "review_status": "reviewed",
        "adjudication_note": "",
    }


@pytest.mark.parametrize(
    ("group", "code"),
    [
        ("", ""),
        ("MARINE", "M"),
        ("MARITIME", "T"),
        ("OCEANIC", "O"),
        ("HYDRONIZATION", "H"),
    ],
)
def test_qmbd_gold_schema_accepts_only_canonical_axis_pairs(
    group: str, code: str
) -> None:
    schema = json.loads(QMBD_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors([_valid_qmbd_gold_row(group, code)])) == []


@pytest.mark.parametrize(
    ("group", "code"),
    [
        ("MARINE", "T"),
        ("MARITIME", "O"),
        ("OCEANIC", "H"),
        ("HYDRONIZATION", "M"),
        ("", "M"),
        ("MARINE", ""),
    ],
)
def test_qmbd_gold_schema_rejects_contradictory_axis_pairs(
    group: str, code: str
) -> None:
    schema = json.loads(QMBD_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors([_valid_qmbd_gold_row(group, code)]))
    assert errors, "contradictory group/code pair unexpectedly validated"
