#!/usr/bin/env python3
"""Validate integrity of archived runs under outputs/run_archive/."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

MANIFEST_SCHEMA_PATH = "schemas/run_archive_manifest.schema.json"
CHECKSUM_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CHECKSUM_SEPARATOR = "  "


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_safe_relative(path_text: str) -> bool:
    if not path_text or path_text.startswith("/"):
        return False
    path = Path(path_text)
    return ".." not in path.parts


def _parse_checksums(path: Path) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    checksums: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {}, [f"{path}: cannot read checksum file: {exc}"]

    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        if CHECKSUM_SEPARATOR not in raw_line:
            errors.append(f"{path}: invalid checksum format on line {index}")
            continue
        digest, rel_path = raw_line.split(CHECKSUM_SEPARATOR, maxsplit=1)
        digest = digest.strip()
        rel_path = rel_path.strip()
        if not CHECKSUM_PATTERN.match(digest):
            errors.append(f"{path}: invalid sha256 digest on line {index}")
            continue
        if not _is_safe_relative(rel_path):
            errors.append(f"{path}: unsafe relative path on line {index}: {rel_path}")
            continue
        if rel_path in checksums:
            errors.append(f"{path}: duplicate checksum entry for {rel_path}")
            continue
        checksums[rel_path] = digest
    return checksums, errors


def _collect_archived_paths(run_dir: Path) -> list[Path]:
    ignored = {"_run_manifest.json", "_checksums.sha256"}
    return sorted(
        item
        for item in run_dir.rglob("*")
        if item.is_file() and item.relative_to(run_dir).as_posix() not in ignored
    )


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path}: invalid JSON ({exc})"


def _validate_one_run(
    run_dir: Path, validator: Draft202012Validator
) -> tuple[str, list[str]]:
    run_id = run_dir.name
    errors: list[str] = []

    manifest_path = run_dir / "_run_manifest.json"
    checksums_path = run_dir / "_checksums.sha256"

    if not manifest_path.is_file():
        errors.append(f"{run_dir}: missing _run_manifest.json")
        return run_id, errors
    if not checksums_path.is_file():
        errors.append(f"{run_dir}: missing _checksums.sha256")
        return run_id, errors

    manifest, manifest_error = _load_json(manifest_path)
    if manifest_error is not None:
        errors.append(manifest_error)
        return run_id, errors
    if not isinstance(manifest, dict):
        errors.append(f"{manifest_path}: manifest root must be a JSON object")
        return run_id, errors

    schema_errors = sorted(validator.iter_errors(manifest), key=lambda item: item.path)
    if schema_errors:
        for schema_error in schema_errors:
            errors.append(f"{manifest_path}: schema validation error: {schema_error.message}")
        return run_id, errors

    if str(manifest.get("run_id", "")) != run_id:
        errors.append(f"{manifest_path}: run_id '{manifest.get('run_id')}' != directory '{run_id}'")

    manifest_files_raw = manifest.get("files", [])
    if not isinstance(manifest_files_raw, list):
        errors.append(f"{manifest_path}: files must be an array")
        return run_id, errors

    manifest_files: dict[str, dict[str, Any]] = {}
    for item in manifest_files_raw:
        if not isinstance(item, dict):
            errors.append(f"{manifest_path}: file descriptor must be an object")
            continue
        rel_path = str(item.get("path", ""))
        if not _is_safe_relative(rel_path):
            errors.append(f"{manifest_path}: unsafe file path in manifest: {rel_path}")
            continue
        if rel_path in manifest_files:
            errors.append(f"{manifest_path}: duplicate file entry in manifest: {rel_path}")
            continue
        manifest_files[rel_path] = item

    archived_paths = _collect_archived_paths(run_dir)
    archived_rel_paths = {item.relative_to(run_dir).as_posix(): item for item in archived_paths}

    if set(manifest_files.keys()) != set(archived_rel_paths.keys()):
        errors.append(
            f"{manifest_path}: manifest files set does not match archived files on disk"
        )

    checksums, checksum_errors = _parse_checksums(checksums_path)
    errors.extend(checksum_errors)
    if set(checksums.keys()) != set(archived_rel_paths.keys()):
        errors.append(
            f"{checksums_path}: checksum files set does not match archived files on disk"
        )

    for rel_path, archived_path in archived_rel_paths.items():
        digest = _sha256_file(archived_path)
        size_bytes = archived_path.stat().st_size

        manifest_item = manifest_files.get(rel_path)
        if manifest_item is not None:
            expected_digest = str(manifest_item.get("sha256", ""))
            expected_size = int(manifest_item.get("size_bytes", -1))
            if expected_digest != digest:
                errors.append(
                    f"{manifest_path}: sha256 mismatch for {rel_path} "
                    f"(expected {expected_digest}, got {digest})"
                )
            if expected_size != size_bytes:
                errors.append(
                    f"{manifest_path}: size mismatch for {rel_path} "
                    f"(expected {expected_size}, got {size_bytes})"
                )

        checksum_digest = checksums.get(rel_path)
        if checksum_digest is not None and checksum_digest != digest:
            errors.append(
                f"{checksums_path}: sha256 mismatch for {rel_path} "
                f"(expected {checksum_digest}, got {digest})"
            )

    expected_file_count = int(manifest.get("file_count", -1))
    expected_total_bytes = int(manifest.get("total_bytes", -1))
    actual_file_count = len(archived_rel_paths)
    actual_total_bytes = sum(path.stat().st_size for path in archived_paths)
    if expected_file_count != actual_file_count:
        errors.append(
            f"{manifest_path}: file_count mismatch "
            f"(expected {expected_file_count}, got {actual_file_count})"
        )
    if expected_total_bytes != actual_total_bytes:
        errors.append(
            f"{manifest_path}: total_bytes mismatch "
            f"(expected {expected_total_bytes}, got {actual_total_bytes})"
        )

    return run_id, errors


def _validate_index(archive_root: Path, run_ids: set[str]) -> list[str]:
    errors: list[str] = []
    index_path = archive_root / "_index" / "runs_index.jsonl"
    if not index_path.is_file():
        return [f"{index_path}: missing run index file"]

    entries: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(
            index_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict):
                errors.append(f"{index_path}: line {line_number} must be a JSON object")
                continue
            entries.append(entry)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{index_path}: invalid JSONL ({exc})"]

    if not entries:
        errors.append(f"{index_path}: expected at least one index entry")
        return errors

    indexed_runs: set[str] = set()
    for entry in entries:
        run_id = str(entry.get("run_id", ""))
        run_path = str(entry.get("run_path", ""))
        if run_id and run_path == f"runs/{run_id}":
            indexed_runs.add(run_id)

    missing = sorted(run_id for run_id in run_ids if run_id not in indexed_runs)
    if missing:
        errors.append(
            f"{index_path}: missing index entries for run ids: {', '.join(missing)}"
        )
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate run archive manifest/index/checksum integrity."
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root path (default: current directory).",
    )
    parser.add_argument(
        "--archive-root",
        default="outputs/run_archive",
        help="Archive root path relative to repo root (default: outputs/run_archive).",
    )
    parser.add_argument(
        "--require-present",
        action="store_true",
        help="Fail when archive root does not exist.",
    )
    return parser.parse_args([] if argv is None else argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(str(args.repo_root)).resolve()
    archive_root = (repo_root / str(args.archive_root)).resolve()
    schema_path = repo_root / MANIFEST_SCHEMA_PATH

    if not archive_root.exists():
        if args.require_present:
            print(
                f"ERROR: archive root not found at {archive_root} and --require-present was set",
                file=sys.stderr,
            )
            return 1
        print(f"Archive root not found at {archive_root}; skipping validation.")
        return 0

    if not archive_root.is_dir():
        print(f"ERROR: archive root exists but is not a directory: {archive_root}", file=sys.stderr)
        return 1

    if not schema_path.is_file():
        print(f"ERROR: manifest schema not found: {schema_path}", file=sys.stderr)
        return 1

    schema, schema_error = _load_json(schema_path)
    if schema_error is not None or not isinstance(schema, dict):
        print(
            f"ERROR: could not load manifest schema: {schema_error or 'invalid schema root'}",
            file=sys.stderr,
        )
        return 1
    validator = Draft202012Validator(schema)

    runs_dir = archive_root / "runs"
    if not runs_dir.is_dir():
        print(f"ERROR: missing runs directory: {runs_dir}", file=sys.stderr)
        return 1

    run_dirs = sorted(item for item in runs_dir.iterdir() if item.is_dir())
    if not run_dirs:
        print(f"ERROR: no archived runs found under {runs_dir}", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    run_ids: set[str] = set()
    for run_dir in run_dirs:
        run_id, run_errors = _validate_one_run(run_dir, validator)
        run_ids.add(run_id)
        all_errors.extend(run_errors)

    all_errors.extend(_validate_index(archive_root, run_ids))

    if all_errors:
        print("Run archive integrity validation FAILED:")
        for error in all_errors:
            print(f"  - {error}")
        return 1

    print(
        f"Run archive integrity validation passed for {len(run_dirs)} run(s) under {archive_root}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
