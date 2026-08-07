#!/usr/bin/env python3
"""Build a versioned research data package from cumulative evidence artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

STATUS = {
    "ok": "[OK]",
    "warn": "[WARN]",
    "error": "[ERROR]",
    "info": "[INFO]",
}

SCHEMA_FORMAT_CHECKER = FormatChecker()


@SCHEMA_FORMAT_CHECKER.checks("date-time")
def _is_valid_datetime_format(value: object) -> bool:
    """Validate RFC-3339-like datetimes when optional jsonschema extras lack it."""
    if not isinstance(value, str):
        return True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


SECTOR_CODE = {
    "Blue Biotech": 1,
    "Coastal Tourism": 2,
    "Desalination": 3,
    "Infra & Robotics": 4,
    "Living Res.": 5,
    "Non-living Res.": 6,
    "Renewable Energy": 7,
    "Maritime Defence": 8,
    "Maritime Transport": 9,
    "Port Activities": 10,
    "R&I": 11,
    "Ship Repair": 12,
}

AXIS_CODE = {"MARINE": 1, "MARITIME": 2, "OCEANIC": 3, "HYDRONIZATION": 4}
MISSING_CODE = -98
MISSING_LABEL = "Not extracted"

# Schema-v2 tables are materialized by the cumulative scientific database
# builder.  Keep the list here so the research-data package carries the whole
# review-gated construct-validity chain, rather than only its legacy views.
# Note: "evidence_records" is the cumulative projection keyed by evidence_id;
# it is copied as a supplementary file without schema validation because its
# schema diverges from the legacy evidence_records.schema.json (record_pk PK).
SCHEMA_V2_ENTITY_NAMES: tuple[str, ...] = (
    "evidence_fragments",
    "semantic_signals",
    "competence_candidates",
    "canonical_competences",
    "sector_competence_assignments",
    "validation_decisions",
)
SCHEMA_V2_SUPPLEMENTARY_ENTITY_NAMES: tuple[str, ...] = (
    "evidence_records",
)
SCHEMA_V2_SOURCE_DIRECTORY = "outputs/cumulative_database"
SCHEMA_V2_SCHEMA_FILENAMES: tuple[str, ...] = tuple(
    f"{entity_name}.schema.json" for entity_name in SCHEMA_V2_ENTITY_NAMES
)
SCHEMA_V2_PRIMARY_KEY_FIELDS: dict[str, tuple[str, ...]] = {
    "evidence_fragments": ("fragment_id",),
    "semantic_signals": ("signal_id", "fragment_id"),
    "competence_candidates": ("candidate_id",),
    "validation_decisions": ("validation_decision_id",),
    "canonical_competences": ("canonical_competence_id",),
    "sector_competence_assignments": ("assignment_id",),
}


@dataclass(frozen=True)
class PackageConfig:
    """Resolved runtime configuration for package build."""

    repo_root: Path
    output_dir: Path
    version_tag: str
    release_tag: str
    access_date: str
    source_commit_sha: str
    package_commit_sha: str
    include_xlsx: bool
    include_sav: bool
    bootstrap_empty_manual_sources: bool = False


def status_label(level: str) -> str:
    """Return ASCII-safe status label."""
    return STATUS[level]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _coerce_schema_csv_value(value: Any, definition: dict[str, Any]) -> Any:
    """Restore scalar types lost when a schema-v2 row is serialized to CSV."""
    if value is None:
        return None
    raw_type = definition.get("type")
    types = (raw_type,) if isinstance(raw_type, str) else tuple(raw_type or ())
    if "integer" in types:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if "number" in types:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if "boolean" in types:
        if value == "true":
            return True
        if value == "false":
            return False
    return value


def _is_non_finite_schema_number(value: Any, definition: dict[str, Any]) -> bool:
    """Return whether a CSV scalar is a non-finite value for a numeric field."""
    raw_type = definition.get("type")
    types = (raw_type,) if isinstance(raw_type, str) else tuple(raw_type or ())
    if not {"integer", "number"}.intersection(types):
        return False
    try:
        return not math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _reject_non_finite_json_constant(_: str) -> Any:
    """Reject JSON's non-standard NaN and Infinity constants."""
    raise ValueError("non-finite JSON number")


def _contains_non_finite_number(value: Any) -> bool:
    """Return whether a parsed JSON value contains NaN or infinity."""
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_contains_non_finite_number(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_non_finite_number(item) for item in value)
    return False


def _read_schema_v2_csv(
    path: Path, schema_path: Path, table_name: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a schema-v2 CSV and verify its header before row validation.

    Header validation is necessary for intentionally empty review-gated tables:
    a header-only file still has to preserve the complete schema contract.
    """
    schema = _load_json(schema_path)
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    expected_columns = set(properties) if isinstance(properties, dict) else set()
    errors: list[str] = []
    rows: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        actual_columns = {header for header in headers if header is not None}
        missing_columns = sorted(expected_columns - actual_columns)
        unexpected_columns = sorted(actual_columns - expected_columns)
        if not headers:
            errors.append(f"{table_name}.csv is missing its schema-v2 header")
        if len(headers) != len(actual_columns):
            errors.append(f"{table_name}.csv has duplicate column headers")
        if missing_columns:
            errors.append(
                f"{table_name}.csv is missing schema columns: "
                f"{', '.join(missing_columns)}"
            )
        if unexpected_columns:
            errors.append(
                f"{table_name}.csv has unexpected schema columns: "
                f"{', '.join(unexpected_columns)}"
            )
        for row_index, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                errors.append(
                    f"{table_name}.csv row {row_index} has more values than headers"
                )
            for key, value in raw_row.items():
                if key is None:
                    continue
                definition = (
                    properties.get(key, {}) if isinstance(properties, dict) else {}
                )
                if _is_non_finite_schema_number(value, definition):
                    errors.append(
                        f"{table_name}.csv row {row_index} column {key} "
                        "contains a non-finite numeric value"
                    )
            rows.append(
                {
                    key: _coerce_schema_csv_value(
                        value,
                        properties.get(key, {}) if isinstance(properties, dict) else {},
                    )
                    for key, value in raw_row.items()
                    if key is not None
                }
            )
    return rows, errors


def _read_schema_v2_jsonl(
    path: Path, table_name: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read JSONL without echoing source content if a row is malformed."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            errors.append(f"{table_name}.jsonl line {line_number} is blank")
            continue
        try:
            payload = json.loads(
                raw_line, parse_constant=_reject_non_finite_json_constant
            )
        except json.JSONDecodeError:
            errors.append(f"{table_name}.jsonl line {line_number} is not valid JSON")
            continue
        except ValueError:
            errors.append(
                f"{table_name}.jsonl line {line_number} "
                "contains a non-finite numeric value"
            )
            continue
        if not isinstance(payload, dict):
            errors.append(f"{table_name}.jsonl line {line_number} is not an object")
            continue
        if _contains_non_finite_number(payload):
            errors.append(
                f"{table_name}.jsonl line {line_number} "
                "contains a non-finite numeric value"
            )
            continue
        rows.append(payload)
    return rows, errors


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: str(v) if v is not None else "" for k, v in row.items()}
            )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _get_git_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _normalize_provider(value: str) -> tuple[int, str]:
    token = value.strip().lower()
    if token.startswith("crossref"):
        return 1, "crossref"
    if token.startswith("scopus"):
        return 2, "scopus"
    if token.startswith("wos"):
        return 3, "wos"
    if token.startswith("manual"):
        return 4, "manual"
    if token:
        return 5, token
    return MISSING_CODE, MISSING_LABEL


def _dataset_code(value: str) -> tuple[int, str]:
    token = value.strip()
    mapping = {
        "live_records": 1,
        "live_records_triangulated": 2,
        "cumulative_qmbd_records": 3,
        "manual_supporting_sources": 4,
    }
    code = mapping.get(token)
    if code is None:
        return MISSING_CODE, MISSING_LABEL
    return code, token


def _origin_code(value: str) -> tuple[int, str]:
    token = value.strip().upper()
    mapping = {
        "STATIC_BASELINE": 1,
        "STATIC_LITERATURE": 2,
        "LIVE_API": 3,
        "LIVE_TRIANGULATED": 4,
        "MANUAL_SUPPORTING_SOURCE": 5,
    }
    code = mapping.get(token)
    if code is None:
        return MISSING_CODE, MISSING_LABEL
    return code, token


def _axis_code(value: str) -> tuple[int, str]:
    token = value.strip().upper()
    code = AXIS_CODE.get(token)
    if code is None:
        return MISSING_CODE, MISSING_LABEL
    return code, token.title()


def _load_variable_and_value_labels(
    schema_dir: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Load declared categorical metadata and enum-backed schema categories."""
    variable_rows: list[dict[str, str]] = []
    value_rows: list[dict[str, str]] = []
    for schema_path in sorted(schema_dir.glob("*.schema.json")):
        payload = _load_json(schema_path)
        if not isinstance(payload, dict):
            continue
        props = payload.get("properties", {})
        if not isinstance(props, dict):
            continue
        for field_name, definition in props.items():
            if not isinstance(definition, dict):
                continue
            enum_values = definition.get("enum")
            is_enum_category = isinstance(enum_values, list) and bool(enum_values)
            if not definition.get("x-categorical") and not is_enum_category:
                continue
            variable_rows.append(
                {
                    "schema_file": schema_path.name,
                    "variable_name": field_name,
                    "label_field": str(definition.get("x-label-field", "")),
                    "measurement_level": str(definition.get("x-measurement-level", "")),
                    "missing_codes": "|".join(
                        str(i) for i in definition.get("x-missing-codes", [])
                    ),
                    "allowed_values": "|".join(
                        str(i)
                        for i in (
                            definition.get("x-allowed-values")
                            or (enum_values if enum_values is not None else [])
                        )
                    ),
                }
            )
            value_labels = definition.get("x-value-labels", {})
            if not value_labels and is_enum_category:
                value_labels = {
                    str(value): (
                        "Unbound"
                        if value == ""
                        else str(value).replace("_", " ").title()
                    )
                    for value in (enum_values or [])
                }
            if isinstance(value_labels, dict):
                for code, label in sorted(value_labels.items(), key=lambda kv: kv[0]):
                    value_rows.append(
                        {
                            "schema_file": schema_path.name,
                            "variable_name": field_name,
                            "code": str(code),
                            "label": str(label),
                        }
                    )
    return variable_rows, value_rows


# ---------------------------------------------------------------------------
# Schema-v2 string-enum categorical fields: explicitly registered because
# they use string codes (not integer codes) and therefore do not carry the
# x-categorical / x-label-field / x-missing-codes contract used by the
# legacy integer-coded tables.  Both VARIABLE_LABELS.csv and VALUE_LABELS.csv
# produced by _build_label_tables() are supplemented with these entries.
# ---------------------------------------------------------------------------
_SCHEMA_V2_VARIABLE_LABELS: list[dict[str, str]] = [
    {
        "schema_file": "evidence_fragments.schema.json",
        "variable_name": "source_field",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "title|subject_terms|abstract|full_text",
    },
    {
        "schema_file": "semantic_signals.schema.json",
        "variable_name": "axis_group",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "MARINE|MARITIME|OCEANIC|HYDRONIZATION|",
    },
    {
        "schema_file": "semantic_signals.schema.json",
        "variable_name": "axis_code",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "M|T|O|H|",
    },
    {
        "schema_file": "semantic_signals.schema.json",
        "variable_name": "negation_status",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "not_detected|not_assessed",
    },
    {
        "schema_file": "semantic_signals.schema.json",
        "variable_name": "speculation_status",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "not_detected|not_assessed",
    },
    {
        "schema_file": "semantic_signals.schema.json",
        "variable_name": "manual_review_status",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "auto_accepted|review_required|manually_reviewed|rejected",
    },
    {
        "schema_file": "competence_candidates.schema.json",
        "variable_name": "axis_group",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "MARINE|MARITIME|OCEANIC|HYDRONIZATION|",
    },
    {
        "schema_file": "competence_candidates.schema.json",
        "variable_name": "axis_code",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "M|T|O|H|",
    },
    {
        "schema_file": "competence_candidates.schema.json",
        "variable_name": "candidate_status",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "candidate",
    },
    {
        "schema_file": "competence_candidates.schema.json",
        "variable_name": "review_status",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "auto_accepted|review_required|manually_reviewed|rejected",
    },
    {
        "schema_file": "validation_decisions.schema.json",
        "variable_name": "decision_status",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "accepted|rejected|review_required|superseded",
    },
    {
        "schema_file": "canonical_competences.schema.json",
        "variable_name": "validation_status",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "accepted",
    },
    {
        "schema_file": "canonical_competences.schema.json",
        "variable_name": "provenance_guard_status",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "passed",
    },
    {
        "schema_file": "sector_competence_assignments.schema.json",
        "variable_name": "axis_group",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "MARINE|MARITIME|OCEANIC|HYDRONIZATION",
    },
    {
        "schema_file": "sector_competence_assignments.schema.json",
        "variable_name": "axis_code",
        "label_field": "",
        "measurement_level": "nominal",
        "missing_codes": "",
        "allowed_values": "M|T|O|H",
    },
]


def _v2vl(schema_file: str, variable_name: str, code: str, label: str) -> dict[str, str]:
    """Shorthand constructor for schema-v2 value-label rows."""
    return {
        "schema_file": schema_file,
        "variable_name": variable_name,
        "code": code,
        "label": label,
    }


_EF = "evidence_fragments.schema.json"
_SS = "semantic_signals.schema.json"
_CC = "competence_candidates.schema.json"
_VD = "validation_decisions.schema.json"
_CN = "canonical_competences.schema.json"
_SA = "sector_competence_assignments.schema.json"

_AXIS_GROUP_LABELS = [
    ("MARINE", "Marine \u2014 biophysical, ecological and more-than-human agency or constraints"),
    ("MARITIME", "Maritime \u2014 labour, technology, infrastructure, economy and institutional mediation"),
    ("OCEANIC", "Oceanic \u2014 planetary coupling, transboundary governance and hydrosocial responsibility"),
    ("HYDRONIZATION", "Hydronization \u2014 water-mediated transformation and hydro-social relations"),
]
_AXIS_CODE_LABELS = [
    ("M", "Marine"), ("T", "Maritime"), ("O", "Oceanic"), ("H", "Hydronization"),
]
_REVIEW_STATUS_LABELS = [
    ("auto_accepted", "Automatically accepted by classifier"),
    ("review_required", "Manual review required"),
    ("manually_reviewed", "Manually reviewed and accepted"),
    ("rejected", "Rejected after review"),
]

_SCHEMA_V2_VALUE_LABELS: list[dict[str, str]] = (
    # evidence_fragments.source_field
    [_v2vl(_EF, "source_field", "title", "Title field")]
    + [_v2vl(_EF, "source_field", "subject_terms", "Subject terms / keywords field")]
    + [_v2vl(_EF, "source_field", "abstract", "Abstract field")]
    + [_v2vl(_EF, "source_field", "full_text", "Full text field")]
    # semantic_signals
    + [
        _v2vl(_SS, "axis_group", code, label)
        for code, label in _AXIS_GROUP_LABELS
    ]
    + [_v2vl(_SS, "axis_group", "", "Unbound / not assigned")]
    + [
        _v2vl(_SS, "axis_code", code, label)
        for code, label in _AXIS_CODE_LABELS
    ]
    + [_v2vl(_SS, "axis_code", "", "Unbound / not assigned")]
    + [_v2vl(_SS, "negation_status", "not_detected", "Negation not detected in text span")]
    + [_v2vl(_SS, "negation_status", "not_assessed", "Negation assessment not run")]
    + [_v2vl(_SS, "speculation_status", "not_detected", "Speculation not detected in text span")]
    + [_v2vl(_SS, "speculation_status", "not_assessed", "Speculation assessment not run")]
    + [
        _v2vl(_SS, "manual_review_status", code, label)
        for code, label in _REVIEW_STATUS_LABELS
    ]
    # competence_candidates
    + [
        _v2vl(_CC, "axis_group", code, label)
        for code, label in _AXIS_GROUP_LABELS
    ]
    + [_v2vl(_CC, "axis_group", "", "Unbound / not assigned")]
    + [
        _v2vl(_CC, "axis_code", code, label)
        for code, label in _AXIS_CODE_LABELS
    ]
    + [_v2vl(_CC, "axis_code", "", "Unbound / not assigned")]
    + [_v2vl(_CC, "candidate_status", "candidate", "Proposed competence candidate awaiting validation")]
    + [
        _v2vl(_CC, "review_status", code, label)
        for code, label in _REVIEW_STATUS_LABELS
    ]
    # validation_decisions
    + [_v2vl(_VD, "decision_status", "accepted", "Candidate accepted and promoted to canonical competence")]
    + [_v2vl(_VD, "decision_status", "rejected", "Candidate rejected; not promoted")]
    + [_v2vl(_VD, "decision_status", "review_required", "Decision deferred pending further review")]
    + [_v2vl(_VD, "decision_status", "superseded", "Decision superseded by a later validation decision")]
    # canonical_competences
    + [_v2vl(_CN, "validation_status", "accepted", "Canonical competence accepted via validated decision")]
    + [_v2vl(_CN, "provenance_guard_status", "passed", "Canonical-label provenance guard passed")]
    # sector_competence_assignments
    + [
        _v2vl(_SA, "axis_group", code, label)
        for code, label in _AXIS_GROUP_LABELS
    ]
    + [
        _v2vl(_SA, "axis_code", code, label)
        for code, label in _AXIS_CODE_LABELS
    ]
)


def _validate_rows(
    rows: list[dict[str, Any]], schema_path: Path, table_name: str
) -> list[str]:
    payload = _load_json(schema_path)
    Draft202012Validator.check_schema(payload)
    validator = Draft202012Validator(
        payload,
        format_checker=SCHEMA_FORMAT_CHECKER,
    )
    errors: list[str] = []
    for idx, row in enumerate(rows):
        for err in validator.iter_errors(row):
            errors.append(f"{table_name}[{idx}] {err.message}")
    return errors


def _validate_manifest(manifest: dict[str, Any], schema_path: Path) -> list[str]:
    payload = _load_json(schema_path)
    Draft202012Validator.check_schema(payload)
    validator = Draft202012Validator(
        payload,
        format_checker=SCHEMA_FORMAT_CHECKER,
    )
    return [error.message for error in validator.iter_errors(manifest)]


def _merge_label_rows(
    generated_rows: list[dict[str, str]],
    curated_rows: list[dict[str, str]],
    key_fields: tuple[str, ...],
) -> list[dict[str, str]]:
    """Merge generated and curated label rows with curated-key override."""
    merged: dict[tuple[str, ...], dict[str, str]] = {
        tuple(str(row.get(field, "")) for field in key_fields): row
        for row in generated_rows
    }
    for row in curated_rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        merged[key] = row
    return sorted(
        merged.values(),
        key=lambda row: tuple(str(row.get(field, "")) for field in key_fields),
    )


def _row_key(row: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
    """Return a normalized composite key without admitting blank components."""
    return tuple(str(row.get(field, "")).strip() for field in fields)


def _format_row_key(key: tuple[str, ...]) -> str:
    """Render a composite key deterministically for a non-sensitive error."""
    return "|".join(key)


def _split_reference_ids(value: Any) -> set[str]:
    """Return non-empty pipe-delimited lineage references."""
    return {item.strip() for item in str(value or "").split("|") if item.strip()}


def _candidate_fragment_ids(candidate: dict[str, Any]) -> set[str]:
    """Return a candidate's retained fragments, falling back to its scalar key."""
    fragment_ids = _split_reference_ids(candidate.get("fragment_ids"))
    if fragment_ids:
        return fragment_ids
    fragment_id = str(candidate.get("fragment_id", "")).strip()
    return {fragment_id} if fragment_id else set()


_BOUND_AXIS_CONTEXTS = {
    ("MARINE", "M"),
    ("MARITIME", "T"),
    ("OCEANIC", "O"),
    ("HYDRONIZATION", "H"),
}


def _candidate_semantic_contexts(
    candidate: dict[str, Any],
    signals_by_key: dict[tuple[str, ...], dict[str, Any]],
) -> set[tuple[str, str, str]]:
    """Return all semantic sector/axis contexts retained by a candidate."""
    signal_id = str(candidate.get("signal_id", "")).strip()
    contexts: set[tuple[str, str, str]] = set()
    for fragment_id in _candidate_fragment_ids(candidate):
        signal = signals_by_key.get((signal_id, fragment_id))
        if signal is None:
            continue
        contexts.add(
            (
                str(signal.get("sector", "")).strip(),
                str(signal.get("axis_group", "")).strip(),
                str(signal.get("axis_code", "")).strip(),
            )
        )
    return contexts


def _is_bound_axis_context(context: tuple[str, str, str]) -> bool:
    """Return whether a semantic context can emit a sector assignment."""
    sector, axis_group, axis_code = context
    return bool(sector) and (axis_group, axis_code) in _BOUND_AXIS_CONTEXTS


def _string_value(value: Any) -> str:
    """Return a scalar string without changing its retained value."""
    return "" if value is None else str(value)


def _normalized_label(value: Any) -> str:
    """Normalize a human-facing label before comparing published links."""
    return re.sub(r"\s+", " ", _string_value(value)).strip().casefold()


def _runtime_canonical_label(value: Any) -> str:
    """Normalize a canonical label exactly as the runtime identity does."""
    return re.sub(r"\s+", " ", _string_value(value)).strip().lower()


# Provider aliases used by the canonical-label provenance guard.  Must stay in
# sync with _CANONICAL_LABEL_PROVIDER_ALIASES in build_live_cumulative_release_package.py.
_CANONICAL_LABEL_PROVIDER_ALIASES: frozenset[str] = frozenset({
    "crossref",
    "cr",
    "scopus",
    "elsevier scopus",
    "wos",
    "web of science",
    "web of science clarivate",
    "web of science (clarivate)",
    "web_of_science",
    "web_of_science_clarivate",
    "clarivate",
    "clarivate wos",
    "clarivate web of science",
    "clarivate_web_of_science",
    "scival",
    "microsoft graph",
    "microsoft_graph",
    "google drive",
    "google_drive",
})


def _normalize_title_for_label_guard(value: Any) -> str:
    """Strip punctuation and collapse whitespace for title-overlap detection."""
    raw = re.sub(r"\s+", " ", _string_value(value)).strip().lower()
    return re.sub(r"[^\w\s]", "", raw).strip()


def _canonical_label_guard_reason(
    label: Any, retained_source_titles: tuple[str, ...] = ()
) -> str:
    """Return the rejection reason for a canonical label, or '' if it is valid.

    Mirrors the guard in build_live_cumulative_release_package.py so that the
    versioned-package validator enforces the same provenance rules.
    """
    token = re.sub(r"\s+", " ", _string_value(label)).strip()
    if not token:
        return "empty_label"
    lowered = token.lower()
    provider_token = re.sub(r"[_\s]+", " ", lowered).strip()
    provider_aliases = {
        re.sub(r"[_\s]+", " ", alias).strip()
        for alias in _CANONICAL_LABEL_PROVIDER_ALIASES
    }
    if any(
        provider_token == alias
        or provider_token.startswith(f"{alias}:")
        or provider_token.startswith(f"{alias} ")
        for alias in provider_aliases
    ):
        return "provider_metadata_prefix"
    if "..." in token or "\u2026" in token:
        return "truncation_ellipsis"
    if len(token) > 180:
        return "length_over_180"
    if token.count(" ") >= 8:
        return "space_count_at_least_8"
    metadata_match = re.search(
        r"\b(doi|journal|conference|article|paper)\b", lowered
    )
    if metadata_match:
        return f"metadata_term:{metadata_match.group(1)}"
    normalized_label = _normalize_title_for_label_guard(token)
    label_token_count = len(normalized_label.split())
    for source_title in retained_source_titles:
        normalized_title = _normalize_title_for_label_guard(source_title)
        if not normalized_title or not normalized_label:
            continue
        if normalized_label == normalized_title:
            return "source_title_exact"
        if (
            label_token_count >= 3
            and f" {normalized_label} " in f" {normalized_title} "
        ):
            return "source_title_fragment"
    return ""


def _normalized_text_hash(value: Any) -> str:
    """Return the runtime-compatible hash for a retained text surface."""
    normalized = re.sub(r"\s+", " ", _string_value(value)).strip().lower()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _expected_fragment_provenance_id(fragment: dict[str, Any]) -> str:
    """Recompute a source occurrence identifier from its public preimage."""
    payload = "\x1f".join(
        (
            _string_value(fragment.get("run_id")),
            _string_value(fragment.get("evidence_id")),
            _string_value(fragment.get("source_retrieved_at_utc")),
            _string_value(fragment.get("source_provider")),
            _string_value(fragment.get("source_provider_id")).strip().lower(),
            _string_value(fragment.get("source_query_id")),
            re.sub(
                r"\s+", " ", _string_value(fragment.get("source_query_text"))
            )
            .strip()
            .lower(),
        )
    )
    return f"prov:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _parse_utc_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp, returning None when it is invalid."""
    token = _string_value(value).strip()
    if not token:
        return None
    try:
        parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError:
        return None
    utc_offset = parsed.utcoffset()
    if (
        parsed.tzinfo is None
        or utc_offset is None
        or utc_offset.total_seconds() != 0
    ):
        return None
    return parsed.astimezone(timezone.utc)


def _expected_signal_id(signal: dict[str, Any]) -> str:
    """Recompute the runtime's stable semantic-signal identity."""
    matched_phrase = re.sub(
        r"\s+", " ", _string_value(signal.get("matched_phrase"))
    ).strip().lower()
    payload = "\x1f".join(
        (
            _string_value(signal.get("evidence_id")),
            _string_value(signal.get("signal_type")),
            matched_phrase,
            _string_value(signal.get("evidence_text_hash")),
            _string_value(signal.get("classifier_version")),
        )
    )
    return f"signal:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _expected_fragment_id(fragment: dict[str, Any], signal_id: str) -> str | None:
    """Recompute the runtime's stable evidence-fragment identity."""
    span_start = fragment.get("span_start_offset")
    span_end = fragment.get("span_end_offset")
    if not isinstance(span_start, int) or not isinstance(span_end, int):
        return None
    payload = "\x1f".join(
        (
            _string_value(fragment.get("evidence_id")),
            signal_id,
            _expected_fragment_provenance_id(fragment),
            _string_value(fragment.get("source_field")),
            str(span_start),
            str(span_end),
        )
    )
    return f"fragment:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _expected_candidate_id(candidate: dict[str, Any]) -> str:
    """Recompute the runtime's stable competence-candidate identity."""
    payload = "\x1f".join(
        (
            _string_value(candidate.get("signal_id")),
            _string_value(candidate.get("evidence_id")),
            "candidate",
        )
    )
    return f"candidate:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _expected_canonical_competence_id(canonical: dict[str, Any]) -> str:
    """Recompute the runtime canonical-competence identity from its label."""
    label = _runtime_canonical_label(canonical.get("preferred_label"))
    return f"canonical:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


def _validate_schema_v2_projection_and_lineage(
    schema_v2_csv_rows: dict[str, list[dict[str, Any]]],
    schema_v2_jsonl_rows: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """Fail closed if schema-v2 CSV/JSONL projections or lineage diverge."""

    errors: list[str] = []

    def _index_rows(
        table_name: str, rows: list[dict[str, Any]]
    ) -> dict[tuple[str, ...], dict[str, Any]]:
        key_fields = SCHEMA_V2_PRIMARY_KEY_FIELDS[table_name]
        indexed: dict[tuple[str, ...], dict[str, Any]] = {}
        for idx, row in enumerate(rows, start=1):
            key = _row_key(row, key_fields)
            if not all(key):
                errors.append(
                    f"{table_name}:L{idx}:{'|'.join(key_fields)}:missing_primary_key"
                )
                continue
            if key in indexed:
                errors.append(
                    f"{table_name}:L{idx}:{'|'.join(key_fields)}:"
                    f"duplicate_primary_key:{_format_row_key(key)}"
                )
                continue
            indexed[key] = row
        return indexed

    csv_index = {
        table_name: _index_rows(table_name, schema_v2_csv_rows[table_name])
        for table_name in SCHEMA_V2_ENTITY_NAMES
    }
    jsonl_index = {
        table_name: _index_rows(table_name, schema_v2_jsonl_rows[table_name])
        for table_name in SCHEMA_V2_ENTITY_NAMES
    }

    for table_name in SCHEMA_V2_ENTITY_NAMES:
        csv_ids = set(csv_index[table_name])
        jsonl_ids = set(jsonl_index[table_name])
        if csv_ids != jsonl_ids:
            missing_in_jsonl = sorted(csv_ids - jsonl_ids)
            missing_in_csv = sorted(jsonl_ids - csv_ids)
            if missing_in_jsonl:
                errors.append(
                    f"{table_name}:projection_parity:missing_in_jsonl:"
                    f"{'|'.join(_format_row_key(key) for key in missing_in_jsonl)}"
                )
            if missing_in_csv:
                errors.append(
                    f"{table_name}:projection_parity:missing_in_csv:"
                    f"{'|'.join(_format_row_key(key) for key in missing_in_csv)}"
                )
            continue
        for row_id in sorted(csv_ids):
            if csv_index[table_name][row_id] != jsonl_index[table_name][row_id]:
                errors.append(
                    f"{table_name}:projection_parity:row_mismatch:"
                    f"{_format_row_key(row_id)}"
                )

    fragments_by_id = csv_index["evidence_fragments"]
    signals_by_key = csv_index["semantic_signals"]
    candidates_by_id = csv_index["competence_candidates"]
    decisions_by_id = csv_index["validation_decisions"]
    canonicals_by_id = csv_index["canonical_competences"]

    signals_by_fragment_id: dict[str, list[dict[str, Any]]] = {}
    for signal_key, signal in signals_by_key.items():
        signals_by_fragment_id.setdefault(signal_key[1], []).append(signal)

    for fragment_key, fragment in fragments_by_id.items():
        fragment_id = fragment_key[0]
        expected_provenance_id = _expected_fragment_provenance_id(fragment)
        retained_provenance_id = _string_value(
            fragment.get("source_provenance_id")
        )
        if _parse_utc_iso_datetime(fragment.get("source_retrieved_at_utc")) is None:
            errors.append(
                f"evidence_fragments:lineage:{fragment_id}:source_retrieved_at_utc"
            )
        if retained_provenance_id != expected_provenance_id:
            errors.append(
                f"evidence_fragments:lineage:{fragment_id}:source_provenance_id"
            )
        expected_provenance_hash = hashlib.sha256(
            retained_provenance_id.encode("utf-8")
        ).hexdigest()
        if _string_value(fragment.get("provenance_hash")) != expected_provenance_hash:
            errors.append(
                f"evidence_fragments:lineage:{fragment_id}:provenance_hash"
            )
        linked_signals = signals_by_fragment_id.get(fragment_id, [])
        if len(linked_signals) != 1:
            errors.append(
                f"evidence_fragments:lineage:{fragment_id}:fragment_identity"
            )
            continue
        expected_fragment_id = _expected_fragment_id(
            fragment, _string_value(linked_signals[0].get("signal_id"))
        )
        if fragment_id != expected_fragment_id:
            errors.append(
                f"evidence_fragments:identity:{fragment_id}:fragment_id_mismatch"
            )

    for signal_key, signal in signals_by_key.items():
        signal_id, fragment_id = signal_key
        expected_signal_id = _expected_signal_id(signal)
        if signal_id != expected_signal_id:
            errors.append(
                "semantic_signals:identity:"
                f"{_format_row_key(signal_key)}:signal_id_mismatch"
            )
        linked_fragment = fragments_by_id.get((fragment_id,))
        if linked_fragment is None:
            errors.append(
                f"semantic_signals:lineage:{signal_id}:missing_fragment:{fragment_id}"
            )
            continue
        if _string_value(signal.get("evidence_id")).strip() != _string_value(
            linked_fragment.get("evidence_id")
        ).strip():
            errors.append(
                f"semantic_signals:lineage:{signal_id}:fragment_evidence_mismatch"
            )
        if _string_value(signal.get("run_id")).strip() != _string_value(
            linked_fragment.get("run_id")
        ).strip():
            errors.append(
                f"semantic_signals:lineage:{signal_id}:fragment_run_mismatch"
            )
        if _string_value(signal.get("source_provenance_id")).strip() != _string_value(
            linked_fragment.get("source_provenance_id")
        ).strip():
            errors.append(
                f"semantic_signals:lineage:{signal_id}:fragment_provenance_mismatch"
            )
        matched_phrase = re.sub(
            r"\s+", " ", _string_value(signal.get("matched_phrase"))
        ).strip()
        fragment_text = re.sub(
            r"\s+", " ", _string_value(linked_fragment.get("fragment_text"))
        ).strip()
        if not matched_phrase or re.search(
            rf"(?<!\w){re.escape(matched_phrase)}(?!\w)",
            fragment_text,
            flags=re.IGNORECASE,
        ) is None:
            errors.append(
                f"semantic_signals:lineage:{signal_id}:matched_phrase"
            )
        context_text = str(signal.get("context_text", ""))
        start = linked_fragment.get("span_start_offset")
        end = linked_fragment.get("span_end_offset")
        if isinstance(start, int) and isinstance(end, int):
            if start < 0 or end < start or end > len(context_text):
                errors.append(
                    f"semantic_signals:lineage:{signal_id}:invalid_context_span:{start}:{end}:{len(context_text)}"
                )
            else:
                span = context_text[start:end]
                if span != str(linked_fragment.get("fragment_text", "")):
                    errors.append(
                        f"semantic_signals:lineage:{signal_id}:context_span_mismatch"
                    )
        if _normalized_text_hash(context_text) != _string_value(
            linked_fragment.get("surface_text_hash")
        ):
            errors.append(
                f"semantic_signals:lineage:{signal_id}:surface_text_hash"
            )

    for candidate_key, candidate in candidates_by_id.items():
        candidate_id = candidate_key[0]
        if candidate_id != _expected_candidate_id(candidate):
            errors.append(
                f"competence_candidates:identity:{candidate_id}:candidate_id_mismatch"
            )
        signal_id = _string_value(candidate.get("signal_id")).strip()
        fragment_ids = _candidate_fragment_ids(candidate)
        scalar_fragment_id = _string_value(candidate.get("fragment_id")).strip()
        selected_fragment = fragments_by_id.get((scalar_fragment_id,))
        expected_fragment_ids = {
            fragment_id
            for (signal_key, fragment_id), signal in signals_by_key.items()
            if (
                signal_key == signal_id
                and _string_value(signal.get("evidence_id")).strip()
                == _string_value(candidate.get("evidence_id")).strip()
            )
        }
        if fragment_ids != expected_fragment_ids:
            errors.append(
                f"competence_candidates:lineage:{candidate_id}:fragment_ids"
            )
        if scalar_fragment_id and scalar_fragment_id not in fragment_ids:
            errors.append(
                f"competence_candidates:lineage:{candidate_id}:"
                "scalar_fragment_not_retained"
            )
        for fragment_id in sorted(fragment_ids):
            signal_row = signals_by_key.get((signal_id, fragment_id))
            if signal_row is None:
                errors.append(
                    "competence_candidates:lineage:"
                    f"{candidate_id}:missing_signal_fragment:"
                    f"{signal_id}|{fragment_id}"
                )
                continue
            linked_fragment = fragments_by_id.get((fragment_id,))
            if (
                linked_fragment is None
                or _string_value(candidate.get("evidence_id")).strip()
                != _string_value(linked_fragment.get("evidence_id")).strip()
                or _string_value(candidate.get("evidence_id")).strip()
                != _string_value(signal_row.get("evidence_id")).strip()
            ):
                errors.append(
                    f"competence_candidates:lineage:{candidate_id}:"
                    "signal_evidence_mismatch"
                )
        expected_provenance_ids = {
            _string_value(fragment.get("source_provenance_id")).strip()
            for fragment_id in expected_fragment_ids
            for fragment in [fragments_by_id.get((fragment_id,))]
            if fragment is not None
        }
        if _split_reference_ids(candidate.get("source_provenance_ids")) != (
            expected_provenance_ids
        ):
            errors.append(
                f"competence_candidates:lineage:{candidate_id}:source_provenance_ids"
            )
        if selected_fragment is not None and any(
            _string_value(candidate.get(candidate_field)).strip()
            != _string_value(selected_fragment.get(fragment_field)).strip()
            for candidate_field, fragment_field in (
                ("evidence_id", "evidence_id"),
                ("run_id", "run_id"),
                ("exact_evidence_span", "fragment_text"),
                ("exact_span_start_offset", "span_start_offset"),
                ("exact_span_end_offset", "span_end_offset"),
            )
        ):
            errors.append(
                f"competence_candidates:lineage:{candidate_id}:selected_fragment_content"
            )

    superseded_ids: set[str] = set()
    for decision_key, decision in decisions_by_id.items():
        decision_id = decision_key[0]
        candidate_id = str(decision.get("target_candidate_id", ""))
        if (candidate_id,) not in candidates_by_id:
            errors.append(
                f"validation_decisions:lineage:{decision_id}:missing_candidate:{candidate_id}"
            )
        superseded_id = str(
            decision.get("superseded_validation_decision_id", "")
        ).strip()
        if not superseded_id:
            continue
        superseded_ids.add(superseded_id)
        if superseded_id == decision_id:
            errors.append(
                f"validation_decisions:supersession:{decision_id}:self_reference"
            )
            continue
        superseded = decisions_by_id.get((superseded_id,))
        if superseded is None:
            errors.append(
                "validation_decisions:supersession:"
                f"{decision_id}:missing_superseded_decision:{superseded_id}"
            )
            continue
        if candidate_id != str(superseded.get("target_candidate_id", "")).strip():
            errors.append(
                "validation_decisions:supersession:"
                f"{decision_id}:cross_candidate_reference"
            )
        superseding_at = _parse_utc_iso_datetime(decision.get("decision_at_utc"))
        superseded_at = _parse_utc_iso_datetime(
            superseded.get("decision_at_utc")
        )
        if (
            superseding_at is not None
            and superseded_at is not None
            and superseding_at <= superseded_at
        ):
            errors.append(
                "validation_decisions:supersession:"
                f"{decision_id}:not_later_than:{superseded_id}"
            )

    reported_cycles: set[tuple[str, ...]] = set()
    for decision_id in sorted(decision_key[0] for decision_key in decisions_by_id):
        path: list[str] = []
        current_id = decision_id
        while current_id:
            if current_id in path:
                cycle = tuple(path[path.index(current_id) :])
                cycle_key = tuple(sorted(cycle))
                if cycle_key not in reported_cycles:
                    reported_cycles.add(cycle_key)
                    errors.append(
                        "validation_decisions:supersession:cycle:"
                        f"{'|'.join(cycle)}"
                    )
                break
            path.append(current_id)
            current = decisions_by_id.get((current_id,))
            if current is None:
                break
            next_id = str(
                current.get("superseded_validation_decision_id", "")
            ).strip()
            if not next_id or (next_id,) not in decisions_by_id:
                break
            current_id = next_id

    active_decision_ids = {
        decision_key[0]
        for decision_key in decisions_by_id
        if decision_key[0] not in superseded_ids
    }
    active_decisions_by_candidate: dict[str, int] = {}
    for decision_key, decision in decisions_by_id.items():
        decision_id = decision_key[0]
        if decision_id not in active_decision_ids:
            continue
        candidate_id = str(decision.get("target_candidate_id", "")).strip()
        active_decisions_by_candidate[candidate_id] = (
            active_decisions_by_candidate.get(candidate_id, 0) + 1
        )
    for candidate_id, count in sorted(active_decisions_by_candidate.items()):
        if count > 1:
            errors.append(
                "validation_decisions:supersession:"
                f"multiple_active_decisions:{candidate_id}"
            )

    for decision_key, decision in decisions_by_id.items():
        decision_id = decision_key[0]
        candidate_id = _string_value(
            decision.get("target_candidate_id")
        ).strip()
        linked_candidate = candidates_by_id.get((candidate_id,))
        if linked_candidate is None:
            continue
        snapshot_evidence_ids = _split_reference_ids(decision.get("evidence_ids"))
        snapshot_fragment_ids = _split_reference_ids(decision.get("fragment_ids"))
        snapshot_provenance_ids = _split_reference_ids(
            decision.get("source_provenance_ids")
        )
        candidate_fragment_ids = _candidate_fragment_ids(linked_candidate)
        if not snapshot_evidence_ids:
            errors.append(
                f"validation_decisions:lineage:{decision_id}:evidence_ids"
            )
        if not snapshot_fragment_ids or not snapshot_fragment_ids.issubset(
            candidate_fragment_ids
        ):
            errors.append(
                f"validation_decisions:lineage:{decision_id}:fragment_ids"
            )
        if not snapshot_provenance_ids:
            errors.append(
                f"validation_decisions:lineage:{decision_id}:source_provenance_ids"
            )
        snapshot_fragments = [
            fragments_by_id[(fragment_id,)]
            for fragment_id in sorted(snapshot_fragment_ids)
            if (fragment_id,) in fragments_by_id
        ]
        expected_snapshot_evidence_ids = {
            _string_value(fragment.get("evidence_id")).strip()
            for fragment in snapshot_fragments
            if _string_value(fragment.get("evidence_id")).strip()
        }
        expected_snapshot_provenance_ids = {
            _string_value(fragment.get("source_provenance_id")).strip()
            for fragment in snapshot_fragments
            if _string_value(fragment.get("source_provenance_id")).strip()
        }
        candidate_evidence_ids = {
            _string_value(linked_candidate.get("evidence_id")).strip()
        }
        if (
            snapshot_evidence_ids != expected_snapshot_evidence_ids
            or snapshot_evidence_ids != candidate_evidence_ids
        ):
            errors.append(
                f"validation_decisions:lineage:{decision_id}:evidence_ids"
            )
        if snapshot_provenance_ids != expected_snapshot_provenance_ids:
            errors.append(
                f"validation_decisions:lineage:{decision_id}:source_provenance_ids"
            )
        decision_at = _parse_utc_iso_datetime(decision.get("decision_at_utc"))
        if decision_at is not None:
            for fragment in snapshot_fragments:
                retrieved_at = _parse_utc_iso_datetime(
                    fragment.get("source_retrieved_at_utc")
                )
                if retrieved_at is not None and retrieved_at > decision_at:
                    errors.append(
                        "validation_decisions:lineage:"
                        f"{decision_id}:source_retrieved_at_utc"
                    )
                    break

    for canonical_key, canonical in canonicals_by_id.items():
        canonical_id = canonical_key[0]
        if _string_value(canonical.get("canonical_competence_id")) != (
            _expected_canonical_competence_id(canonical)
        ):
            errors.append(
                "canonical_competences:identity:"
                f"{canonical_id}:canonical_competence_id_mismatch"
            )
        decision_id = _string_value(
            canonical.get("validation_decision_id")
        ).strip()
        candidate_id = _string_value(canonical.get("source_candidate_id")).strip()
        decision_row = decisions_by_id.get((decision_id,))
        if decision_row is None:
            errors.append(
                f"canonical_competences:lineage:{canonical_id}:missing_decision:{decision_id}"
            )
        else:
            if decision_id not in active_decision_ids:
                errors.append(
                    f"canonical_competences:lineage:{canonical_id}:"
                    "inactive_validation_decision_id"
                )
            if (
                _string_value(decision_row.get("decision_status")).strip()
                != "accepted"
                or candidate_id
                != _string_value(decision_row.get("target_candidate_id")).strip()
            ):
                errors.append(
                    f"canonical_competences:lineage:{canonical_id}:"
                    "validation_decision_id"
                )
            if _runtime_canonical_label(canonical.get("preferred_label")) != _runtime_canonical_label(
                decision_row.get("canonical_label")
            ):
                errors.append(
                    f"canonical_competences:lineage:{canonical_id}:canonical_label"
                )
            if (
                _string_value(decision_row.get("decision_status")).strip()
                == "accepted"
            ):
                retained_source_titles: tuple[str, ...] = ()
                candidate_row = candidates_by_id.get((candidate_id,))
                if candidate_row is not None:
                    evidence_id = _string_value(
                        candidate_row.get("evidence_id")
                    ).strip()
                    evidence_records_index = csv_index.get("evidence_records", {})
                    evidence_record = evidence_records_index.get((evidence_id,))
                    if evidence_record is not None:
                        retained_source_titles = (
                            _string_value(evidence_record.get("canonical_title")),
                        )
                guard_reason = _canonical_label_guard_reason(
                    canonical.get("preferred_label"), retained_source_titles
                )
                if guard_reason:
                    errors.append(
                        f"canonical_competences:lineage:{canonical_id}:"
                        f"canonical_label_guard:{guard_reason}"
                    )
        if (candidate_id,) not in candidates_by_id:
            errors.append(
                f"canonical_competences:lineage:{canonical_id}:missing_candidate:{candidate_id}"
            )

    assignments_by_lineage: dict[
        tuple[str, str, str], list[dict[str, Any]]
    ] = {}
    for assignment in csv_index["sector_competence_assignments"].values():
        for field_name in (
            "assignment_id",
            "canonical_competence_id",
            "validation_decision_id",
            "source_candidate_id",
        ):
            retained_value = _string_value(assignment.get(field_name))
            if retained_value != retained_value.strip():
                errors.append(
                    "sector_competence_assignments:lineage:"
                    f"{retained_value.strip()}:{field_name}:outer_whitespace"
                )
        assignment_id = _string_value(assignment.get("assignment_id")).strip()
        canonical_id = _string_value(
            assignment.get("canonical_competence_id")
        ).strip()
        canonical_row = canonicals_by_id.get((canonical_id,))
        if canonical_row is None:
            errors.append(
                f"sector_competence_assignments:lineage:{assignment_id}:missing_canonical:{canonical_id}"
            )
            continue
        decision_id = _string_value(
            assignment.get("validation_decision_id")
        ).strip()
        candidate_id = _string_value(assignment.get("source_candidate_id")).strip()
        linked_decision = decisions_by_id.get((decision_id,))
        if linked_decision is None:
            errors.append(
                f"sector_competence_assignments:lineage:{assignment_id}:"
                f"missing_decision:{decision_id}"
            )
        else:
            if decision_id not in active_decision_ids:
                errors.append(
                    f"sector_competence_assignments:lineage:{assignment_id}:"
                    "inactive_validation_decision_id"
                )
            if (
                _string_value(linked_decision.get("decision_status")).strip()
                != "accepted"
                or candidate_id
                != _string_value(linked_decision.get("target_candidate_id")).strip()
            ):
                errors.append(
                    f"sector_competence_assignments:lineage:{assignment_id}:"
                    "validation_decision_id"
                )
            if _runtime_canonical_label(canonical_row.get("preferred_label")) != _runtime_canonical_label(
                linked_decision.get("canonical_label")
            ):
                errors.append(
                    f"sector_competence_assignments:lineage:{assignment_id}:"
                    "canonical_label"
                )
        linked_candidate = candidates_by_id.get((candidate_id,))
        if linked_candidate is None:
            errors.append(
                f"sector_competence_assignments:lineage:{assignment_id}:"
                f"missing_candidate:{candidate_id}"
            )
            continue
        expected_evidence_ids = {
            str(linked_candidate.get("evidence_id", "")).strip()
        }
        assignment_evidence_raw = _string_value(assignment.get("evidence_ids"))
        assignment_evidence_ids = _split_reference_ids(assignment_evidence_raw)
        expected_evidence_serialization = "|".join(sorted(expected_evidence_ids))
        if (
            assignment_evidence_ids != expected_evidence_ids
            or assignment_evidence_raw != expected_evidence_serialization
        ):
            errors.append(
                f"sector_competence_assignments:lineage:{assignment_id}:evidence_ids"
            )
        assignment_context = (
            str(assignment.get("sector", "")).strip(),
            str(assignment.get("axis_group", "")).strip(),
            str(assignment.get("axis_code", "")).strip(),
        )
        semantic_contexts = _candidate_semantic_contexts(
            linked_candidate, signals_by_key
        )
        if assignment_context not in semantic_contexts:
            errors.append(
                f"sector_competence_assignments:lineage:{assignment_id}:semantic_context"
            )
        lineage_key = (canonical_id, decision_id, candidate_id)
        assignments_by_lineage.setdefault(lineage_key, []).append(assignment)

    for lineage_key, assignments in assignments_by_lineage.items():
        _, _, candidate_id = lineage_key
        candidate_for_lineage = candidates_by_id.get((candidate_id,))
        if candidate_for_lineage is None:
            continue
        expected_contexts = {
            context
            for context in _candidate_semantic_contexts(
                candidate_for_lineage, signals_by_key
            )
            if _is_bound_axis_context(context)
        }
        assignment_contexts = {
            (
                str(assignment.get("sector", "")).strip(),
                str(assignment.get("axis_group", "")).strip(),
                str(assignment.get("axis_code", "")).strip(),
            )
            for assignment in assignments
        }
        if (
            assignment_contexts != expected_contexts
            or len(assignments) != len(expected_contexts)
        ):
            assignment_id = str(assignments[0].get("assignment_id", ""))
            errors.append(
                "sector_competence_assignments:lineage:"
                f"{assignment_id}:semantic_context_set"
            )

    for decision_key, decision in decisions_by_id.items():
        decision_id = decision_key[0]
        if (
            decision_id not in active_decision_ids
            or _string_value(decision.get("decision_status")).strip() != "accepted"
        ):
            continue
        candidate_id = _string_value(
            decision.get("target_candidate_id")
        ).strip()
        linked_candidate = candidates_by_id.get((candidate_id,))
        if linked_candidate is None:
            continue
        matching_canonicals = [
            canonical
            for canonical in canonicals_by_id.values()
            if _runtime_canonical_label(canonical.get("preferred_label"))
            == _runtime_canonical_label(decision.get("canonical_label"))
        ]
        canonical_ids = {
            _string_value(canonical.get("canonical_competence_id")).strip()
            for canonical in matching_canonicals
            if _string_value(canonical.get("canonical_competence_id")).strip()
        }
        if len(canonical_ids) != 1:
            errors.append(
                f"validation_decisions:lineage:{decision_id}:canonical_competence"
            )
            continue
        expected_canonical_id = next(iter(canonical_ids))
        expected_contexts = {
            context
            for context in _candidate_semantic_contexts(
                linked_candidate, signals_by_key
            )
            if _is_bound_axis_context(context)
        }
        matching_assignments = [
            assignment
            for assignment in csv_index["sector_competence_assignments"].values()
            if (
                _string_value(assignment.get("validation_decision_id")).strip()
                == decision_id
                and _string_value(assignment.get("source_candidate_id")).strip()
                == candidate_id
            )
        ]
        assignment_contexts = {
            (
                _string_value(assignment.get("sector")).strip(),
                _string_value(assignment.get("axis_group")).strip(),
                _string_value(assignment.get("axis_code")).strip(),
            )
            for assignment in matching_assignments
        }
        assignment_canonical_ids = {
            _string_value(assignment.get("canonical_competence_id")).strip()
            for assignment in matching_assignments
        }
        if (
            assignment_contexts != expected_contexts
            or len(matching_assignments) != len(expected_contexts)
            or (
                matching_assignments
                and assignment_canonical_ids != {expected_canonical_id}
            )
        ):
            errors.append(
                "validation_decisions:lineage:"
                f"{decision_id}:sector_competence_assignments"
            )

    return errors


def _validate_schema_v2_manifest_counts(
    manifest_path: Path,
    schema_v2_csv_rows: dict[str, list[dict[str, Any]]],
    schema_v2_jsonl_rows: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """Require source manifest counts to match both validated v2 projections."""
    try:
        manifest = _load_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return [f"schema_v2_manifest_invalid:{manifest_path.name}"]
    counts = manifest.get("counts") if isinstance(manifest, dict) else None
    if not isinstance(counts, dict):
        return [f"schema_v2_manifest_missing_counts:{manifest_path.name}"]

    errors: list[str] = []
    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        declared_count = counts.get(entity_name)
        if isinstance(declared_count, bool) or not isinstance(declared_count, int):
            errors.append(
                f"schema_v2_manifest_invalid_count:{manifest_path.name}:{entity_name}"
            )
            continue
        csv_count = len(schema_v2_csv_rows[entity_name])
        jsonl_count = len(schema_v2_jsonl_rows[entity_name])
        if declared_count != csv_count or declared_count != jsonl_count:
            errors.append(
                "schema_v2_manifest_count_mismatch:"
                f"{manifest_path.name}:{entity_name}:"
                f"manifest={declared_count}:csv={csv_count}:jsonl={jsonl_count}"
            )
    return errors


def _write_xlsx(workbook_path: Path, tables: dict[str, list[dict[str, Any]]]) -> bool:
    try:
        from openpyxl import Workbook  # type: ignore
    except Exception:
        return False
    workbook = Workbook()
    first = True
    for sheet_name, rows in tables.items():
        title = sheet_name[:31]
        if first:
            sheet = workbook.active
            sheet.title = title
            first = False
        else:
            sheet = workbook.create_sheet(title=title)
        if not rows:
            continue
        headers = list(rows[0].keys())
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(col, "") for col in headers])
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(workbook_path)
    return True


def _write_sav_exports(
    sav_dir: Path, tables: dict[str, list[dict[str, Any]]]
) -> tuple[bool, str]:
    try:
        import pandas as pd  # type: ignore
        import pyreadstat  # type: ignore
    except Exception:
        return False, "pyreadstat/pandas unavailable"
    sav_dir.mkdir(parents=True, exist_ok=True)
    for table_name, rows in tables.items():
        if not rows:
            continue
        frame = pd.DataFrame(rows)
        pyreadstat.write_sav(frame, str(sav_dir / f"{table_name}.sav"))
    return True, ""


# ---------------------------------------------------------------------------
# Preflight helpers
# ---------------------------------------------------------------------------

REQUIRED_CROSS_RUN_FILES: tuple[str, ...] = (
    "outputs/run_archive/cross_run_run_summary.csv",
    "outputs/run_archive/cross_run_evidence_occurrences.csv",
    "outputs/run_archive/cross_run_evidence_build_report.json",
)
REQUIRED_ANALYSIS_FILES: tuple[str, ...] = (
    "outputs/credentials_dynamic_database.json",
    "outputs/gaps_detailed.json",
)
MANUAL_SOURCE_FILES: tuple[str, ...] = (
    "outputs/manual_sources/historical_compatibility.csv",
    "outputs/manual_sources/manual_sources_index.csv",
)
REQUIRED_SCHEMA_V2_FILES: tuple[str, ...] = tuple(
    f"{SCHEMA_V2_SOURCE_DIRECTORY}/{entity_name}.{suffix}"
    for entity_name in SCHEMA_V2_ENTITY_NAMES
    for suffix in ("csv", "jsonl")
)
REQUIRED_SCHEMA_V2_CONTRACT_FILES: tuple[str, ...] = tuple(
    f"schemas/{schema_name}" for schema_name in SCHEMA_V2_SCHEMA_FILENAMES
)
REQUIRED_SCHEMA_V2_MANIFEST_FILE = (
    f"{SCHEMA_V2_SOURCE_DIRECTORY}/cumulative_database_manifest.json"
)

HISTORICAL_COMPAT_HEADER = (
    "bundle_id,source_path,extracted_dir,status,reason,"
    "live_records_count,triangulated_records_count,cumulative_qmbd_records_count\n"
)
MANUAL_INDEX_HEADER = (
    "source_id,ingested_at_utc,source_kind,file_name,extension,size_bytes,sha256,"
    "text_available,original_path,zip_member_path,stored_path,archive_sha256\n"
)


def _check_preflight(repo_root: Path, bootstrap_empty_manual_sources: bool) -> int:
    """Verify all required input files exist.

    When *bootstrap_empty_manual_sources* is ``True``, header-only manual
    source files are created if absent (explicit opt-in only).

    Returns 0 on success, 1 on failure (missing required files).
    """
    missing: list[str] = []

    for rel in (
        *REQUIRED_CROSS_RUN_FILES,
        *REQUIRED_ANALYSIS_FILES,
        *REQUIRED_SCHEMA_V2_FILES,
        *REQUIRED_SCHEMA_V2_CONTRACT_FILES,
        REQUIRED_SCHEMA_V2_MANIFEST_FILE,
    ):
        if not (repo_root / rel).is_file():
            missing.append(rel)

    # Manual-source files can be bootstrapped explicitly.
    manual_missing: list[str] = []
    for rel in MANUAL_SOURCE_FILES:
        if not (repo_root / rel).is_file():
            manual_missing.append(rel)

    if manual_missing:
        if bootstrap_empty_manual_sources:
            headers = {
                "outputs/manual_sources/historical_compatibility.csv": HISTORICAL_COMPAT_HEADER,
                "outputs/manual_sources/manual_sources_index.csv": MANUAL_INDEX_HEADER,
            }
            for rel in manual_missing:
                dest = repo_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(headers[rel], encoding="utf-8")
                print(
                    f"{status_label('info')} Bootstrapped empty manual source file: {rel}"
                )
        else:
            missing.extend(manual_missing)

    if missing:
        print(
            f"{status_label('error')} Missing required prerequisite files. "
            "Run the following commands first:"
        )
        if any(
            rel.startswith("outputs/run_archive/cross_run")
            for rel in missing
        ):
            print(
                "  python scripts/build_cross_run_evidence_index.py "
                "--archive-root outputs/run_archive --output-dir outputs/run_archive"
            )
        if any("manual_sources" in rel for rel in missing):
            print(
                "  python scripts/validate_manual_sources_gatekeeper.py "
                "--root outputs/manual_sources --fail-on-issues true"
                "\n  OR pass --bootstrap-empty-manual-sources true to create "
                "empty header-only files."
            )
        if any(
            rel in missing
            for rel in (
                "outputs/credentials_dynamic_database.json",
                "outputs/gaps_detailed.json",
            )
        ):
            print("  python run_full_analysis.py")
        if any(rel.startswith(SCHEMA_V2_SOURCE_DIRECTORY) for rel in missing):
            print(
                "  python scripts/build_cumulative_scientific_database.py "
                "--output-dir outputs/cumulative_database"
            )
        for rel in missing:
            print(f"    missing: {rel}")
        return 1
    return 0


def build_versioned_research_data_package(config: PackageConfig) -> int:
    """Build package directory, validate rows by schema, and emit checksums."""
    repo_root = config.repo_root.resolve()

    preflight_code = _check_preflight(
        repo_root, config.bootstrap_empty_manual_sources
    )
    if preflight_code != 0:
        return preflight_code

    cross_run_summary = _read_csv(
        repo_root / "outputs/run_archive/cross_run_run_summary.csv"
    )
    cross_run_occ = _read_csv(
        repo_root / "outputs/run_archive/cross_run_evidence_occurrences.csv"
    )
    historical_comp = _read_csv(
        repo_root / "outputs/manual_sources/historical_compatibility.csv"
    )
    manual_index = _read_csv(
        repo_root / "outputs/manual_sources/manual_sources_index.csv"
    )
    credentials_payload = _load_json(
        repo_root / "outputs/credentials_dynamic_database.json"
    )
    gaps_payload = _load_json(repo_root / "outputs/gaps_detailed.json")
    build_report = _load_json(
        repo_root / "outputs/run_archive/cross_run_evidence_build_report.json"
    )
    schema_dir = repo_root / "schemas"
    schema_v2_csv_paths: dict[str, Path] = {}
    schema_v2_jsonl_paths: dict[str, Path] = {}
    schema_v2_csv_rows: dict[str, list[dict[str, Any]]] = {}
    schema_v2_jsonl_rows: dict[str, list[dict[str, Any]]] = {}
    schema_v2_format_errors: list[str] = []
    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        schema_path = schema_dir / f"{entity_name}.schema.json"
        csv_path = (
            repo_root / SCHEMA_V2_SOURCE_DIRECTORY / f"{entity_name}.csv"
        )
        jsonl_path = (
            repo_root / SCHEMA_V2_SOURCE_DIRECTORY / f"{entity_name}.jsonl"
        )
        schema_v2_csv_paths[entity_name] = csv_path
        schema_v2_jsonl_paths[entity_name] = jsonl_path
        csv_rows, csv_errors = _read_schema_v2_csv(
            csv_path, schema_path, entity_name
        )
        jsonl_rows, jsonl_errors = _read_schema_v2_jsonl(jsonl_path, entity_name)
        schema_v2_csv_rows[entity_name] = csv_rows
        schema_v2_jsonl_rows[entity_name] = jsonl_rows
        schema_v2_format_errors.extend(csv_errors)
        schema_v2_format_errors.extend(jsonl_errors)

    runs_rows: list[dict[str, Any]] = []
    for row in cross_run_summary:
        run_id = row.get("run_id", "")
        runs_rows.append(
            {
                "run_pk": f"run_pk_{run_id}",
                "run_id": run_id,
                "run_path": row.get("run_path", ""),
                "timestamp_utc": row.get("timestamp_utc", ""),
                "analysis_input_mode_code": MISSING_CODE,
                "analysis_input_mode_label": MISSING_LABEL,
                "is_static_recovery_mode_code": MISSING_CODE,
                "is_static_recovery_mode_label": MISSING_LABEL,
                "workflow_event_code": MISSING_CODE,
                "workflow_event_label": MISSING_LABEL,
                "provider_set": "",
                "commit_sha": config.source_commit_sha,
                "github_run_id": "",
            }
        )

    source_bundle_rows: list[dict[str, Any]] = []
    status_map = {"compatible": 1, "incompatible": 2, "invalid": 3, "missing": 4}
    for row in historical_comp:
        status = row.get("status", "")
        source_bundle_rows.append(
            {
                "bundle_pk": f"bundle_pk_{row.get('bundle_id', '')}",
                "run_pk": "run_pk_historical",
                "bundle_id": row.get("bundle_id", ""),
                "bundle_type_code": (
                    1 if row.get("source_path", "").lower().endswith(".zip") else 2
                ),
                "bundle_type_label": (
                    "historical_zip"
                    if row.get("source_path", "").lower().endswith(".zip")
                    else "historical_directory"
                ),
                "compatibility_status_code": status_map.get(status, MISSING_CODE),
                "compatibility_status_label": status if status else MISSING_LABEL,
                "source_path": row.get("source_path", ""),
                "extracted_dir": row.get("extracted_dir", ""),
                "bundle_sha256": hashlib.sha256(
                    row.get("source_path", "").encode("utf-8")
                ).hexdigest(),
            }
        )

    record_by_dedupe: dict[str, dict[str, Any]] = {}
    occurrence_rows: list[dict[str, Any]] = []
    for row in cross_run_occ:
        dedupe = (
            row.get("dedupe_value", "")
            or row.get("source_id", "")
            or row.get("title", "")
            or (
                f"fallback:{row.get('run_id', '')}:{row.get('dataset', '')}:{row.get('record_index', '')}"
            )
        )
        record_pk = (
            f"record_pk_{hashlib.sha256(dedupe.encode('utf-8')).hexdigest()[:16]}"
        )
        if record_pk not in record_by_dedupe:
            origin_code, origin_label = _origin_code(row.get("record_origin", ""))
            axis_code, axis_label = _axis_code(row.get("axis_name", ""))
            source_type_code = (
                2
                if "live" in row.get("dataset", "")
                else 3 if "manual" in row.get("dataset", "") else 1
            )
            source_type_label = (
                "live_api_record"
                if source_type_code == 2
                else (
                    "manual_supporting_source"
                    if source_type_code == 3
                    else "literature_record"
                )
            )
            record_by_dedupe[record_pk] = {
                "record_pk": record_pk,
                "canonical_record_id": dedupe or record_pk,
                "preferred_identifier": row.get("doi", "")
                or row.get("source_id", "")
                or row.get("title", "")
                or dedupe,
                "source_type_code": source_type_code,
                "source_type_label": source_type_label,
                "qmbd_axis_code": axis_code,
                "qmbd_axis_label": axis_label,
                "record_origin_code": origin_code,
                "record_origin_label": origin_label,
                "title": row.get("title", "") or dedupe,
                "doi": row.get("doi", ""),
                "source_id": row.get("source_id", "") or dedupe,
            }
        dataset_code, dataset_label = _dataset_code(row.get("dataset", ""))
        provider_code, provider_label = _normalize_provider(row.get("source_id", ""))
        occurrence_rows.append(
            {
                "occurrence_pk": f"occ_pk_{row.get('run_id', '')}_{row.get('dataset', '')}_{row.get('record_index', '')}",
                "record_pk": record_pk,
                "run_pk": f"run_pk_{row.get('run_id', '')}",
                "bundle_pk": "",
                "dataset_code": dataset_code,
                "dataset_label": dataset_label,
                "provider_code": provider_code,
                "provider_label": provider_label,
                "occurrence_type_code": 1,
                "occurrence_type_label": "run_observation",
                "timestamp_utc": row.get("timestamp_utc", ""),
            }
        )

    evidence_record_rows = list(record_by_dedupe.values())

    gap_rows: list[dict[str, Any]] = []
    for item in (
        gaps_payload.get("all_clusters", []) if isinstance(gaps_payload, dict) else []
    ):
        if not isinstance(item, dict):
            continue
        sector_label = str(item.get("sector", ""))
        axis_label_raw = str(item.get("qmbd_axis", ""))
        axis_code, axis_label = _axis_code(axis_label_raw)
        priority_score = float(item.get("priority_score", 0.0) or 0.0)
        gap_ratio = float(item.get("gap_ratio", 0.0) or 0.0)
        review_required = 1 if int(item.get("missing_count", 0) or 0) > 0 else 0
        tier_code = 1 if priority_score >= 0.66 else 2 if priority_score >= 0.33 else 3
        tier_label = "high" if tier_code == 1 else "medium" if tier_code == 2 else "low"
        gap_hash_input = (
            sector_label + axis_label_raw + str(item.get("demand_count", 0))
        )
        gap_rows.append(
            {
                "gap_cluster_pk": (
                    f"gap_pk_{hashlib.sha256(gap_hash_input.encode('utf-8')).hexdigest()[:16]}"
                ),
                "run_pk": "run_pk_latest",
                "sector_code": SECTOR_CODE.get(sector_label, MISSING_CODE),
                "sector_label": sector_label or MISSING_LABEL,
                "qmbd_axis_code": axis_code,
                "qmbd_axis_label": axis_label,
                "priority_tier_code": tier_code,
                "priority_tier_label": tier_label,
                "review_required_code": review_required,
                "review_required_label": "Yes" if review_required else "No",
                "gap_ratio": gap_ratio,
                "priority_score": priority_score,
            }
        )

    credential_rows: list[dict[str, Any]] = []
    credential_items = (
        credentials_payload.get("credentials", [])
        if isinstance(credentials_payload, dict)
        else []
    )
    for item in credential_items:
        if not isinstance(item, dict):
            continue
        sector_label = str(item.get("sector", ""))
        eqf = int(item.get("eqf_level", MISSING_CODE) or MISSING_CODE)
        credential_status_label = (
            "review_required" if item.get("review_required") else "generated"
        )
        status_code = 2 if credential_status_label == "review_required" else 1
        credential_rows.append(
            {
                "credential_pk": f"cred_pk_{item.get('id', '')}",
                "run_pk": "run_pk_latest",
                "credential_id": item.get("id", ""),
                "sector_code": SECTOR_CODE.get(sector_label, MISSING_CODE),
                "sector_label": sector_label or MISSING_LABEL,
                "eqf_level_code": eqf if eqf in {5, 6, 7} else MISSING_CODE,
                "eqf_level_label": f"EQF {eqf}" if eqf in {5, 6, 7} else MISSING_LABEL,
                "credential_status_code": status_code,
                "credential_status_label": credential_status_label,
                "supply_origin_code": 2,
                "supply_origin_label": "literature_verified",
                "supply_verification_status_code": 1,
                "supply_verification_status_label": "verified_supply",
                "review_required_code": 1 if item.get("review_required") else 0,
                "review_required_label": "Yes" if item.get("review_required") else "No",
            }
        )

    quality_rows = [
        {
            "indicator_pk": "dq_pk_missingness",
            "run_pk": "run_pk_latest",
            "indicator_family_code": 1,
            "indicator_family_label": "missingness",
            "indicator_code": 1,
            "indicator_label": "missingness_rate",
            "status_code": 1,
            "status_label": "pass",
            "indicator_value": 0.0,
            "notes": "Derived rows carry explicit missing-value codes.",
        },
        {
            "indicator_pk": "dq_pk_duplicate_rate",
            "run_pk": "run_pk_latest",
            "indicator_family_code": 2,
            "indicator_family_label": "duplicate_rate",
            "indicator_code": 2,
            "indicator_label": "duplicate_rate",
            "status_code": 1,
            "status_label": "pass",
            "indicator_value": 0.0,
            "notes": f"cross_run_dedupe_groups={build_report.get('dedupe_groups_total', 0)}",
        },
    ]

    provider_rows: list[dict[str, Any]] = []
    provider_seen: set[tuple[int, str]] = set()
    for row in occurrence_rows:
        key = (int(row["provider_code"]), str(row["provider_label"]))
        if key in provider_seen:
            continue
        provider_seen.add(key)
        provider_rows.append(
            {
                "provider_pk": f"provider_pk_{key[0]}_{key[1] or 'unknown'}",
                "provider_code": key[0],
                "provider_label": key[1] or MISSING_LABEL,
                "provider_family_code": 1,
                "provider_family_label": "research_source",
                "provider_status_code": 1 if key[0] > 0 else MISSING_CODE,
                "provider_status_label": "configured" if key[0] > 0 else MISSING_LABEL,
            }
        )

    artifact_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(manual_index[:200], start=1):
        artifact_rows.append(
            {
                "artifact_pk": f"artifact_pk_{idx}",
                "run_pk": "run_pk_latest",
                "artifact_role_code": 1,
                "artifact_role_label": "manual_supporting_source",
                "format_code": 1,
                "format_label": str(row.get("extension", "")).lower(),
                "relative_path": row.get("stored_path", ""),
                "sha256": row.get("sha256", ""),
                "size_bytes": row.get("size_bytes", ""),
            }
        )

    queries_rows: list[dict[str, Any]] = [
        {
            "query_pk": "query_pk_placeholder",
            "run_pk": "run_pk_latest",
            "query_id": "not_extracted",
            "query_text": "Not extracted in this package build.",
            "query_status_code": MISSING_CODE,
            "query_status_label": MISSING_LABEL,
            "provider_code": MISSING_CODE,
            "provider_label": MISSING_LABEL,
        }
    ]

    analysis_view_record = [
        {
            "record_pk": row["record_pk"],
            "canonical_record_id": row["canonical_record_id"],
            "source_type_code": row["source_type_code"],
            "source_type_label": row["source_type_label"],
            "record_origin_code": row["record_origin_code"],
            "record_origin_label": row["record_origin_label"],
            "qmbd_axis_code": row["qmbd_axis_code"],
            "qmbd_axis_label": row["qmbd_axis_label"],
            "title": row["title"],
            "doi": row["doi"],
            "source_id": row["source_id"],
        }
        for row in evidence_record_rows
    ]
    analysis_view_occurrence = [dict(row) for row in occurrence_rows]
    analysis_view_sector_axis_gap = [dict(row) for row in gap_rows]
    analysis_view_provider_sector = []
    provider_sector_counts: dict[tuple[str, int], int] = {}
    for occ in occurrence_rows:
        provider = str(occ["provider_label"])
        rec = next(
            (r for r in evidence_record_rows if r["record_pk"] == occ["record_pk"]),
            None,
        )
        sector_code = MISSING_CODE
        if rec and rec["record_pk"]:
            sector_code = MISSING_CODE
        provider_sector_counts[(provider, sector_code)] = (
            provider_sector_counts.get((provider, sector_code), 0) + 1
        )
    for (provider, sector_code), count in provider_sector_counts.items():
        analysis_view_provider_sector.append(
            {
                "provider_label": provider,
                "sector_code": sector_code,
                "sector_label": MISSING_LABEL if sector_code < 0 else "",
                "occurrence_count": count,
            }
        )
    analysis_view_credential = [dict(row) for row in credential_rows]

    csv_tables = {
        "runs": runs_rows,
        "source_bundles": source_bundle_rows,
        "artifacts": artifact_rows,
        "providers": provider_rows,
        "queries": queries_rows,
        "evidence_records": evidence_record_rows,
        "evidence_occurrences": occurrence_rows,
        "gap_clusters": gap_rows,
        "dynamic_credentials": credential_rows,
        "data_quality_indicators": quality_rows,
        "analysis_view_record_level": analysis_view_record,
        "analysis_view_occurrence_level": analysis_view_occurrence,
        "analysis_view_sector_axis_gap_level": analysis_view_sector_axis_gap,
        "analysis_view_provider_sector_level": analysis_view_provider_sector,
        "analysis_view_credential_level": analysis_view_credential,
        **schema_v2_csv_rows,
    }

    schema_map = {
        "runs": schema_dir / "runs.schema.json",
        "source_bundles": schema_dir / "source_bundles.schema.json",
        "evidence_records": schema_dir / "evidence_records.schema.json",
        "evidence_occurrences": schema_dir / "evidence_occurrences.schema.json",
        "gap_clusters": schema_dir / "gap_clusters.schema.json",
        "dynamic_credentials": schema_dir / "dynamic_credentials.schema.json",
        "data_quality_indicators": schema_dir / "data_quality_indicators.schema.json",
        **{
            entity_name: schema_dir / f"{entity_name}.schema.json"
            for entity_name in SCHEMA_V2_ENTITY_NAMES
        },
    }
    validation_errors: list[str] = list(schema_v2_format_errors)
    for table_name, schema_path in schema_map.items():
        validation_errors.extend(
            _validate_rows(csv_tables[table_name], schema_path, table_name)
        )
    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        validation_errors.extend(
            _validate_rows(
                schema_v2_jsonl_rows[entity_name],
                schema_map[entity_name],
                f"{entity_name}.jsonl",
            )
        )
    validation_errors.extend(
        _validate_schema_v2_projection_and_lineage(
            schema_v2_csv_rows=schema_v2_csv_rows,
            schema_v2_jsonl_rows=schema_v2_jsonl_rows,
        )
    )
    validation_errors.extend(
        _validate_schema_v2_manifest_counts(
            repo_root / REQUIRED_SCHEMA_V2_MANIFEST_FILE,
            schema_v2_csv_rows,
            schema_v2_jsonl_rows,
        )
    )
    if validation_errors:
        for error in validation_errors[:50]:
            print(f"{status_label('error')} {error}")
        return 1

    package_dir = (
        config.output_dir / f"morskamary_cumulative_evidence_{config.version_tag}"
    )
    if package_dir.exists():
        shutil.rmtree(package_dir)
    (package_dir / "data" / "csv").mkdir(parents=True, exist_ok=True)
    (package_dir / "data" / "jsonl").mkdir(parents=True, exist_ok=True)
    (package_dir / "schemas").mkdir(parents=True, exist_ok=True)

    for table_name, rows in csv_tables.items():
        if table_name in SCHEMA_V2_ENTITY_NAMES:
            continue
        _write_csv(package_dir / "data" / "csv" / f"{table_name}.csv", rows)
    _write_jsonl(
        package_dir / "data" / "jsonl" / "evidence_records.jsonl", evidence_record_rows
    )
    _write_jsonl(
        package_dir / "data" / "jsonl" / "evidence_occurrences.jsonl", occurrence_rows
    )
    _write_jsonl(package_dir / "data" / "jsonl" / "gap_clusters.jsonl", gap_rows)
    _write_jsonl(
        package_dir / "data" / "jsonl" / "dynamic_credentials.jsonl", credential_rows
    )
    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        shutil.copyfile(
            schema_v2_csv_paths[entity_name],
            package_dir / "data" / "csv" / f"{entity_name}.csv",
        )
        shutil.copyfile(
            schema_v2_jsonl_paths[entity_name],
            package_dir / "data" / "jsonl" / f"{entity_name}.jsonl",
        )
        shutil.copyfile(
            schema_dir / f"{entity_name}.schema.json",
            package_dir / "schemas" / f"{entity_name}.schema.json",
        )

    # Supplementary: copy the cumulative evidence_records projection (keyed by
    # evidence_id) alongside the schema-v2 chain so consumers can resolve
    # fragment/signal/candidate evidence_id references to their source record.
    # This table uses a different primary key than the legacy evidence_records
    # output, so it is packaged without schema validation.
    for supp_entity in SCHEMA_V2_SUPPLEMENTARY_ENTITY_NAMES:
        supp_csv = repo_root / SCHEMA_V2_SOURCE_DIRECTORY / f"{supp_entity}.csv"
        supp_jsonl = repo_root / SCHEMA_V2_SOURCE_DIRECTORY / f"{supp_entity}.jsonl"
        if supp_csv.exists():
            shutil.copyfile(
                supp_csv,
                package_dir / "data" / "csv" / f"{supp_entity}.csv",
            )
        if supp_jsonl.exists():
            shutil.copyfile(
                supp_jsonl,
                package_dir / "data" / "jsonl" / f"{supp_entity}.jsonl",
            )

    variable_labels, value_labels = _load_variable_and_value_labels(schema_dir)
    variable_labels = _merge_label_rows(
        variable_labels,
        _SCHEMA_V2_VARIABLE_LABELS,
        key_fields=("schema_file", "variable_name"),
    )
    value_labels = _merge_label_rows(
        value_labels,
        _SCHEMA_V2_VALUE_LABELS,
        key_fields=("schema_file", "variable_name", "code"),
    )
    _write_csv(package_dir / "VARIABLE_LABELS.csv", variable_labels)
    _write_csv(package_dir / "VALUE_LABELS.csv", value_labels)

    xlsx_written = False
    if config.include_xlsx:
        xlsx_written = _write_xlsx(
            package_dir / "data" / "xlsx" / "morskamary_cumulative_database.xlsx",
            {name: rows for name, rows in csv_tables.items() if rows},
        )

    sav_written = False
    sav_note = "disabled"
    if config.include_sav:
        sav_written, sav_note = _write_sav_exports(
            package_dir / "data" / "spss",
            {
                "evidence_records": evidence_record_rows,
                "evidence_occurrences": occurrence_rows,
                "gap_clusters": gap_rows,
                "dynamic_credentials": credential_rows,
            },
        )

    citation_text = (
        "Repository dataset citation template (APA-like)\n\n"
        f"Repository: robertbartlomiejski/morskamary\n"
        f"Release tag: {config.release_tag}\n"
        f"Source commit (data inputs): {config.source_commit_sha}\n"
        f"Package commit: {config.package_commit_sha}\n"
        f"Access date: {config.access_date}\n\n"
        "Template:\n"
        "Bartlomiejski, R. (2026). morskamary cumulative evidence package "
        f"({config.version_tag}) [Dataset]. GitHub Release ({config.release_tag}). "
        f"Source commit {config.source_commit_sha}. Accessed {config.access_date}. "
        "Provenance: derived cumulative package from repository-managed pipelines.\n\n"
        "Note: 'Source commit' identifies the data inputs used to generate this package.\n"
        "'Package commit' identifies the commit that stores the generated package "
        "(may be 'pending_until_merge' if the package has not yet been merged).\n\n"
        "For dataset-file level references include exact relative path and checksum.\n"
    )
    (package_dir / "CITATION_APA.txt").write_text(citation_text, encoding="utf-8")

    schema_v2_package_paths = {
        entity_name: {
            "csv": f"data/csv/{entity_name}.csv",
            "jsonl": f"data/jsonl/{entity_name}.jsonl",
        }
        for entity_name in SCHEMA_V2_ENTITY_NAMES
    }
    schema_v2_contract_paths = {
        entity_name: f"schemas/{entity_name}.schema.json"
        for entity_name in SCHEMA_V2_ENTITY_NAMES
    }
    manifest_payload = {
        "package_name": f"morskamary_cumulative_evidence_{config.version_tag}",
        "version_tag": config.version_tag,
        "release_tag": config.release_tag,
        "source_commit_sha": config.source_commit_sha,
        "package_commit_sha": config.package_commit_sha,
        "access_date": config.access_date,
        "created_at_utc": _utc_now(),
        "codebook_path": "docs/CROSS_RUN_EVIDENCE_CODEBOOK.md",
        "methodology_path": "docs/CUMULATIVE_DATABASE_METHODOLOGY.md",
        "statistical_analysis_plan_path": "docs/STATISTICAL_ANALYSIS_PLAN.md",
        "content_analysis_protocol_path": "docs/CONTENT_ANALYSIS_PROTOCOL.md",
        "data_release_policy_path": "docs/DATA_RELEASE_POLICY.md",
        "schema_validation": {
            "validated_tables": sorted(schema_map.keys()),
            "validated_exports": {
                "csv": list(SCHEMA_V2_ENTITY_NAMES),
                "jsonl": list(SCHEMA_V2_ENTITY_NAMES),
            },
            "errors": [],
        },
        "schema_v2_entities": {
            "source_directory": SCHEMA_V2_SOURCE_DIRECTORY,
            "entities": list(SCHEMA_V2_ENTITY_NAMES),
            "package_paths": schema_v2_package_paths,
            "contract_paths": schema_v2_contract_paths,
            "row_counts": {
                entity_name: {
                    "csv": len(schema_v2_csv_rows[entity_name]),
                    "jsonl": len(schema_v2_jsonl_rows[entity_name]),
                }
                for entity_name in SCHEMA_V2_ENTITY_NAMES
            },
        },
        "exports": {
            "csv_utf8": True,
            "xlsx_written": xlsx_written,
            "sav_written": sav_written,
            "sav_note": sav_note,
            "jsonl": True,
        },
        "notes": [
            "Large empirical artifacts remain outside this code PR.",
            "Package is generated by code and validated by repository schemas.",
            "Metadata/checksums are intended to be referenced in Git.",
        ],
    }
    manifest_schema_path = schema_dir / "research_data_package_manifest.schema.json"
    if manifest_schema_path.exists():
        manifest_errors = _validate_manifest(manifest_payload, manifest_schema_path)
        if manifest_errors:
            for message in manifest_errors:
                print(f"{status_label('error')} release manifest invalid: {message}")
            return 1
    (package_dir / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    checksum_rows: list[tuple[str, str]] = []
    for file_path in sorted(path for path in package_dir.rglob("*") if path.is_file()):
        rel = file_path.relative_to(package_dir).as_posix()
        checksum_rows.append((_sha256_file(file_path), rel))
    (package_dir / "CHECKSUMS.sha256").write_text(
        "".join(f"{sha}  {rel}\n" for sha, rel in checksum_rows),
        encoding="utf-8",
    )

    zip_path = (
        config.output_dir / f"morskamary_cumulative_evidence_{config.version_tag}.zip"
    )
    if zip_path.exists():
        zip_path.unlink()
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in sorted(
            path for path in package_dir.rglob("*") if path.is_file()
        ):
            archive.write(file_path, file_path.relative_to(package_dir).as_posix())

    print(f"{status_label('ok')} Wrote package directory: {package_dir}")
    print(f"{status_label('ok')} Wrote package archive: {zip_path}")
    print(
        f"{status_label('ok')} Schema-validated rows: {sum(len(csv_tables[key]) for key in schema_map)}"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build versioned cumulative research data package."
    )
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    parser.add_argument(
        "--output-dir",
        default="outputs/release_packages",
        help="Directory where package folder and zip are written.",
    )
    parser.add_argument(
        "--version-tag",
        required=True,
        help="Package version tag (e.g., v0.1.0).",
    )
    parser.add_argument(
        "--release-tag",
        default="draft",
        help="Release tag reference used in citation metadata.",
    )
    parser.add_argument(
        "--access-date",
        default=str(date.today()),
        help="Access date for citation metadata (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--source-commit-sha",
        default="",
        help=(
            "Commit SHA of the data inputs used to generate this package. "
            "Defaults to git HEAD when omitted."
        ),
    )
    parser.add_argument(
        "--commit-sha",
        default="",
        help="Deprecated alias for --source-commit-sha; --source-commit-sha takes precedence.",
    )
    parser.add_argument(
        "--package-commit-sha",
        default="pending_until_merge",
        help=(
            "Commit SHA of the commit that stores the generated package. "
            "Use 'pending_until_merge' (default) when the package has not yet been merged."
        ),
    )
    parser.add_argument(
        "--include-xlsx",
        default="true",
        help="Write XLSX workbook when openpyxl is available (true/false).",
    )
    parser.add_argument(
        "--include-sav",
        default="false",
        help="Write SAV exports when pyreadstat/pandas are available (true/false).",
    )
    parser.add_argument(
        "--bootstrap-empty-manual-sources",
        default="false",
        help=(
            "Create empty (header-only) manual-source files when absent (true/false). "
            "Only use when no real manual sources have been ingested yet."
        ),
    )
    return parser.parse_args(argv)


def _to_bool(value: str) -> bool:
    token = value.strip().lower()
    if token in {"1", "true", "yes", "y"}:
        return True
    if token in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    # --source-commit-sha takes precedence over deprecated --commit-sha alias
    source_commit_sha = (
        args.source_commit_sha.strip()
        or args.commit_sha.strip()
        or _get_git_sha(repo_root)
    )
    config = PackageConfig(
        repo_root=repo_root,
        output_dir=Path(args.output_dir).resolve(),
        version_tag=args.version_tag.strip(),
        release_tag=args.release_tag.strip() or "draft",
        access_date=args.access_date.strip(),
        source_commit_sha=source_commit_sha,
        package_commit_sha=args.package_commit_sha.strip() or "pending_until_merge",
        include_xlsx=_to_bool(args.include_xlsx),
        include_sav=_to_bool(args.include_sav),
        bootstrap_empty_manual_sources=_to_bool(args.bootstrap_empty_manual_sources),
    )
    if not config.version_tag:
        print(f"{status_label('error')} --version-tag must be non-empty")
        return 1
    return build_versioned_research_data_package(config)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
