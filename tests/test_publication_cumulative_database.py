from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
DOCS_DIR = REPO_ROOT / "docs"
FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "cumulative_database_schema_samples.json"
)
STANDARD_MISSING_CODES = [-99, -98, -97, -96, -95]

SCHEMA_TO_FIXTURE = {
    "runs.schema.json": ("runs", "run_pk"),
    "source_bundles.schema.json": ("source_bundles", "bundle_pk"),
    "evidence_records.schema.json": ("evidence_records", "record_pk"),
    "evidence_occurrences.schema.json": ("evidence_occurrences", "occurrence_pk"),
    "evidence_segments.schema.json": ("evidence_segments", "segment_pk"),
    "evidence_fragments.schema.json": ("evidence_fragments", "fragment_id"),
    "semantic_signals.schema.json": ("semantic_signals", "signal_id"),
    "competence_candidates.schema.json": ("competence_candidates", "candidate_id"),
    "canonical_competences.schema.json": (
        "canonical_competences",
        "canonical_competence_id",
    ),
    "sector_competence_assignments.schema.json": (
        "sector_competence_assignments",
        "assignment_id",
    ),
    "validation_decisions.schema.json": (
        "validation_decisions",
        "validation_decision_id",
    ),
    "coding_assignments.schema.json": ("coding_assignments", "assignment_pk"),
    "reliability_metrics.schema.json": ("reliability_metrics", "reliability_pk"),
    "gap_clusters.schema.json": ("gap_clusters", "gap_cluster_pk"),
    "dynamic_credentials.schema.json": ("dynamic_credentials", "credential_pk"),
    "data_quality_indicators.schema.json": (
        "data_quality_indicators",
        "indicator_pk",
    ),
}

REQUIRED_DOCS = {
    "CROSS_RUN_EVIDENCE_CODEBOOK.md": [
        "analysis_view_record_level.csv",
        "analysis_view_occurrence_level.csv",
        "analysis_view_sector_axis_gap_level.csv",
        "analysis_view_provider_sector_level.csv",
        "analysis_view_credential_level.csv",
        "-99",
        "-98",
        "-97",
        "-96",
        "-95",
        "466",
    ],
    "CUMULATIVE_DATABASE_METHODOLOGY.md": [
        "15 baseline + 451 literature-derived",
        "CSV",
        "XLSX",
        ".sav",
        "JSONL",
        "checksum",
    ],
    "CONTENT_ANALYSIS_PROTOCOL.md": [
        "Cohen kappa",
        "Krippendorff alpha",
        "precision",
        "recall",
        "F1",
        "provider bias",
    ],
    "STATISTICAL_ANALYSIS_PLAN.md": [
        "Excel",
        "Statistica",
        "PS IMAGO/SPSS",
        "Python",
        "R",
    ],
    "DATA_RELEASE_POLICY.md": [
        "versioned downloadable",
        "checksums",
        "restricted/copyrighted",
        "raw sources are never overwritten",
        "reproducible from parent sources",
    ],
}


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text(encoding="utf-8"))


def test_schema_positive_fixtures_validate() -> None:
    fixture = _load_fixture()
    for schema_name, (fixture_key, _) in SCHEMA_TO_FIXTURE.items():
        schema = _load_schema(schema_name)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        assert list(validator.iter_errors(fixture[fixture_key])) == [], schema_name


def test_schemas_reject_missing_primary_keys() -> None:
    fixture = _load_fixture()
    for schema_name, (fixture_key, primary_key) in SCHEMA_TO_FIXTURE.items():
        schema = _load_schema(schema_name)
        validator = Draft202012Validator(schema)
        payload = copy.deepcopy(fixture[fixture_key])
        assert primary_key in schema["required"], schema_name
        payload.pop(primary_key, None)
        errors = list(validator.iter_errors(payload))
        assert errors, schema_name


def test_categorical_variables_define_labels_and_missing_codes() -> None:
    for schema_name in SCHEMA_TO_FIXTURE:
        schema = _load_schema(schema_name)
        properties = schema["properties"]
        for field_name, definition in properties.items():
            if not definition.get("x-categorical"):
                continue
            label_field = definition["x-label-field"]
            assert label_field in properties, (schema_name, field_name)
            assert definition["x-missing-codes"] == STANDARD_MISSING_CODES
            assert set(str(code) for code in STANDARD_MISSING_CODES).issubset(
                definition["x-value-labels"].keys()
            )
            assert definition["x-measurement-level"] in {"nominal", "ordinal"}
            assert definition["x-allowed-values"]


def test_missing_codes_validate_for_categorical_fields() -> None:
    fixture = _load_fixture()
    for schema_name, (fixture_key, _) in SCHEMA_TO_FIXTURE.items():
        schema = _load_schema(schema_name)
        validator = Draft202012Validator(schema)
        base = fixture[fixture_key]
        for field_name, definition in schema["properties"].items():
            if not definition.get("x-categorical"):
                continue
            label_field = definition["x-label-field"]
            for missing_code in STANDARD_MISSING_CODES:
                payload = copy.deepcopy(base)
                payload[field_name] = missing_code
                payload[label_field] = definition["x-value-labels"][str(missing_code)]
                assert list(validator.iter_errors(payload)) == [], (
                    schema_name,
                    field_name,
                    missing_code,
                )


def test_evidence_records_and_occurrences_separate_uniques_from_repeats() -> None:
    fixture = _load_fixture()["occurrence_scenario"]
    records = fixture["evidence_records"]
    occurrences = fixture["evidence_occurrences"]
    assert len(records) == 1
    assert len(occurrences) == 2
    assert {row["record_pk"] for row in records} == {"record_pk_001"}
    assert {row["record_pk"] for row in occurrences} == {"record_pk_001"}


def test_generated_supply_cannot_become_verified_supply() -> None:
    schema = _load_schema("dynamic_credentials.schema.json")
    validator = Draft202012Validator(schema)
    negative_payload = _load_fixture()["dynamic_credentials_generated_supply_negative"]
    errors = list(validator.iter_errors(negative_payload))
    assert errors


def test_schema_v2_fixture_preserves_construct_valid_lineage() -> None:
    fixture = _load_fixture()
    evidence_record = fixture["evidence_records"]
    fragment = fixture["evidence_fragments"]
    signal = fixture["semantic_signals"]
    candidate = fixture["competence_candidates"]
    decision = fixture["validation_decisions"]
    canonical = fixture["canonical_competences"]
    assignment = fixture["sector_competence_assignments"]

    assert fragment["evidence_id"] == evidence_record["canonical_record_id"]
    assert signal["fragment_id"] == fragment["fragment_id"]
    assert signal["evidence_id"] == fragment["evidence_id"]
    assert signal["source_provenance_id"] == fragment["source_provenance_id"]
    assert candidate["signal_id"] == signal["signal_id"]
    assert candidate["fragment_id"] == fragment["fragment_id"]
    assert candidate["evidence_id"] == fragment["evidence_id"]
    assert candidate["source_provenance_ids"] == fragment["source_provenance_id"]
    assert decision["target_candidate_id"] == candidate["candidate_id"]
    assert decision["evidence_ids"] == candidate["evidence_id"]
    assert decision["fragment_ids"] == candidate["fragment_id"]
    assert decision["source_provenance_ids"] == candidate["source_provenance_ids"]
    assert decision["decision_status"] == "accepted"
    assert canonical["validation_decision_id"] == decision["validation_decision_id"]
    assert canonical["source_candidate_id"] == decision["target_candidate_id"]
    assert assignment["canonical_competence_id"] == canonical["canonical_competence_id"]
    assert assignment["validation_decision_id"] == decision["validation_decision_id"]
    assert assignment["source_candidate_id"] == candidate["candidate_id"]
    assert assignment["evidence_ids"] == candidate["evidence_id"]


def test_validation_decision_schema_requires_accepted_labels_and_pseudonymous_reviewers() -> None:
    fixture = _load_fixture()
    schema = _load_schema("validation_decisions.schema.json")
    validator = Draft202012Validator(schema)

    accepted_blank_label = copy.deepcopy(fixture["validation_decisions"])
    accepted_blank_label["canonical_label"] = ""
    assert list(validator.iter_errors(accepted_blank_label))

    for decision_status in ("rejected", "review_required", "superseded"):
        non_promoting_decision = copy.deepcopy(fixture["validation_decisions"])
        non_promoting_decision["decision_status"] = decision_status
        non_promoting_decision["canonical_label"] = ""
        assert list(validator.iter_errors(non_promoting_decision)) == []

    email_reviewer = copy.deepcopy(fixture["validation_decisions"])
    email_reviewer["reviewer"] = "reviewer@example.org"
    assert list(validator.iter_errors(email_reviewer))


def test_schema_v2_status_vocabularies_are_closed() -> None:
    fixture = _load_fixture()
    invalid_values = (
        ("semantic_signals.schema.json", "semantic_signals", "negation_status", "unknown"),
        ("semantic_signals.schema.json", "semantic_signals", "speculation_status", "unknown"),
        ("semantic_signals.schema.json", "semantic_signals", "manual_review_status", "pending"),
        ("canonical_competences.schema.json", "canonical_competences", "validation_status", "draft"),
        (
            "canonical_competences.schema.json",
            "canonical_competences",
            "provenance_guard_status",
            "unchecked",
        ),
        ("competence_candidates.schema.json", "competence_candidates", "candidate_status", "accepted"),
        ("competence_candidates.schema.json", "competence_candidates", "review_status", "pending"),
    )
    for schema_name, fixture_key, field_name, invalid_value in invalid_values:
        validator = Draft202012Validator(_load_schema(schema_name))
        payload = copy.deepcopy(fixture[fixture_key])
        payload[field_name] = invalid_value
        assert list(validator.iter_errors(payload)), (schema_name, field_name)


def test_sector_assignment_axis_code_schema_uses_canonical_codes() -> None:
    fixture = _load_fixture()
    validator = Draft202012Validator(
        _load_schema("sector_competence_assignments.schema.json")
    )
    for axis_code in ("M", "T", "O", "H"):
        payload = copy.deepcopy(fixture["sector_competence_assignments"])
        payload["axis_code"] = axis_code
        assert list(validator.iter_errors(payload)) == []

    for invalid_axis_code in ("", "OCEANIC", "X"):
        payload = copy.deepcopy(fixture["sector_competence_assignments"])
        payload["axis_code"] = invalid_axis_code
        assert list(validator.iter_errors(payload))


def test_small_fixtures_stay_small() -> None:
    fixture_files = list((REPO_ROOT / "tests" / "fixtures").rglob("*"))
    for path in fixture_files:
        if path.is_file():
            assert path.stat().st_size <= 16 * 1024, path


def test_publication_docs_exist_with_required_content() -> None:
    for filename, required_tokens in REQUIRED_DOCS.items():
        content = (DOCS_DIR / filename).read_text(encoding="utf-8")
        for token in required_tokens:
            assert token in content, (filename, token)


def test_research_data_package_manifest_schema_is_valid() -> None:
    schema = _load_schema("research_data_package_manifest.schema.json")
    Draft202012Validator.check_schema(schema)
