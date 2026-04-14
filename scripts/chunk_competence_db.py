#!/usr/bin/env python3
"""Split large competence JSON files into smaller, processable chunks."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

AXIS_MAP = {"M": "MARINE", "T": "MARITIME", "O": "OCEANIC"}
VALID_AXES = set(AXIS_MAP.values())
DEFAULT_INPUT = Path("outputs/competences_full_database.json")
DEFAULT_OUTPUT_DIR = Path("outputs/chunks")
CSV_COLUMNS = ["id", "name", "description", "axis", "level", "source"]


def extract_competences(payload: Any) -> List[Dict[str, Any]]:
    """Extract the competence list from known repository JSON structures."""
    if isinstance(payload, list):
        return _as_competence_list(payload, key_name="root")

    if not isinstance(payload, dict):
        raise ValueError("Unsupported JSON structure: expected object or array.")

    competences = payload.get("competences")
    if isinstance(competences, list):
        return _as_competence_list(competences, key_name="competences")

    baseline = payload.get("baseline")
    literature = payload.get("literature")
    if isinstance(baseline, list) and isinstance(literature, list):
        return _as_competence_list(baseline, key_name="baseline") + _as_competence_list(
            literature, key_name="literature"
        )

    raise ValueError(
        "Could not find competences array. Expected keys: 'competences' or"
        " ('baseline' + 'literature')."
    )


def _as_competence_list(items: Sequence[Any], key_name: str) -> List[Dict[str, Any]]:
    """Validate that a JSON array contains competence-like records."""
    records: List[Dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(
                f"Invalid record in '{key_name}' at index {idx}: expected object."
            )
        records.append(dict(item))
    return records


def normalize_axis(record: Dict[str, Any], idx: int) -> str:
    """Return canonical axis name (MARINE, MARITIME, OCEANIC)."""
    raw = record.get("axis_name", record.get("axis"))
    if not isinstance(raw, str):
        raise ValueError(f"Record {idx} is missing axis information.")

    axis_candidate = raw.strip().upper()
    axis = AXIS_MAP.get(axis_candidate, axis_candidate)
    if axis not in VALID_AXES:
        raise ValueError(
            f"Record {idx} has invalid axis '{raw}'. Expected MARINE/MARITIME/OCEANIC "
            "or M/T/O."
        )
    return axis


def validate_required_fields(
    record: Dict[str, Any], idx: int, strict_level: bool
) -> None:
    """Ensure required competence fields are present."""
    for field in ("id", "name", "description"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Record {idx} is missing required field '{field}'.")

    if strict_level:
        level = record.get("level")
        if not isinstance(level, str) or not level.strip():
            raise ValueError(
                f"Record {idx} is missing required field 'level' in strict mode."
            )


def prepare_records(
    competences: Sequence[Dict[str, Any]], strict_level: bool
) -> List[Dict[str, Any]]:
    """Validate and normalize records before chunk export."""
    prepared: List[Dict[str, Any]] = []
    for idx, competence in enumerate(competences):
        validate_required_fields(competence, idx, strict_level=strict_level)
        normalized = dict(competence)
        normalized["axis"] = normalize_axis(competence, idx)
        prepared.append(normalized)
    return prepared


def chunked(
    items: Sequence[Dict[str, Any]], chunk_size: int
) -> Iterable[List[Dict[str, Any]]]:
    """Yield consecutive record batches of at most chunk_size."""
    for start in range(0, len(items), chunk_size):
        yield list(items[start : start + chunk_size])


def export_chunks(
    records: Sequence[Dict[str, Any]],
    source_path: Path,
    output_dir: Path,
    chunk_size: int,
) -> List[Path]:
    """Write JSON chunk files to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    parts = list(chunked(records, chunk_size))
    total_parts = len(parts)
    paths: List[Path] = []

    for part_idx, part_records in enumerate(parts, start=1):
        part_path = output_dir / f"competences_part_{part_idx}.json"
        payload = {
            "metadata": {
                "source_file": source_path.as_posix(),
                "part": part_idx,
                "parts_total": total_parts,
                "records_in_part": len(part_records),
                "chunk_size": chunk_size,
            },
            "competences": part_records,
        }
        with part_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        paths.append(part_path)

    return paths


def _extract_source(record: Dict[str, Any]) -> str:
    source = record.get("source")
    if isinstance(source, dict):
        file_value = source.get("file")
        if isinstance(file_value, str):
            return file_value
    if isinstance(source, str):
        return source
    return ""


def export_csv(records: Sequence[Dict[str, Any]], output_path: Path) -> None:
    """Write a lightweight CSV export with key competence fields."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "id": record.get("id", ""),
                    "name": record.get("name", ""),
                    "description": record.get("description", ""),
                    "axis": record.get("axis", ""),
                    "level": record.get("level", ""),
                    "source": _extract_source(record),
                }
            )


def run_chunking(
    input_path: Path,
    output_dir: Path,
    chunk_size: int,
    strict_level: bool,
    export_lightweight_csv: bool,
) -> Dict[str, Any]:
    """Read source JSON, validate records, and export chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer.")
    if not input_path.exists():
        raise FileNotFoundError(f"Source file not found: {input_path}")

    with input_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    extracted = extract_competences(payload)
    prepared = prepare_records(extracted, strict_level=strict_level)
    chunk_paths = export_chunks(
        prepared, source_path=input_path, output_dir=output_dir, chunk_size=chunk_size
    )

    csv_path = output_dir / "competences_export.csv"
    if export_lightweight_csv:
        export_csv(prepared, csv_path)

    return {
        "source": input_path,
        "total_records": len(prepared),
        "chunk_files": chunk_paths,
        "csv_file": csv_path if export_lightweight_csv else None,
    }


def parse_args() -> argparse.Namespace:
    """Build command-line interface."""
    parser = argparse.ArgumentParser(
        description="Split competence databases into smaller JSON chunks."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to source competence JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for chunked JSON files.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=100,
        help="Number of competences per chunk file.",
    )
    parser.add_argument(
        "--strict-level",
        action="store_true",
        help="Require each competence to include a non-empty 'level' field.",
    )
    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Skip lightweight CSV export.",
    )
    return parser.parse_args()


def main() -> int:
    """Entrypoint for CLI usage."""
    args = parse_args()
    result = run_chunking(
        input_path=args.input,
        output_dir=args.output_dir,
        chunk_size=args.chunk_size,
        strict_level=args.strict_level,
        export_lightweight_csv=not args.no_csv,
    )
    print(f"Source: {result['source']}")
    print(f"Records: {result['total_records']}")
    print(f"Chunk files: {len(result['chunk_files'])}")
    if result["csv_file"] is not None:
        print(f"CSV export: {result['csv_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
