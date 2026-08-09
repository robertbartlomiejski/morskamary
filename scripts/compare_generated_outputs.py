"""Compare generated outputs while allowing only declared run metadata drift."""

from __future__ import annotations

import argparse
import csv
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
        "static_recovery_reason",
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

NONDETERMINISTIC_COLUMNS_BY_FILE: dict[str, set[str]] = {
    "gaps_summary.csv": {
        "Generated_at",
        "Run_id",
    }
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

    if filename == "cumulative_qmbd_records.json":
        for label, payload in (("current", current), ("committed", committed)):
            metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
            if not isinstance(metadata, dict):
                raise ValueError(
                    f"{filename}: {label} metadata must be an object, got "
                    f"{type(metadata).__name__}"
                )
            if metadata.get("is_static_recovery_mode") and not str(
                metadata.get("static_recovery_reason", "")
            ).strip():
                raise ValueError(
                    f"{filename}: {label} static_recovery_reason is required and "
                    "must be nonempty when is_static_recovery_mode is true"
                )

    ignored_keys = NONDETERMINISTIC_KEYS_BY_FILE.get(filename, set())
    return bool(
        normalize_payload(current, ignored_keys)
        == normalize_payload(committed, ignored_keys)
    )


def compare_csv_payloads(current: str, committed: str, *, filename: str) -> bool:
    """Compare a supported generated CSV file after narrow normalization."""

    ignored_columns = NONDETERMINISTIC_COLUMNS_BY_FILE.get(filename)
    if ignored_columns is None:
        return current == committed

    def _normalized_rows(payload: str) -> list[dict[str, str]]:
        reader = csv.DictReader(payload.splitlines(), restkey="__extra__")
        rows: list[dict[str, str]] = []
        for index, row in enumerate(reader, start=1):
            extras = row.get("__extra__")
            if extras:
                raise ValueError(
                    f"{filename}: malformed CSV row {index} with extra column(s): {extras}"
                )
            rows.append(
                {
                    key: value
                    for key, value in sorted(row.items())
                    if key not in ignored_columns and key != "__extra__"
                }
            )
        return rows

    return _normalized_rows(current) == _normalized_rows(committed)


def _changed_output_paths(root: Path) -> list[Path]:
    tracked = subprocess.run(
        ["git", "diff", "--name-only", "--", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    changed = {
        Path(line.strip())
        for line in tracked.stdout.splitlines()
        if line.strip()
    }
    changed.update(
        Path(line.strip())
        for line in untracked.stdout.splitlines()
        if line.strip()
    )
    return sorted(changed)


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
        if current_path.suffix.lower() == ".json":
            if filename not in NONDETERMINISTIC_KEYS_BY_FILE:
                errors.append(f"{relative_path}: substantive generated-output drift")
                continue

            try:
                current_payload = json.loads(current_path.read_text(encoding="utf-8"))
                committed_payload = json.loads(
                    _committed_bytes(current_path).decode("utf-8")
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{relative_path}: cannot compare JSON safely: {exc}")
                continue

            try:
                in_sync = compare_json_payloads(
                    current_payload,
                    committed_payload,
                    filename=filename,
                )
            except ValueError as exc:
                errors.append(f"{relative_path}: {exc}")
                continue

            if not in_sync:
                errors.append(f"{relative_path}: substantive JSON drift")
            continue

        if current_path.suffix.lower() == ".csv":
            if filename not in NONDETERMINISTIC_COLUMNS_BY_FILE:
                errors.append(f"{relative_path}: substantive generated-output drift")
                continue

            try:
                current_text = current_path.read_text(encoding="utf-8")
                committed_text = _committed_bytes(current_path).decode("utf-8")
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors.append(f"{relative_path}: cannot compare CSV safely: {exc}")
                continue

            try:
                in_sync = compare_csv_payloads(current_text, committed_text, filename=filename)
            except ValueError as exc:
                errors.append(f"{relative_path}: {exc}")
                continue

            if not in_sync:
                errors.append(f"{relative_path}: substantive CSV drift")
            continue

        errors.append(f"{relative_path}: substantive generated-output drift")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="outputs")
    args = parser.parse_args(argv)

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
