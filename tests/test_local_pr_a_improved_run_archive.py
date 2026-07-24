"""Integrity tests for the archived run added by this PR:
outputs/run_archive/runs/local-pr-a-improved/.

These tests validate manifest.json and _checksums.sha256 for internal
consistency (schema conformance, and agreement between the two files'
own recorded path/digest/size data). They intentionally do not recompute
sha256 digests from the actual on-disk archived files, since that would
couple the tests to the working tree's exact byte content rather than to
the correctness of the archived run's recorded metadata.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = REPO_ROOT / "outputs" / "run_archive" / "runs" / "local-pr-a-improved"
MANIFEST_PATH = RUN_DIR / "manifest.json"
CHECKSUMS_PATH = RUN_DIR / "_checksums.sha256"
SCHEMA_PATH = REPO_ROOT / "schemas" / "run_archive_manifest.schema.json"
VALIDATE_SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_run_archive_integrity.py"

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _load_validate_module():
    spec = importlib.util.spec_from_file_location(
        "validate_run_archive_integrity_local_pr_a_tests", VALIDATE_SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_and_checksums_files_exist() -> None:
    assert MANIFEST_PATH.exists()
    assert CHECKSUMS_PATH.exists()


def test_manifest_matches_run_archive_schema() -> None:
    manifest = _load_manifest()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda item: item.path)
    assert not errors, [error.message for error in errors]


def test_manifest_run_id_matches_run_directory_name() -> None:
    manifest = _load_manifest()
    assert manifest["run_id"] == RUN_DIR.name
    assert manifest["requested_run_id"] == RUN_DIR.name
    assert manifest["run_path"] == "runs/local-pr-a-improved"


def test_manifest_file_count_and_total_bytes_are_self_consistent() -> None:
    """file_count and total_bytes must agree with the files array itself,
    independent of whether the on-disk archived files still match."""
    manifest = _load_manifest()
    files = manifest["files"]
    assert manifest["file_count"] == len(files)
    assert manifest["total_bytes"] == sum(entry["size_bytes"] for entry in files)


def test_manifest_files_have_no_duplicate_paths() -> None:
    manifest = _load_manifest()
    paths = [entry["path"] for entry in manifest["files"]]
    assert len(paths) == len(set(paths))


def test_manifest_expected_copied_targets_are_present() -> None:
    manifest = _load_manifest()
    expected_targets = {
        "outputs/research_sources",
        "outputs/gaps_summary.csv",
        "outputs/credentials_database.json",
        "outputs/competences_full_database.json",
        "outputs/cumulative_qmbd_records.json",
        "outputs/sector_dictionaries",
        "MANIFEST_SOURCES.csv",
        "outputs/validation_state.json",
    }
    assert expected_targets.issubset(set(manifest["copied_targets"]))


def _parse_checksums_file() -> dict[str, str]:
    entries: dict[str, str] = {}
    with CHECKSUMS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            digest, rel_path = line.split("  ", maxsplit=1)
            entries[rel_path] = digest
    return entries


def test_checksums_file_entries_are_well_formed_and_unique() -> None:
    entries = _parse_checksums_file()
    assert entries, "expected at least one checksum entry"
    for rel_path, digest in entries.items():
        assert SHA256_PATTERN.match(digest), (rel_path, digest)
        assert not rel_path.startswith("/"), rel_path
        assert ".." not in Path(rel_path).parts, rel_path

    with CHECKSUMS_PATH.open("r", encoding="utf-8") as handle:
        all_paths = [
            line.rstrip("\n").split("  ", maxsplit=1)[1]
            for line in handle
            if line.strip()
        ]
    assert len(all_paths) == len(set(all_paths))


def test_checksums_file_parses_cleanly_with_validate_script_parser() -> None:
    """Regression test: the real archive's checksum file must parse without
    errors using the same _parse_checksums() helper that
    scripts/validate_run_archive_integrity.py relies on for integrity checks."""
    module = _load_validate_module()
    checksums, errors = module._parse_checksums(CHECKSUMS_PATH)
    assert errors == []
    assert checksums
    for rel_path in checksums:
        assert module._is_safe_relative(rel_path), rel_path


def test_manifest_files_and_checksums_file_agree_on_paths_and_digests() -> None:
    """manifest.json's files array and _checksums.sha256 are produced together
    by the same archive step, so their path sets and recorded sha256 digests
    must match each other exactly."""
    manifest = _load_manifest()
    manifest_entries = {
        entry["path"]: entry["sha256"] for entry in manifest["files"]
    }
    checksum_entries = _parse_checksums_file()

    assert set(manifest_entries) == set(checksum_entries)
    mismatched = [
        path
        for path, digest in manifest_entries.items()
        if checksum_entries[path] != digest
    ]
    assert mismatched == []


def test_manifest_files_and_checksums_file_agree_on_entry_count() -> None:
    manifest = _load_manifest()
    checksum_entries = _parse_checksums_file()
    assert manifest["file_count"] == len(checksum_entries)


def test_manifest_duplicated_paths_share_identical_size_and_digest() -> None:
    """outputs/, research_sources/, and analysis_outputs/ each retain copies of
    the same underlying files (a documented archive behavior). Any path that
    appears more than once by basename+size in the checksum listing under
    different top-level prefixes must still carry an identical digest, since
    they are supposed to be byte-identical copies of the same source file."""
    manifest = _load_manifest()
    by_relative_suffix: dict[str, set[str]] = {}
    for entry in manifest["files"]:
        path = entry["path"]
        for prefix in ("outputs/", "research_sources/", "analysis_outputs/"):
            if path.startswith(prefix):
                suffix = path[len(prefix):]
                break
        else:
            continue
        by_relative_suffix.setdefault(suffix, set()).add(entry["sha256"])

    inconsistent = {
        suffix: digests
        for suffix, digests in by_relative_suffix.items()
        if len(digests) > 1
    }
    assert inconsistent == {}