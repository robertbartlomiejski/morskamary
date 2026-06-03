#!/usr/bin/env python3
"""Assert that cumulative QMBD records contain live-enriched evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

LIVE_SOURCE_PREFIXES = (
    "crossref:",
    "scopus:",
    "wos:",
    "scival:",
    "microsoft_graph:",
)


def _is_live_like_record(record: dict[str, Any]) -> bool:
    origin = str(record.get("record_origin", "")).upper()
    source_id = str(record.get("source_id", "")).lower()
    return origin.startswith("LIVE") or source_id.startswith(LIVE_SOURCE_PREFIXES)


def load_records(path: Path) -> list[dict[str, Any]] | None:
    """Load cumulative records, printing controlled errors for malformed input."""
    if not path.exists():
        print(f"ERROR: {path} is missing")
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path} is not valid JSON: {exc}")
        return None
    except OSError as exc:
        print(f"ERROR: {path} could not be read: {exc}")
        return None

    if not isinstance(data, list):
        print(f"ERROR: {path} must contain a JSON list, got {type(data).__name__}")
        return None

    non_objects = sum(1 for item in data if not isinstance(item, dict))
    if non_objects:
        print(f"ERROR: {path} contains {non_objects} non-object record(s)")
        return None

    return data


def assert_cumulative_live_enriched(path: Path, *, require_live: bool) -> int:
    """Print cumulative/live-like counts and fail when required live evidence is absent."""
    records = load_records(path)
    if records is None:
        return 1

    live_records = [record for record in records if _is_live_like_record(record)]

    print(f"cumulative_records={len(records)}")
    print(f"cumulative_live_like_records={len(live_records)}")

    if require_live and not live_records:
        print("ERROR: live-enriched mode produced no live-like cumulative records.")
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("outputs/cumulative_qmbd_records.json"),
        help="Path to cumulative_qmbd_records.json",
    )
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="Fail if no LIVE_* or live-provider-prefixed records are present",
    )
    args = parser.parse_args([] if argv is None else argv)
    return assert_cumulative_live_enriched(args.path, require_live=args.require_live)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
