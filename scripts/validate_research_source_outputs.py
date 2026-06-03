#!/usr/bin/env python3
"""
Validate research source output files for capability, health, provenance,
coverage, and live-record completeness.

Default behavior is conservative and CI-friendly:
- missing optional files produce warnings;
- malformed present files produce errors;
- --require-health requires outputs/research_api_health.json;
- --require-live requires non-empty live research-source exports.

Usage:
    python scripts/validate_research_source_outputs.py
    python scripts/validate_research_source_outputs.py --require-health
    python scripts/validate_research_source_outputs.py --require-live --min-live-records 1
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")

ERRORS: list[str] = []
WARNINGS: list[str] = []


def _outputs_path() -> Path:
    return Path(OUTPUTS_DIR)


def _err(msg: str) -> None:
    ERRORS.append(msg)
    print(f"  ERROR: {msg}")


def _warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"  WARN:  {msg}")


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _err(f"{path.name} is not valid JSON: {exc}")
    except OSError as exc:
        _err(f"{path.name} could not be read: {exc}")
    return None


def _count_json_records(path: Path) -> int | None:
    data = _load_json(path)
    if data is None:
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        if isinstance(data.get("records"), list):
            return len(data["records"])
        if isinstance(data.get("statuses"), list):
            return len(data["statuses"])
        return len(data.keys())
    _err(f"{path.name} must contain a JSON list or object, got {type(data).__name__}")
    return None


def _count_csv_rows(path: Path) -> int | None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return sum(1 for _ in csv.DictReader(fh))
    except OSError as exc:
        _err(f"{path.name} could not be read: {exc}")
        return None


def validate_capabilities_json() -> None:
    """Validate outputs/research_source_capabilities.json if present."""
    path = _outputs_path() / "research_source_capabilities.json"
    if not path.is_file():
        _warn("research_source_capabilities.json not found (run export script first)")
        return

    data = _load_json(path)
    if data is None:
        return

    if "providers" not in data:
        _err("research_source_capabilities.json missing key: providers")
        return

    providers = data.get("providers", {})
    if not isinstance(providers, dict):
        _err("research_source_capabilities.json providers must be an object")
        return

    if "crossref" not in providers:
        _err("crossref provider missing from capabilities export")
    elif not providers["crossref"].get("configured"):
        _err("crossref should always be configured=true")

    print(f"  OK: research_source_capabilities.json ({len(providers)} providers)")


def validate_health_json(require_health: bool = False) -> None:
    """Validate outputs/research_api_health.json if present or required."""
    path = _outputs_path() / "research_api_health.json"
    if not path.is_file():
        if require_health:
            _err("research_api_health.json not found but --require-health was set")
        else:
            _warn("research_api_health.json not found")
        return

    data = _load_json(path)
    if data is None:
        return

    statuses = data.get("statuses") if isinstance(data, dict) else None
    if not isinstance(statuses, list):
        _err("research_api_health.json missing list key: statuses")
        return

    providers = {
        str(item.get("provider", "")).strip(): str(item.get("status", "")).strip()
        for item in statuses
        if isinstance(item, dict)
    }

    if providers.get("crossref") != "ok":
        _err("crossref health status should be ok")

    invalid = {
        provider: status
        for provider, status in providers.items()
        if status in {"present-but-invalid", "rate-limited"}
    }
    if invalid:
        _warn(f"provider health contains invalid/rate-limited statuses: {invalid}")

    print(f"  OK: research_api_health.json ({len(statuses)} statuses)")


def validate_smoke_report() -> None:
    """Validate outputs/research_api_smoke_report.json if present."""
    path = _outputs_path() / "research_api_smoke_report.json"
    if not path.is_file():
        _warn("research_api_smoke_report.json not found (run smoke script first)")
        return

    data = _load_json(path)
    if data is None:
        return

    print("  OK: research_api_smoke_report.json")


def validate_live_research_sources(
    *,
    require_live: bool = False,
    min_live_records: int = 1,
) -> None:
    """Validate outputs/research_sources live export files."""
    base = _outputs_path() / "research_sources"
    if not base.is_dir():
        if require_live:
            _err("outputs/research_sources directory not found but --require-live was set")
        else:
            _warn("outputs/research_sources directory not found")
        return

    json_files = [
        "live_records.json",
        "live_records_triangulated.json",
        "crossref_records.json",
        "live_provenance.json",
        "low_confidence_live_records.json",
    ]
    csv_files = [
        "live_records.csv",
        "live_source_coverage.csv",
    ]

    counts: dict[str, int] = {}

    for name in json_files:
        path = base / name
        if not path.is_file():
            if require_live and name in {
                "live_records.json",
                "live_records_triangulated.json",
                "crossref_records.json",
                "live_provenance.json",
            }:
                _err(f"{name} missing from outputs/research_sources")
            else:
                _warn(f"{name} not found")
            continue

        count = _count_json_records(path)
        if count is not None:
            counts[name] = count
            print(f"  OK: {name} ({count} JSON records/items)")

    for name in csv_files:
        path = base / name
        if not path.is_file():
            if require_live:
                _err(f"{name} missing from outputs/research_sources")
            else:
                _warn(f"{name} not found")
            continue

        count = _count_csv_rows(path)
        if count is not None:
            counts[name] = count
            print(f"  OK: {name} ({count} CSV rows)")

    if require_live:
        live_count = counts.get("live_records.json", 0)
        triangulated_count = counts.get("live_records_triangulated.json", 0)
        coverage_count = counts.get("live_source_coverage.csv", 0)

        if live_count < min_live_records:
            _err(
                "live_records.json contains "
                f"{live_count} records, expected at least {min_live_records}"
            )
        if triangulated_count < min_live_records:
            _err(
                "live_records_triangulated.json contains "
                f"{triangulated_count} records, expected at least {min_live_records}"
            )
        if coverage_count <= 0:
            _err("live_source_coverage.csv must contain at least one coverage row")


def main(argv: list[str] | None = None) -> int:
    """Run all output validations."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-health", action="store_true")
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--min-live-records", type=int, default=1)
    args = parser.parse_args([] if argv is None else argv)

    ERRORS.clear()
    WARNINGS.clear()

    print("=== Research Source Output Validation ===\n")

    outputs_dir = _outputs_path()
    if not outputs_dir.is_dir():
        _warn(f"outputs/ directory not found at {outputs_dir}")
    else:
        validate_capabilities_json()
        validate_health_json(require_health=args.require_health)
        validate_smoke_report()
        validate_live_research_sources(
            require_live=args.require_live,
            min_live_records=args.min_live_records,
        )

    print(f"\nErrors:   {len(ERRORS)}")
    print(f"Warnings: {len(WARNINGS)}")

    if ERRORS:
        print("\nValidation FAILED.")
        return 1

    print("\nValidation passed (warnings are informational).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
