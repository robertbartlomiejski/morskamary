#!/usr/bin/env python3
"""Archive complete full-live-analysis outputs into a durable per-run corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA_PATH = "schemas/run_archive_manifest.schema.json"

ARCHIVE_REQUIRED_TARGETS: tuple[str, ...] = (
    "outputs/research_sources",
    "outputs/gaps_summary.csv",
    "outputs/credentials_database.json",
    "outputs/competences_full_database.json",
    "outputs/cumulative_qmbd_records.json",
    "outputs/report_index.html",
    "outputs/gaps_by_sector.html",
    "outputs/credentials_matrix.html",
    "outputs/literature_integration.html",
    "outputs/sector_dictionaries",
    "MANIFEST_SOURCES.csv",
)

ARCHIVE_OPTIONAL_TARGETS: tuple[str, ...] = (
    "outputs/research_api_health.json",
    "outputs/research_source_capabilities.json",
    "outputs/validation_state.json",
)


@dataclass(frozen=True)
class ArchivedFile:
    """One archived file descriptor used in manifest/checksum payloads."""

    relative_path: str
    size_bytes: int
    sha256: str


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_run_id(value: str) -> str:
    token = value.strip()
    if not token:
        raise ValueError("run_id must be non-empty")
    cleaned = "".join(ch for ch in token if ch.isalnum() or ch in ("-", "_", "."))
    if not cleaned:
        raise ValueError("run_id must contain at least one safe character")
    if cleaned != token:
        raise ValueError("run_id contains unsupported characters")
    return cleaned


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_archived_files(run_dir: Path) -> list[ArchivedFile]:
    files: list[ArchivedFile] = []
    for file_path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel = file_path.relative_to(run_dir).as_posix()
        if rel in {"_run_manifest.json", "_checksums.sha256"}:
            continue
        files.append(
            ArchivedFile(
                relative_path=rel,
                size_bytes=file_path.stat().st_size,
                sha256=_sha256_file(file_path),
            )
        )
    return files


def _copy_target(repo_root: Path, run_dir: Path, rel_target: str) -> None:
    source = (repo_root / rel_target).resolve()
    if repo_root.resolve() not in source.parents and source != repo_root.resolve():
        raise ValueError(f"Target escapes repo root: {rel_target}")

    destination = run_dir / rel_target
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)


def _write_checksums(run_dir: Path, archived_files: list[ArchivedFile]) -> None:
    checksum_path = run_dir / "_checksums.sha256"
    lines = [f"{item.sha256}  {item.relative_path}" for item in archived_files]
    checksum_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _append_run_index(
    archive_root: Path,
    run_id: str,
    archived_files: list[ArchivedFile],
    workflow_metadata: dict[str, Any],
) -> None:
    index_dir = archive_root / "_index"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / "runs_index.jsonl"
    summary = {
        "run_id": run_id,
        "archived_at": _now_utc_iso(),
        "run_path": f"runs/{run_id}",
        "file_count": len(archived_files),
        "total_bytes": sum(item.size_bytes for item in archived_files),
        "workflow": workflow_metadata,
    }
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False) + "\n")


def _resolve_run_path(archive_root: Path, run_id: str) -> tuple[str, Path]:
    """Return a non-colliding run directory so previous archives are preserved."""
    runs_dir = archive_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = run_id
    candidate_path = runs_dir / candidate_id
    suffix = 1
    while candidate_path.exists():
        suffix += 1
        candidate_id = f"{run_id}.{suffix}"
        candidate_path = runs_dir / candidate_id
    return candidate_id, candidate_path


def archive_run_outputs(
    *,
    repo_root: Path,
    archive_root: Path,
    run_id: str,
    workflow_metadata: dict[str, Any],
) -> int:
    """Archive one full analysis run under outputs/run_archive/runs/<run_id>."""
    missing_required = [
        rel for rel in ARCHIVE_REQUIRED_TARGETS if not (repo_root / rel).exists()
    ]
    if missing_required:
        print(
            "ERROR: missing required targets for archive:\n"
            + "\n".join(f"  - {rel}" for rel in missing_required),
            file=sys.stderr,
        )
        return 1

    archive_root.mkdir(parents=True, exist_ok=True)
    resolved_run_id, run_dir = _resolve_run_path(archive_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=False)

    copy_targets = list(ARCHIVE_REQUIRED_TARGETS) + [
        rel for rel in ARCHIVE_OPTIONAL_TARGETS if (repo_root / rel).exists()
    ]
    for rel_target in copy_targets:
        _copy_target(repo_root, run_dir, rel_target)

    archived_files = _collect_archived_files(run_dir)
    _write_checksums(run_dir, archived_files)

    manifest_path = run_dir / "_run_manifest.json"
    manifest_payload: dict[str, Any] = {
        "manifest_schema": MANIFEST_SCHEMA_PATH,
        "requested_run_id": run_id,
        "run_id": resolved_run_id,
        "archived_at": _now_utc_iso(),
        "archive_root": archive_root.as_posix(),
        "run_path": run_dir.as_posix(),
        "copied_targets": copy_targets,
        "file_count": len(archived_files),
        "total_bytes": sum(item.size_bytes for item in archived_files),
        "workflow": workflow_metadata,
        "files": [
            {
                "path": item.relative_path,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in archived_files
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    _append_run_index(
        archive_root=archive_root,
        run_id=resolved_run_id,
        archived_files=archived_files,
        workflow_metadata=workflow_metadata,
    )

    print(f"Archived run outputs to {run_dir}")
    print(f"Archived files: {len(archived_files)}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive full-live-analysis outputs into outputs/run_archive."
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root path (default: current directory).",
    )
    parser.add_argument(
        "--archive-root",
        default="outputs/run_archive",
        help="Archive root path (default: outputs/run_archive).",
    )
    parser.add_argument(
        "--run-id",
        default=(
            os.environ.get("GITHUB_RUN_ID")
            or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        ),
        help="Unique run identifier; use github.run_id-github.run_attempt in CI.",
    )
    parser.add_argument("--workflow-name", default=os.environ.get("GITHUB_WORKFLOW", ""))
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--git-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--git-ref", default=os.environ.get("GITHUB_REF", ""))
    parser.add_argument("--providers", default="")
    parser.add_argument("--max-results-per-query", default="")
    parser.add_argument("--offline", default="")
    parser.add_argument("--require-live-records", default="")
    return parser.parse_args([] if argv is None else argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run_id = _safe_run_id(str(args.run_id))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    repo_root = Path(str(args.repo_root)).resolve()
    archive_root = (repo_root / str(args.archive_root)).resolve()

    workflow_metadata = {
        "name": str(args.workflow_name),
        "event": str(args.event_name),
        "git_sha": str(args.git_sha),
        "git_ref": str(args.git_ref),
        "inputs": {
            "providers": str(args.providers),
            "max_results_per_query": str(args.max_results_per_query),
            "offline": str(args.offline),
            "require_live_records": str(args.require_live_records),
        },
    }
    return archive_run_outputs(
        repo_root=repo_root,
        archive_root=archive_root,
        run_id=run_id,
        workflow_metadata=workflow_metadata,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
