"""Stage 2 schema governance tests for research metadata exports."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.export_live_research_records import export_records_json
from src.scientific_sources.models import LiteratureRecord

SCHEMA_PATH = Path("schemas/research_metadata.schema.json")


def _load_schema() -> dict:
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _validate_against_stage2_schema(payload: dict, schema: dict) -> None:
    required = set(schema["required"])
    props = set(schema["properties"].keys())

    missing = required - set(payload.keys())
    assert not missing, f"Missing required fields: {sorted(missing)}"

    extra = set(payload.keys()) - props
    assert not extra, f"Unexpected fields (violates additionalProperties=false): {sorted(extra)}"


def _make_record(**kwargs) -> LiteratureRecord:
    base = dict(
        title="Blue Economy Governance",
        authors="Ada Lovelace",
        year="2024",
        doi="10.1234/blue",
        source_id="crossref:10.1234/blue",
        provider="crossref",
        journal="Ocean Studies",
        url="https://example.org/paper",
        subject_terms=["blue economy"],
        source_query="blue economy governance",
        retrieval_timestamp="2026-05-12T00:00:00+00:00",
        licence_note="open metadata",
    )
    base.update(kwargs)
    return LiteratureRecord(**base)


def test_schema_file_exists_and_blocks_restricted_fields():
    schema = _load_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    props = schema["properties"]
    assert "citation_count" not in props
    assert "abstract_available" not in props
    assert "abstract_stored" not in props


def test_exported_records_conform_to_stage2_schema(tmp_path: Path):
    schema = _load_schema()
    out = tmp_path / "records.json"

    record = _make_record(citation_count=42, abstract_available=True, abstract_stored=True)
    export_records_json([record], out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 1
    _validate_against_stage2_schema(data[0], schema)


def test_schema_rejects_restricted_fields_in_payload():
    schema = _load_schema()
    payload = {
        "title": "X",
        "authors": "Y",
        "year": "2025",
        "doi": "10.1/x",
        "source_id": "crossref:10.1/x",
        "provider": "crossref",
        "journal": "J",
        "url": "https://example.org",
        "subject_terms": [],
        "source_query": "q",
        "retrieval_timestamp": "2026-05-12T00:00:00+00:00",
        "licence_note": "open metadata",
        "citation_count": 10,
    }

    try:
        _validate_against_stage2_schema(payload, schema)
        raised = False
    except AssertionError:
        raised = True

    assert raised, "Stage 2 schema validation must reject citation_count"
