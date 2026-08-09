#!/usr/bin/env python3
"""Validate integrity of archived runs under outputs/run_archive/."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

MANIFEST_SCHEMA_PATH = "schemas/run_archive_manifest.schema.json"
CANONICAL_MANIFEST_FILENAME = "manifest.json"
RUN_MANIFEST_FILENAME = "run_manifest.json"
LEGACY_RUN_MANIFEST_FILENAME = "_run_manifest.json"
INDEX_CSV_FILENAME = "cumulative_runs_index.csv"
INDEX_CSV_REQUIRED_COLUMNS: tuple[str, ...] = (
    "timestamp_utc",
    "analysis_timestamp_utc",
    "run_id",
    "run_path",
    "github_run_id",
    "github_run_attempt",
    "github_run_number",
    "github_job",
    "workflow_name",
    "event_name",
    "commit_sha",
    "branch_ref",
    "providers",
    "max_results_per_query",
    "offline",
    "require_live_records",
    "query_file_sha256",
    "live_records_count",
    "triangulated_records_count",
    "cumulative_qmbd_records_count",
    "competences_total",
    "baseline_count",
    "static_literature_count",
    "live_enrichment_count",
    "gaps_summary_available",
    "credentials_count",
    "file_count",
    "total_bytes",
)
INDEX_CSV_MANIFEST_FIELDS: tuple[str, ...] = (
    "timestamp_utc",
    "analysis_timestamp_utc",
    "github_run_id",
    "github_run_attempt",
    "github_run_number",
    "github_job",
    "workflow_name",
    "event_name",
    "commit_sha",
    "branch_ref",
    "providers",
    "max_results_per_query",
    "offline",
    "require_live_records",
    "query_file_sha256",
    "live_records_count",
    "triangulated_records_count",
    "cumulative_qmbd_records_count",
    "competences_total",
    "baseline_count",
    "static_literature_count",
    "live_enrichment_count",
    "gaps_summary_available",
    "credentials_count",
)
CHECKSUM_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CHECKSUM_SEPARATOR = "  "
TEXT_SCAN_SUFFIXES = frozenset(
    {".csv", ".html", ".json", ".jsonl", ".md", ".sha256", ".txt", ".yml", ".yaml"}
)
LEGACY_PATH_METADATA_MANIFEST_SHA256 = {
    "28625632237-1": "44b2c5cffa7827d6de2cd0f6de1b896598b7dc027abb8f2f3618b6e254233aa6",
    "28967267944.2": "e425d4eb99dea0295c336c7ba04a53df94921dcedb2b86191a9833cf3b28ebe9",
    "30090903921-1": "e8b66a5d7d2451f19ea6de760985c53fceb7060cbfa6bb513e624a045f8e35d4",
}
LEGACY_INDEX_TOTALS: dict[str, tuple[int, int]] = {
    "28625632237-1": (64, 44642361),
    "28967267944.2": (64, 45636058),
    "30090903921-1": (76, 74314641),
}
ABSOLUTE_PATH_PATTERN = re.compile(
    r"""
    (?:
        (?<![A-Za-z0-9:])[A-Za-z]:[\\/][^\s"'<>]+
        |
        \\{2,}[^\s\\/"'<>]+[\\/]+[^\s\\/"'<>]+(?:[\\/]+[^\s"'<>]+)*
        |
        (?<![A-Za-z0-9:])/(?!/)[^\s/"'<>]+(?:/[^\s/"'<>]+)+
    )
    """,
    re.VERBOSE,
)
ENCODED_HTML_CLOSING_TAG_PATTERN = re.compile(
    r"&lt;/[A-Za-z][A-Za-z0-9:-]*\s*&gt;",
    re.IGNORECASE,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_safe_relative(path_text: str) -> bool:
    if not path_text or path_text.startswith("/"):
        return False
    if PureWindowsPath(path_text).is_absolute():
        return False
    path = Path(path_text)
    return ".." not in path.parts


def _looks_like_absolute_path(path_text: str) -> bool:
    return Path(path_text).is_absolute() or PureWindowsPath(path_text).is_absolute()


def _is_valid_utc_iso8601(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _index_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value if value is not None else "").strip()


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
    ignored = {
        CANONICAL_MANIFEST_FILENAME,
        RUN_MANIFEST_FILENAME,
        LEGACY_RUN_MANIFEST_FILENAME,
        "_checksums.sha256",
    }
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


def _is_grandfathered_legacy_run(run_id: str, manifest_path: Path) -> bool:
    expected_digest = LEGACY_PATH_METADATA_MANIFEST_SHA256.get(run_id)
    return bool(
        expected_digest
        and manifest_path.is_file()
        and _sha256_file(manifest_path) == expected_digest
    )


def _allows_legacy_absolute_index_path(run_id: str, archive_root: Path) -> bool:
    return _is_grandfathered_legacy_run(
        run_id, archive_root / "runs" / run_id / CANONICAL_MANIFEST_FILENAME
    )


def _legacy_index_totals(
    run_id: str, archive_root: Path
) -> tuple[int, int] | None:
    if not _allows_legacy_absolute_index_path(run_id, archive_root):
        return None
    return LEGACY_INDEX_TOTALS.get(run_id)


def _count_absolute_path_leaks(text: str, *, repo_root: Path) -> int:
    scan_text = ENCODED_HTML_CLOSING_TAG_PATTERN.sub(" ", text)
    normalized_repo_root = repo_root.resolve().as_posix().rstrip("/")
    explicit_root_matches = scan_text.count(normalized_repo_root + "/")
    portable_matches = sum(
        1
        for match in ABSOLUTE_PATH_PATTERN.finditer(scan_text)
        if not (
            match.group().startswith("/")
            and scan_text[: match.start()].endswith(":/")
        )
    )
    return max(explicit_root_matches, portable_matches)


def _validate_public_path_leaks(
    run_dir: Path,
    archived_paths: list[Path],
    *,
    repo_root: Path,
) -> list[str]:
    errors: list[str] = []
    for archived_path in archived_paths:
        if archived_path.suffix.lower() not in TEXT_SCAN_SUFFIXES:
            continue
        try:
            text = archived_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"{archived_path}: expected UTF-8 text artifact")
            continue
        except OSError as exc:
            errors.append(f"{archived_path}: cannot read text artifact: {exc}")
            continue
        matches = _count_absolute_path_leaks(text, repo_root=repo_root)
        if matches:
            rel_path = archived_path.relative_to(run_dir).as_posix()
            errors.append(
                f"{run_dir / CANONICAL_MANIFEST_FILENAME}: public artifact path leak in "
                f"{rel_path} ({matches} occurrence(s))"
            )
    return errors


def _validate_one_run(
    run_dir: Path, validator: Draft202012Validator, *, repo_root: Path
) -> tuple[str, dict[str, Any] | None, list[str]]:
    run_id = run_dir.name
    errors: list[str] = []

    manifest_path = run_dir / CANONICAL_MANIFEST_FILENAME
    compat_manifest_path = run_dir / RUN_MANIFEST_FILENAME
    legacy_manifest_path = run_dir / LEGACY_RUN_MANIFEST_FILENAME
    checksums_path = run_dir / "_checksums.sha256"

    if not manifest_path.is_file():
        if compat_manifest_path.is_file():
            manifest_path = compat_manifest_path
        elif legacy_manifest_path.is_file():
            manifest_path = legacy_manifest_path
        else:
            errors.append(
                f"{run_dir}: missing {CANONICAL_MANIFEST_FILENAME} "
                f"(or compatibility {RUN_MANIFEST_FILENAME}/{LEGACY_RUN_MANIFEST_FILENAME})"
            )
            return run_id, None, errors
    if not checksums_path.is_file():
        errors.append(f"{run_dir}: missing _checksums.sha256")
        return run_id, None, errors

    manifest, manifest_error = _load_json(manifest_path)
    if manifest_error is not None:
        errors.append(manifest_error)
        return run_id, None, errors
    if not isinstance(manifest, dict):
        errors.append(f"{manifest_path}: manifest root must be a JSON object")
        return run_id, None, errors

    schema_errors = sorted(validator.iter_errors(manifest), key=lambda item: item.path)
    if schema_errors:
        for schema_error in schema_errors:
            errors.append(f"{manifest_path}: schema validation error: {schema_error.message}")
        return run_id, None, errors

    if str(manifest.get("run_id", "")) != run_id:
        errors.append(f"{manifest_path}: run_id '{manifest.get('run_id')}' != directory '{run_id}'")
    grandfathered_legacy_run = _is_grandfathered_legacy_run(run_id, manifest_path)
    archive_root = str(manifest.get("archive_root", "")).strip()
    if (
        archive_root
        and not _is_safe_relative(archive_root)
        and not grandfathered_legacy_run
    ):
        errors.append(f"{manifest_path}: unsafe archive_root in manifest: {archive_root}")

    manifest_files_raw = manifest.get("files", [])
    if not isinstance(manifest_files_raw, list):
        errors.append(f"{manifest_path}: files must be an array")
        return run_id, None, errors

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
    if not grandfathered_legacy_run:
        errors.extend(
            _validate_public_path_leaks(run_dir, archived_paths, repo_root=repo_root)
        )

    return run_id, manifest, errors


def _validate_index_totals(
    index_path: Path,
    location: str,
    run_id: str,
    entry: dict[str, Any],
    expected_totals: tuple[int, int],
    legacy_totals: tuple[int, int] | None = None,
) -> list[str]:
    errors: list[str] = []
    fields = ("file_count", "total_bytes")
    actual_totals: list[int] = []
    for field in fields:
        raw_value = entry.get(field)
        try:
            actual_totals.append(int(str(raw_value).strip()))
        except (TypeError, ValueError):
            errors.append(
                f"{index_path}: invalid {field} for run_id '{run_id}' at {location}: "
                f"{raw_value!r}"
            )
    if errors:
        return errors

    actual_totals_tuple = tuple(actual_totals)
    if actual_totals_tuple == expected_totals or actual_totals_tuple == legacy_totals:
        return []

    for field, expected_value, actual_value in zip(
        fields, expected_totals, actual_totals_tuple, strict=True
    ):
        if actual_value != expected_value:
            errors.append(
                f"{index_path}: inconsistent {field} for run_id '{run_id}' at "
                f"{location} (expected {expected_value}, got {actual_value})"
            )
    return errors


def _validate_index_jsonl(
    archive_root: Path,
    run_ids: set[str],
    expected_manifests: dict[str, dict[str, Any]],
    expected_manifest_totals: dict[str, tuple[int, int]],
) -> list[str]:
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
    for line_number, entry in enumerate(entries, start=1):
        run_id = str(entry.get("run_id", ""))
        run_path = str(entry.get("run_path", ""))
        if not run_id:
            errors.append(f"{index_path}: line {line_number} has a blank run_id")
            continue
        if run_id not in run_ids:
            errors.append(
                f"{index_path}: line {line_number} references unknown run_id "
                f"'{run_id}'"
            )
            continue
        if run_id and run_path == f"runs/{run_id}":
            archived_at = entry.get("archived_at")
            if not _is_valid_utc_iso8601(archived_at):
                errors.append(
                    f"{index_path}: archived_at for run_id '{run_id}' on line "
                    f"{line_number} must be a nonblank UTC ISO-8601 timestamp"
                )
                continue
            manifest_timestamp = expected_manifests.get(run_id, {}).get(
                "timestamp_utc"
            )
            if _index_scalar(archived_at) != _index_scalar(manifest_timestamp):
                errors.append(
                    f"{index_path}: archived_at for run_id '{run_id}' on line "
                    f"{line_number} does not match manifest timestamp_utc"
                )
                continue
            expected_totals = expected_manifest_totals.get(run_id)
            if expected_totals is not None:
                entry_errors = _validate_index_totals(
                    index_path,
                    f"line {line_number}",
                    run_id,
                    entry,
                    expected_totals,
                    _legacy_index_totals(run_id, archive_root),
                )
                errors.extend(entry_errors)
                if entry_errors:
                    continue
            indexed_runs.add(run_id)

    missing = sorted(run_id for run_id in run_ids if run_id not in indexed_runs)
    if missing:
        errors.append(
            f"{index_path}: missing index entries for run ids: {', '.join(missing)}"
        )
    return errors


def _validate_index_csv(
    archive_root: Path,
    run_ids: set[str],
    expected_manifests: dict[str, dict[str, Any]],
    expected_manifest_totals: dict[str, tuple[int, int]],
) -> list[str]:
    errors: list[str] = []
    csv_path = archive_root / INDEX_CSV_FILENAME
    if not csv_path.is_file():
        return [f"{csv_path}: missing cumulative run index file"]

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            missing_columns = [
                column
                for column in INDEX_CSV_REQUIRED_COLUMNS
                if column not in fieldnames
            ]
            if missing_columns:
                errors.append(
                    f"{csv_path}: missing required columns: {', '.join(missing_columns)}"
                )
                return errors

            rows = list(reader)
    except OSError as exc:
        return [f"{csv_path}: cannot read CSV index ({exc})"]
    except csv.Error as exc:
        return [f"{csv_path}: invalid CSV ({exc})"]

    if not rows:
        return [f"{csv_path}: expected at least one index entry"]

    indexed_runs: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        run_id = str(row.get("run_id", "")).strip()
        run_path = str(row.get("run_path", "")).strip()
        if not run_id:
            errors.append(f"{csv_path}: line {row_number} has a blank run_id")
            continue
        if run_id not in run_ids:
            errors.append(
                f"{csv_path}: line {row_number} references unknown run_id '{run_id}'"
            )
            continue
        if run_id in run_ids:
            expected_relative = f"runs/{run_id}"
            legacy_absolute_path_allowed = (
                _looks_like_absolute_path(run_path)
                and _allows_legacy_absolute_index_path(run_id, archive_root)
                and (
                    Path(run_path).name == run_id
                    or PureWindowsPath(run_path).name == run_id
                )
            )
            if run_path != expected_relative and not legacy_absolute_path_allowed:
                errors.append(
                    f"{csv_path}: inconsistent run_path for run_id '{run_id}' on line "
                    f"{row_number} (expected {expected_relative}; absolute paths are "
                    f"allowed only for fingerprinted legacy manifests, got {run_path})"
                )
                continue
            archive_root_value = str(row.get("archive_root", "")).strip()
            if archive_root_value and not _is_safe_relative(archive_root_value):
                errors.append(
                    f"{csv_path}: unsafe archive_root for run_id '{run_id}' on line "
                    f"{row_number}: {archive_root_value}"
                )
                continue
            manifest = expected_manifests.get(run_id, {})
            for timestamp_field in ("timestamp_utc", "analysis_timestamp_utc"):
                timestamp_value = row.get(timestamp_field)
                if not _is_valid_utc_iso8601(timestamp_value):
                    errors.append(
                        f"{csv_path}: {timestamp_field} for run_id '{run_id}' on "
                        f"line {row_number} must be a nonblank UTC ISO-8601 timestamp"
                    )
            metadata_errors = False
            for field in INDEX_CSV_MANIFEST_FIELDS:
                if _index_scalar(row.get(field)) != _index_scalar(
                    manifest.get(field)
                ):
                    errors.append(
                        f"{csv_path}: {field} for run_id '{run_id}' on line "
                        f"{row_number} does not match manifest metadata"
                    )
                    metadata_errors = True
            if metadata_errors:
                continue
            expected_totals = expected_manifest_totals.get(run_id)
            if expected_totals is not None:
                row_errors = _validate_index_totals(
                    csv_path,
                    f"line {row_number}",
                    run_id,
                    row,
                    expected_totals,
                    _legacy_index_totals(run_id, archive_root),
                )
                errors.extend(row_errors)
                if row_errors:
                    continue
            indexed_runs.add(run_id)

    missing = sorted(run_id for run_id in run_ids if run_id not in indexed_runs)
    if missing:
        errors.append(
            f"{csv_path}: missing index entries for run ids: {', '.join(missing)}"
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
    expected_manifests: dict[str, dict[str, Any]] = {}
    expected_manifest_totals: dict[str, tuple[int, int]] = {}
    for run_dir in run_dirs:
        run_id, manifest, run_errors = _validate_one_run(
            run_dir,
            validator,
            repo_root=repo_root,
        )
        run_ids.add(run_id)
        if manifest is not None:
            expected_manifests[run_id] = manifest
            expected_manifest_totals[run_id] = (
                int(manifest["file_count"]),
                int(manifest["total_bytes"]),
            )
        all_errors.extend(run_errors)

    all_errors.extend(
        _validate_index_jsonl(
            archive_root,
            run_ids,
            expected_manifests,
            expected_manifest_totals,
        )
    )
    all_errors.extend(
        _validate_index_csv(
            archive_root,
            run_ids,
            expected_manifests,
            expected_manifest_totals,
        )
    )

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
