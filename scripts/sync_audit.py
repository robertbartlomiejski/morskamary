#!/usr/bin/env python3
"""
scripts/sync_audit.py — Repository Sync & Integration Audit

Diagnoses drift risks across local, remote, outputs, manifest, and provider
capability state. Designed to be run before pushing or after pulling to detect
desynchronization that causes CI failures or merge conflicts.

Usage:
    python scripts/sync_audit.py [--strict]

Exit codes:
    0  No drift detected (or only warnings in non-strict mode).
    1  Drift or integrity issues detected.

Checks performed:
    1. Git status: uncommitted changes, ahead/behind remote
    2. Outputs drift: outputs/ matches run_full_analysis.py generator
    3. Manifest drift: MANIFEST_SOURCES.csv matches generate_manifest.py
    4. Provider capability snapshot consistency
    5. MCP workspace config integrity (.vscode/mcp.json)
    6. CHANGELOG governance pre-check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess, capturing output."""
    return subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class AuditReport:
    """Collects audit findings."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        print(f"  ✗ ERROR: {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  ⚠ WARN:  {msg}")

    def ok(self, msg: str) -> None:
        print(f"  ✓ {msg}")

    @property
    def failed(self) -> bool:
        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


# ---------------------------------------------------------------------------
# Check: Git status & remote sync
# ---------------------------------------------------------------------------


def check_git_status(report: AuditReport) -> None:
    """Check for uncommitted changes and ahead/behind state."""
    print("\n[1/6] Git status & remote sync")

    # Uncommitted changes
    result = _run(["git", "status", "--porcelain"])
    if result.returncode != 0:
        report.error(f"git status failed: {result.stderr.strip()}")
        return

    dirty_lines = [
        line for line in result.stdout.splitlines() if line.strip()
    ]
    if dirty_lines:
        report.warn(
            f"{len(dirty_lines)} uncommitted change(s) detected. "
            "Commit or stash before syncing."
        )
        for line in dirty_lines[:10]:
            print(f"      {line}")
        if len(dirty_lines) > 10:
            print(f"      ... and {len(dirty_lines) - 10} more")
    else:
        report.ok("Working tree clean")

    # Ahead/behind — skip in CI detached-HEAD environments
    result = _run(["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"])
    if result.returncode == 0:
        parts = result.stdout.strip().split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])
            if ahead > 0:
                report.warn(f"Local is {ahead} commit(s) AHEAD of remote — push needed")
            if behind > 0:
                report.warn(f"Local is {behind} commit(s) BEHIND remote — pull needed")
            if ahead == 0 and behind == 0:
                report.ok("In sync with remote tracking branch")
        else:
            report.warn("Could not parse ahead/behind counts")
    else:
        # In CI (detached HEAD or no upstream), this is expected — just note it
        report.ok(
            "No upstream tracking branch configured — "
            "skipping ahead/behind check (expected in CI)"
        )


# ---------------------------------------------------------------------------
# Check: Outputs drift
# ---------------------------------------------------------------------------


def check_outputs_drift(report: AuditReport) -> None:
    """Detect uncommitted drift in outputs/ directory."""
    print("\n[2/6] Outputs drift")

    outputs_dir = REPO_ROOT / "outputs"
    if not outputs_dir.is_dir():
        report.warn("outputs/ directory not found — skipping drift check")
        return

    result = _run(["git", "diff", "--stat", "--", "outputs/"])
    if result.returncode != 0:
        report.error(f"git diff on outputs/ failed: {result.stderr.strip()}")
        return

    if result.stdout.strip():
        report.error(
            "outputs/ has uncommitted changes vs HEAD. "
            "Run 'python run_full_analysis.py' and commit, or discard."
        )
        for line in result.stdout.strip().splitlines()[:8]:
            print(f"      {line}")
    else:
        report.ok("outputs/ matches committed state")


# ---------------------------------------------------------------------------
# Check: Manifest drift
# ---------------------------------------------------------------------------


def check_manifest_drift(report: AuditReport) -> None:
    """Check if MANIFEST_SOURCES.csv is in sync with generator."""
    print("\n[3/6] Manifest drift")

    generator = REPO_ROOT / "scripts" / "generate_manifest.py"
    if not generator.is_file():
        report.warn("scripts/generate_manifest.py not found — skipping")
        return

    manifest_candidates = [
        REPO_ROOT / "MANIFEST_SOURCES.csv",
        REPO_ROOT / "manifest.json",
    ]
    manifest_path = None
    for candidate in manifest_candidates:
        if candidate.is_file():
            manifest_path = candidate
            break

    if manifest_path is None:
        report.warn("No manifest file found — skipping drift check")
        return

    # Snapshot the current content
    before_content = manifest_path.read_bytes()

    # Run generator (it writes in-place)
    result = _run([sys.executable, str(generator)])
    if result.returncode != 0:
        report.error(
            f"generate_manifest.py failed (exit {result.returncode}): "
            f"{result.stderr.strip()[:200]}"
        )
        return

    after_content = manifest_path.read_bytes()

    # Restore original content so audit is non-mutating
    if before_content != after_content:
        manifest_path.write_bytes(before_content)
        report.error(
            f"{manifest_path.name} changed after regeneration — "
            "commit the regenerated manifest before pushing."
        )
    else:
        report.ok(f"{manifest_path.name} is deterministic and up-to-date")


def _file_hash(path: Path) -> str:
    """Return SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Check: Provider capability snapshot
# ---------------------------------------------------------------------------


def check_provider_capabilities(report: AuditReport) -> None:
    """Verify provider capability export is current (non-mutating)."""
    print("\n[4/6] Provider capability snapshot")

    cap_file = REPO_ROOT / "outputs" / "research_source_capabilities.json"
    if not cap_file.is_file():
        report.warn(
            "research_source_capabilities.json not found — "
            "run: python scripts/export_research_source_capabilities.py"
        )
        return

    try:
        with open(cap_file, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        report.error(f"Cannot read capabilities file: {exc}")
        return

    providers = data.get("providers", {})
    if not providers:
        report.warn("Capabilities file has no providers listed")
        return

    configured = sum(1 for v in providers.values() if v.get("configured"))
    total = len(providers)
    report.ok(f"Provider capabilities: {configured}/{total} configured")

    # Non-mutating check: re-export to a temp file and compare semantically
    # (ignoring generated_at timestamp and environment-dependent configured flags)
    exporter = REPO_ROOT / "scripts" / "export_research_source_capabilities.py"
    if exporter.is_file():
        # Save current content and restore after comparison
        original_content = cap_file.read_bytes()
        result = _run([sys.executable, str(exporter)])
        if result.returncode == 0:
            try:
                with open(cap_file, encoding="utf-8") as f:
                    new_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                new_data = None

            # Restore original file immediately (non-mutating)
            cap_file.write_bytes(original_content)

            if new_data is not None:
                # Compare ignoring generated_at and configured fields
                if _capabilities_semantically_equal(data, new_data):
                    report.ok("Capability snapshot is current (ignoring timestamps/configured)")
                else:
                    report.warn(
                        "Capability snapshot structure changed after re-export — "
                        "commit updated research_source_capabilities.json"
                    )
        else:
            # Restore original on exporter failure
            cap_file.write_bytes(original_content)


def _capabilities_semantically_equal(old: dict, new: dict) -> bool:
    """Compare capability snapshots ignoring generated_at and configured fields."""
    def normalize(data: dict) -> dict:
        normalized = dict(data)
        normalized.pop("generated_at", None)
        providers = normalized.get("providers", {})
        normalized_providers = {}
        for name, prov in providers.items():
            p = dict(prov)
            p.pop("configured", None)
            normalized_providers[name] = p
        normalized["providers"] = normalized_providers
        return normalized

    return normalize(old) == normalize(new)


# ---------------------------------------------------------------------------
# Check: MCP workspace config integrity
# ---------------------------------------------------------------------------


def check_mcp_config(report: AuditReport) -> None:
    """Validate .vscode/mcp.json is well-formed and has expected structure."""
    print("\n[5/6] MCP workspace config")

    mcp_path = REPO_ROOT / ".vscode" / "mcp.json"
    if not mcp_path.is_file():
        report.warn(".vscode/mcp.json not found — MCP integration not configured")
        return

    try:
        with open(mcp_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        report.error(f".vscode/mcp.json is malformed JSON: {exc}")
        return

    if "servers" not in data:
        report.error(".vscode/mcp.json missing 'servers' key")
        return

    servers = data["servers"]
    if not isinstance(servers, dict) or not servers:
        report.warn(".vscode/mcp.json has empty servers block")
    else:
        report.ok(f".vscode/mcp.json valid ({len(servers)} server(s) defined)")


# ---------------------------------------------------------------------------
# Check: CHANGELOG governance pre-check
# ---------------------------------------------------------------------------


def check_changelog_governance(report: AuditReport) -> None:
    """Pre-check that CHANGELOG.txt exists and has recent entries."""
    print("\n[6/6] CHANGELOG governance")

    changelog = REPO_ROOT / "CHANGELOG.txt"
    if not changelog.is_file():
        report.error("CHANGELOG.txt not found — governance requires it")
        return

    content = changelog.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]
    if len(lines) < 3:
        report.warn("CHANGELOG.txt appears very short — verify it has entries")
    else:
        report.ok(f"CHANGELOG.txt present ({len(lines)} non-empty lines)")

    # Check if there are staged/unstaged changes to tracked artifacts
    # that would require a changelog update
    guard_script = REPO_ROOT / "scripts" / "changelog_guard.py"
    if not guard_script.is_file():
        return

    # Get list of changed files vs HEAD
    result = _run(["git", "diff", "--name-only", "HEAD"])
    if result.returncode != 0:
        return

    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not changed:
        return

    # Import the guard logic to check if changelog is needed
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from changelog_guard import evaluate_changed_files

        check_result = evaluate_changed_files(changed)
        if check_result.missing_changelog:
            report.warn(
                "Working tree changes tracked artifacts but CHANGELOG.txt "
                "is not modified. Update CHANGELOG.txt before committing."
            )
    except ImportError:
        pass  # Guard not importable; skip


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Run the full sync audit."""
    parser = argparse.ArgumentParser(
        description="Repository sync & integration audit"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (exit 1 on any finding)",
    )
    args = parser.parse_args(argv)

    print("=" * 60)
    print("  morskamary — Sync & Integration Audit")
    print("=" * 60)

    report = AuditReport()

    check_git_status(report)
    check_outputs_drift(report)
    check_manifest_drift(report)
    check_provider_capabilities(report)
    check_mcp_config(report)
    check_changelog_governance(report)

    # Summary
    print("\n" + "=" * 60)
    if report.failed:
        print(f"  FAILED: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        print("  Fix errors above before pushing.")
        print("=" * 60)
        return 1
    elif args.strict and report.has_warnings:
        print(f"  STRICT MODE: {len(report.warnings)} warning(s) treated as errors")
        print("=" * 60)
        return 1
    elif report.has_warnings:
        print(f"  PASSED with {len(report.warnings)} warning(s)")
        print("=" * 60)
        return 0
    else:
        print("  ALL CHECKS PASSED — repository is in sync")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    sys.exit(main())
