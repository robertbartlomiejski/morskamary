Scripts in this folder are optional helpers to make the repository "work with the assistant" under strict evidence and traceability rules.

Prerequisites
- Python 3.10+ recommended
- Install dependencies from repository root:
  pip install -r requirements.txt

1) Generate or refresh MANIFEST_SOURCES.csv
- Creates a skeleton manifest listing every file in the repository.
- Preserves any existing manual metadata already entered in MANIFEST_SOURCES.csv.

Run:
  python scripts/generate_manifest.py

2) Convert PDFs to plain-text sidecar files (.txt)
- Produces file.pdf.txt next to each PDF (or file.txt, depending on option).
- This improves fast quoting and searching.

Run (safe, skips if text already exists):
  python scripts/convert_pdfs_to_txt.py

Run (force overwrite existing txt):
  python scripts/convert_pdfs_to_txt.py --force

3) Rebuild derived CSV exports from Excel matrices
- Exports every sheet from each detected Excel matrix into data/derived/
- Also writes a basic column dictionary per exported table.

Run:
  python scripts/build_derived.py

4) Optional organization helper (dry-run by default)
- Prints a file-move plan that places PDFs into docs/, Excel into data/raw, CSV into data/derived, and DOCX into manuscripts/drafts.
- Does not move anything unless you add --apply.

Dry-run:
  python scripts/organize_repo.py

Apply moves:
  python scripts/organize_repo.py --apply

Notes
- After running scripts, commit the generated outputs (MANIFEST_SOURCES.csv, .txt sidecars, data/derived/*) and record the changes in CHANGELOG.txt.