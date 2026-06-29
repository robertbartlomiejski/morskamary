#!/usr/bin/env python3
"""Archive complete full-live-analysis outputs into a durable per-run corpus."""

from __future__ import annotations

import argparse
import csv
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
CANONICAL_MANIFEST_FILENAME = "manifest.json"
COMPAT_MANIFEST_FILENAME = "run_manifest.json"

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

ANALYSIS_VIEW_TARGETS: tuple[str, ...] = (
    "outputs/gaps_summary.csv",
    "outputs/credentials_database.json",
    "outputs/competences_full_database.json",
    "outputs/cumulative_qmbd_records.json",
    "outputs/report_index.html",
    "outputs/gaps_by_sector.html",
    "outputs/credentials_matrix.html",
    "outputs/literature_integration.html",
    "outputs/sector_dictionaries",
)

INDEX_CSV_COLUMNS: tuple[str, ...] = (
    "timestamp_utc",
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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_json_records(path: Path) -> int:
    payload = _load_json(path)
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        if isinstance(payload.get("records"), list):
            return len(payload["records"])
        if isinstance(payload.get("items"), list):
            return len(payload["items"])
        return len(payload)
    raise ValueError(f"Unsupported JSON payload type in {path}: {type(payload).__name__}")


def _count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _extract_competence_metrics(path: Path) -> tuple[int, int, int]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    baseline = payload.get("baseline", [])
    literature = payload.get("literature", [])
    baseline_count = len(baseline) if isinstance(baseline, list) else 0
    static_literature_count = len(literature) if isinstance(literature, list) else 0
    return baseline_count + static_literature_count, baseline_count, static_literature_count


def _extract_cumulative_metrics(path: Path) -> tuple[int, int]:
    payload = _load_json(path)
    records: list[dict[str, Any]] = []
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
        records = [item for item in payload["records"] if isinstance(item, dict)]
    else:
        raise ValueError(f"Unsupported cumulative payload in {path}")

    live_enrichment_count = 0
    for item in records:
        origin = str(item.get("record_origin", "")).lower()
        if "live" in origin:
            live_enrichment_count += 1
    return len(records), live_enrichment_count


def _compute_query_file_sha256(repo_root: Path, query_file: str) -> str:
    path = (repo_root / query_file).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Query file not found: {query_file}")
    return _sha256_file(path)


def _collect_methodological_metrics(repo_root: Path, query_file: str) -> dict[str, Any]:
    live_records_path = repo_root / "outputs/research_sources/live_records.json"
    triangulated_path = repo_root / "outputs/research_sources/live_records_triangulated.json"
    cumulative_path = repo_root / "outputs/cumulative_qmbd_records.json"
    competences_path = repo_root / "outputs/competences_full_database.json"
    credentials_path = repo_root / "outputs/credentials_database.json"
    gaps_summary_path = repo_root / "outputs/gaps_summary.csv"

    required_paths = [
        live_records_path,
        triangulated_path,
        cumulative_path,
        competences_path,
        credentials_path,
        gaps_summary_path,
    ]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        missing_lines = "\n".join(f"  - {path.relative_to(repo_root).as_posix()}" for path in missing)
        raise FileNotFoundError(f"Missing required metric sources:\n{missing_lines}")

    live_records_count = _count_json_records(live_records_path)
    triangulated_records_count = _count_json_records(triangulated_path)
    cumulative_qmbd_records_count, live_enrichment_count = _extract_cumulative_metrics(
        cumulative_path
    )
    competences_total, baseline_count, static_literature_count = _extract_competence_metrics(
        competences_path
    )
    credentials_count = _count_json_records(credentials_path)
    gaps_summary_available = _count_csv_rows(gaps_summary_path) > 0
    query_file_sha256 = _compute_query_file_sha256(repo_root, query_file)

    return {
        "query_file_sha256": query_file_sha256,
        "live_records_count": live_records_count,
        "triangulated_records_count": triangulated_records_count,
        "cumulative_qmbd_records_count": cumulative_qmbd_records_count,
        "competences_total": competences_total,
        "baseline_count": baseline_count,
        "static_literature_count": static_literature_count,
        "live_enrichment_count": live_enrichment_count,
        "gaps_summary_available": gaps_summary_available,
        "credentials_count": credentials_count,
    }


def _collect_archived_files(run_dir: Path) -> list[ArchivedFile]:
    files: list[ArchivedFile] = []
    ignored = {
        CANONICAL_MANIFEST_FILENAME,
        COMPAT_MANIFEST_FILENAME,
        "_checksums.sha256",
    }
    for file_path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel = file_path.relative_to(run_dir).as_posix()
        if rel in ignored:
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


def _copy_methodological_views(repo_root: Path, run_dir: Path) -> None:
    research_source = (repo_root / "outputs/research_sources").resolve()
    research_dest = run_dir / "research_sources"
    shutil.copytree(research_source, research_dest, dirs_exist_ok=True)

    for rel_target in ANALYSIS_VIEW_TARGETS:
        source = (repo_root / rel_target).resolve()
        relative = Path(rel_target)
        if relative.parts and relative.parts[0] == "outputs":
            relative = Path(*relative.parts[1:])
        destination = run_dir / "analysis_outputs" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)


def _write_checksums(run_dir: Path, archived_files: list[ArchivedFile]) -> None:
    checksum_path = run_dir / "_checksums.sha256"
    lines = [f"{item.sha256}  {item.relative_path}" for item in archived_files]
    checksum_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _append_jsonl_index(
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


def _append_csv_index(archive_root: Path, manifest_payload: dict[str, Any]) -> None:
    csv_path = archive_root / "cumulative_runs_index.csv"
    row = {
        "timestamp_utc": manifest_payload["timestamp_utc"],
        "run_id": manifest_payload["run_id"],
        "run_path": manifest_payload["run_path"],
        "github_run_id": manifest_payload["github_run_id"],
        "github_run_attempt": manifest_payload["github_run_attempt"],
        "github_run_number": manifest_payload["github_run_number"],
        "github_job": manifest_payload["github_job"],
        "workflow_name": manifest_payload["workflow_name"],
        "event_name": manifest_payload["event_name"],
        "commit_sha": manifest_payload["commit_sha"],
        "branch_ref": manifest_payload["branch_ref"],
        "providers": manifest_payload["providers"],
        "max_results_per_query": manifest_payload["max_results_per_query"],
        "offline": manifest_payload["offline"],
        "require_live_records": manifest_payload["require_live_records"],
        "query_file_sha256": manifest_payload["query_file_sha256"],
        "live_records_count": str(manifest_payload["live_records_count"]),
        "triangulated_records_count": str(manifest_payload["triangulated_records_count"]),
        "cumulative_qmbd_records_count": str(
            manifest_payload["cumulative_qmbd_records_count"]
        ),
        "competences_total": str(manifest_payload["competences_total"]),
        "baseline_count": str(manifest_payload["baseline_count"]),
        "static_literature_count": str(manifest_payload["static_literature_count"]),
        "live_enrichment_count": str(manifest_payload["live_enrichment_count"]),
        "gaps_summary_available": str(manifest_payload["gaps_summary_available"]).lower(),
        "credentials_count": str(manifest_payload["credentials_count"]),
        "file_count": str(manifest_payload["file_count"]),
        "total_bytes": str(manifest_payload["total_bytes"]),
    }

    write_header = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(INDEX_CSV_COLUMNS))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


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

    query_file = str(workflow_metadata["query_file"])
    try:
        metrics = _collect_methodological_metrics(repo_root, query_file)
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: could not compute methodological metrics: {exc}", file=sys.stderr)
        return 1

    archive_root.mkdir(parents=True, exist_ok=True)
    resolved_run_id, run_dir = _resolve_run_path(archive_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=False)

    copy_targets = list(ARCHIVE_REQUIRED_TARGETS) + [
        rel for rel in ARCHIVE_OPTIONAL_TARGETS if (repo_root / rel).exists()
    ]
    for rel_target in copy_targets:
        _copy_target(repo_root, run_dir, rel_target)

    _copy_methodological_views(repo_root, run_dir)

    archived_files = _collect_archived_files(run_dir)
    _write_checksums(run_dir, archived_files)

    timestamp_utc = _now_utc_iso()
    manifest_payload: dict[str, Any] = {
        "manifest_schema": MANIFEST_SCHEMA_PATH,
        "requested_run_id": run_id,
        "run_id": resolved_run_id,
        "timestamp_utc": timestamp_utc,
        "archived_at": timestamp_utc,
        "archive_root": archive_root.as_posix(),
        "run_path": run_dir.as_posix(),
        "copied_targets": copy_targets,
        "file_count": len(archived_files),
        "total_bytes": sum(item.size_bytes for item in archived_files),
        "workflow": workflow_metadata,
        "workflow_name": str(workflow_metadata["name"]),
        "event_name": str(workflow_metadata["event"]),
        "commit_sha": str(workflow_metadata["git_sha"]),
        "branch_ref": str(workflow_metadata["git_ref"]),
        "github_run_id": str(workflow_metadata["github_run_id"]),
        "github_run_attempt": str(workflow_metadata["github_run_attempt"]),
        "github_run_number": str(workflow_metadata["github_run_number"]),
        "github_job": str(workflow_metadata["github_job"]),
        "providers": str(workflow_metadata["inputs"]["providers"]),
        "max_results_per_query": str(
            workflow_metadata["inputs"]["max_results_per_query"]
        ),
        "offline": str(workflow_metadata["inputs"]["offline"]),
        "require_live_records": str(workflow_metadata["inputs"]["require_live_records"]),
        "query_file_sha256": metrics["query_file_sha256"],
        "live_records_count": metrics["live_records_count"],
        "triangulated_records_count": metrics["triangulated_records_count"],
        "cumulative_qmbd_records_count": metrics["cumulative_qmbd_records_count"],
        "competences_total": metrics["competences_total"],
        "baseline_count": metrics["baseline_count"],
        "static_literature_count": metrics["static_literature_count"],
        "live_enrichment_count": metrics["live_enrichment_count"],
        "gaps_summary_available": metrics["gaps_summary_available"],
        "credentials_count": metrics["credentials_count"],
        "files": [
            {
                "path": item.relative_path,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in archived_files
        ],
    }

    manifest_json = json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n"
    (run_dir / CANONICAL_MANIFEST_FILENAME).write_text(manifest_json, encoding="utf-8")
    (run_dir / COMPAT_MANIFEST_FILENAME).write_text(manifest_json, encoding="utf-8")

    _append_jsonl_index(
        archive_root=archive_root,
        run_id=resolved_run_id,
        archived_files=archived_files,
        workflow_metadata=workflow_metadata,
    )
    _append_csv_index(archive_root, manifest_payload)

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
    parser.add_argument("--github-run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument(
        "--github-run-attempt", default=os.environ.get("GITHUB_RUN_ATTEMPT", "")
    )
    parser.add_argument(
        "--github-run-number", default=os.environ.get("GITHUB_RUN_NUMBER", "")
    )
    parser.add_argument("--github-job", default=os.environ.get("GITHUB_JOB", ""))
    parser.add_argument(
        "--query-file",
        default="config/research_queries.yml",
        help="Repository-relative query config used for live export.",
    )
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
        "github_run_id": str(args.github_run_id),
        "github_run_attempt": str(args.github_run_attempt),
        "github_run_number": str(args.github_run_number),
        "github_job": str(args.github_job),
        "query_file": str(args.query_file),
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
