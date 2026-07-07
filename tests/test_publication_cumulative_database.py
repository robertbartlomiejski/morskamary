from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = REPO_ROOT / "schemas"
DOCS_DIR = REPO_ROOT / "docs"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "cumulative_database_schema_samples.json"
STANDARD_MISSING_CODES = [-99, -98, -97, -96, -95]

SCHEMA_TO_FIXTURE = {
    "runs.schema.json": "runs",
    "source_bundles.schema.json": "source_bundles",
    "evidence_records.schema.json": "evidence_records",
    "evidence_occurrences.schema.json": "evidence_occurrences",
    "evidence_segments.schema.json": "evidence_segments",
    "coding_assignments.schema.json": "coding_assignments",
    "reliability_metrics.schema.json": "reliability_metrics",
    "gap_clusters.schema.json": "gap_clusters",
    "dynamic_credentials.schema.json": "dynamic_credentials",
    "data_quality_indicators.schema.json": "data_quality_indicators",
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
    for schema_name, fixture_key in SCHEMA_TO_FIXTURE.items():
        schema = _load_schema(schema_name)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        assert list(validator.iter_errors(fixture[fixture_key])) == [], schema_name


def test_schemas_reject_missing_primary_keys() -> None:
    fixture = _load_fixture()
    for schema_name, fixture_key in SCHEMA_TO_FIXTURE.items():
        schema = _load_schema(schema_name)
        validator = Draft202012Validator(schema)
        payload = copy.deepcopy(fixture[fixture_key])
        primary_key = next(
            field
            for field in schema["required"]
            if field.endswith("_pk")
        )
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
    for schema_name, fixture_key in SCHEMA_TO_FIXTURE.items():
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
