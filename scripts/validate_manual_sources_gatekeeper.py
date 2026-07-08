#!/usr/bin/env python3
"""Gatekeeper checks for manual source ledger and historical revalidation artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path("outputs/manual_sources")
LEDGER_FILENAME = "manual_sources_ledger.jsonl"
HISTORICAL_FILENAME = "historical_cumulative_records.jsonl"
COMPATIBILITY_FILENAME = "historical_compatibility.csv"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_sha256(token: str) -> bool:
    return len(token) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in token)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            try:
                row = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def validate_gatekeeper(root: Path, fail_on_issues: bool) -> int:
    root = root.resolve()
    ledger = _load_jsonl(root / LEDGER_FILENAME)
    historical = _load_jsonl(root / HISTORICAL_FILENAME)

    duplicate_ids: dict[str, int] = {}
    checksum_mismatches: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_sha: set[str] = set()

    for row in ledger:
        source_id = _normalize(row.get("source_id"))
        checksum = _normalize(row.get("sha256"))
        stored_path = _normalize(row.get("stored_path"))
        if source_id:
            if source_id in seen_ids:
                duplicate_ids[source_id] = duplicate_ids.get(source_id, 1) + 1
            seen_ids.add(source_id)
        if checksum:
            if checksum in seen_sha:
                # duplicate checksums are allowed for same content but still tracked by source_id uniqueness
                pass
            seen_sha.add(checksum)
            if not _is_sha256(checksum):
                checksum_mismatches.append(
                    {
                        "source_id": source_id,
                        "reason": "invalid_sha256_format",
                        "sha256": checksum,
                    }
                )
        if stored_path:
            binary_path = Path(stored_path)
            if binary_path.exists() and checksum and _is_sha256(checksum):
                digest = hashlib.sha256(binary_path.read_bytes()).hexdigest()
                if digest != checksum:
                    checksum_mismatches.append(
                        {
                            "source_id": source_id,
                            "reason": "stored_file_checksum_mismatch",
                            "sha256": checksum,
                            "computed_sha256": digest,
                            "stored_path": stored_path,
                        }
                    )

    historical_ids = [_normalize(row.get("canonical_record_id")) for row in historical]
    historical_ids = [token for token in historical_ids if token]
    growth_delta_payload = {
        "captured_at_utc": _utc_now(),
        "manual_sources_total": len(ledger),
        "historical_records_total": len(historical_ids),
        "historical_unique_ids": len(set(historical_ids)),
        "historical_duplicate_ids": len(historical_ids) - len(set(historical_ids)),
    }

    compatibility_summary_payload = {
        "captured_at_utc": _utc_now(),
        "compatibility_file_exists": (root / COMPATIBILITY_FILENAME).exists(),
        "ledger_exists": (root / LEDGER_FILENAME).exists(),
        "historical_exists": (root / HISTORICAL_FILENAME).exists(),
    }

    _write_json(root / "gatekeeper_duplicate_ids.json", duplicate_ids)
    _write_json(root / "gatekeeper_checksum_mismatches.json", checksum_mismatches)
    _write_json(root / "gatekeeper_cumulative_growth_delta.json", growth_delta_payload)
    _write_json(
        root / "gatekeeper_compatibility_summary.json", compatibility_summary_payload
    )

    issues = bool(duplicate_ids) or bool(checksum_mismatches)
    print(f"Wrote {root / 'gatekeeper_duplicate_ids.json'}")
    print(f"Wrote {root / 'gatekeeper_checksum_mismatches.json'}")
    print(f"Wrote {root / 'gatekeeper_cumulative_growth_delta.json'}")
    print(f"Wrote {root / 'gatekeeper_compatibility_summary.json'}")

    if issues and fail_on_issues:
        print("Gatekeeper FAILED: duplicate IDs or checksum mismatches detected.")
        return 1
    print("Gatekeeper checks completed.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate gatekeeping constraints for manual source ingestion."
    )
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Directory containing manual source and historical artifacts.",
    )
    parser.add_argument(
        "--fail-on-issues",
        default="true",
        help="Exit with code 1 when duplicate IDs or checksum mismatches exist.",
    )
    return parser.parse_args(argv)


def _to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        fail_on_issues = _to_bool(str(args.fail_on_issues))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return validate_gatekeeper(Path(str(args.root)), fail_on_issues)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
