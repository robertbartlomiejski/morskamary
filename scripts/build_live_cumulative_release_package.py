#!/usr/bin/env python3
"""Build the single browser-downloadable cumulative scientific package.

CLI::

    python scripts/build_live_cumulative_release_package.py \\
      --database-dir outputs/cumulative_database \\
      --reports-dir reports \\
      --version-tag latest \\
      --output outputs/release_packages/morskamary_live_cumulative_latest.zip

ZIP contents (per PR-190 Task C spec)::

    README_DATA_PACKAGE.md
    RELEASE_MANIFEST.json
    CHECKSUMS.sha256
    CITATION_APA.txt
    VARIABLE_LABELS.csv
    VALUE_LABELS.csv
    data/csv/*.csv
    data/jsonl/*.jsonl
    data/sqlite/morskamary_live_cumulative.sqlite   (may be skipped)
    reports/morskamary_statistical_report.html
    reports/morskamary_statistical_report.pdf       (may be a text stub)
    reports/morskamary_methodological_audit.html
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CSV_FILES = (
    "evidence_records.csv",
    "competence_demand_signals.csv",
    "derived_competence_demands.csv",
    "sector_axis_gap_model.csv",
    "credential_translation_eqf4_7.csv",
    "learning_outcomes.csv",
    "run_novelty_metrics.csv",
)

# Optional CSVs — included when present alongside the database dir.
OPTIONAL_CSV_FILES = (
    "query_execution_log.csv",
    "provider_run_quality.csv",
)

JSONL_FILES = (
    "evidence_records.jsonl",
    "competence_demand_signals.jsonl",
    "derived_competence_demands.jsonl",
)

REPORT_FILES = (
    "morskamary_statistical_report.html",
    "morskamary_statistical_report.pdf",
    "morskamary_methodological_audit.html",
)

DEMAND_STRENGTH_FORMULA = (
    "demand_strength_score = "
    "0.30*normalized_unique_doi_count "
    "+ 0.20*provider_diversity_score "
    "+ 0.20*temporal_recency_score "
    "+ 0.15*query_diversity_score "
    "+ 0.15*semantic_confidence_mean"
)


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _read_bytes_if_exists(path: Path) -> Optional[bytes]:
    if not path.exists():
        return None
    return path.read_bytes()


def _build_sqlite_from_csvs(csv_dir: Path) -> Tuple[Optional[bytes], Dict[str, str]]:
    """Materialize the CSV bundle into a portable SQLite database.

    Returns ``(sqlite_bytes, status_dict)``. ``sqlite_bytes`` is ``None`` if
    the SQLite build was skipped.
    """
    try:
        # Use an in-memory DB to avoid touching the filesystem, then
        # serialize deterministically. Requires Python 3.11+ for
        # sqlite3.Connection.serialize, so we fall back gracefully.
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        for name in CSV_FILES:
            p = csv_dir / name
            if not p.exists():
                continue
            table = name.replace(".csv", "")
            with p.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                headers = next(reader, None)
                if not headers:
                    continue
                cols = ", ".join(f'"{h}" TEXT' for h in headers)
                cursor.execute(f'CREATE TABLE "{table}" ({cols})')
                placeholders = ", ".join("?" for _ in headers)
                insert = f'INSERT INTO "{table}" VALUES ({placeholders})'
                for row in reader:
                    padded = row + [""] * (len(headers) - len(row))
                    cursor.execute(insert, padded[: len(headers)])
        conn.commit()
        try:
            data = conn.serialize()  # type: ignore[attr-defined]
        except AttributeError:
            # Python < 3.11 fallback: dump to temp path via file.
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
                temp_path = Path(tf.name)
            file_conn = sqlite3.connect(str(temp_path))
            conn.backup(file_conn)
            file_conn.close()
            data = temp_path.read_bytes()
            temp_path.unlink(missing_ok=True)
        conn.close()
        return bytes(data), {"sqlite_status": "generated", "sqlite_skip_reason": ""}
    except Exception as exc:
        return None, {"sqlite_status": "skipped",
                      "sqlite_skip_reason": f"sqlite build failed: {exc}"}


def _readme_text(version_tag: str, generated_at: str) -> str:
    return (
        "# morskamary — live cumulative scientific package\n\n"
        f"**Version tag**: {version_tag}\n"
        f"**Generated**: {generated_at}\n\n"
        "## Contents\n\n"
        "- `RELEASE_MANIFEST.json` — package manifest with checksums and "
        "provenance metadata.\n"
        "- `CHECKSUMS.sha256` — one line per file with its SHA-256 digest.\n"
        "- `CITATION_APA.txt` — APA-style citation template.\n"
        "- `VARIABLE_LABELS.csv`, `VALUE_LABELS.csv` — statistical software "
        "value/variable dictionaries.\n"
        "- `data/csv/` — deterministic CSV tables (evidence, signals, "
        "derived demands, gap model, credentials, outcomes, novelty).\n"
        "- `data/jsonl/` — canonical JSONL audit records.\n"
        "- `data/sqlite/` — portable SQLite database (may be skipped; see "
        "`RELEASE_MANIFEST.json`).\n"
        "- `reports/` — HTML statistical report, methodological audit, "
        "and PDF (may be a text stub if PDF rendering is unavailable).\n\n"
        "## Demand-strength formula\n\n"
        f"    {DEMAND_STRENGTH_FORMULA}\n\n"
        "## Reliability rule\n\n"
        "Records with `record_novelty_status = duplicate_only` are excluded "
        "from statistical growth metrics. Growth indexes are recalculated "
        "only on `new_record`, `updated_metadata`, `provider_enriched`, and "
        "`semantic_enriched` records.\n"
    )


def _citation_text(version_tag: str, generated_at: str) -> str:
    year = generated_at[:4]
    return (
        f"Bartłomiejski, R. ({year}). morskamary — Live Cumulative Blue "
        f"Economy Competence Demand Package ({version_tag}) [Data set]. "
        "https://github.com/robertbartlomiejski/morskamary\n"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-dir", default="outputs/cumulative_database")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--version-tag", default="latest")
    parser.add_argument(
        "--output",
        default="outputs/release_packages/morskamary_live_cumulative_latest.zip",
    )
    args = parser.parse_args(argv)

    database_dir = Path(args.database_dir)
    reports_dir = Path(args.reports_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    entries: List[Tuple[str, bytes]] = []

    # Collect CSVs (required + optional if present).
    for name in CSV_FILES:
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((f"data/csv/{name}", blob))
    for name in OPTIONAL_CSV_FILES:
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((f"data/csv/{name}", blob))

    # JSONL
    for name in JSONL_FILES:
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((f"data/jsonl/{name}", blob))

    # Reports
    for name in REPORT_FILES:
        blob = _read_bytes_if_exists(reports_dir / name)
        if blob is not None:
            entries.append((f"reports/{name}", blob))

    # Variable/value labels (root)
    for name in ("VARIABLE_LABELS.csv", "VALUE_LABELS.csv"):
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((name, blob))

    # SQLite
    sqlite_bytes, sqlite_status = _build_sqlite_from_csvs(database_dir)
    if sqlite_bytes is not None:
        entries.append(("data/sqlite/morskamary_live_cumulative.sqlite", sqlite_bytes))

    # README + citation
    entries.append(("README_DATA_PACKAGE.md",
                    _readme_text(args.version_tag, generated_at).encode("utf-8")))
    entries.append(("CITATION_APA.txt",
                    _citation_text(args.version_tag, generated_at).encode("utf-8")))

    # Sort deterministically before hashing so CHECKSUMS.sha256 order is stable.
    entries.sort(key=lambda e: e[0])
    checksums_text = "".join(
        f"{_sha256_bytes(blob)}  {name}\n" for name, blob in entries
    )
    manifest = {
        "package_name": "morskamary_live_cumulative",
        "version_tag": args.version_tag,
        "generated_at_utc": generated_at,
        "demand_strength_formula": DEMAND_STRENGTH_FORMULA,
        "file_count": len(entries) + 2,  # + manifest + checksums
        "files": sorted(name for name, _ in entries),
        **sqlite_status,
    }
    manifest_text = json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                               indent=2) + "\n"
    # Append manifest + checksums entries after they're finalized.
    entries.append(("RELEASE_MANIFEST.json", manifest_text.encode("utf-8")))
    entries.append(("CHECKSUMS.sha256", checksums_text.encode("utf-8")))
    entries.sort(key=lambda e: e[0])

    # Write ZIP with a fixed timestamp so repeated builds are byte-identical.
    fixed_ts = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, blob in entries:
            info = zipfile.ZipInfo(name, date_time=fixed_ts)
            info.external_attr = (0o644 & 0xFFFF) << 16
            zf.writestr(info, blob)

    package_bytes = output.read_bytes()
    package_sha = _sha256_bytes(package_bytes)
    print(json.dumps({
        "package_path": str(output),
        "package_size_bytes": len(package_bytes),
        "package_sha256": package_sha,
        "sqlite_status": sqlite_status.get("sqlite_status"),
        "file_count": len(entries),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
