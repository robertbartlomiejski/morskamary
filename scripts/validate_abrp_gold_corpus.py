#!/usr/bin/env python3
"""Validate MOR-15A ABRP annotation packages and frozen Pilot-v7 seed metadata."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = REPO_ROOT / "schemas" / "abrp_gold_annotation.schema.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _span_errors(annotation: Mapping[str, Any], key: str) -> list[str]:
    span = annotation.get(key)
    if span is None:
        return []
    evidence_text = str(annotation.get("evidence_text", ""))
    if not isinstance(span, Mapping):
        return [f"{key}: span must be an object or null"]
    start = span.get("start")
    end = span.get("end")
    text = span.get("text")
    if not isinstance(start, int) or not isinstance(end, int) or not isinstance(text, str):
        return [f"{key}: malformed span"]
    if start < 0 or end <= start or end > len(evidence_text):
        return [f"{key}: offsets outside evidence_text"]
    if evidence_text[start:end] != text:
        return [f"{key}: span text does not equal evidence_text[start:end]"]
    return []


def validate_document(payload: Any, schema: Mapping[str, Any]) -> list[str]:
    errors = [
        f"schema:{error.json_path}: {error.message}"
        for error in Draft202012Validator(schema).iter_errors(payload)
    ]
    if not isinstance(payload, Mapping):
        return sorted(errors)
    phase = payload.get("coding_phase")
    corpus_status = payload.get("corpus_status")
    annotations = payload.get("annotations")
    if not isinstance(annotations, list):
        return sorted(errors)

    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(annotations):
        if not isinstance(raw, Mapping):
            continue
        prefix = f"annotations[{index}]"
        key = (
            str(raw.get("evidence_id", "")),
            str(raw.get("fragment_id", "")),
            str(raw.get("annotation_id", "")),
        )
        if key in seen:
            errors.append(f"{prefix}: duplicate evidence/fragment/annotation identity")
        seen.add(key)

        for span_key in (
            "exact_evidence_span",
            "actor_span",
            "action_span",
            "action_object_span",
            "transformation_span",
            "effect_span",
        ):
            errors.extend(
                f"{prefix}.{message}" for message in _span_errors(raw, span_key)
            )

        action_span = raw.get("action_span")
        gate = raw.get("capability_content_gate")
        candidate = raw.get("candidate_capability")
        if action_span is None:
            if gate == "PASS":
                errors.append(f"{prefix}: PASS requires an exact action_span")
            if candidate not in (None, ""):
                errors.append(
                    f"{prefix}: candidate_capability forbidden without action_span"
                )

        if gate == "PASS":
            required_abpr = (
                "actor_span",
                "action_span",
                "action_object_span",
                "transformation_span",
            )
            for name in required_abpr:
                if raw.get(name) is None:
                    errors.append(f"{prefix}: PASS requires {name}")
            for name in (
                "actor",
                "primary_action",
                "action_object",
                "transformation_driver",
                "affected_relation",
                "candidate_capability",
            ):
                if not str(raw.get(name) or "").strip():
                    errors.append(f"{prefix}: PASS requires non-empty {name}")

        if phase == "A":
            for hidden in ("sector", "qmbd_axis", "axis_fit", "candidate_capability"):
                if raw.get(hidden) is not None:
                    errors.append(f"{prefix}: Phase A requires hidden {hidden}=null")
            if raw.get("axis_hidden_phase_A") is not True:
                errors.append(f"{prefix}: Phase A must declare axis_hidden_phase_A=true")
            if raw.get("axis_revealed_phase_B") is not False:
                errors.append(f"{prefix}: Phase A cannot reveal Phase-B axis")

        if corpus_status == "adjudicated_gold":
            if not str(raw.get("reviewer") or "").strip():
                errors.append(f"{prefix}: adjudicated gold requires reviewer")
            if raw.get("adjudication") in (None, "pending"):
                errors.append(f"{prefix}: adjudicated gold requires final adjudication")
    return sorted(set(errors))


def validate_pilot_seed(seed_path: Path, metadata_path: Path) -> list[str]:
    errors: list[str] = []
    metadata = _load_json(metadata_path)
    with seed_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    expected = int(metadata.get("expected_case_count", -1))
    if len(rows) != expected:
        errors.append(f"pilot seed row count {len(rows)} != expected {expected}")
    if [str(index) for index in range(expected)] != [
        str(row.get("index", "")) for row in rows
    ]:
        errors.append("pilot seed indexes must be exactly 0..N-1")
    identities = [str(row.get("evidence_id", "")).strip() for row in rows]
    if len(set(identities)) != len(identities) or any(not item for item in identities):
        errors.append("pilot seed evidence_id values must be unique and non-empty")
    for index, row in enumerate(rows):
        if row.get("evidence_surface") != "title":
            errors.append(f"pilot row {index}: evidence_surface must remain title")
        if row.get("validity_warning") != "metadata_only_limitation":
            errors.append(f"pilot row {index}: metadata-only warning changed")
        if "not yet adjudicated" not in str(row.get("status", "")):
            errors.append(f"pilot row {index}: seed must remain non-adjudicated")
    baseline = metadata.get("phase_a_baseline_summary", {})
    if baseline != {
        "total": 24,
        "complete_action_proposition": 0,
        "partial_action_proposition": 15,
        "underspecified": 4,
        "meta_signal": 1,
        "context_only_or_non_human_capability": 4,
    }:
        errors.append("pilot aggregate baseline summary differs from frozen contract")
    if metadata.get("corpus_status") != "pilot_seed_non_gold":
        errors.append("pilot seed must never be labelled adjudicated gold")
    return sorted(set(errors))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("annotation_package", type=Path, nargs="?")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--pilot-seed", type=Path)
    parser.add_argument("--pilot-metadata", type=Path)
    args = parser.parse_args(argv)

    errors: list[str] = []
    if args.annotation_package:
        errors.extend(
            validate_document(
                _load_json(args.annotation_package),
                _load_json(args.schema),
            )
        )
    if bool(args.pilot_seed) != bool(args.pilot_metadata):
        errors.append("--pilot-seed and --pilot-metadata must be supplied together")
    elif args.pilot_seed and args.pilot_metadata:
        errors.extend(validate_pilot_seed(args.pilot_seed, args.pilot_metadata))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("ABRP gold-corpus validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
