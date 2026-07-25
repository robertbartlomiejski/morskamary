"""Compare generated outputs while allowing only declared run metadata drift."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

NONDETERMINISTIC_KEYS_BY_FILE: dict[str, set[str]] = {
    "cumulative_qmbd_records.json": {
        "commit_sha",
        "github_run_id",
        "timestamp_utc",
        "analysis_timestamp_utc",
    },
    "credentials_dynamic_database.json": {
        "generated_supply_audit_only_count",
        "generated_supply_sector_summary",
    },
    "credentials_generation_rationale.json": {
        "generated_supply_audit_only_count",
        "generated_supply_sector_summary",
    },
    "gaps_detailed.json": {
        "generated_supply_audit_only_count",
        "generated_supply_sector_summary",
    },
}


def normalize_payload(payload: Any, ignored_keys: set[str]) -> Any:
    """Return a recursively normalized JSON payload."""

    if isinstance(payload, dict):
        return {
            key: normalize_payload(value, ignored_keys)
            for key, value in sorted(payload.items())
            if key not in ignored_keys
        }
    if isinstance(payload, list):
        return [normalize_payload(item, ignored_keys) for item in payload]
    return payload


def compare_json_payloads(
    current: Any,
    committed: Any,
    *,
    filename: str,
) -> bool:
    """Compare a supported generated JSON file after narrow normalization."""

    ignored_keys = NONDETERMINISTIC_KEYS_BY_FILE.get(filename, set())
    return bool(
        normalize_payload(current, ignored_keys)
        == normalize_payload(committed, ignored_keys)
    )


def _changed_output_paths(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", "--", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line.strip()) for line in completed.stdout.splitlines() if line.strip()]


def _committed_bytes(path: Path) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"HEAD:{path.as_posix()}"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ValueError(f"{path} is not present in HEAD")
    return completed.stdout


def compare_outputs(root: Path) -> list[str]:
    """Return substantive output-drift errors for the current worktree."""

    errors: list[str] = []
    for relative_path in _changed_output_paths(root):
        current_path = Path(relative_path)
        if not current_path.is_file():
            errors.append(f"{relative_path}: generated file is missing from worktree")
            continue

        filename = current_path.name
        if current_path.suffix.lower() != ".json" or filename not in NONDETERMINISTIC_KEYS_BY_FILE:
            errors.append(f"{relative_path}: substantive generated-output drift")
            continue

        try:
            current_payload = json.loads(current_path.read_text(encoding="utf-8"))
            committed_payload = json.loads(_committed_bytes(current_path).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{relative_path}: cannot compare JSON safely: {exc}")
            continue

        if not compare_json_payloads(
            current_payload,
            committed_payload,
            filename=filename,
        ):
            errors.append(f"{relative_path}: substantive JSON drift")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="outputs")
    args = parser.parse_args([] if argv is None else argv)

    errors = compare_outputs(Path(args.root))
    if errors:
        print("Generated output comparison failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Generated outputs are in sync after declared metadata normalization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
