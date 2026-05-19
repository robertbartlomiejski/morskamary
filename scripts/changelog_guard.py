#!/usr/bin/env python3
"""Enforce CHANGELOG.txt updates for substantive repository changes."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence

CHANGELOG_PATH = "CHANGELOG.txt"
TRIGGER_PREFIXES = ("scripts/", "prompts/", "templates/", "data/")
TRIGGER_SUFFIXES = (".csv", ".xlsx", ".pdf")
TRIGGER_EXACT_PATHS = {
    "CITATION.txt",
    "DATA_GOVERNANCE.txt",
    "LLM_CONTEXT_INSTRUCTION.txt",
}


@dataclass(frozen=True)
class ChangelogCheckResult:
    """Structured result for the changelog policy check."""

    changed_files: tuple[str, ...]
    triggering_files: tuple[str, ...]
    requires_changelog: bool
    has_changelog_update: bool
    missing_changelog: bool


def normalize_changed_file(path: str) -> str:
    """Normalize a git diff path to repository-relative POSIX form."""
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        return ""
    normalized_path = PurePosixPath(normalized).as_posix()
    return "" if normalized_path == "." else normalized_path


def requires_changelog_for_file(path: str) -> bool:
    """Return True when a changed file should require a changelog update."""
    normalized = normalize_changed_file(path)
    if not normalized or normalized == CHANGELOG_PATH:
        return False
    if normalized in TRIGGER_EXACT_PATHS:
        return True
    if normalized.endswith(TRIGGER_SUFFIXES):
        return True
    return normalized.startswith(TRIGGER_PREFIXES)


def evaluate_changed_files(changed_files: Iterable[str]) -> ChangelogCheckResult:
    """Evaluate whether the provided changed files require a changelog update."""
    normalized_files = tuple(
        normalized
        for path in changed_files
        if (normalized := normalize_changed_file(path))
    )
    triggering_files = tuple(
        path for path in normalized_files if requires_changelog_for_file(path)
    )
    has_changelog_update = CHANGELOG_PATH in normalized_files
    requires_changelog = bool(triggering_files)
    return ChangelogCheckResult(
        changed_files=normalized_files,
        triggering_files=triggering_files,
        requires_changelog=requires_changelog,
        has_changelog_update=has_changelog_update,
        missing_changelog=requires_changelog and not has_changelog_update,
    )


def diff_changed_files(
    base_ref: str,
    head_ref: str = "HEAD",
    repo_root: Path | None = None,
) -> tuple[str, ...]:
    """Return repository-relative changed files between the base ref and head."""
    if not base_ref.strip():
        raise ValueError("base_ref must not be empty")
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base_ref}...{head_ref}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "git diff failed"
        raise RuntimeError(stderr)
    return tuple(
        normalized
        for line in completed.stdout.splitlines()
        if (normalized := normalize_changed_file(line))
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the changelog guard as a CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root used for git diff when --base-ref is provided.",
    )
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="Explicit changed file path. May be repeated.",
    )
    args = parser.parse_args(argv)

    explicit_changed_files = tuple(args.changed_file)
    if explicit_changed_files:
        changed_files = explicit_changed_files
    else:
        if not args.base_ref:
            parser.error("either --base-ref or at least one --changed-file is required")
        changed_files = diff_changed_files(
            base_ref=args.base_ref,
            head_ref=args.head_ref,
            repo_root=Path(args.repo_root),
        )

    result = evaluate_changed_files(changed_files)
    if result.missing_changelog:
        print("PR changes substantive artifacts but does not update CHANGELOG.txt.")
        print("Changed files:")
        for path in result.changed_files:
            print(path)
        return 1

    print("CHANGELOG enforcement passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
