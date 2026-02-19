#!/usr/bin/env python3
"""Rebuild derived CSV exports from Excel matrices.

What it does
- Searches for known Excel matrices (by filename) anywhere in the repository.
- Exports each worksheet to data/derived/<base>__<sheet>.csv
- Writes a simple column dictionary to data/derived/<base>__<sheet>__datadict.csv

Why
- Enables deterministic regeneration of CSVs used for mappings, tables, and micro-credential design.
- Supports traceability and reduces manual editing of derived outputs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DERIVED_DIR = REPO_ROOT / "data" / "derived"
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache"}

KNOWN_EXCEL_NAMES = {
    "Blue Social Competences Univ Szczecin matrix.xlsx",
    "Blue Social Competences Univ Szczecin.xlsx",
}


def sanitize(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "sheet"


def scan_excel_files() -> list[Path]:
    hits: list[Path] = []
    for root, dirs, filenames in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for fn in filenames:
            if fn in KNOWN_EXCEL_NAMES or fn.lower().endswith((".xlsx", ".xls")):
                p = Path(root) / fn
                # avoid exporting temp files
                if fn.startswith("~$"):
                    continue
                hits.append(p)
    # prioritize known names
    hits.sort(key=lambda p: (p.name not in KNOWN_EXCEL_NAMES, p.relative_to(REPO_ROOT).as_posix().lower()))
    return hits


def export_sheet(df: pd.DataFrame, out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False, encoding="utf-8")


def write_datadict(df: pd.DataFrame, out_dd: Path) -> None:
    dd = pd.DataFrame(
        {
            "column": list(df.columns),
            "dtype": [str(df[c].dtype) for c in df.columns],
            "non_null": [int(df[c].notna().sum()) for c in df.columns],
            "null": [int(df[c].isna().sum()) for c in df.columns],
        }
    )
    dd.to_csv(out_dd, index=False, encoding="utf-8")


def main() -> None:
    excel_files = scan_excel_files()
    if not excel_files:
        print("No Excel files found.")
        return

    exported = 0
    skipped = 0

    for xlsx in excel_files:
        rel = xlsx.relative_to(REPO_ROOT).as_posix()
        base = sanitize(Path(xlsx.name).stem)
        try:
            xls = pd.ExcelFile(xlsx)
        except Exception as e:
            print(f"FAILED to open: {rel} ({e})")
            continue

        for sheet in xls.sheet_names:
            try:
                df = xls.parse(sheet_name=sheet)
            except Exception as e:
                print(f"FAILED to parse: {rel} :: {sheet} ({e})")
                continue

            # Skip completely empty sheets
            if df.shape[0] == 0 and df.shape[1] == 0:
                skipped += 1
                continue

            sheet_tag = sanitize(sheet)
            out_csv = DERIVED_DIR / f"{base}__{sheet_tag}.csv"
            out_dd = DERIVED_DIR / f"{base}__{sheet_tag}__datadict.csv"

            export_sheet(df, out_csv)
            write_datadict(df, out_dd)
            exported += 1

        print(f"Processed: {rel} (sheets={len(xls.sheet_names)})")

    print(f"Derived exports written to {DERIVED_DIR.relative_to(REPO_ROOT).as_posix()}: exported_tables={exported} skipped_empty={skipped}")


if __name__ == "__main__":
    main()