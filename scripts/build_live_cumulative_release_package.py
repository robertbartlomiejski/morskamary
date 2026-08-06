#!/usr/bin/env python3
"""Build the single browser-downloadable cumulative scientific package.

CLI::

    python scripts/build_live_cumulative_release_package.py \\
      --database-dir outputs/cumulative_database \\
      --reports-dir reports \\
      --version-tag latest \\
      --output outputs/release_packages/morskamary_live_cumulative_latest.zip

ZIP contents (per PR-190 Task C spec)::

    README_DATA_PACKAGE.md
    RELEASE_MANIFEST.json
    CHECKSUMS.sha256
    CITATION_APA.txt
    VARIABLE_LABELS.csv
    VALUE_LABELS.csv
    data/csv/*.csv
    data/jsonl/*.jsonl
    data/sqlite/morskamary_live_cumulative.sqlite   (may be skipped)
    reports/morskamary_statistical_report.html
    reports/morskamary_statistical_report.pdf       (may be a text stub)
    reports/morskamary_methodological_audit.html
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from io import StringIO
import json
import math
import re
import sqlite3
import sys
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from jsonschema import Draft202012Validator

# Versioned schemas are the authoritative schema-v2 field contract.
_SCHEMA_V2_DIR = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_V2_ENTITY_NAMES = (
    "evidence_fragments",
    "semantic_signals",
    "competence_candidates",
    "canonical_competences",
    "sector_competence_assignments",
    "validation_decisions",
)
SCHEMA_V2_SCHEMA_FILENAMES = tuple(
    f"{entity_name}.schema.json" for entity_name in SCHEMA_V2_ENTITY_NAMES
)

_CANONICAL_LABEL_PROVIDER_ALIASES = {
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
}


def _load_schema_v2_contract(
    entity_name: str,
) -> Tuple[Dict[str, Any], Tuple[str, ...], Set[str]]:
    """Read required fields and fields permitted to be empty from the schema."""
    schema_path = _SCHEMA_V2_DIR / f"{entity_name}.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required_fields = tuple(str(value) for value in schema["required"])
    properties = schema.get("properties", {})
    nonempty_fields = set()
    for field_name in required_fields:
        definition = properties.get(field_name, {})
        enum_values = definition.get("enum") if isinstance(definition, dict) else None
        enum_excludes_empty = (
            isinstance(enum_values, list) and "" not in enum_values
        )
        if (
            definition.get("minLength", 0) >= 1
            or definition.get("type") != "string"
            or enum_excludes_empty
        ):
            nonempty_fields.add(field_name)
    # Non-accepted decisions may deliberately have no canonical label.
    if entity_name == "validation_decisions":
        nonempty_fields.discard("canonical_label")
    return schema, required_fields, set(required_fields) - nonempty_fields


SCHEMA_V2_REQUIRED_COLUMNS: Dict[str, Tuple[str, ...]] = {}
SCHEMA_V2_EMPTY_ALLOWED_FIELDS: Dict[str, Set[str]] = {}
SCHEMA_V2_SCHEMAS: Dict[str, Dict[str, Any]] = {}
SCHEMA_V2_VALIDATORS: Dict[str, Draft202012Validator] = {}
for _entity_name in SCHEMA_V2_ENTITY_NAMES:
    (
        _schema,
        SCHEMA_V2_REQUIRED_COLUMNS[_entity_name],
        SCHEMA_V2_EMPTY_ALLOWED_FIELDS[_entity_name],
    ) = _load_schema_v2_contract(_entity_name)
    Draft202012Validator.check_schema(_schema)
    SCHEMA_V2_SCHEMAS[_entity_name] = _schema
    SCHEMA_V2_VALIDATORS[_entity_name] = Draft202012Validator(
        _schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )

ENTITY_ID_FIELDS: Dict[str, Tuple[str, ...]] = {
    "evidence_records": ("evidence_id",),
    "evidence_fragments": ("fragment_id",),
    "semantic_signals": ("signal_id", "fragment_id"),
    "competence_candidates": ("candidate_id",),
    "canonical_competences": ("canonical_competence_id",),
    "sector_competence_assignments": ("assignment_id",),
    "validation_decisions": ("validation_decision_id",),
}

SCHEMA_V2_FOREIGN_KEYS: Tuple[
    Tuple[str, Tuple[str, ...], str, Tuple[str, ...]], ...
] = (
    ("evidence_fragments", ("evidence_id",), "evidence_records", ("evidence_id",)),
    ("semantic_signals", ("fragment_id",), "evidence_fragments", ("fragment_id",)),
    ("semantic_signals", ("evidence_id",), "evidence_records", ("evidence_id",)),
    ("competence_candidates", ("signal_id", "fragment_id"), "semantic_signals", ("signal_id", "fragment_id")),
    ("competence_candidates", ("fragment_id",), "evidence_fragments", ("fragment_id",)),
    ("competence_candidates", ("evidence_id",), "evidence_records", ("evidence_id",)),
    ("validation_decisions", ("target_candidate_id",), "competence_candidates", ("candidate_id",)),
    ("validation_decisions", ("superseded_validation_decision_id",), "validation_decisions", ("validation_decision_id",)),
    ("canonical_competences", ("validation_decision_id",), "validation_decisions", ("validation_decision_id",)),
    ("canonical_competences", ("source_candidate_id",), "competence_candidates", ("candidate_id",)),
    ("sector_competence_assignments", ("canonical_competence_id",), "canonical_competences", ("canonical_competence_id",)),
    ("sector_competence_assignments", ("validation_decision_id",), "validation_decisions", ("validation_decision_id",)),
    ("sector_competence_assignments", ("source_candidate_id",), "competence_candidates", ("candidate_id",)),
)

SCHEMA_V2_LIST_FOREIGN_KEYS: Tuple[Tuple[str, str, str, str], ...] = (
    ("competence_candidates", "fragment_ids", "evidence_fragments", "fragment_id"),
    ("competence_candidates", "source_provenance_ids", "evidence_fragments", "source_provenance_id"),
    ("validation_decisions", "evidence_ids", "evidence_records", "evidence_id"),
    ("validation_decisions", "fragment_ids", "evidence_fragments", "fragment_id"),
    ("validation_decisions", "source_provenance_ids", "evidence_fragments", "source_provenance_id"),
    ("sector_competence_assignments", "evidence_ids", "evidence_records", "evidence_id"),
)

LEGACY_DERIVED_DEMAND_VIEW_KIND = "legacy_category_aggregate_compatibility_view"
LEGACY_DERIVED_DEMAND_SCIENTIFIC_STATUS = (
    "legacy_not_validated_canonical_competence"
)

# Required minimum columns per CSV file.
CSV_REQUIRED_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "evidence_records.csv": (
        "evidence_id", "canonical_doi", "canonical_title",
        "first_seen_run_id", "latest_seen_run_id",
        "providers_seen", "record_novelty_status",
    ),
    **{
        f"{entity_name}.csv": SCHEMA_V2_REQUIRED_COLUMNS[entity_name]
        for entity_name in SCHEMA_V2_ENTITY_NAMES
    },
    "competence_demand_signals.csv": (
        "signal_id", "evidence_id", "run_id", "sector",
        "axis_group", "signal_type", "competence_label",
    ),
    "hypothesis_semantic_fragments.csv": (
        "fragment_id", "hypothesis_ids", "signal_id",
        "evidence_id", "run_id", "sector", "axis_group",
        "matched_hypothesis_phrase", "indicator_family",
        "semantic_fragment", "evidence_surface",
    ),
    "derived_competence_demands.csv": (
        "competence_demand_id", "competence_label", "view_kind",
        "scientific_status", "sector", "axis_group",
        "demand_strength_score", "evidence_ids",
    ),
    "sector_axis_gap_model.csv": (
        "sector", "axis_group", "live_literature_demand_count",
        "gap_ratio",
    ),
    "credential_translation_eqf4_7.csv": (
        "credential_id", "credential_title", "sector",
        "eqf_level", "coverage_status",
    ),
    "learning_outcomes.csv": (
        "outcome_id", "credential_id", "sector",
        "eqf_level", "outcome_statement",
        "competence_demand_id", "evidence_id",
    ),
}


CSV_FILES = (
    "evidence_records.csv",
    "evidence_fragments.csv",
    "semantic_signals.csv",
    "competence_candidates.csv",
    "canonical_competences.csv",
    "sector_competence_assignments.csv",
    "validation_decisions.csv",
    "competence_demand_signals.csv",
    "hypothesis_semantic_fragments.csv",
    "derived_competence_demands.csv",
    "sector_axis_gap_model.csv",
    "credential_translation_eqf4_7.csv",
    "learning_outcomes.csv",
    "run_novelty_metrics.csv",
)

# Optional CSVs — included when present alongside the database dir.
OPTIONAL_CSV_FILES = (
    "query_execution_log.csv",
    "provider_run_quality.csv",
)

JSONL_FILES = (
    "evidence_records.jsonl",
    "evidence_fragments.jsonl",
    "semantic_signals.jsonl",
    "competence_candidates.jsonl",
    "canonical_competences.jsonl",
    "sector_competence_assignments.jsonl",
    "validation_decisions.jsonl",
    "competence_demand_signals.jsonl",
    "hypothesis_semantic_fragments.jsonl",
    "derived_competence_demands.jsonl",
)

ALLOW_EMPTY_JSONL = {
    "evidence_fragments.jsonl",
    "semantic_signals.jsonl",
    "competence_candidates.jsonl",
    "canonical_competences.jsonl",
    "sector_competence_assignments.jsonl",
    "validation_decisions.jsonl",
    "competence_demand_signals.jsonl",
    "hypothesis_semantic_fragments.jsonl",
    "derived_competence_demands.jsonl",
}

DATABASE_METADATA_FILES = (
    "run_novelty_metrics.json",
    "novelty_gate_report.json",
    "cumulative_database_manifest.json",
    "_checksums.sha256",
    "layer4_manifest.json",
    "layer5_manifest.json",
    "layer_readiness_report.json",
)

LAYER4_STAT_FILES = (
    "qmbd_cross_tables.csv",
    "sector_gap_matrices.json",
    "multivariate_induction_results.json",
    "taxonomic_clusters.csv",
)

REPORT_FILES = (
    "morskamary_statistical_report.html",
    "morskamary_statistical_report.pdf",
    "morskamary_methodological_audit.html",
)

DEMAND_STRENGTH_FORMULA = (
    "demand_strength_score = "
    "0.30*normalized_unique_doi_count "
    "+ 0.20*provider_diversity_score "
    "+ 0.20*temporal_recency_score "
    "+ 0.15*query_diversity_score "
    "+ 0.15*semantic_confidence_mean"
)


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _read_bytes_if_exists(path: Path) -> Optional[bytes]:
    if not path.exists():
        return None
    return path.read_bytes()


def _load_json_required(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _load_jsonl_rows(
    path: Path,
) -> Tuple[List[Dict[str, Any]], List[int], List[str]]:
    rows: List[Dict[str, Any]] = []
    line_numbers: List[int] = []
    errors: List[str] = []
    if not path.is_file():
        return rows, line_numbers, errors
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return rows, line_numbers, [f"unreadable_jsonl:{path.name}:{exc}"]
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            errors.append(f"malformed_jsonl:{path.name}:L{line_no}:{exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"jsonl_not_object:{path.name}:L{line_no}")
            continue
        rows.append(payload)
        line_numbers.append(line_no)
    if not rows and not errors:
        if path.name in ALLOW_EMPTY_JSONL and not text:
            return rows, line_numbers, errors
        if path.name in ALLOW_EMPTY_JSONL:
            errors.append(f"allowed_empty_jsonl_not_truly_empty:{path.name}")
        else:
            errors.append(f"empty_jsonl:{path.name}")
    return rows, line_numbers, errors


def _is_nonempty(value: Any) -> bool:
    """Return whether a schema-required value has a retained value."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _identifier(value: Any) -> str:
    """Return a normalized identifier without treating numeric zero as empty."""
    return str(value).strip() if value is not None else ""


def _split_references(value: Any) -> List[str]:
    """Split the package's pipe-delimited provenance/reference fields."""
    return [
        item.strip()
        for item in _identifier(value).split("|")
        if item.strip()
    ]


def _row_line_number(
    file_name: str,
    row_index: int,
    line_numbers_by_file: Optional[Dict[str, List[int]]] = None,
) -> int:
    """Return a physical source line number for a parsed projection row."""
    if line_numbers_by_file is not None:
        line_numbers = line_numbers_by_file.get(file_name, [])
        if 0 < row_index <= len(line_numbers):
            return line_numbers[row_index - 1]
    # CSV rows begin after the header; JSONL row numbering begins at one.
    return row_index + (1 if file_name.endswith(".csv") else 0)


def _coerce_csv_schema_value(value: Any, definition: Any) -> Any:
    """Coerce CSV scalar text to the JSON Schema scalar type when possible."""
    if not isinstance(value, str) or not isinstance(definition, dict):
        return value
    value_type = definition.get("type")
    if value_type == "integer":
        if re.fullmatch(r"[+-]?\d+", value):
            try:
                return int(value)
            except ValueError:
                return value
    elif value_type == "number":
        try:
            numeric_value = float(value)
        except ValueError:
            return value
        if math.isfinite(numeric_value):
            return numeric_value
    return value


def _coerce_csv_row_for_schema(
    row: Dict[str, Any], schema: Dict[str, Any]
) -> Dict[str, Any]:
    """Return a typed copy of one CSV row for Draft 2020-12 validation."""
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return dict(row)
    return {
        field_name: _coerce_csv_schema_value(
            value, properties.get(field_name, {})
        )
        for field_name, value in row.items()
    }


def _schema_error_path(error: Any) -> str:
    """Return a concise, deterministic JSON-pointer-like schema error path."""
    path = [str(part) for part in error.absolute_path]
    return ".".join(path) if path else "$"


def _validate_schema_v2_json_schema(
    rows_by_file: Dict[str, List[Dict[str, Any]]],
    suffix: str,
    line_numbers_by_file: Optional[Dict[str, List[int]]] = None,
) -> List[str]:
    """Validate every schema-v2 row with its full Draft 2020-12 contract."""
    errors: List[str] = []
    for entity_name, validator in SCHEMA_V2_VALIDATORS.items():
        file_name = f"{entity_name}.{suffix}"
        schema = SCHEMA_V2_SCHEMAS[entity_name]
        for row_index, row in enumerate(rows_by_file.get(file_name, []), start=1):
            payload = (
                _coerce_csv_row_for_schema(row, schema)
                if suffix == "csv"
                else row
            )
            line_number = _row_line_number(
                file_name, row_index, line_numbers_by_file
            )
            for error in sorted(
                validator.iter_errors(payload),
                key=lambda item: (list(item.absolute_path), item.validator),
            ):
                errors.append(
                    "schema_v2_schema_validation:"
                    f"{file_name}:L{line_number}:{_schema_error_path(error)}:"
                    f"{error.validator}"
                )
    return errors


def _validate_schema_v2_required_fields(
    rows_by_file: Dict[str, List[Dict[str, Any]]],
    suffix: str,
    line_numbers_by_file: Optional[Dict[str, List[int]]] = None,
) -> List[str]:
    """Validate required schema-v2 fields for one CSV or JSONL projection."""
    errors: List[str] = []
    for entity_name, required_columns in SCHEMA_V2_REQUIRED_COLUMNS.items():
        file_name = f"{entity_name}.{suffix}"
        for row_index, row in enumerate(rows_by_file.get(file_name, []), start=1):
            line_number = _row_line_number(
                file_name, row_index, line_numbers_by_file
            )
            for field_name in required_columns:
                if field_name not in row:
                    issue = "missing_required_field"
                elif (
                    field_name in SCHEMA_V2_EMPTY_ALLOWED_FIELDS[entity_name]
                    or _is_nonempty(row.get(field_name))
                ):
                    continue
                else:
                    issue = "empty_required_field"
                errors.append(
                    f"schema_v2_{issue}:{file_name}:L{line_number}:{field_name}"
                )
            if (
                entity_name == "validation_decisions"
                and _identifier(row.get("decision_status")) == "accepted"
                and not _is_nonempty(row.get("canonical_label"))
            ):
                errors.append(
                    "schema_v2_empty_required_field:"
                    f"{file_name}:L{line_number}:canonical_label"
                )
            if (
                entity_name == "validation_decisions"
                and not _is_utc_iso_datetime(row.get("decision_at_utc"))
            ):
                errors.append(
                    "schema_v2_invalid_decision_at_utc:"
                    f"{file_name}:L{line_number}:decision_at_utc"
                )
    return errors


def _row_key(row: Dict[str, Any], fields: Tuple[str, ...]) -> Tuple[str, ...]:
    """Return an ordered, normalized identity or foreign-key value."""
    return tuple(_identifier(row.get(field_name)) for field_name in fields)


def _normalized_label(value: Any) -> str:
    """Normalize a human-facing label before comparing linked projections."""
    return re.sub(r"\s+", " ", _identifier(value)).strip().casefold()


def _string_value(value: Any) -> str:
    """Return a raw scalar string without normalizing retained text."""
    return "" if value is None else str(value)


def _normalized_text_hash(value: Any) -> str:
    """Return the runtime-compatible SHA-256 for a retained text surface."""
    normalized = re.sub(r"\s+", " ", _string_value(value)).strip().lower()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _expected_fragment_provenance_id(fragment: Dict[str, Any]) -> str:
    """Recreate a fragment occurrence identifier from its published preimage."""
    payload = "\x1f".join(
        (
            _string_value(fragment.get("run_id")),
            _string_value(fragment.get("evidence_id")),
            _string_value(fragment.get("source_retrieved_at_utc")),
            _string_value(fragment.get("source_provider")),
            _string_value(fragment.get("source_provider_id")).strip().lower(),
            _string_value(fragment.get("source_query_id")),
            re.sub(
                r"\s+",
                " ",
                _string_value(fragment.get("source_query_text")),
            ).strip().lower(),
        )
    )
    return "prov:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_integer(value: Any) -> Optional[int]:
    """Parse an integer from either a typed JSON value or a CSV scalar."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _is_utc_iso_datetime(value: Any) -> bool:
    """Return whether a retained decision timestamp is ISO-8601 UTC."""
    token = _string_value(value).strip()
    if not token:
        return False
    try:
        parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError:
        return False
    utc_offset = parsed.utcoffset()
    return (
        parsed.tzinfo is not None
        and utc_offset is not None
        and utc_offset.total_seconds() == 0
    )


def _normalize_title_for_label_guard(value: Any) -> str:
    """Normalize labels/titles with the runtime canonical-label semantics."""
    ascii_value = unicodedata.normalize(
        "NFKD", _string_value(value)
    ).encode("ascii", "ignore").decode("ascii")
    return re.sub(
        r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", ascii_value.lower())
    ).strip()


def _canonical_label_guard_reason(
    label: Any, retained_source_titles: Tuple[str, ...] = ()
) -> str:
    """Return the runtime-compatible rejection reason for a canonical label."""
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


def _fragment_contains_phrase(fragment_text: Any, matched_phrase: Any) -> bool:
    """Return whether a semantic phrase remains present in its evidence span."""
    phrase = re.sub(r"\s+", " ", _identifier(matched_phrase)).strip()
    text = re.sub(r"\s+", " ", _identifier(fragment_text)).strip()
    if not phrase or not text:
        return False
    return re.search(
        rf"(?<!\w){re.escape(phrase)}(?!\w)", text, flags=re.IGNORECASE
    ) is not None


def _candidate_reference_ids(
    candidate: Dict[str, Any], plural_field: str, scalar_field: str
) -> Set[str]:
    """Return retained plural references, retaining a scalar fallback for errors."""
    references = set(_split_references(candidate.get(plural_field)))
    if references:
        return references
    scalar_reference = _identifier(candidate.get(scalar_field))
    return {scalar_reference} if scalar_reference else set()


_BOUND_AXIS_CONTEXTS = {
    ("MARINE", "M"),
    ("MARITIME", "T"),
    ("OCEANIC", "O"),
    ("HYDRONIZATION", "H"),
}


def _candidate_semantic_contexts(
    candidate: Dict[str, Any],
    signals: Dict[Tuple[str, ...], Dict[str, Any]],
) -> Set[Tuple[str, str, str]]:
    """Return all retained semantic sector/axis contexts for a candidate."""
    signal_id = _identifier(candidate.get("signal_id"))
    contexts: Set[Tuple[str, str, str]] = set()
    for fragment_id in _candidate_reference_ids(
        candidate, "fragment_ids", "fragment_id"
    ):
        signal = signals.get((signal_id, fragment_id))
        if signal is not None:
            contexts.add(
                (
                    _identifier(signal.get("sector")),
                    _identifier(signal.get("axis_group")),
                    _identifier(signal.get("axis_code")),
                )
            )
    return contexts


def _is_bound_axis_context(context: Tuple[str, str, str]) -> bool:
    """Return whether a semantic context can validly emit an assignment."""
    sector, axis_group, axis_code = context
    return bool(sector) and (axis_group, axis_code) in _BOUND_AXIS_CONTEXTS


def _validate_schema_v2_foreign_keys(
    rows_by_file: Dict[str, List[Dict[str, Any]]],
    suffix: str,
    line_numbers_by_file: Optional[Dict[str, List[int]]] = None,
) -> List[str]:
    """Validate schema-v2 keys and the retained evidence-to-decision chain."""
    errors: List[str] = []
    entity_rows = {
        entity_name: rows_by_file.get(f"{entity_name}.{suffix}", [])
        for entity_name in ENTITY_ID_FIELDS
    }
    indexes: Dict[str, Dict[Tuple[str, ...], Dict[str, Any]]] = {}
    for entity_name, fields in ENTITY_ID_FIELDS.items():
        index: Dict[Tuple[str, ...], Dict[str, Any]] = {}
        file_name = f"{entity_name}.{suffix}"
        for row_index, row in enumerate(entity_rows[entity_name], start=1):
            key = _row_key(row, fields)
            if not all(key):
                continue
            if key in index:
                line_number = _row_line_number(
                    file_name, row_index, line_numbers_by_file
                )
                errors.append(
                    "schema_v2_duplicate_primary_key:"
                    f"{file_name}:L{line_number}:{'+'.join(fields)}"
                )
                continue
            index[key] = row
        indexes[entity_name] = index

    for source, source_fields, target, target_fields in SCHEMA_V2_FOREIGN_KEYS:
        target_index = {
            _row_key(row, target_fields)
            for row in entity_rows[target]
            if all(_row_key(row, target_fields))
        }
        file_name = f"{source}.{suffix}"
        for row_index, row in enumerate(entity_rows[source], start=1):
            key = _row_key(row, source_fields)
            if all(key) and key not in target_index:
                line_number = _row_line_number(
                    file_name, row_index, line_numbers_by_file
                )
                errors.append(
                    "schema_v2_broken_foreign_key:"
                    f"{file_name}:L{line_number}:{'+'.join(source_fields)}"
                )

    for source, field_name, target, target_field in SCHEMA_V2_LIST_FOREIGN_KEYS:
        file_name = f"{source}.{suffix}"
        target_values = {
            _identifier(row.get(target_field))
            for row in entity_rows[target]
            if _identifier(row.get(target_field))
        }
        for row_index, row in enumerate(entity_rows[source], start=1):
            for value in _split_references(row.get(field_name)):
                if value not in target_values:
                    line_number = _row_line_number(
                        file_name, row_index, line_numbers_by_file
                    )
                    errors.append(
                        "schema_v2_broken_foreign_key:"
                        f"{file_name}:L{line_number}:{field_name}:{value}"
                    )

    fragments = indexes["evidence_fragments"]
    signals = indexes["semantic_signals"]
    candidates = indexes["competence_candidates"]
    decisions = indexes["validation_decisions"]
    canonical_competences = indexes["canonical_competences"]
    evidence_records = indexes["evidence_records"]
    inactive_decision_ids = {
        _identifier(decision.get("superseded_validation_decision_id"))
        for decision in entity_rows["validation_decisions"]
        if _identifier(decision.get("superseded_validation_decision_id"))
    }
    for row_index, decision in enumerate(
        entity_rows["validation_decisions"], start=1
    ):
        file_name = f"validation_decisions.{suffix}"
        line_number = _row_line_number(
            file_name, row_index, line_numbers_by_file
        )
        decision_id = _identifier(decision.get("validation_decision_id"))
        superseded_id = _identifier(
            decision.get("superseded_validation_decision_id")
        )
        if not superseded_id:
            continue
        if superseded_id == decision_id:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:"
                "superseded_validation_decision_self_reference"
            )
            continue
        superseded_decision = decisions.get((superseded_id,))
        if (
            superseded_decision is not None
            and _identifier(superseded_decision.get("target_candidate_id"))
            != _identifier(decision.get("target_candidate_id"))
        ):
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:"
                "superseded_validation_decision_target_candidate"
            )
    for row_index, fragment in enumerate(
        entity_rows["evidence_fragments"], start=1
    ):
        file_name = f"evidence_fragments.{suffix}"
        line_number = _row_line_number(
            file_name, row_index, line_numbers_by_file
        )
        expected_provenance_id = _expected_fragment_provenance_id(fragment)
        retained_provenance_id = _string_value(
            fragment.get("source_provenance_id")
        )
        if retained_provenance_id != expected_provenance_id:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:source_provenance_id"
            )
        expected_provenance_hash = hashlib.sha256(
            retained_provenance_id.encode("utf-8")
        ).hexdigest()
        if _string_value(fragment.get("provenance_hash")) != expected_provenance_hash:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:provenance_hash"
            )
    for row_index, signal in enumerate(entity_rows["semantic_signals"], start=1):
        file_name = f"semantic_signals.{suffix}"
        line_number = _row_line_number(
            file_name, row_index, line_numbers_by_file
        )
        linked_fragment = fragments.get(
            (_identifier(signal.get("fragment_id")),)
        )
        if linked_fragment and any(
            _identifier(signal.get(field_name))
            != _identifier(linked_fragment.get(field_name))
            for field_name in ("evidence_id", "run_id", "source_provenance_id")
        ):
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:fragment_lineage"
            )
        if linked_fragment and not _fragment_contains_phrase(
            linked_fragment.get("fragment_text"), signal.get("matched_phrase")
        ):
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:matched_phrase"
            )
        if linked_fragment:
            start_offset = _parse_integer(
                linked_fragment.get("span_start_offset")
            )
            end_offset = _parse_integer(
                linked_fragment.get("span_end_offset")
            )
            context_text = _string_value(signal.get("context_text"))
            if (
                start_offset is None
                or end_offset is None
                or start_offset < 0
                or end_offset < start_offset
                or end_offset > len(context_text)
            ):
                errors.append(
                    "schema_v2_lineage_mismatch:"
                    f"{file_name}:L{line_number}:fragment_context_offsets"
                )
            elif context_text[start_offset:end_offset] != _string_value(
                linked_fragment.get("fragment_text")
            ):
                errors.append(
                    "schema_v2_lineage_mismatch:"
                    f"{file_name}:L{line_number}:fragment_context_slice"
                )
            if _normalized_text_hash(context_text) != _string_value(
                linked_fragment.get("surface_text_hash")
            ):
                errors.append(
                    "schema_v2_lineage_mismatch:"
                    f"{file_name}:L{line_number}:surface_text_hash"
                )

    for row_index, candidate in enumerate(
        entity_rows["competence_candidates"], start=1
    ):
        file_name = f"competence_candidates.{suffix}"
        line_number = _row_line_number(
            file_name, row_index, line_numbers_by_file
        )
        fragment_id = _identifier(candidate.get("fragment_id"))
        selected_fragment = fragments.get((fragment_id,))
        references = _candidate_reference_ids(
            candidate, "fragment_ids", "fragment_id"
        )
        expected_fragment_ids = {
            signal_fragment_id
            for (signal_id, signal_fragment_id), signal in signals.items()
            if (
                signal_id == _identifier(candidate.get("signal_id"))
                and _identifier(signal.get("evidence_id"))
                == _identifier(candidate.get("evidence_id"))
            )
        }
        if references != expected_fragment_ids:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:fragment_ids"
            )
        if fragment_id and fragment_id not in references:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:fragment_ids"
            )
        provenance_ids = set(
            _split_references(candidate.get("source_provenance_ids"))
        )
        for referenced_fragment_id in sorted(references):
            referenced_fragment = fragments.get((referenced_fragment_id,))
            linked_signal = signals.get(
                (
                    _identifier(candidate.get("signal_id")),
                    referenced_fragment_id,
                )
            )
            if referenced_fragment is None or linked_signal is None:
                errors.append(
                    "schema_v2_lineage_mismatch:"
                    f"{file_name}:L{line_number}:fragment_ids_signal_pair"
                )
                continue
            if _identifier(candidate.get("evidence_id")) != _identifier(
                referenced_fragment.get("evidence_id")
            ):
                errors.append(
                    "schema_v2_lineage_mismatch:"
                    f"{file_name}:L{line_number}:fragment_ids_evidence_id"
                )
        expected_provenance_ids = {
            _identifier(referenced_fragment.get("source_provenance_id"))
            for referenced_fragment_id in expected_fragment_ids
            for referenced_fragment in [
                fragments.get((referenced_fragment_id,))
            ]
            if referenced_fragment is not None
        }
        if provenance_ids != expected_provenance_ids:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:source_provenance_ids"
            )
        if selected_fragment and any(
            _identifier(candidate.get(field_name))
            != _identifier(selected_fragment.get(fragment_field))
            for field_name, fragment_field in (
                ("evidence_id", "evidence_id"),
                ("run_id", "run_id"),
                ("exact_evidence_span", "fragment_text"),
                ("exact_span_start_offset", "span_start_offset"),
                ("exact_span_end_offset", "span_end_offset"),
            )
        ):
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:selected_fragment_content"
            )

    for row_index, decision in enumerate(
        entity_rows["validation_decisions"], start=1
    ):
        file_name = f"validation_decisions.{suffix}"
        line_number = _row_line_number(
            file_name, row_index, line_numbers_by_file
        )
        linked_candidate = candidates.get(
            (_identifier(decision.get("target_candidate_id")),)
        )
        if linked_candidate is None:
            continue
        expected = {
            "evidence_ids": {_identifier(linked_candidate.get("evidence_id"))},
            "fragment_ids": _candidate_reference_ids(
                linked_candidate, "fragment_ids", "fragment_id"
            ),
            "source_provenance_ids": _candidate_reference_ids(
                linked_candidate,
                "source_provenance_ids",
                "source_provenance_id",
            ),
        }
        for field_name, expected_values in expected.items():
            if expected_values == set(_split_references(decision.get(field_name))):
                continue
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:{field_name}"
            )

    for row_index, canonical in enumerate(
        entity_rows["canonical_competences"], start=1
    ):
        file_name = f"canonical_competences.{suffix}"
        line_number = _row_line_number(
            file_name, row_index, line_numbers_by_file
        )
        linked_decision = decisions.get(
            (_identifier(canonical.get("validation_decision_id")),)
        )
        if linked_decision is None:
            continue
        if _identifier(canonical.get("validation_decision_id")) in inactive_decision_ids:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:inactive_validation_decision_id"
            )
        if (
            _identifier(linked_decision.get("decision_status")) != "accepted"
            or _identifier(canonical.get("source_candidate_id"))
            != _identifier(linked_decision.get("target_candidate_id"))
        ):
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:validation_decision_id"
            )
        if _normalized_label(canonical.get("preferred_label")) != _normalized_label(
            linked_decision.get("canonical_label")
        ):
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:canonical_label"
            )
        if _identifier(linked_decision.get("decision_status")) == "accepted":
            linked_candidate = candidates.get(
                (_identifier(canonical.get("source_candidate_id")),)
            )
            retained_source_titles: Tuple[str, ...] = ()
            if linked_candidate is not None:
                evidence_record = evidence_records.get(
                    (_identifier(linked_candidate.get("evidence_id")),)
                )
                if evidence_record is not None:
                    retained_source_titles = (
                        _string_value(evidence_record.get("canonical_title")),
                    )
            guard_reason = _canonical_label_guard_reason(
                canonical.get("preferred_label"), retained_source_titles
            )
            if guard_reason:
                errors.append(
                    "schema_v2_lineage_mismatch:"
                    f"{file_name}:L{line_number}:canonical_label_guard:"
                    f"{guard_reason}"
                )

    for row_index, assignment in enumerate(
        entity_rows["sector_competence_assignments"], start=1
    ):
        file_name = f"sector_competence_assignments.{suffix}"
        line_number = _row_line_number(
            file_name, row_index, line_numbers_by_file
        )
        linked_candidate = candidates.get(
            (_identifier(assignment.get("source_candidate_id")),)
        )
        linked_decision = decisions.get(
            (_identifier(assignment.get("validation_decision_id")),)
        )
        linked_canonical = canonical_competences.get(
            (_identifier(assignment.get("canonical_competence_id")),)
        )
        if _identifier(assignment.get("validation_decision_id")) in inactive_decision_ids:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:inactive_validation_decision_id"
            )
        if linked_decision is not None and (
            _identifier(linked_decision.get("decision_status")) != "accepted"
            or _identifier(assignment.get("source_candidate_id"))
            != _identifier(linked_decision.get("target_candidate_id"))
        ):
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:validation_decision_id"
            )
        if linked_decision is not None and linked_canonical is not None and (
            _normalized_label(linked_canonical.get("preferred_label"))
            != _normalized_label(linked_decision.get("canonical_label"))
        ):
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:canonical_label"
            )
        if linked_candidate is None:
            continue
        assignment_evidence_ids = set(
            _split_references(assignment.get("evidence_ids"))
        )
        expected_evidence_ids = {_identifier(linked_candidate.get("evidence_id"))}
        if assignment_evidence_ids != expected_evidence_ids:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:evidence_ids"
            )
        semantic_contexts = _candidate_semantic_contexts(
            linked_candidate, signals
        )
        assignment_context = (
            _identifier(assignment.get("sector")),
            _identifier(assignment.get("axis_group")),
            _identifier(assignment.get("axis_code")),
        )
        if assignment_context not in semantic_contexts:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:semantic_context"
            )

    for row_index, decision in enumerate(
        entity_rows["validation_decisions"], start=1
    ):
        decision_id = _identifier(decision.get("validation_decision_id"))
        if (
            _identifier(decision.get("decision_status")) != "accepted"
            or decision_id in inactive_decision_ids
        ):
            continue
        file_name = f"validation_decisions.{suffix}"
        line_number = _row_line_number(
            file_name, row_index, line_numbers_by_file
        )
        candidate_id = _identifier(decision.get("target_candidate_id"))
        linked_candidate = candidates.get((candidate_id,))
        if linked_candidate is None:
            continue
        expected_contexts = {
            context
            for context in _candidate_semantic_contexts(
                linked_candidate, signals
            )
            if _is_bound_axis_context(context)
        }
        matching_canonicals = [
            canonical
            for canonical in entity_rows["canonical_competences"]
            if _normalized_label(canonical.get("preferred_label"))
            == _normalized_label(decision.get("canonical_label"))
        ]
        canonical_ids = {
            _identifier(canonical.get("canonical_competence_id"))
            for canonical in matching_canonicals
            if _identifier(canonical.get("canonical_competence_id"))
        }
        if len(canonical_ids) != 1:
            errors.append(
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:canonical_competence"
            )
            continue
        expected_canonical_id = next(iter(canonical_ids))
        matching_assignments = [
            assignment
            for assignment in entity_rows["sector_competence_assignments"]
            if (
                _identifier(assignment.get("validation_decision_id"))
                == decision_id
                and _identifier(assignment.get("source_candidate_id"))
                == candidate_id
            )
        ]
        assignment_contexts = {
            (
                _identifier(assignment.get("sector")),
                _identifier(assignment.get("axis_group")),
                _identifier(assignment.get("axis_code")),
            )
            for assignment in matching_assignments
        }
        assignment_canonical_ids = {
            _identifier(assignment.get("canonical_competence_id"))
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
                "schema_v2_lineage_mismatch:"
                f"{file_name}:L{line_number}:sector_competence_assignments"
            )
    return errors


def _projection_value(value: Any) -> str:
    """Return a stable scalar representation for CSV/JSONL parity checks."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _validate_schema_v2_cross_projection_parity(
    csv_rows_by_file: Dict[str, List[Dict[str, Any]]],
    jsonl_rows_by_file: Dict[str, List[Dict[str, Any]]],
    csv_line_numbers: Optional[Dict[str, List[int]]] = None,
    jsonl_line_numbers: Optional[Dict[str, List[int]]] = None,
) -> List[str]:
    """Require CSV and JSONL schema-v2 projections to retain the same rows."""
    errors: List[str] = []
    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        identity_fields = ENTITY_ID_FIELDS[entity_name]
        csv_file = f"{entity_name}.csv"
        jsonl_file = f"{entity_name}.jsonl"
        csv_index: Dict[Tuple[str, ...], Tuple[int, Dict[str, Any]]] = {}
        jsonl_index: Dict[Tuple[str, ...], Tuple[int, Dict[str, Any]]] = {}
        for row_index, row in enumerate(csv_rows_by_file.get(csv_file, []), start=1):
            key = _row_key(row, identity_fields)
            if all(key):
                csv_index.setdefault(key, (row_index, row))
        for row_index, row in enumerate(
            jsonl_rows_by_file.get(jsonl_file, []), start=1
        ):
            key = _row_key(row, identity_fields)
            if all(key):
                jsonl_index.setdefault(key, (row_index, row))

        for key in sorted(set(csv_index) - set(jsonl_index)):
            row_index, _ = csv_index[key]
            line_number = _row_line_number(
                csv_file, row_index, csv_line_numbers
            )
            errors.append(
                "schema_v2_cross_projection_missing_jsonl_key:"
                f"{entity_name}:csv:L{line_number}"
            )
        for key in sorted(set(jsonl_index) - set(csv_index)):
            row_index, _ = jsonl_index[key]
            line_number = _row_line_number(
                jsonl_file, row_index, jsonl_line_numbers
            )
            errors.append(
                "schema_v2_cross_projection_missing_csv_key:"
                f"{entity_name}:jsonl:L{line_number}"
            )
        for key in sorted(set(csv_index) & set(jsonl_index)):
            csv_row_index, csv_row = csv_index[key]
            jsonl_row_index, jsonl_row = jsonl_index[key]
            csv_line_number = _row_line_number(
                csv_file, csv_row_index, csv_line_numbers
            )
            jsonl_line_number = _row_line_number(
                jsonl_file, jsonl_row_index, jsonl_line_numbers
            )
            for field_name in SCHEMA_V2_REQUIRED_COLUMNS[entity_name]:
                if _projection_value(csv_row.get(field_name)) == _projection_value(
                    jsonl_row.get(field_name)
                ):
                    continue
                errors.append(
                    "schema_v2_cross_projection_value_mismatch:"
                    f"{entity_name}:{field_name}:csv:L{csv_line_number}:"
                    f"jsonl:L{jsonl_line_number}"
                )
    return errors


def _validate_schema_v2_manifest_counts(
    manifest_path: Path,
    csv_rows_by_file: Dict[str, List[Dict[str, Any]]],
    jsonl_rows_by_file: Dict[str, List[Dict[str, Any]]],
) -> List[str]:
    """Require the database manifest to count each schema-v2 table exactly."""
    errors: List[str] = []
    manifest = _load_json_required(manifest_path)
    counts = manifest.get("counts") if manifest is not None else None
    if not isinstance(counts, dict):
        return [
            "schema_v2_manifest_missing_counts:"
            f"{manifest_path.name}"
        ]

    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        declared_count = counts.get(entity_name)
        if isinstance(declared_count, bool) or not isinstance(
            declared_count, int
        ):
            errors.append(
                "schema_v2_manifest_invalid_count:"
                f"{manifest_path.name}:{entity_name}"
            )
            continue
        csv_count = len(csv_rows_by_file.get(f"{entity_name}.csv", []))
        jsonl_count = len(jsonl_rows_by_file.get(f"{entity_name}.jsonl", []))
        if declared_count != csv_count or declared_count != jsonl_count:
            errors.append(
                "schema_v2_manifest_count_mismatch:"
                f"{manifest_path.name}:{entity_name}:"
                f"manifest={declared_count}:csv={csv_count}:jsonl={jsonl_count}"
            )
    return errors


def _validate_legacy_derived_demand_metadata(
    csv_rows: List[Dict[str, Any]],
    jsonl_rows: List[Dict[str, Any]],
) -> List[str]:
    """Require identical legacy-view metadata for each derived-demand ID."""
    errors: List[str] = []

    def metadata_by_demand(
        rows: List[Dict[str, Any]], file_name: str, row_start: int = 1
    ) -> Dict[str, Tuple[str, str, Tuple[str, ...]]]:
        metadata: Dict[str, Tuple[str, str, Tuple[str, ...]]] = {}
        for row_index, row in enumerate(rows, start=row_start):
            demand_id = _identifier(row.get("competence_demand_id"))
            if not demand_id:
                errors.append(
                    "derived_demand_missing_required_field:"
                    f"{file_name}:L{row_index}:competence_demand_id"
                )
                continue
            evidence_ids = tuple(sorted(_split_references(row.get("evidence_ids"))))
            if not evidence_ids or any(
                value.lower() == "unavailable" for value in evidence_ids
            ):
                errors.append(
                    "derived_demand_missing_supporting_evidence_ids:"
                    f"{file_name}:L{row_index}:{demand_id}"
                )
            values = (
                _identifier(row.get("view_kind")),
                _identifier(row.get("scientific_status")),
                evidence_ids,
            )
            for field_name, value, expected_value in (
                (
                    "view_kind",
                    values[0],
                    LEGACY_DERIVED_DEMAND_VIEW_KIND,
                ),
                (
                    "scientific_status",
                    values[1],
                    LEGACY_DERIVED_DEMAND_SCIENTIFIC_STATUS,
                ),
            ):
                if not value:
                    errors.append(
                        "derived_demand_missing_required_field:"
                        f"{file_name}:L{row_index}:{field_name}"
                    )
                elif value != expected_value:
                    errors.append(
                        "derived_demand_invalid_legacy_metadata:"
                        f"{file_name}:L{row_index}:{field_name}"
                    )
            if demand_id in metadata:
                errors.append(
                    f"duplicate_derived_demand_id:{file_name}:L{row_index}:{demand_id}"
                )
                continue
            metadata[demand_id] = values
        return metadata

    csv_metadata = metadata_by_demand(
        csv_rows, "derived_competence_demands.csv", row_start=2
    )
    jsonl_metadata = metadata_by_demand(
        jsonl_rows, "derived_competence_demands.jsonl", row_start=1
    )
    for demand_id in sorted(set(csv_metadata) | set(jsonl_metadata)):
        if demand_id not in csv_metadata:
            errors.append(
                "derived_demand_missing_csv_metadata:"
                f"competence_demand_id:{demand_id}"
            )
            continue
        if demand_id not in jsonl_metadata:
            errors.append(
                "derived_demand_missing_jsonl_metadata:"
                f"competence_demand_id:{demand_id}"
            )
            continue
        if csv_metadata[demand_id] != jsonl_metadata[demand_id]:
            errors.append(
                "derived_demand_metadata_mismatch:"
                f"competence_demand_id:{demand_id}"
            )
    return errors


def _report_has_required_sections(path: Path) -> List[str]:
    required_tokens = [
        "scientific hypothesis verification",
        "h1",
        "h2",
        "h3",
        "validity threats",
        "reproducibility appendix",
    ]
    text = path.read_text(encoding="utf-8").lower()
    return [token for token in required_tokens if token not in text]


def _build_sqlite_from_csvs(csv_dir: Path) -> Tuple[Optional[bytes], Dict[str, str]]:
    """Materialize the CSV bundle into a portable SQLite database.

    Returns ``(sqlite_bytes, status_dict)``. ``sqlite_bytes`` is ``None`` if
    the SQLite build was skipped.
    """
    try:
        # Use an in-memory DB to avoid touching the filesystem, then
        # serialize deterministically. Requires Python 3.11+ for
        # sqlite3.Connection.serialize, so we fall back gracefully.
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        for name in CSV_FILES:
            p = csv_dir / name
            if not p.exists():
                continue
            table = name.replace(".csv", "")
            with p.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                headers = next(reader, None)
                if not headers:
                    continue
                cols = ", ".join(f'"{h}" TEXT' for h in headers)
                cursor.execute(f'CREATE TABLE "{table}" ({cols})')
                placeholders = ", ".join("?" for _ in headers)
                insert = f'INSERT INTO "{table}" VALUES ({placeholders})'
                for row in reader:
                    padded = row + [""] * (len(headers) - len(row))
                    cursor.execute(insert, padded[: len(headers)])
        conn.commit()
        try:
            data = conn.serialize()  # type: ignore[attr-defined]
        except AttributeError:
            # Python < 3.11 fallback: dump to temp path via file.
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                temp_path = Path(tf.name)
            file_conn = sqlite3.connect(str(temp_path))
            conn.backup(file_conn)
            file_conn.close()
            data = temp_path.read_bytes()
            temp_path.unlink(missing_ok=True)
        conn.close()
        return bytes(data), {"sqlite_status": "generated", "sqlite_skip_reason": ""}
    except Exception as exc:
        return None, {"sqlite_status": "skipped",
                      "sqlite_skip_reason": f"sqlite build failed: {exc}"}


def _readme_text(version_tag: str, generated_at: str) -> str:
    return (
        "# morskamary — live cumulative scientific package\n\n"
        f"**Version tag**: {version_tag}\n"
        f"**Generated**: {generated_at}\n\n"
        "## Contents\n\n"
        "- `RELEASE_MANIFEST.json` — package manifest with checksums and "
        "provenance metadata.\n"
        "- `CHECKSUMS.sha256` — one line per file with its SHA-256 digest.\n"
        "- `CITATION_APA.txt` — APA-style citation template.\n"
        "- `VARIABLE_LABELS.csv`, `VALUE_LABELS.csv` — statistical software "
        "value/variable dictionaries.\n"
        "- `data/csv/` — deterministic CSV tables (evidence, signals, "
        "derived demands, gap model, credentials, outcomes, novelty).\n"
        "- `data/jsonl/` — canonical JSONL audit records and evidence-bound "
        "hypothesis fragments.\n"
        "- `schemas/` — bundled Draft 2020-12 schema-v2 contracts for the "
        "evidence-to-decision tables.\n"
        "- `protocol/` — authoritative protocol, executable projection, and "
        "declared acquisition constraints.\n"
        "- `provenance/` — query execution log and Layer 1 raw acquisition "
        "index for the packaged run.\n"
        "- `statistics/` — Layer 4 cross-tables, matrices, multivariate "
        "results, and taxonomic clusters.\n"
        "- `data/sqlite/` — portable SQLite database (may be skipped; see "
        "`RELEASE_MANIFEST.json`).\n"
        "- `reports/` — HTML statistical report, methodological audit, "
        "and PDF (may be a text stub if PDF rendering is unavailable).\n\n"
        "## Demand-strength formula\n\n"
        f"    {DEMAND_STRENGTH_FORMULA}\n\n"
        "## Reliability rule\n\n"
        "Records with `record_novelty_status = duplicate_only` are excluded "
        "from statistical growth metrics. Growth indexes are recalculated "
        "only on `new_record`, `updated_metadata`, `provider_enriched`, and "
        "`semantic_enriched` records.\n"
    )


def _citation_text(version_tag: str, generated_at: str) -> str:
    year = generated_at[:4]
    return (
        f"Bartłomiejski, R. ({year}). morskamary — Live Cumulative Blue "
        f"Economy Competence Demand Package ({version_tag}) [Data set]. "
        "https://github.com/robertbartlomiejski/morskamary\n"
    )


def main(argv: Optional[List[str]] = None) -> int:
    _doc_description = next(
        (line.strip() for line in (__doc__ or "").splitlines() if line.strip()),
        "",
    )
    parser = argparse.ArgumentParser(description=_doc_description)
    parser.add_argument("--database-dir", default="outputs/cumulative_database")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--stats-dir", default="outputs/layer4_statistics")
    parser.add_argument(
        "--protocol-path",
        default="config/live_query_protocol.yml",
    )
    parser.add_argument(
        "--projection-path",
        default="outputs/research_sources/research_queries_from_protocol.yml",
    )
    parser.add_argument(
        "--constraints-path",
        default="outputs/research_sources/query_protocol_constraints.json",
    )
    parser.add_argument(
        "--query-execution-log",
        default="outputs/research_sources/query_execution_log.csv",
    )
    parser.add_argument(
        "--raw-acquisition-index",
        default=None,
        help="Layer 1 raw_acquisition_index.csv for this exact run.",
    )
    parser.add_argument("--version-tag", default="latest")
    parser.add_argument(
        "--current-run-id",
        default="",
        help=(
            "Optional run id guard (e.g. <github.run_id>-<run_attempt>). "
            "When set, package assembly fails if manifests/metrics are stale."
        ),
    )
    parser.add_argument(
        "--output",
        default="outputs/release_packages/morskamary_live_cumulative_latest.zip",
    )
    parser.add_argument(
        "--generated-at-utc",
        default=None,
        help=(
            "Optional ISO-8601 UTC timestamp embedded in README, citation, "
            "and manifest. Pass a frozen value for byte-identical rebuilds."
        ),
    )
    args = parser.parse_args(argv)

    database_dir = Path(args.database_dir)
    reports_dir = Path(args.reports_dir)
    stats_dir = Path(args.stats_dir)
    protocol_path = Path(args.protocol_path)
    projection_path = Path(args.projection_path)
    constraints_path = Path(args.constraints_path)
    query_execution_log = Path(args.query_execution_log)
    raw_acquisition_index = (
        Path(args.raw_acquisition_index)
        if args.raw_acquisition_index
        else None
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Remove any stale release ZIP so that a failed preflight cannot leave an
    # old package for downstream `if: always()` artifact uploads to publish.
    if output.exists():
        output.unlink()
    expected_run_id = str(args.current_run_id or "").strip()
    generated_at = (
        args.generated_at_utc
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )

    entries: List[Tuple[str, bytes]] = []

    # Fail non-zero before ZIP publication if any Layer 0-5, provenance,
    # statistical, or report artifact is absent.
    required_paths = [
        *(database_dir / name for name in CSV_FILES),
        *(database_dir / name for name in JSONL_FILES),
        *(database_dir / name for name in DATABASE_METADATA_FILES),
        database_dir / "VARIABLE_LABELS.csv",
        database_dir / "VALUE_LABELS.csv",
        *(stats_dir / name for name in LAYER4_STAT_FILES),
        *(reports_dir / name for name in REPORT_FILES),
        protocol_path,
        projection_path,
        constraints_path,
        query_execution_log,
    ]
    if raw_acquisition_index is None:
        missing_required = ["--raw-acquisition-index was not provided"]
    else:
        required_paths.append(raw_acquisition_index)
        missing_required = [
            str(required_path)
            for required_path in required_paths
            if not required_path.is_file()
        ]

    # Schema/content validation for manifests, checksums, and CSVs.
    for name in DATABASE_METADATA_FILES:
        candidate = database_dir / name
        if not candidate.is_file():
            continue
        if name.endswith(".json"):
            try:
                json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                missing_required.append(f"malformed_json:{name}:{exc}")
        elif name.endswith(".sha256"):
            try:
                _HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
                text = candidate.read_text(encoding="utf-8")
                seen_refs: Set[str] = set()
                expected_checksum_refs = set(
                    list(CSV_FILES)
                    + list(JSONL_FILES)
                    + [
                        n for n in DATABASE_METADATA_FILES
                        if not n.endswith(".sha256")
                    ]
                )
                for lineno, line in enumerate(
                    text.strip().splitlines(), start=1
                ):
                    parts = line.split("  ", 1)
                    if len(parts) != 2 or not _HEX64.match(parts[0]):
                        missing_required.append(
                            f"malformed_checksum_line:{name}:L{lineno}"
                        )
                        break
                    declared_digest, ref_path = parts
                    if ref_path in seen_refs:
                        missing_required.append(
                            f"duplicate_checksum_entry:{name}:{ref_path}"
                        )
                        break
                    seen_refs.add(ref_path)
                    ref_file = database_dir / ref_path
                    if not ref_file.is_file():
                        missing_required.append(
                            f"checksum_ref_missing:{name}:{ref_path}"
                        )
                        continue
                    actual_digest = hashlib.sha256(
                        ref_file.read_bytes()
                    ).hexdigest()
                    if actual_digest != declared_digest.lower():
                        missing_required.append(
                            f"checksum_mismatch:{name}:{ref_path}"
                        )
                missing_refs = sorted(expected_checksum_refs - seen_refs)
                if missing_refs:
                    missing_required.append(
                        "checksum_missing_required_refs:"
                        + ",".join(missing_refs)
                    )
            except OSError as exc:
                missing_required.append(f"unreadable_checksum:{name}:{exc}")
    csv_rows: Dict[str, List[Dict[str, Any]]] = {}
    csv_line_numbers: Dict[str, List[int]] = {}
    for name in CSV_FILES:
        candidate = database_dir / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
            reader = csv.reader(StringIO(text, newline=""))
            header = next(reader, None)
            if not header:
                missing_required.append(f"empty_csv:{name}")
            else:
                header_counts: Dict[str, int] = {}
                for header_name in header:
                    header_counts[header_name] = (
                        header_counts.get(header_name, 0) + 1
                    )
                duplicate_headers = sorted(
                    header_name
                    for header_name, count in header_counts.items()
                    if count > 1
                )
                if duplicate_headers:
                    rendered_headers = ",".join(
                        header_name or "<empty>"
                        for header_name in duplicate_headers
                    )
                    missing_required.append(
                        f"csv_duplicate_headers:{name}:L1:{rendered_headers}"
                    )
                if name in CSV_REQUIRED_COLUMNS:
                    header_set = set(header)
                    missing_cols = sorted(
                        col for col in CSV_REQUIRED_COLUMNS[name]
                        if col not in header_set
                    )
                    if missing_cols:
                        missing_required.append(
                            f"csv_missing_columns:{name}:"
                            + ",".join(missing_cols)
                        )
            dict_reader = csv.DictReader(StringIO(text, newline=""))
            parsed_rows = []
            line_numbers = []
            for row in dict_reader:
                if row.get(None):
                    missing_required.append(
                        f"csv_surplus_values:{name}:L{dict_reader.line_num}"
                    )
                parsed_rows.append(
                    {
                        str(key): value
                        for key, value in row.items()
                        if key is not None
                    }
                )
                line_numbers.append(dict_reader.line_num)
            csv_rows[name] = parsed_rows
            csv_line_numbers[name] = line_numbers
            if name == "derived_competence_demands.csv":
                for row_index, row in enumerate(parsed_rows, start=2):
                    evidence_ids = str(row.get("evidence_ids", "")).strip()
                    if evidence_ids and evidence_ids.lower() != "unavailable":
                        continue
                    demand_id = str(
                        row.get("competence_demand_id", "")
                    ).strip() or f"row_{row_index}"
                    missing_required.append(
                        f"derived_demand_missing_supporting_evidence_ids:{demand_id}"
                    )
        except (OSError, csv.Error) as exc:
            missing_required.append(f"malformed_csv:{name}:{exc}")

    # JSONL scientific-content checks (non-empty, parseable, and structurally linked).
    jsonl_rows: Dict[str, List[Dict[str, Any]]] = {}
    jsonl_line_numbers: Dict[str, List[int]] = {}
    for name in JSONL_FILES:
        rows, line_numbers, errors = _load_jsonl_rows(database_dir / name)
        jsonl_rows[name] = rows
        jsonl_line_numbers[name] = line_numbers
        missing_required.extend(errors)

    missing_required.extend(
        _validate_schema_v2_json_schema(
            csv_rows, "csv", csv_line_numbers
        )
    )
    missing_required.extend(
        _validate_schema_v2_json_schema(
            jsonl_rows, "jsonl", jsonl_line_numbers
        )
    )
    missing_required.extend(
        _validate_schema_v2_required_fields(
            csv_rows, "csv", csv_line_numbers
        )
    )
    missing_required.extend(
        _validate_schema_v2_required_fields(
            jsonl_rows, "jsonl", jsonl_line_numbers
        )
    )
    missing_required.extend(
        _validate_schema_v2_foreign_keys(
            csv_rows, "csv", csv_line_numbers
        )
    )
    missing_required.extend(
        _validate_schema_v2_foreign_keys(
            jsonl_rows, "jsonl", jsonl_line_numbers
        )
    )
    missing_required.extend(
        _validate_schema_v2_cross_projection_parity(
            csv_rows,
            jsonl_rows,
            csv_line_numbers,
            jsonl_line_numbers,
        )
    )
    missing_required.extend(
        _validate_schema_v2_manifest_counts(
            database_dir / "cumulative_database_manifest.json",
            csv_rows,
            jsonl_rows,
        )
    )
    missing_required.extend(
        _validate_legacy_derived_demand_metadata(
            csv_rows.get("derived_competence_demands.csv", []),
            jsonl_rows.get("derived_competence_demands.jsonl", []),
        )
    )

    fragment_rows = jsonl_rows.get("hypothesis_semantic_fragments.jsonl", [])
    for row_index, row in enumerate(fragment_rows, start=1):
        for field_name in (
            "hypothesis_id",
            "signal_id",
            "evidence_id",
            "matched_hypothesis_phrase",
            "indicator_family",
            "semantic_fragment",
            "evidence_surface",
        ):
            if str(row.get(field_name, "")).strip():
                continue
            missing_required.append(
                f"hypothesis_fragment_missing_field:L{row_index}:{field_name}"
            )

    evidence_ids_from_fragments = {
        str(row.get("evidence_id", "")).strip()
        for row in fragment_rows
        if str(row.get("evidence_id", "")).strip()
    }

    demand_rows = csv_rows.get("derived_competence_demands.csv", [])
    learning_rows = csv_rows.get("learning_outcomes.csv", [])

    demand_ids = {
        str(row.get("competence_demand_id", "")).strip()
        for row in demand_rows
        if str(row.get("competence_demand_id", "")).strip()
    }
    linked_outcomes = {
        str(row.get("competence_demand_id", "")).strip()
        for row in learning_rows
        if str(row.get("competence_demand_id", "")).strip()
    }
    missing_outcome_links = sorted(demand_ids - linked_outcomes)
    if missing_outcome_links:
        missing_required.append(
            "learning_outcome_missing_demand_links:"
            + ",".join(missing_outcome_links[:20])
        )

    for row in demand_rows:
        demand_id = str(row.get("competence_demand_id", "")).strip()
        declares_hypothesis = bool(str(row.get("hypothesis_ids", "")).strip())
        for evidence_id in [
            item.strip()
            for item in str(row.get("evidence_ids", "")).split("|")
            if item.strip()
        ]:
            if evidence_id.lower() == "unavailable":
                continue
            if not declares_hypothesis or evidence_id in evidence_ids_from_fragments:
                continue
            missing_required.append(
                f"demand_evidence_not_in_hypothesis_fragments:{demand_id}:{evidence_id}"
            )

    # Report structural checks (required sections + declared hypothesis completeness).
    report_path = reports_dir / "morskamary_statistical_report.html"
    if report_path.is_file():
        missing_sections = _report_has_required_sections(report_path)
        if missing_sections:
            missing_required.append(
                "report_missing_sections:" + ",".join(sorted(missing_sections))
            )

    layer5_manifest = _load_json_required(database_dir / "layer5_manifest.json") or {}
    hypotheses = layer5_manifest.get("hypothesis_results", {})
    if not isinstance(hypotheses, dict):
        missing_required.append("layer5_manifest_missing_hypothesis_results")
    else:
        for hypothesis_id in ("H1", "H2", "H3"):
            if hypothesis_id not in hypotheses:
                missing_required.append(
                    f"layer5_manifest_missing_declared_hypothesis:{hypothesis_id}"
                )
    if expected_run_id:
        run_guard_failures: List[str] = []
        for name in (
            "run_novelty_metrics.json",
            "layer4_manifest.json",
            "layer5_manifest.json",
        ):
            payload = _load_json_required(database_dir / name)
            run_id = str(payload.get("current_run_id", "")).strip() if payload else ""
            if not run_id:
                run_guard_failures.append(f"{name}:missing_current_run_id")
            elif run_id != expected_run_id:
                run_guard_failures.append(f"{name}:{run_id}")
        if raw_acquisition_index is not None:
            normalized_raw_path = str(raw_acquisition_index).replace("\\", "/")
            # Validate the exact path contract: the path must contain
            # the sequence live_runs/<run_id>/raw/raw_acquisition_index.csv
            # as contiguous directory components.
            expected_suffix = (
                f"outputs/live_runs/{expected_run_id}/raw/raw_acquisition_index.csv"
            )
            if (
                normalized_raw_path != expected_suffix
                and not normalized_raw_path.endswith(f"/{expected_suffix}")
            ):
                run_guard_failures.append(
                    "raw_acquisition_index_path_contract_violation"
                )
        if run_guard_failures:
            missing_required.extend(
                f"current-run-guard:{entry}" for entry in run_guard_failures
            )

    if missing_required:
        print(
            f"error: {len(missing_required)} required Layer 0-5 artifact(s) "
            "missing; release ZIP was not created:",
            file=sys.stderr,
        )
        for missing_path in missing_required:
            print(f"  {missing_path}", file=sys.stderr)
        return 1

    # Collect CSVs (required + optional if present).
    for name in CSV_FILES:
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((f"data/csv/{name}", blob))
    for name in OPTIONAL_CSV_FILES:
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((f"data/csv/{name}", blob))

    # JSONL
    for name in JSONL_FILES:
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((f"data/jsonl/{name}", blob))

    # The versioned schema-v2 contracts are part of the publication package,
    # so consumers can validate each CSV/JSONL projection without relying on
    # a mutable repository checkout.
    for name in SCHEMA_V2_SCHEMA_FILENAMES:
        schema_path = _SCHEMA_V2_DIR / name
        entries.append((f"schemas/{name}", schema_path.read_bytes()))

    # Database manifests, novelty results, and internal checksums.
    for name in DATABASE_METADATA_FILES:
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((f"metadata/{name}", blob))

    # Layer 4 statistical tables.
    for name in LAYER4_STAT_FILES:
        blob = _read_bytes_if_exists(stats_dir / name)
        if blob is not None:
            entries.append((f"statistics/{name}", blob))

    # Authoritative protocol, executable projection, and acquisition provenance.
    source_files = (
        (protocol_path, "protocol/live_query_protocol.yml"),
        (projection_path, "protocol/research_queries_from_protocol.yml"),
        (constraints_path, "protocol/query_protocol_constraints.json"),
        (query_execution_log, "provenance/query_execution_log.csv"),
        (
            raw_acquisition_index,
            "provenance/raw_acquisition_index.csv",
        ),
    )
    for source_path, archive_name in source_files:
        if source_path is not None:
            entries.append((archive_name, source_path.read_bytes()))

    # Reports
    for name in REPORT_FILES:
        blob = _read_bytes_if_exists(reports_dir / name)
        if blob is not None:
            entries.append((f"reports/{name}", blob))

    # Variable/value labels (root)
    for name in ("VARIABLE_LABELS.csv", "VALUE_LABELS.csv"):
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((name, blob))

    # SQLite
    sqlite_bytes, sqlite_status = _build_sqlite_from_csvs(database_dir)
    if sqlite_bytes is not None:
        entries.append(("data/sqlite/morskamary_live_cumulative.sqlite", sqlite_bytes))

    # README + citation
    entries.append(("README_DATA_PACKAGE.md",
                    _readme_text(args.version_tag, generated_at).encode("utf-8")))
    entries.append(("CITATION_APA.txt",
                    _citation_text(args.version_tag, generated_at).encode("utf-8")))

    # Finalize the manifest, then checksum every package member except the
    # checksum file itself. This makes RELEASE_MANIFEST.json verifiable.
    entries.sort(key=lambda entry: entry[0])
    final_names = sorted(
        [name for name, _ in entries]
        + ["RELEASE_MANIFEST.json", "CHECKSUMS.sha256"]
    )
    manifest = {
        "package_name": "morskamary_live_cumulative",
        "version_tag": args.version_tag,
        "generated_at_utc": generated_at,
        "demand_strength_formula": DEMAND_STRENGTH_FORMULA,
        "file_count": len(final_names),
        "files": final_names,
        "checksum_scope": (
            "all package members including RELEASE_MANIFEST.json; "
            "CHECKSUMS.sha256 explicitly excluded"
        ),
        **sqlite_status,
    }
    manifest_text = (
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2)
        + "\n"
    )
    entries.append(
        ("RELEASE_MANIFEST.json", manifest_text.encode("utf-8"))
    )
    entries.sort(key=lambda entry: entry[0])
    checksums_text = "".join(
        f"{_sha256_bytes(blob)}  {name}\n"
        for name, blob in entries
    )
    entries.append(
        ("CHECKSUMS.sha256", checksums_text.encode("utf-8"))
    )
    entries.sort(key=lambda entry: entry[0])

    # Write ZIP with a fixed timestamp so repeated builds are byte-identical.
    fixed_ts = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, blob in entries:
            info = zipfile.ZipInfo(name, date_time=fixed_ts)
            info.external_attr = (0o644 & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, blob)

    package_bytes = output.read_bytes()
    package_sha = _sha256_bytes(package_bytes)
    print(json.dumps({
        "package_path": str(output),
        "package_size_bytes": len(package_bytes),
        "package_sha256": package_sha,
        "sqlite_status": sqlite_status.get("sqlite_status"),
        "file_count": len(entries),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
