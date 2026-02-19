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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
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

IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "env", ".mypy_cache", ".ruff_cache", ".tox"}


def classify(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if rel in {"README.md", "CITATION.txt", "DATA_GOVERNANCE.txt", "LLM_CONTEXT_INSTRUCTION.txt", "CHANGELOG.txt", "PROMPT_REQUEST_TEMPLATE.txt", "MANIFEST_SOURCES.csv"}:
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
    return "other"


def text_available(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".md", ".csv"}:
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


def scan_files() -> List[Path]:
    files: List[Path] = []
    for root, dirs, filenames in os.walk(REPO_ROOT):
        # prune ignored dirs
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for name in filenames:
            p = Path(root) / name
            # ignore manifest while generating to avoid churn
            if p.resolve() == MANIFEST_PATH.resolve():
                continue
            # ignore binary junk
            if name in {".DS_Store"}:
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


if __name__ == "__main__":
    main()