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

    def _run_git(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command),
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )

    def _git_stderr(completed: subprocess.CompletedProcess[str], fallback: str) -> str:
        return completed.stderr.strip() or fallback

    def _run_name_only_diff(diff_base: str) -> subprocess.CompletedProcess[str]:
        return _run_git(["git", "diff", "--name-only", f"{diff_base}..{head_ref}"])

    origin_base_ref = f"origin/{base_ref}"
    merge_base_completed = _run_git(["git", "merge-base", origin_base_ref, head_ref])
    if merge_base_completed.returncode == 0:
        merge_base = merge_base_completed.stdout.strip()
        if not merge_base:
            raise RuntimeError(
                f"git merge-base {origin_base_ref} {head_ref} returned an empty commit"
            )
        completed = _run_name_only_diff(merge_base)
        if completed.returncode != 0:
            stderr = _git_stderr(completed, "git diff failed")
            raise RuntimeError(
                f"git diff --name-only {merge_base}..{head_ref} failed: {stderr}"
            )
    else:
        merge_base_stderr = _git_stderr(
            merge_base_completed, f"git merge-base {origin_base_ref} {head_ref} failed"
        )
        shallow_check = _run_git(["git", "rev-parse", "--is-shallow-repository"])
        is_shallow_repository = shallow_check.returncode == 0 and (
            shallow_check.stdout.strip().lower() == "true"
        )
        allow_fallback_diff = is_shallow_repository or (
            "no merge base" in merge_base_stderr.lower()
        )
        if is_shallow_repository:
            deepen_completed = _run_git(
                ["git", "fetch", "--no-tags", "--deepen=200", "origin", base_ref]
            )
            if deepen_completed.returncode == 0:
                merge_base_completed = _run_git(["git", "merge-base", origin_base_ref, head_ref])
                if merge_base_completed.returncode == 0:
                    merge_base = merge_base_completed.stdout.strip()
                    if not merge_base:
                        raise RuntimeError(
                            f"git merge-base {origin_base_ref} {head_ref} returned an empty commit after fetch retry"
                        )
                    completed = _run_name_only_diff(merge_base)
                    if completed.returncode != 0:
                        stderr = _git_stderr(completed, "git diff failed")
                        raise RuntimeError(
                            f"git diff --name-only {merge_base}..{head_ref} failed after fetch retry: {stderr}"
                        )
                else:
                    merge_base_stderr = _git_stderr(
                        merge_base_completed,
                        f"git merge-base {origin_base_ref} {head_ref} failed after fetch retry",
                    )
            else:
                merge_base_stderr = (
                    f"{merge_base_stderr}; git fetch --no-tags --deepen=200 origin {base_ref} "
                    f"failed: {_git_stderr(deepen_completed, 'git fetch failed')}"
                )
        if merge_base_completed.returncode != 0:
            if not allow_fallback_diff:
                raise RuntimeError(
                    f"git merge-base {origin_base_ref} {head_ref} failed: {merge_base_stderr}"
                )
            completed = _run_name_only_diff(origin_base_ref)
            if completed.returncode != 0:
                fallback_stderr = _git_stderr(completed, "git diff failed")
                raise RuntimeError(
                    f"git merge-base {origin_base_ref} {head_ref} failed: {merge_base_stderr}; "
                    f"fallback git diff --name-only {origin_base_ref}..{head_ref} failed: {fallback_stderr}"
                )
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
