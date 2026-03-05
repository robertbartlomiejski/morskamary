#!/usr/bin/env python3
"""Convert PDFs in the repository to plain-text sidecar files.

Default behavior
- For each *.pdf found, create a sidecar text file next to it.
- Sidecar naming: file.pdf.txt (to avoid collisions with existing file.txt).
- Skip conversion if sidecar already exists, unless --force.

This supports the quote-then-reason workflow by making documents quickly searchable.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", "__pycache__", ".pytest_cache"}


def extract_with_pypdf(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    parts = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        parts.append(t)
    return "\n\n".join(parts)


def extract_with_pdfminer(pdf_path: Path) -> str:
    from pdfminer.high_level import extract_text

    return extract_text(str(pdf_path)) or ""


def scan_pdfs() -> list[Path]:
    pdfs: list[Path] = []
    for root, dirs, filenames in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for name in filenames:
            if name.lower().endswith(".pdf"):
                pdfs.append(Path(root) / name)
    pdfs.sort(key=lambda p: p.relative_to(REPO_ROOT).as_posix().lower())
    return pdfs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Overwrite existing sidecar text files")
    ap.add_argument("--limit", type=int, default=0, help="Convert only first N PDFs (0 = no limit)")
    args = ap.parse_args()

    pdfs = scan_pdfs()
    if args.limit and args.limit > 0:
        pdfs = pdfs[: args.limit]

    converted = 0
    skipped = 0
    failed = 0

    for pdf in pdfs:
        sidecar = pdf.with_suffix(pdf.suffix + ".txt")  # file.pdf.txt
        if sidecar.exists() and not args.force:
            skipped += 1
            continue

        text = ""
        # prefer pypdf; fall back to pdfminer
        try:
            text = extract_with_pypdf(pdf)
        except Exception:
            try:
                text = extract_with_pdfminer(pdf)
            except Exception:
                text = ""

        if not text.strip():
            failed += 1
            continue

        sidecar.write_text(text, encoding="utf-8")
        converted += 1

    print(f"PDF sidecars: converted={converted} skipped={skipped} failed={failed} (repo_root={REPO_ROOT})")


if __name__ == "__main__":
    main()