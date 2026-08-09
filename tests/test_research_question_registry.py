from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, cast

import pytest
import yaml
from jsonschema import Draft202012Validator

from scripts.validate_research_question_registry import main as validator_main
from src.scientific_sources.research_question_registry import (
    ALLOWED_RESULT_STATUSES,
    BASELINE_ACCOUNTABILITY_FIELDS,
    CANONICAL_AXES,
    DEFAULT_ACCOUNTABILITY_SCHEMA_PATH,
    DEFAULT_PROTOCOL_PATH,
    DEFAULT_REGISTRY_PATH,
    DEFAULT_REGISTRY_SCHEMA_PATH,
    REQUIRED_EXTENDED_QUESTION_IDS,
    REQUIRED_QUESTION_IDS,
    SCIENTIFIC_STATUS_BY_RESULT,
    ResearchQuestionRegistry,
    ResearchQuestionRegistryError,
    load_research_question_registry,
    validate_accountability_payload,
)


EXPECTED_RQ_TEXTS = (
    "What detailed competences does the Blue Economy demand across the four "
    "QMBD axes and 12 Blue Economy sectors?",
    "What unique skills does the Blue Economy demand across the four QMBD axes "
    "and 12 Blue Economy sectors?",
    "What sector gaps are communicated across the four QMBD axes and 12 Blue "
    "Economy sectors?",
    "How are the 12 Blue Economy sectors distributed across cumulative "
    "competences and QMBD axes?",
    "What is the sector cross-table for the MARINE axis?",
    "What is the sector cross-table for the MARITIME axis?",
    "What is the sector cross-table for the OCEANIC axis?",
    "What is the sector cross-table for the HYDRONIZATION axis?",
    "What is the taxonomy of competences and skills needed to accelerate the "
    "Blue Economy?",
    "What is the taxonomy of structural competence and skill gaps constraining "
    "Blue Economy demands?",
    "What micro-credential pathways across the 12 sectors are proposed to "
    "address identified competence gaps?",
    "How do competence-demand and validated-credential distributions align "
    "with or challenge H1, H2 and H3?",
)
EXPECTED_ETQ_TEXTS = (
    "How do structural competence gaps across the 12 sectors reveal a systemic "
    "deficit in sociological, ethical and governance skills?",
    "What reviewed relations connect evidence authors, publishers and source "
    "scope to baselines, validated credentials, EQF levels, target groups, "
    "sectors, axes, dictionaries, competences and gaps?",
    "How does QMBD translate Blue Economy and Blue Sustainability from "
    "political ideology toward socio-technical reality?",
    "What is the performativity of the World Ocean in competence demand, "
    "educational deficits, courses, EQF mappings, credentials and dictionaries?",
    "What is the performativity of the Blue Economy in competence demand, "
    "educational deficits, courses, EQF mappings, credentials and dictionaries?",
    "How are Blue Economy demands mediated across credentials, competences, "
    "gaps, courses and EQF through marinization, maritimization, oceanization "
    "and hydronization across sectors, domains and realms?",
    "How do FAIR and CARE principles in maritime data governance protect local "
    "and Indigenous knowledge during Marine Spatial Planning?",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, Any], payload)


def _write_mutated_registry(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> Path:
    payload = copy.deepcopy(_load_yaml(DEFAULT_REGISTRY_PATH))
    mutate(payload)
    path = tmp_path / "research_question_registry.yml"
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return path


def _expect_registry_failure(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    path = _write_mutated_registry(tmp_path, mutate)
    with pytest.raises(ResearchQuestionRegistryError, match=message):
        load_research_question_registry(path)


def _future_accountability_payload(
    registry: ResearchQuestionRegistry,
) -> dict[str, Any]:
    result_statuses = {
        "RQ1": "review_required",
        "RQ2": "not_operationalised",
        "RQ3": "not_computable",
        "RQ4": "review_required",
        "RQ4.1": "review_required",
        "RQ4.2": "review_required",
        "RQ4.3": "review_required",
        "RQ4.4": "review_required",
        "RQ5": "not_operationalised",
        "RQ6": "not_computable",
        "RQ7": "review_required",
        "RQ8": "not_computable",
    }
    common = {
        "registry_version": registry.version,
        "registry_fingerprint": registry.fingerprint,
        "protocol_version": registry.protocol.version,
        "protocol_fingerprint": registry.protocol.fingerprint,
        "identity_schema_version": "2.0.0",
        "classifier_version": "not_applied",
        "analysis_timestamp": "2026-08-09T20:35:04Z",
    }
    entries: list[dict[str, Any]] = []
    for question in registry.questions:
        result_status = result_statuses[question.question_id]
        method = question.methods[0]
        entry = {
            "question_id": question.question_id,
            "item_type": "research_question",
            "result_status": result_status,
            "view_kind": question.view_kind,
            "scientific_status": SCIENTIFIC_STATUS_BY_RESULT[result_status],
            "observational_unit": question.observational_unit,
            "population_definition": question.population_definition,
            "n": None,
            "missing_n": None,
            "excluded_n": None,
            "denominator": question.denominator,
            "method": method.name,
            "method_readiness": method.readiness,
            "evidence_references": [],
            "validity_threats": [
                "The declared logical view is not materialized."
            ],
            "permitted_interpretation": question.permitted_interpretation,
            "prohibited_interpretation": question.prohibited_interpretation,
            "warnings": ["No empirical answer is established."],
            **common,
        }
        if question.question_id == "RQ8":
            entry["hypothesis_results"] = [
                {
                    "hypothesis_id": hypothesis_id,
                    "outcome": "not_computable",
                    "validated_supply_status": (
                        "not_available"
                        if hypothesis_id == "H2"
                        else "not_applicable"
                    ),
                    "evidence_references": [],
                    "warnings": ["Required inputs are not established."],
                }
                for hypothesis_id in registry.protocol.ordered_hypothesis_ids
            ]
        entries.append(entry)
    for question in registry.extended_questions:
        entries.append(
            {
                "question_id": question.question_id,
                "item_type": "extended_question",
                "result_status": question.status,
                "view_kind": "not_defined",
                "scientific_status": SCIENTIFIC_STATUS_BY_RESULT[question.status],
                "observational_unit": "not_defined_pending_operationalisation",
                "population_definition": "not_defined_pending_operationalisation",
                "n": None,
                "missing_n": None,
                "excluded_n": None,
                "denominator": "not_defined_pending_operationalisation",
                "method": "not_applicable",
                "method_readiness": "not_applicable",
                "evidence_references": [],
                "validity_threats": [
                    "The question is not operationalised or not collected."
                ],
                "permitted_interpretation": question.permitted_interpretation,
                "prohibited_interpretation": question.prohibited_interpretation,
                "warnings": ["Prerequisites remain unresolved."],
                **common,
            }
        )
    return {"ledger_version": "1.0.0", "entries": entries}


def _entry(payload: Mapping[str, Any], question_id: str) -> dict[str, Any]:
    entries = cast(Sequence[dict[str, Any]], payload["entries"])
    return next(item for item in entries if item["question_id"] == question_id)


def test_registry_schemas_are_valid_draft_2020_12() -> None:
    for path in (
        DEFAULT_REGISTRY_SCHEMA_PATH,
        DEFAULT_ACCOUNTABILITY_SCHEMA_PATH,
    ):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_registry_preserves_exact_approved_agenda_order_and_wording() -> None:
    registry = load_research_question_registry()

    assert registry.status == "proposed_for_review"
    assert tuple(item.question_id for item in registry.questions) == (
        REQUIRED_QUESTION_IDS
    )
    assert tuple(item.text for item in registry.questions) == EXPECTED_RQ_TEXTS
    assert tuple(item.question_id for item in registry.extended_questions) == (
        REQUIRED_EXTENDED_QUESTION_IDS
    )
    assert tuple(item.text for item in registry.extended_questions) == (
        EXPECTED_ETQ_TEXTS
    )


def test_registry_preserves_four_axis_name_code_pairs_and_rq4_children() -> None:
    registry = load_research_question_registry()
    axis_pairs = tuple(
        (axis.canonical_name, axis.display_code) for axis in registry.axes
    )
    child_pairs = tuple(
        (question.axis_name, question.axis_code)
        for question in registry.questions
        if question.parent_id == "RQ4"
    )

    assert axis_pairs == CANONICAL_AXES
    assert child_pairs == CANONICAL_AXES


def test_registry_ids_are_unique_and_parent_links_are_valid() -> None:
    registry = load_research_question_registry()
    all_ids = registry.all_question_ids
    rq_ids = {question.question_id for question in registry.questions}

    assert len(all_ids) == len(set(all_ids))
    assert all(
        not question.parent_id or question.parent_id in rq_ids
        for question in registry.questions
    )


def test_extended_questions_keep_prerequisite_only_nonresult_status() -> None:
    raw = _load_yaml(DEFAULT_REGISTRY_PATH)
    extended = cast(Sequence[Mapping[str, Any]], raw["extended_questions"])

    assert len(extended) == 7
    assert [item["status"] for item in extended] == [
        "not_operationalised",
        "not_operationalised",
        "not_operationalised",
        "not_operationalised",
        "not_operationalised",
        "not_operationalised",
        "not_collected",
    ]
    assert all(item["prerequisites"] for item in extended)
    assert all("variables" not in item and "results" not in item for item in extended)


def test_operational_questions_have_full_operationalisation_fields() -> None:
    registry = load_research_question_registry()

    for question in registry.questions:
        assert question.construct
        assert question.population_definition
        assert question.view_kind
        assert question.observational_unit
        assert question.variables
        assert question.indicators
        assert question.measures
        assert question.denominator
        assert question.missing_handling
        assert question.excluded_handling
        assert question.evidence_boundary
        assert question.methods
        assert question.permitted_interpretation
        assert question.prohibited_interpretation
        assert question.repository_source_basis


def test_registry_separates_planned_methods_from_materialized_implementation() -> None:
    registry = load_research_question_registry()

    assert all(
        method.readiness in {"planned", "conditional"}
        for question in registry.questions
        for method in question.methods
    )
    assert all(
        question.materialization_status == "logical_unmaterialized"
        and question.materialization_readiness == "review_required"
        and not question.artifact_path
        for question in registry.questions
    )


def test_protocol_hypothesis_ids_match_exactly_without_definition_duplication() -> None:
    registry = load_research_question_registry()
    protocol = _load_yaml(DEFAULT_PROTOCOL_PATH)
    raw_registry = _load_yaml(DEFAULT_REGISTRY_PATH)
    reference = cast(Mapping[str, Any], raw_registry["hypothesis_reference"])

    assert registry.protocol.ordered_hypothesis_ids == tuple(protocol["hypotheses"])
    assert reference["ordered_ids"] == list(protocol["hypotheses"])
    assert "definitions" not in reference
    assert "definition" not in reference


def test_h2_requires_independent_eqf_6_7_supply_and_excludes_designs() -> None:
    raw = _load_yaml(DEFAULT_REGISTRY_PATH)
    reference = cast(Mapping[str, Any], raw["hypothesis_reference"])
    h2_rule = cast(Mapping[str, Any], reference["h2_supply_rule"])

    assert h2_rule == {
        "minimum_eqf_levels": [6, 7],
        "required_supply_status": "independently_validated",
        "generated_designs_are_supply": False,
        "default_without_supply": "not_computable",
    }


def test_query_provenance_and_candidate_design_boundaries_are_explicit() -> None:
    registry = load_research_question_registry()
    all_boundaries = " ".join(
        question.evidence_boundary.lower() for question in registry.questions
    )
    rq7 = next(item for item in registry.questions if item.question_id == "RQ7")

    assert "source_query" in all_boundaries
    assert "provenance only" in all_boundaries
    assert "validated supply" in rq7.prohibited_interpretation


def test_accountability_schema_retains_baseline_and_stronger_provenance() -> None:
    schema = json.loads(
        DEFAULT_ACCOUNTABILITY_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    required = set(schema["$defs"]["accountabilityEntry"]["required"])

    assert BASELINE_ACCOUNTABILITY_FIELDS <= required
    assert {
        "item_type",
        "population_definition",
        "excluded_n",
        "method_readiness",
        "registry_version",
        "registry_fingerprint",
        "protocol_version",
        "protocol_fingerprint",
        "identity_schema_version",
        "classifier_version",
        "analysis_timestamp",
        "warnings",
    } <= required


def test_future_accountability_covers_every_question_and_unresolved_status() -> None:
    registry = load_research_question_registry()
    payload = _future_accountability_payload(registry)
    ledger = validate_accountability_payload(payload, registry)

    assert tuple(item.question_id for item in ledger.entries) == (
        registry.all_question_ids
    )
    statuses = {item.result_status for item in ledger.entries}
    assert {
        "not_computable",
        "not_operationalised",
        "not_collected",
        "review_required",
    } <= statuses
    assert set(ALLOWED_RESULT_STATUSES) > statuses
    rq8 = next(item for item in ledger.entries if item.question_id == "RQ8")
    assert tuple(
        item.hypothesis_id for item in rq8.hypothesis_results
    ) == registry.protocol.ordered_hypothesis_ids
    assert all(item.outcome == "not_computable" for item in rq8.hypothesis_results)


def test_duplicate_question_ids_are_rejected(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["questions"][1]["id"] = "RQ1"

    _expect_registry_failure(tmp_path, mutate, "unique")


def test_invalid_parent_link_is_rejected(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["questions"][4]["parent_id"] = "RQ99"

    _expect_registry_failure(tmp_path, mutate, "parent_id")


def test_noncanonical_rq4_axis_pair_is_rejected(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["questions"][4]["axis_name"] = "OCEANIC"
        payload["questions"][4]["axis_code"] = "O"

    _expect_registry_failure(tmp_path, mutate, "expected canonical axis")


def test_unknown_question_status_is_rejected(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["questions"][0]["status"] = "answered"

    _expect_registry_failure(tmp_path, mutate, "is not one of")


def test_missing_operational_field_is_rejected(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        del payload["questions"][0]["denominator"]

    _expect_registry_failure(tmp_path, mutate, "denominator.*required")


def test_unapproved_method_cannot_be_represented_as_implemented(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["questions"][0]["methods"][0]["readiness"] = "implemented"

    _expect_registry_failure(tmp_path, mutate, "repository_approved")


def test_unresolved_artifact_cannot_be_represented_as_materialized(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        materialization = payload["questions"][0]["materialization"]
        materialization["status"] = "materialized"
        materialization["readiness"] = "ready"
        materialization["artifact_path"] = "outputs/not-a-real-rq-view.json"

    _expect_registry_failure(tmp_path, mutate, "existing repository artifact_path")


def test_protocol_hypothesis_id_mismatch_is_rejected(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["hypothesis_reference"]["ordered_ids"] = ["H1", "H3", "H2"]

    _expect_registry_failure(tmp_path, mutate, "authoritative protocol order")


def test_h2_generated_supply_or_answer_default_is_rejected(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        h2_rule = payload["hypothesis_reference"]["h2_supply_rule"]
        h2_rule["generated_designs_are_supply"] = True
        h2_rule["default_without_supply"] = "answered"

    _expect_registry_failure(tmp_path, mutate, "False was expected")


def test_incomplete_accountability_ledger_is_rejected() -> None:
    registry = load_research_question_registry()
    payload = _future_accountability_payload(registry)
    cast(list[dict[str, Any]], payload["entries"]).pop()

    with pytest.raises(ResearchQuestionRegistryError, match="omits: ETQ7"):
        validate_accountability_payload(payload, registry)


def test_accountability_entry_missing_baseline_field_is_rejected() -> None:
    registry = load_research_question_registry()
    payload = _future_accountability_payload(registry)
    del _entry(payload, "RQ1")["evidence_references"]

    with pytest.raises(
        ResearchQuestionRegistryError,
        match="evidence_references.*required",
    ):
        validate_accountability_payload(payload, registry)


def test_manufactured_answered_state_is_rejected() -> None:
    registry = load_research_question_registry()
    payload = _future_accountability_payload(registry)
    rq1 = _entry(payload, "RQ1")
    rq1.update(
        {
            "result_status": "answered",
            "scientific_status": "answer_established",
            "n": 1,
            "missing_n": 0,
            "excluded_n": 0,
            "evidence_references": ["fragment:fixture-not-empirical"],
            "warnings": [],
        }
    )

    with pytest.raises(
        ResearchQuestionRegistryError,
        match="answered state requires a materialized target",
    ):
        validate_accountability_payload(payload, registry)


def test_h2_cannot_claim_support_without_independent_validated_supply() -> None:
    registry = load_research_question_registry()
    payload = _future_accountability_payload(registry)
    rq8 = _entry(payload, "RQ8")
    hypothesis_results = cast(
        list[dict[str, Any]], rq8["hypothesis_results"]
    )
    h2 = next(
        item for item in hypothesis_results if item["hypothesis_id"] == "H2"
    )
    h2["outcome"] = "supported"
    h2["validated_supply_status"] = "not_available"

    with pytest.raises(
        ResearchQuestionRegistryError,
        match="must remain not_computable",
    ):
        validate_accountability_payload(payload, registry)


def test_extended_question_cannot_be_manufactured_as_answered() -> None:
    registry = load_research_question_registry()
    payload = _future_accountability_payload(registry)
    etq1 = _entry(payload, "ETQ1")
    etq1["result_status"] = "answered"
    etq1["scientific_status"] = "answer_established"

    with pytest.raises(
        ResearchQuestionRegistryError,
        match="must remain not_operationalised",
    ):
        validate_accountability_payload(payload, registry)


def test_cli_returns_nonzero_for_invalid_registry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["questions"][0]["status"] = "unknown"

    invalid_path = _write_mutated_registry(tmp_path, mutate)
    exit_code = validator_main(["--registry", str(invalid_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "[ERROR]" in captured.err
