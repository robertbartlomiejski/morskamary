#!/usr/bin/env python3
"""Generate or refresh MANIFEST_SOURCES.csv.

Design goals
- Scan the repository tree and list all files.
- Populate minimal metadata fields (file_type, text_available).
- Preserve any manually filled metadata that already exists in MANIFEST_SOURCES.csv.

This supports FAIR-style findability and assistant workflows that require strict allowed_sources.
"""

from __future__ import annotations

import csv
import os
import pathlib
from typing import Dict, List

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "MANIFEST_SOURCES.csv"

COLUMNS = [
    "file_name",
    "file_type",
    "publisher_or_owner",
    "year",
    "version_or_identifier",
    "licence_or_rights_note",
    "summary_1_sentence",
    "preferred_citation_key",
    "text_available",
]

IGNORED_DIRS = {
    ".git",
    ".allai",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "env",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".codex",
}
IGNORED_RELATIVE_DIRS = {
    "outputs/sectors",
    "outputs/sector_dictionaries",
}
IGNORED_FILE_BASENAMES = {
    ".git",
    ".coverage",
    "coverage.json",
    # Transient smoke-test artifact — runtime-only, not committed to git.
    "research_api_smoke_report.json",
}
IGNORED_FILE_PREFIXES = {
    ".coverage.",
}


def should_ignore_file(path: pathlib.Path) -> bool:
    """Return True when a file should be skipped from the manifest scan."""
    name = path.name
    if name in IGNORED_FILE_BASENAMES:
        return True
    if any(name.startswith(prefix) for prefix in IGNORED_FILE_PREFIXES):
        return True
    if ".allai" in path.parts:
        return True
    return False


def classify(path: pathlib.Path) -> str:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if rel in {
        "README.md",
        "CITATION.txt",
        "DATA_GOVERNANCE.txt",
        "LLM_CONTEXT_INSTRUCTION.txt",
        "CHANGELOG.txt",
        "PROMPT_REQUEST_TEMPLATE.txt",
        "MANIFEST_SOURCES.csv",
    }:
        return "governance"
    if rel.startswith("scripts/") or rel == "requirements.txt":
        return "script"
    if rel.startswith("data/raw/"):
        return "dataset_raw"
    if rel.startswith("data/derived/"):
        return "dataset_derived"
    if rel.startswith("docs/policy/"):
        return "policy"
    if rel.startswith("docs/literature/"):
        return "literature"
    if rel.startswith("manuscripts/"):
        return "manuscript"
    if rel.startswith("outputs/research_sources/") and path.suffix.lower() == ".json":
        return "dataset_derived"

    # Fallback by extension
    ext = path.suffix.lower()
    if ext in {".csv"}:
        return "dataset_derived"
    if ext in {".xlsx", ".xls"}:
        return "dataset_raw"
    if ext in {".pdf"}:
        return "policy_or_literature"
    if ext in {".docx", ".doc"}:
        return "manuscript"
    if ext in {".txt", ".md"}:
        return "text"
    if ext == ".py":
        return "script"
    return "other"


def text_available(path: pathlib.Path) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".md", ".csv", ".json", ".py"}:
        return "yes"
    if ext == ".pdf":
        # treat as yes if a sidecar text exists
        sidecar1 = path.with_suffix(path.suffix + ".txt")  # file.pdf.txt
        sidecar2 = path.with_suffix(".txt")  # file.txt
        return "yes" if sidecar1.exists() or sidecar2.exists() else "no"
    if ext in {".xlsx", ".xls", ".docx", ".doc"}:
        return "yes"  # openable by common tools; not necessarily plain-text
    return "no"


def load_existing() -> Dict[str, Dict[str, str]]:
    if not MANIFEST_PATH.exists():
        return {}
    existing: Dict[str, Dict[str, str]] = {}
    with MANIFEST_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fn = row.get("file_name", "").strip()
            if fn:
                existing[fn] = {k: (row.get(k, "") or "") for k in COLUMNS}
    return existing


def scan_files() -> List[pathlib.Path]:
    files: List[pathlib.Path] = []
    for root, dirs, filenames in os.walk(REPO_ROOT):
        root_path = pathlib.Path(root).relative_to(REPO_ROOT)

        # prune ignored dirs
        pruned_dirs = []
        for d in dirs:
            rel_dir = (root_path / d).as_posix()
            if d in IGNORED_DIRS or d.endswith(".egg-info"):
                continue
            if rel_dir in IGNORED_RELATIVE_DIRS:
                continue
            pruned_dirs.append(d)
        dirs[:] = pruned_dirs

        for name in filenames:
            p = pathlib.Path(root) / name
            # ignore manifest while generating to avoid churn
            if p.resolve() == MANIFEST_PATH.resolve():
                continue
            if should_ignore_file(p):
                continue
            if name == ".codex":
                continue
            # ignore binary junk
            if name in {".DS_Store"} or p.suffix.lower() in {".lnk"}:
                continue
            files.append(p)
    files.sort(key=lambda p: p.relative_to(REPO_ROOT).as_posix().lower())
    return files


def main() -> None:
    existing = load_existing()
    rows: List[Dict[str, str]] = []

    for p in scan_files():
        rel = p.relative_to(REPO_ROOT).as_posix()
        row = {k: "" for k in COLUMNS}
        row["file_name"] = rel
        row["file_type"] = classify(p)
        row["text_available"] = text_available(p)

        # preserve manual metadata
        if rel in existing:
            for k in COLUMNS:
                if existing[rel].get(k, "") and k not in {"file_type", "text_available"}:
                    row[k] = existing[rel][k]

        # preserve preferred_citation_key if present; otherwise suggest one
        if not row["preferred_citation_key"]:
            base = p.stem
            # normalize
            key = "".join(ch if ch.isalnum() else "_" for ch in base).strip("_")
            row["preferred_citation_key"] = key[:40] if key else rel.replace("/", "_")[:40]

        rows.append(row)

    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {MANIFEST_PATH} with {len(rows)} entries")
    print(MANIFEST_PATH.name)


if __name__ == "__main__":
    main()
