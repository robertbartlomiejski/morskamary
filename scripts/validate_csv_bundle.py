#!/usr/bin/env python3
"""Fail-closed schema-v2 CSV/JSONL bundle preflight.

This is the lightweight, non-publication entry point for checking an exported
``outputs/cumulative_database`` bundle before it is passed to the full release
package builder.  It deliberately reuses that builder's Draft-2020-12,
lineage, identity, projection-parity, and manifest-count validators so the
offline gate cannot drift into a weaker parallel contract.

Usage::

    python scripts/validate_csv_bundle.py --bundle-dir outputs/cumulative_database
"""

from __future__ import annotations

import argparse
import csv
import sys
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Tuple, cast

from build_live_cumulative_release_package import (  # type: ignore[import-not-found]
    CSV_REQUIRED_COLUMNS,
    SCHEMA_V2_ENTITY_NAMES,
    SCHEMA_V2_REQUIRED_COLUMNS,
    _load_jsonl_rows,
    _validate_schema_v2_cross_projection_parity,
    _validate_schema_v2_foreign_keys,
    _validate_schema_v2_json_schema,
    _validate_schema_v2_manifest_counts,
    _validate_schema_v2_required_fields,
)


_BUNDLE_ENTITY_NAMES = ("evidence_records", *SCHEMA_V2_ENTITY_NAMES)
_BUNDLE_CSV_FILES = tuple(f"{name}.csv" for name in _BUNDLE_ENTITY_NAMES)
_BUNDLE_JSONL_FILES = tuple(f"{name}.jsonl" for name in _BUNDLE_ENTITY_NAMES)
_MANIFEST_FILENAME = "cumulative_database_manifest.json"


def _required_columns(entity_name: str) -> Tuple[str, ...]:
    """Return the release contract's required CSV columns for one entity."""
    if entity_name == "evidence_records":
        return cast(
            Tuple[str, ...], CSV_REQUIRED_COLUMNS["evidence_records.csv"]
        )
    return cast(Tuple[str, ...], SCHEMA_V2_REQUIRED_COLUMNS[entity_name])


def _load_csv_projection(
    bundle_dir: Path,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[int]], List[str]]:
    """Read the CSV projection with the release builder's fail-closed rules."""
    rows_by_file: Dict[str, List[Dict[str, Any]]] = {}
    line_numbers_by_file: Dict[str, List[int]] = {}
    errors: List[str] = []
    for entity_name, file_name in zip(
        _BUNDLE_ENTITY_NAMES, _BUNDLE_CSV_FILES
    ):
        path = bundle_dir / file_name
        if not path.is_file():
            errors.append(f"schema_v2_missing_required_file:{file_name}")
            rows_by_file[file_name] = []
            line_numbers_by_file[file_name] = []
            continue
        try:
            text = path.read_text(encoding="utf-8")
            reader = csv.reader(StringIO(text, newline=""))
            header = next(reader, None)
            if not header:
                errors.append(f"empty_csv:{file_name}")
            else:
                duplicate_headers = sorted(
                    header_name
                    for header_name in set(header)
                    if header.count(header_name) > 1
                )
                if duplicate_headers:
                    rendered_headers = ",".join(
                        header_name or "<empty>"
                        for header_name in duplicate_headers
                    )
                    errors.append(
                        f"csv_duplicate_headers:{file_name}:L1:"
                        f"{rendered_headers}"
                    )
                header_set = set(header)
                missing_columns = sorted(
                    column
                    for column in _required_columns(entity_name)
                    if column not in header_set
                )
                if missing_columns:
                    errors.append(
                        f"csv_missing_columns:{file_name}:"
                        f"{','.join(missing_columns)}"
                    )

            parsed_rows: List[Dict[str, Any]] = []
            line_numbers: List[int] = []
            dict_reader = csv.DictReader(StringIO(text, newline=""))
            for row in dict_reader:
                if row.get(None):
                    errors.append(
                        f"csv_surplus_values:{file_name}:"
                        f"L{dict_reader.line_num}"
                    )
                parsed_rows.append(
                    {
                        str(key): value
                        for key, value in row.items()
                        if key is not None
                    }
                )
                line_numbers.append(dict_reader.line_num)
            rows_by_file[file_name] = parsed_rows
            line_numbers_by_file[file_name] = line_numbers
        except (OSError, UnicodeError, csv.Error) as exc:
            errors.append(f"malformed_csv:{file_name}:{exc}")
            rows_by_file[file_name] = []
            line_numbers_by_file[file_name] = []
    return rows_by_file, line_numbers_by_file, errors


def _load_jsonl_projection(
    bundle_dir: Path,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[int]], List[str]]:
    """Read the JSONL projection through the release builder's strict loader."""
    rows_by_file: Dict[str, List[Dict[str, Any]]] = {}
    line_numbers_by_file: Dict[str, List[int]] = {}
    errors: List[str] = []
    for file_name in _BUNDLE_JSONL_FILES:
        path = bundle_dir / file_name
        if not path.is_file():
            errors.append(f"schema_v2_missing_required_file:{file_name}")
            rows_by_file[file_name] = []
            line_numbers_by_file[file_name] = []
            continue
        rows, line_numbers, load_errors = _load_jsonl_rows(path)
        rows_by_file[file_name] = rows
        line_numbers_by_file[file_name] = line_numbers
        errors.extend(load_errors)
    return rows_by_file, line_numbers_by_file, errors


def _projection_value(value: Any) -> str:
    """Return one stable scalar value for CSV/JSONL projection comparison."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _projection_line_number(
    line_numbers: Dict[str, List[int]], file_name: str, row_index: int
) -> int:
    """Return a physical source line number for a parsed projection row."""
    available_lines = line_numbers.get(file_name, [])
    if 0 < row_index <= len(available_lines):
        return available_lines[row_index - 1]
    return row_index + (1 if file_name.endswith(".csv") else 0)


def _validate_evidence_record_projection(
    csv_rows: Dict[str, List[Dict[str, Any]]],
    jsonl_rows: Dict[str, List[Dict[str, Any]]],
    csv_line_numbers: Dict[str, List[int]],
    jsonl_line_numbers: Dict[str, List[int]],
) -> List[str]:
    """Require evidence-record fields and values in both linked projections."""
    errors: List[str] = []
    required_columns = _required_columns("evidence_records")
    projections = (
        ("csv", csv_rows, csv_line_numbers),
        ("jsonl", jsonl_rows, jsonl_line_numbers),
    )
    for suffix, rows_by_file, line_numbers in projections:
        file_name = f"evidence_records.{suffix}"
        for row_index, row in enumerate(
            rows_by_file.get(file_name, []), start=1
        ):
            line_number = _projection_line_number(
                line_numbers, file_name, row_index
            )
            for field_name in required_columns:
                if field_name not in row:
                    errors.append(
                        "evidence_records_missing_required_field:"
                        f"{file_name}:L{line_number}:{field_name}"
                    )
            if not _projection_value(row.get("evidence_id")):
                errors.append(
                    "evidence_records_empty_required_field:"
                    f"{file_name}:L{line_number}:evidence_id"
                )

    csv_file = "evidence_records.csv"
    jsonl_file = "evidence_records.jsonl"
    csv_index = {
        _projection_value(row.get("evidence_id")): (row_index, row)
        for row_index, row in enumerate(csv_rows.get(csv_file, []), start=1)
        if _projection_value(row.get("evidence_id"))
    }
    jsonl_index = {
        _projection_value(row.get("evidence_id")): (row_index, row)
        for row_index, row in enumerate(jsonl_rows.get(jsonl_file, []), start=1)
        if _projection_value(row.get("evidence_id"))
    }
    for evidence_id in sorted(set(csv_index) - set(jsonl_index)):
        csv_row_index, _ = csv_index[evidence_id]
        line_number = _projection_line_number(
            csv_line_numbers, csv_file, csv_row_index
        )
        errors.append(
            "evidence_records_cross_projection_missing_jsonl_key:"
            f"csv:L{line_number}"
        )
    for evidence_id in sorted(set(jsonl_index) - set(csv_index)):
        jsonl_row_index, _ = jsonl_index[evidence_id]
        line_number = _projection_line_number(
            jsonl_line_numbers, jsonl_file, jsonl_row_index
        )
        errors.append(
            "evidence_records_cross_projection_missing_csv_key:"
            f"jsonl:L{line_number}"
        )
    for evidence_id in sorted(set(csv_index) & set(jsonl_index)):
        csv_row_index, csv_row = csv_index[evidence_id]
        jsonl_row_index, jsonl_row = jsonl_index[evidence_id]
        csv_line_number = _projection_line_number(
            csv_line_numbers, csv_file, csv_row_index
        )
        jsonl_line_number = _projection_line_number(
            jsonl_line_numbers, jsonl_file, jsonl_row_index
        )
        for field_name in required_columns:
            if _projection_value(csv_row.get(field_name)) == _projection_value(
                jsonl_row.get(field_name)
            ):
                continue
            errors.append(
                "evidence_records_cross_projection_value_mismatch:"
                f"{field_name}:csv:L{csv_line_number}:"
                f"jsonl:L{jsonl_line_number}"
            )
    return errors


def validate_bundle(bundle_dir: Path) -> List[str]:
    """Return every schema-v2 bundle violation in stable display order."""
    (
        csv_rows,
        csv_line_numbers,
        errors,
    ) = _load_csv_projection(bundle_dir)
    (
        jsonl_rows,
        jsonl_line_numbers,
        jsonl_errors,
    ) = _load_jsonl_projection(bundle_dir)
    errors.extend(jsonl_errors)
    errors.extend(
        _validate_evidence_record_projection(
            csv_rows,
            jsonl_rows,
            csv_line_numbers,
            jsonl_line_numbers,
        )
    )
    errors.extend(
        _validate_schema_v2_json_schema(csv_rows, "csv", csv_line_numbers)
    )
    errors.extend(
        _validate_schema_v2_json_schema(
            jsonl_rows, "jsonl", jsonl_line_numbers
        )
    )
    errors.extend(
        _validate_schema_v2_required_fields(
            csv_rows, "csv", csv_line_numbers
        )
    )
    errors.extend(
        _validate_schema_v2_required_fields(
            jsonl_rows, "jsonl", jsonl_line_numbers
        )
    )
    errors.extend(
        _validate_schema_v2_foreign_keys(csv_rows, "csv", csv_line_numbers)
    )
    errors.extend(
        _validate_schema_v2_foreign_keys(
            jsonl_rows, "jsonl", jsonl_line_numbers
        )
    )
    errors.extend(
        _validate_schema_v2_cross_projection_parity(
            csv_rows,
            jsonl_rows,
            csv_line_numbers,
            jsonl_line_numbers,
        )
    )
    manifest_path = bundle_dir / _MANIFEST_FILENAME
    if not manifest_path.is_file():
        errors.append(
            f"schema_v2_missing_required_file:{_MANIFEST_FILENAME}"
        )
    else:
        errors.extend(
            _validate_schema_v2_manifest_counts(
                manifest_path, csv_rows, jsonl_rows
            )
        )
    return list(dict.fromkeys(errors))


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    """Parse the standalone preflight command line."""
    parser = argparse.ArgumentParser(
        description="Fail-closed schema-v2 CSV/JSONL bundle preflight."
    )
    parser.add_argument(
        "--bundle-dir",
        required=True,
        help="Directory containing cumulative database CSV, JSONL, and manifest files.",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    """Validate one bundle and return a conventional process status."""
    args = parse_args(argv)
    bundle_dir = Path(args.bundle_dir)
    if not bundle_dir.is_dir():
        print(
            f"[ERROR] bundle directory does not exist: {bundle_dir}",
            file=sys.stderr,
        )
        return 2

    print(f"[INFO] Validating schema-v2 bundle: {bundle_dir}")
    errors = validate_bundle(bundle_dir)
    if errors:
        for error in errors:
            print(f"[ERROR] {error}", file=sys.stderr)
        print(
            f"[ERROR] Schema-v2 bundle preflight failed ({len(errors)} error(s)).",
            file=sys.stderr,
        )
        return 1
    print("[OK] Schema-v2 bundle preflight passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
