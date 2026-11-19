#!/usr/bin/env python3
"""Fail-closed validator for the governed ABRP gold-corpus contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = REPO_ROOT / "schemas" / "abrp_gold_corpus.schema.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _semantic_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    records = payload.get("records", [])
    phase = payload.get("annotation_phase")
    corpus_status = payload.get("corpus_status")
    seen_ids: set[str] = set()

    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        annotation_id = str(record.get("annotation_id", ""))
        if annotation_id in seen_ids:
            errors.append(f"{prefix}: duplicate annotation_id {annotation_id!r}")
        seen_ids.add(annotation_id)

        text = str(record.get("evidence_text", ""))
        span = str(record.get("exact_evidence_span", ""))
        start = record.get("span_start")
        end = record.get("span_end")
        if isinstance(start, int) and isinstance(end, int):
            if end <= start or end > len(text):
                errors.append(f"{prefix}: invalid exact-span offsets")
            elif text[start:end] != span:
                errors.append(
                    f"{prefix}: exact_evidence_span does not match evidence_text offsets"
                )

        for field in (
            "actor_span",
            "action_span",
            "action_object_span",
            "transformation_span",
            "effect_span",
        ):
            component = str(record.get(field, ""))
            if component and component not in span:
                errors.append(
                    f"{prefix}: {field} is not contained in exact_evidence_span"
                )

        action_span = str(record.get("action_span", "")).strip()
        if record.get("validated_human_capability") is True and not action_span:
            errors.append(
                f"{prefix}: no exact action span -> no validated human capability"
            )
        if record.get("capability_content_gate") == "PASS" and not action_span:
            errors.append(f"{prefix}: PASS requires a non-empty exact action span")

        if phase == "A_BLIND":
            leaked = {
                "sector": record.get("sector"),
                "qmbd_axis_group": record.get("qmbd_axis_group"),
                "qmbd_axis_code": record.get("qmbd_axis_code"),
                "axis_fit": record.get("axis_fit"),
                "candidate_capability": record.get("candidate_capability"),
            }
            if any(value not in ("", None) for value in leaked.values()):
                errors.append(
                    f"{prefix}: Phase A contains revealed sector/QMBD/candidate fields"
                )
            if record.get("axis_hidden_phase_A") is not True:
                errors.append(
                    f"{prefix}: Phase A must record axis_hidden_phase_A=true"
                )
            if record.get("axis_revealed_phase_B") is not False:
                errors.append(
                    f"{prefix}: Phase A must record axis_revealed_phase_B=false"
                )

        if phase in {"B_REVEALED", "ADJUDICATED"}:
            if record.get("axis_hidden_phase_A") is not True:
                errors.append(
                    f"{prefix}: revealed phases must preserve Phase-A blindness provenance"
                )
            if record.get("axis_revealed_phase_B") is not True:
                errors.append(
                    f"{prefix}: revealed phases require axis_revealed_phase_B=true"
                )
            if not str(record.get("sector", "")).strip():
                errors.append(f"{prefix}: revealed phases require sector")

        if record.get("is_gold") is True:
            if corpus_status != "adjudicated_gold":
                errors.append(
                    f"{prefix}: is_gold=true requires corpus_status=adjudicated_gold"
                )
            if record.get("adjudication_status") not in {"agreed", "resolved"}:
                errors.append(
                    f"{prefix}: gold records require agreed/resolved adjudication"
                )

        if corpus_status == "seed_non_gold" and record.get("is_gold") is not False:
            errors.append(f"{prefix}: seed_non_gold records must have is_gold=false")

    if corpus_status == "adjudicated_gold" and any(
        record.get("is_gold") is not True for record in records
    ):
        errors.append("adjudicated_gold corpus contains non-gold records")

    return errors


def validate_payload(payload: Any, schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    validator = Draft202012Validator(schema)
    for error in sorted(
        validator.iter_errors(payload),
        key=lambda item: [str(part) for part in item.path],
    ):
        location = ".".join(str(part) for part in error.path) or "$"
        errors.append(f"{location}: {error.message}")
    if isinstance(payload, dict) and not errors:
        errors.extend(_semantic_errors(payload))
    return errors


def validate_file(
    path: Path,
    schema_path: Path = DEFAULT_SCHEMA,
) -> list[str]:
    try:
        schema = _load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        payload = _load_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"input/schema unreadable: {type(exc).__name__}: {exc}"]
    return validate_payload(payload, schema)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args(list(argv) if argv is not None else None)

    errors = validate_file(args.input, args.schema)
    if errors:
        for item in errors:
            print(f"ERROR: {item}")
        return 1
    print("ABRP gold-corpus validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
