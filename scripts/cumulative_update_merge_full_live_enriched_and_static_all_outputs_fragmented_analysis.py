#!/usr/bin/env python3
"""Merge fragmented morskamary outputs from branches and downloaded artifacts.

Purpose
-------
This script is a local recovery utility for cases where GitHub Actions produced
live/static output artifacts but they were not committed back to the repository.
It scans local branches, origin branches, the current working tree, and optional
downloaded/dragged artifact directories. It then merges unique records into the
canonical outputs directory.

Default strategy
----------------
The safest repository strategy is source-first:

1. Merge live/API source artifacts under outputs/research_sources/.
2. Merge outputs/research_source_capabilities.json when present.
3. Run run_full_analysis.py in live-enriched mode when a triangulated live-record
   file exists.
4. Validate generated outputs.

This regenerates credentials, gaps, HTML, sector dictionaries, and cumulative
QMBD records from the merged source layer instead of blindly concatenating
derived policy artifacts.

Use --merge-derived only for emergency recovery when a branch contains generated
derived outputs that cannot be reproduced from live/static sources.

Typical Windows PowerShell usage
--------------------------------
    git checkout main
    git pull --ff-only
    git fetch --all --prune

    python scripts/cumulative_update_merge_full_live_enriched_and_static_all_outputs_fragmented_analysis.py `
      --input-dir ./downloaded-artifacts `
      --run-analysis `
      --validate

Then inspect git diff and commit/push the changed outputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = REPO_ROOT / "outputs"
RESEARCH_SOURCES_DIR = OUTPUTS_DIR / "research_sources"
MANIFEST_PATH = OUTPUTS_DIR / "cumulative_update_merge_manifest.json"

SOURCE_FIRST_EXACT_PATHS = {
    "outputs/research_source_capabilities.json",
}

SOURCE_FIRST_PREFIXES = (
    "outputs/research_sources/",
)

DERIVED_OUTPUT_EXACT_PATHS = {
    "outputs/competences_full_database.json",
    "outputs/credentials_database.json",
    "outputs/sector_pathways.json",
    "outputs/cumulative_qmbd_records.json",
    "outputs/gaps_summary.csv",
}

DERIVED_OUTPUT_PREFIXES = (
    "outputs/sector_dictionaries/",
)

MERGEABLE_SUFFIXES = (".json", ".csv")
HTML_SUFFIXES = (".html", ".htm")
SKIP_PATH_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "_merge_backups",
}


@dataclass(frozen=True)
class Candidate:
    """One candidate file version from a branch, working tree, or artifact dir."""

    source: str
    path: str
    payload: bytes


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _run(
    args: list[str],
    *,
    cwd: Path = REPO_ROOT,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        check=check,
        text=text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _git(args: list[str], *, check: bool = True, text: bool = True) -> str | bytes:
    result = _run(["git", *args], check=check, text=text)
    return result.stdout


def _ensure_repo_root() -> None:
    try:
        top = str(_git(["rev-parse", "--show-toplevel"])).strip()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"ERROR: not inside a Git repository: {exc.stderr}") from exc
    if Path(top).resolve() != REPO_ROOT.resolve():
        raise SystemExit(f"ERROR: script resolved repo root {REPO_ROOT}, but git root is {top}")


def _current_branch() -> str:
    try:
        return str(_git(["branch", "--show-current"])).strip()
    except subprocess.CalledProcessError:
        return ""


def _collect_refs(include_remote: bool = True) -> list[str]:
    ref_spaces = ["refs/heads"]
    if include_remote:
        ref_spaces.append("refs/remotes/origin")

    try:
        raw = str(_git(["for-each-ref", "--format=%(refname:short)", *ref_spaces]))
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"ERROR: could not list branches: {exc.stderr}") from exc

    refs: list[str] = []
    seen: set[str] = set()
    preferred = ["main", "origin/main"]

    for ref in preferred + [line.strip() for line in raw.splitlines()]:
        if not ref or ref.endswith("/HEAD"):
            continue
        if ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def _list_paths_in_ref(ref: str) -> list[str]:
    try:
        raw = _git(["ls-tree", "-r", "--name-only", ref, "--", "outputs"], text=True)
    except subprocess.CalledProcessError:
        return []
    paths = [line.strip() for line in str(raw).splitlines() if line.strip()]
    return [p for p in paths if _is_mergeable_repo_path(p)]


def _read_git_file(ref: str, path: str) -> bytes | None:
    try:
        data = _git(["show", f"{ref}:{path}"], check=True, text=False)
    except subprocess.CalledProcessError:
        return None
    if isinstance(data, str):
        return data.encode("utf-8")
    return data


def _is_mergeable_repo_path(path: str, *, merge_derived: bool = False, include_html: bool = False) -> bool:
    lower = path.lower()

    if not path.startswith("outputs/"):
        return False
    if any(part in path.split("/") for part in SKIP_PATH_PARTS):
        return False
    if include_html and lower.endswith(HTML_SUFFIXES):
        return True
    if not lower.endswith(MERGEABLE_SUFFIXES):
        return False

    if path in SOURCE_FIRST_EXACT_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in SOURCE_FIRST_PREFIXES):
        return True

    if merge_derived and path in DERIVED_OUTPUT_EXACT_PATHS:
        return True
    if merge_derived and any(path.startswith(prefix) for prefix in DERIVED_OUTPUT_PREFIXES):
        return True

    return False


def _collect_working_tree_candidates(
    *,
    merge_derived: bool = False,
    include_html: bool = False,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    if not OUTPUTS_DIR.exists():
        return candidates

    for path in OUTPUTS_DIR.rglob("*"):
        if not path.is_file():
            continue
        rel = _rel(path)
        if _is_mergeable_repo_path(rel, merge_derived=merge_derived, include_html=include_html):
            try:
                candidates.append(Candidate("working-tree", rel, path.read_bytes()))
            except OSError:
                continue
    return candidates


def _artifact_relpath(path: Path, artifact_root: Path) -> str | None:
    """Map a downloaded artifact file to a repository-relative path.

    GitHub's download-artifact step may create either:
    - artifact_root/outputs/...
    - artifact_root/live-enriched-analysis-outputs/outputs/...
    - artifact_root/<files> copied into a manual folder
    """

    try:
        rel_parts = path.relative_to(artifact_root).parts
    except ValueError:
        return None

    if "outputs" not in rel_parts:
        return None
    idx = rel_parts.index("outputs")
    repo_rel = Path(*rel_parts[idx:]).as_posix()
    return repo_rel


def _collect_input_dir_candidates(
    input_dirs: Iterable[Path],
    *,
    merge_derived: bool = False,
    include_html: bool = False,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for root in input_dirs:
        root = root.expanduser().resolve()
        if not root.exists():
            print(f"WARNING: input dir does not exist: {root}")
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            repo_rel = _artifact_relpath(path, root)
            if not repo_rel:
                continue
            if not _is_mergeable_repo_path(repo_rel, merge_derived=merge_derived, include_html=include_html):
                continue
            try:
                candidates.append(Candidate(f"input-dir:{root}", repo_rel, path.read_bytes()))
            except OSError:
                continue
    return candidates


def _collect_branch_candidates(
    refs: list[str],
    *,
    merge_derived: bool = False,
    include_html: bool = False,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for ref in refs:
        for path in _list_paths_in_ref(ref):
            if not _is_mergeable_repo_path(path, merge_derived=merge_derived, include_html=include_html):
                continue
            payload = _read_git_file(ref, path)
            if payload is None:
                continue
            candidates.append(Candidate(f"ref:{ref}", path, payload))
    return candidates


def _decode_json(candidate: Candidate) -> Any | None:
    try:
        text = candidate.payload.decode("utf-8-sig")
        if not text.strip():
            return None
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _decode_csv(candidate: Candidate) -> list[dict[str, str]] | None:
    try:
        text = candidate.payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return []
    rows = list(csv.DictReader(text.splitlines()))
    return [{str(k): "" if v is None else str(v) for k, v in row.items()} for row in rows]


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _norm_doi(value: Any) -> str:
    text = _norm_text(value)
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = text.removeprefix("doi:")
    return text.strip()


def _record_key(item: Any) -> str:
    if isinstance(item, dict):
        doi = _norm_doi(item.get("doi") or item.get("DOI"))
        if doi:
            return f"doi:{doi}"

        for field in (
            "source_id",
            "id",
            "record_id",
            "uid",
            "credential_id",
            "pathway_id",
        ):
            value = _norm_text(item.get(field))
            if value:
                return f"{field}:{value}"

        title = _norm_text(
            item.get("title")
            or item.get("Paper Title")
            or item.get("paper_title")
            or item.get("name")
        )
        authors = _norm_text(item.get("authors") or item.get("Author Names"))
        year = _norm_text(item.get("year") or item.get("Publication Year"))
        if title:
            return f"title:{title}|authors:{authors}|year:{year}"

    stable = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _row_key(row: dict[str, str]) -> str:
    lower = {str(k).lower(): v for k, v in row.items()}

    doi = _norm_doi(lower.get("doi"))
    if doi:
        return f"doi:{doi}"

    for field in ("source_id", "id", "record_id", "title"):
        value = _norm_text(lower.get(field))
        if value:
            return f"{field}:{value}"

    stable = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _richness_score(value: Any) -> tuple[int, int]:
    """Prefer records with more populated fields and larger structured payloads."""

    if isinstance(value, dict):
        populated = 0
        for item in value.values():
            if item not in ("", None, [], {}):
                populated += 1
        size = len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
        return populated, size
    if isinstance(value, list):
        return len(value), len(json.dumps(value, ensure_ascii=False, default=str))
    if value in ("", None):
        return 0, 0
    return 1, len(str(value))


def _merge_lists(values: Iterable[list[Any]]) -> list[Any]:
    merged: list[Any] = []
    index: dict[str, int] = {}

    for values_list in values:
        for item in values_list:
            key = _record_key(item)
            if key not in index:
                index[key] = len(merged)
                merged.append(item)
                continue

            existing_idx = index[key]
            if _richness_score(item) > _richness_score(merged[existing_idx]):
                merged[existing_idx] = item

    return merged


def _merge_dict_values(values: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    keys: list[str] = []

    for value in values:
        for key in value:
            if key not in merged and key not in keys:
                keys.append(key)

    for key in keys:
        present = [value[key] for value in values if key in value]
        if not present:
            continue

        if all(isinstance(item, list) for item in present):
            merged[key] = _merge_lists(item for item in present if isinstance(item, list))
        elif all(isinstance(item, dict) for item in present):
            merged[key] = _merge_dict_values(
                [item for item in present if isinstance(item, dict)]
            )
        else:
            # Keep the richest non-empty scalar/object. This prevents older branch
            # metadata from overwriting richer current/live metadata.
            richest = max(present, key=_richness_score)
            merged[key] = richest

    return merged


def _merge_json_candidates(candidates: list[Candidate]) -> tuple[Any | None, dict[str, Any]]:
    decoded: list[tuple[Candidate, Any]] = []
    skipped: list[str] = []

    for candidate in candidates:
        value = _decode_json(candidate)
        if value is None:
            skipped.append(candidate.source)
        else:
            decoded.append((candidate, value))

    if not decoded:
        return None, {"skipped": skipped, "decoded": 0}

    values = [value for _, value in decoded]

    if all(isinstance(value, list) for value in values):
        merged = _merge_lists(value for value in values if isinstance(value, list))
    elif all(isinstance(value, dict) for value in values):
        merged = _merge_dict_values([value for value in values if isinstance(value, dict)])
    else:
        # Mixed top-level schemas should not normally happen. Prefer the richest
        # candidate rather than forcing an unsafe synthetic schema.
        merged = max(values, key=_richness_score)

    return merged, {
        "decoded": len(decoded),
        "skipped": skipped,
        "candidate_sources": [candidate.source for candidate, _ in decoded],
        "output_count": len(merged) if isinstance(merged, list) else None,
    }


def _merge_csv_candidates(candidates: list[Candidate]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    decoded: list[tuple[Candidate, list[dict[str, str]]]] = []
    skipped: list[str] = []

    for candidate in candidates:
        value = _decode_csv(candidate)
        if value is None:
            skipped.append(candidate.source)
        else:
            decoded.append((candidate, value))

    fieldnames: list[str] = []
    rows_by_key: dict[str, dict[str, str]] = {}

    for _, rows in decoded:
        for row in rows:
            for field in row:
                if field not in fieldnames:
                    fieldnames.append(field)
            key = _row_key(row)
            if key not in rows_by_key:
                rows_by_key[key] = row
            elif _richness_score(row) > _richness_score(rows_by_key[key]):
                rows_by_key[key] = row

    merged = list(rows_by_key.values())
    return merged, {
        "decoded": len(decoded),
        "skipped": skipped,
        "candidate_sources": [candidate.source for candidate, _ in decoded],
        "fieldnames": fieldnames,
        "output_count": len(merged),
    }


def _write_json(path: Path, value: Any, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(
    path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
    *,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_bytes(path: Path, payload: bytes, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _backup_outputs(*, dry_run: bool) -> Path | None:
    if dry_run or not OUTPUTS_DIR.exists():
        return None
    backup_root = OUTPUTS_DIR / "_merge_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_root / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)

    for path in OUTPUTS_DIR.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(OUTPUTS_DIR)
        if rel.parts and rel.parts[0] == "_merge_backups":
            continue
        target = backup_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    return backup_dir


def _group_candidates(candidates: list[Candidate]) -> dict[str, list[Candidate]]:
    grouped: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.path, []).append(candidate)
    return grouped


def _merge_candidate_groups(
    grouped: dict[str, list[Candidate]],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    manifest_paths: dict[str, Any] = {}

    for rel_path in sorted(grouped):
        candidates = grouped[rel_path]
        out_path = REPO_ROOT / rel_path
        suffix = out_path.suffix.lower()

        if suffix == ".json":
            merged, meta = _merge_json_candidates(candidates)
            if merged is None:
                manifest_paths[rel_path] = {"status": "skipped", **meta}
                continue
            _write_json(out_path, merged, dry_run=dry_run)
            manifest_paths[rel_path] = {"status": "written", **meta}

        elif suffix == ".csv":
            merged_rows, meta = _merge_csv_candidates(candidates)
            _write_csv(
                out_path,
                merged_rows,
                meta.get("fieldnames", []),
                dry_run=dry_run,
            )
            manifest_paths[rel_path] = {"status": "written", **meta}

        elif suffix in HTML_SUFFIXES:
            selected = max(
                candidates,
                key=lambda c: (len(c.payload), _sha256_bytes(c.payload), c.source),
            )
            _write_bytes(out_path, selected.payload, dry_run=dry_run)
            manifest_paths[rel_path] = {
                "status": "written",
                "mode": "passthrough",
                "selected_source": selected.source,
                "selected_sha256": _sha256_bytes(selected.payload),
                "selected_size": len(selected.payload),
                "candidates": len(candidates),
                "unique_payloads": len({_sha256_bytes(c.payload) for c in candidates}),
            }

    return manifest_paths


def _run_analysis(*, python_executable: str, dry_run: bool) -> dict[str, Any]:
    live_path = RESEARCH_SOURCES_DIR / "live_records_triangulated.json"
    if not live_path.exists():
        return {
            "status": "skipped",
            "reason": "outputs/research_sources/live_records_triangulated.json is missing",
        }

    command = [
        python_executable,
        "run_full_analysis.py",
        "--analysis-input-mode",
        "live-enriched",
        "--live-records-path",
        str(live_path.relative_to(REPO_ROOT)),
    ]

    if dry_run:
        return {"status": "dry-run", "command": command}

    result = _run(command, check=False, text=True)
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "command": command,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def _run_validations(*, python_executable: str, dry_run: bool) -> dict[str, Any]:
    commands = [
        [python_executable, "scripts/validate_research_source_outputs.py"],
        [python_executable, "scripts/assert_cumulative_live_enriched.py", "--require-live"],
        [python_executable, "scripts/validate_generated_outputs.py"],
    ]

    results: list[dict[str, Any]] = []
    if dry_run:
        return {"status": "dry-run", "commands": commands}

    overall_status = "passed"
    for command in commands:
        result = _run(command, check=False, text=True)
        status = "passed" if result.returncode == 0 else "failed"
        if status == "failed":
            overall_status = "failed"
        results.append(
            {
                "command": command,
                "status": status,
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-4000:],
                "stderr_tail": result.stderr[-4000:],
            }
        )

    return {"status": overall_status, "results": results}


def _write_manifest(manifest: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge unique morskamary output records from all local/origin branches "
            "and optional downloaded GitHub Actions artifact directories."
        )
    )
    parser.add_argument(
        "--input-dir",
        dest="input_dirs",
        action="append",
        default=[],
        type=Path,
        help=(
            "Downloaded/dragged artifact directory. Repeatable. The script searches "
            "inside it for an outputs/ subtree."
        ),
    )
    parser.add_argument(
        "--ref",
        dest="refs",
        action="append",
        default=[],
        help=(
            "Specific branch/ref to scan. Repeatable. If omitted, all local branches "
            "and origin/* branches are scanned."
        ),
    )
    parser.add_argument(
        "--no-remote",
        action="store_true",
        help="Scan local branches only when --ref is not supplied.",
    )
    parser.add_argument(
        "--merge-derived",
        action="store_true",
        help=(
            "Also merge generated derived outputs such as credentials_database.json, "
            "competences_full_database.json, sector_pathways.json, cumulative_qmbd_records.json, "
            "gaps_summary.csv, and sector_dictionaries/*.json. Default is source-first."
        ),
    )
    parser.add_argument(
        "--include-html",
        action="store_true",
        help=(
            "Include HTML files in branch/artifact discovery and restore them via deterministic "
            "passthrough selection. Prefer --run-analysis for full regeneration when possible."
        ),
    )
    parser.add_argument(
        "--run-analysis",
        action="store_true",
        help="Run run_full_analysis.py in live-enriched mode after merging source records.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run research-source, live-enriched, and generated-output validators after merge.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable to use for run_full_analysis.py and validators.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned manifest without writing files or running analysis.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _ensure_repo_root()

    branch = _current_branch()
    if branch and branch != "main":
        print(
            f"WARNING: current branch is {branch!r}. For direct main repair, run: git checkout main"
        )

    refs = args.refs or _collect_refs(include_remote=not args.no_remote)
    refs = list(dict.fromkeys(refs))

    backup_dir = _backup_outputs(dry_run=args.dry_run)

    candidates: list[Candidate] = []
    candidates.extend(
        _collect_working_tree_candidates(
            merge_derived=args.merge_derived,
            include_html=args.include_html,
        )
    )
    candidates.extend(
        _collect_input_dir_candidates(
            args.input_dirs,
            merge_derived=args.merge_derived,
            include_html=args.include_html,
        )
    )
    candidates.extend(
        _collect_branch_candidates(
            refs,
            merge_derived=args.merge_derived,
            include_html=args.include_html,
        )
    )

    if not args.include_html:
        # HTML is deliberately excluded by default: regenerated HTML is safer.
        candidates = [c for c in candidates if not c.path.lower().endswith(HTML_SUFFIXES)]

    grouped = _group_candidates(candidates)
    path_manifest = _merge_candidate_groups(grouped, dry_run=args.dry_run)

    analysis_manifest: dict[str, Any] | None = None
    if args.run_analysis:
        analysis_manifest = _run_analysis(
            python_executable=args.python,
            dry_run=args.dry_run,
        )

    validation_manifest: dict[str, Any] | None = None
    if args.validate:
        validation_manifest = _run_validations(
            python_executable=args.python,
            dry_run=args.dry_run,
        )

    manifest: dict[str, Any] = {
        "generated_at": _utc_timestamp(),
        "repository": "robertbartlomiejski/morskamary",
        "current_branch": branch,
        "strategy": "source-first" if not args.merge_derived else "source-first-plus-derived",
        "refs_scanned": refs,
        "input_dirs": [str(path) for path in args.input_dirs],
        "backup_dir": str(backup_dir.relative_to(REPO_ROOT)) if backup_dir else None,
        "candidate_files": len(candidates),
        "paths": path_manifest,
        "analysis": analysis_manifest,
        "validation": validation_manifest,
        "next_commands": [
            "git status --short",
            "git diff --stat",
            "python scripts/validate_research_source_outputs.py",
            "python scripts/assert_cumulative_live_enriched.py --require-live",
            "python scripts/validate_generated_outputs.py",
            "git add outputs/",
            "git commit -m \"chore: merge cumulative live-enriched and static outputs\"",
            "git push origin main",
        ],
    }

    _write_manifest(manifest, dry_run=args.dry_run)

    written = sum(1 for item in path_manifest.values() if item.get("status") == "written")
    print(f"refs_scanned={len(refs)}")
    print(f"candidate_files={len(candidates)}")
    print(f"paths_written={written}")
    if analysis_manifest:
        print(f"analysis_status={analysis_manifest.get('status')}")
    if validation_manifest:
        print(f"validation_status={validation_manifest.get('status')}")
    if not args.dry_run:
        print(f"manifest={MANIFEST_PATH.relative_to(REPO_ROOT)}")

    failed = False
    if analysis_manifest and analysis_manifest.get("status") == "failed":
        failed = True
    if validation_manifest and validation_manifest.get("status") == "failed":
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
