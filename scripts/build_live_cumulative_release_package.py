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
import re
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Required minimum columns per CSV file.  Imports are deferred to avoid
# circular-import issues; the constants are duplicated intentionally so
# the package builder has zero coupling to analysis internals.
CSV_REQUIRED_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "evidence_records.csv": (
        "evidence_id", "canonical_doi", "canonical_title",
        "first_seen_run_id", "latest_seen_run_id",
        "providers_seen", "record_novelty_status",
    ),
    "competence_demand_signals.csv": (
        "signal_id", "evidence_id", "run_id", "sector",
        "axis_group", "signal_type", "competence_label",
    ),
    "hypothesis_semantic_fragments.csv": (
        "fragment_id", "hypothesis_ids", "signal_id",
        "evidence_id", "run_id", "sector", "axis_group",
        "matched_hypothesis_phrase", "indicator_family",
        "semantic_fragment", "evidence_surface",
    ),
    "derived_competence_demands.csv": (
        "competence_demand_id", "competence_label", "sector",
        "axis_group", "demand_strength_score", "evidence_ids",
    ),
    "sector_axis_gap_model.csv": (
        "sector", "axis_group", "live_literature_demand_count",
        "gap_ratio",
    ),
    "credential_translation_eqf4_7.csv": (
        "credential_id", "credential_title", "sector",
        "eqf_level", "coverage_status",
    ),
    "learning_outcomes.csv": (
        "outcome_id", "credential_id", "sector",
        "eqf_level", "outcome_statement",
        "competence_demand_id", "evidence_id",
    ),
}

CSV_FILES = (
    "evidence_records.csv",
    "competence_demand_signals.csv",
    "hypothesis_semantic_fragments.csv",
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
    "hypothesis_semantic_fragments.jsonl",
    "derived_competence_demands.jsonl",
)

DATABASE_METADATA_FILES = (
    "run_novelty_metrics.json",
    "novelty_gate_report.json",
    "cumulative_database_manifest.json",
    "_checksums.sha256",
    "layer4_manifest.json",
    "layer5_manifest.json",
    "layer_readiness_report.json",
)

LAYER4_STAT_FILES = (
    "qmbd_cross_tables.csv",
    "sector_gap_matrices.json",
    "multivariate_induction_results.json",
    "taxonomic_clusters.csv",
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


def _load_json_required(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _load_jsonl_rows(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    if not path.is_file():
        return rows, errors
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            errors.append(f"malformed_jsonl:{path.name}:L{line_no}:{exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"jsonl_not_object:{path.name}:L{line_no}")
            continue
        rows.append(payload)
    if not rows and not errors:
        errors.append(f"empty_jsonl:{path.name}")
    return rows, errors


def _report_has_required_sections(path: Path) -> List[str]:
    required_tokens = [
        "scientific hypothesis verification",
        "h1",
        "h2",
        "h3",
        "validity threats",
        "reproducibility appendix",
    ]
    text = path.read_text(encoding="utf-8").lower()
    return [token for token in required_tokens if token not in text]


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
        "- `data/jsonl/` — canonical JSONL audit records and evidence-bound "
        "hypothesis fragments.\n"
        "- `protocol/` — authoritative protocol, executable projection, and "
        "declared acquisition constraints.\n"
        "- `provenance/` — query execution log and Layer 1 raw acquisition "
        "index for the packaged run.\n"
        "- `statistics/` — Layer 4 cross-tables, matrices, multivariate "
        "results, and taxonomic clusters.\n"
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
    parser.add_argument("--stats-dir", default="outputs/layer4_statistics")
    parser.add_argument(
        "--protocol-path",
        default="config/live_query_protocol.yml",
    )
    parser.add_argument(
        "--projection-path",
        default="outputs/research_sources/research_queries_from_protocol.yml",
    )
    parser.add_argument(
        "--constraints-path",
        default="outputs/research_sources/query_protocol_constraints.json",
    )
    parser.add_argument(
        "--query-execution-log",
        default="outputs/research_sources/query_execution_log.csv",
    )
    parser.add_argument(
        "--raw-acquisition-index",
        default=None,
        help="Layer 1 raw_acquisition_index.csv for this exact run.",
    )
    parser.add_argument("--version-tag", default="latest")
    parser.add_argument(
        "--current-run-id",
        default="",
        help=(
            "Optional run id guard (e.g. <github.run_id>-<run_attempt>). "
            "When set, package assembly fails if manifests/metrics are stale."
        ),
    )
    parser.add_argument(
        "--output",
        default="outputs/release_packages/morskamary_live_cumulative_latest.zip",
    )
    parser.add_argument(
        "--generated-at-utc",
        default=None,
        help=(
            "Optional ISO-8601 UTC timestamp embedded in README, citation, "
            "and manifest. Pass a frozen value for byte-identical rebuilds."
        ),
    )
    args = parser.parse_args(argv)

    database_dir = Path(args.database_dir)
    reports_dir = Path(args.reports_dir)
    stats_dir = Path(args.stats_dir)
    protocol_path = Path(args.protocol_path)
    projection_path = Path(args.projection_path)
    constraints_path = Path(args.constraints_path)
    query_execution_log = Path(args.query_execution_log)
    raw_acquisition_index = (
        Path(args.raw_acquisition_index)
        if args.raw_acquisition_index
        else None
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Remove any stale release ZIP so that a failed preflight cannot leave an
    # old package for downstream `if: always()` artifact uploads to publish.
    if output.exists():
        output.unlink()
    expected_run_id = str(args.current_run_id or "").strip()
    generated_at = (
        args.generated_at_utc
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )

    entries: List[Tuple[str, bytes]] = []

    # Fail non-zero before ZIP publication if any Layer 0-5, provenance,
    # statistical, or report artifact is absent.
    required_paths = [
        *(database_dir / name for name in CSV_FILES),
        *(database_dir / name for name in JSONL_FILES),
        *(database_dir / name for name in DATABASE_METADATA_FILES),
        database_dir / "VARIABLE_LABELS.csv",
        database_dir / "VALUE_LABELS.csv",
        *(stats_dir / name for name in LAYER4_STAT_FILES),
        *(reports_dir / name for name in REPORT_FILES),
        protocol_path,
        projection_path,
        constraints_path,
        query_execution_log,
    ]
    if raw_acquisition_index is None:
        missing_required = ["--raw-acquisition-index was not provided"]
    else:
        required_paths.append(raw_acquisition_index)
        missing_required = [
            str(required_path)
            for required_path in required_paths
            if not required_path.is_file()
        ]

    # Schema/content validation for manifests, checksums, and CSVs.
    for name in DATABASE_METADATA_FILES:
        candidate = database_dir / name
        if not candidate.is_file():
            continue
        if name.endswith(".json"):
            try:
                json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                missing_required.append(f"malformed_json:{name}:{exc}")
        elif name.endswith(".sha256"):
            try:
                _HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
                text = candidate.read_text(encoding="utf-8")
                seen_refs: Set[str] = set()
                expected_checksum_refs = set(
                    list(CSV_FILES)
                    + list(JSONL_FILES)
                    + [
                        n for n in DATABASE_METADATA_FILES
                        if not n.endswith(".sha256")
                    ]
                )
                for lineno, line in enumerate(
                    text.strip().splitlines(), start=1
                ):
                    parts = line.split("  ", 1)
                    if len(parts) != 2 or not _HEX64.match(parts[0]):
                        missing_required.append(
                            f"malformed_checksum_line:{name}:L{lineno}"
                        )
                        break
                    declared_digest, ref_path = parts
                    if ref_path in seen_refs:
                        missing_required.append(
                            f"duplicate_checksum_entry:{name}:{ref_path}"
                        )
                        break
                    seen_refs.add(ref_path)
                    ref_file = database_dir / ref_path
                    if not ref_file.is_file():
                        missing_required.append(
                            f"checksum_ref_missing:{name}:{ref_path}"
                        )
                        continue
                    actual_digest = hashlib.sha256(
                        ref_file.read_bytes()
                    ).hexdigest()
                    if actual_digest != declared_digest.lower():
                        missing_required.append(
                            f"checksum_mismatch:{name}:{ref_path}"
                        )
                missing_refs = sorted(expected_checksum_refs - seen_refs)
                if missing_refs:
                    missing_required.append(
                        "checksum_missing_required_refs:"
                        + ",".join(missing_refs)
                    )
            except OSError as exc:
                missing_required.append(f"unreadable_checksum:{name}:{exc}")
    for name in CSV_FILES:
        candidate = database_dir / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
            reader = csv.reader(text.splitlines())
            header = next(reader, None)
            if not header:
                missing_required.append(f"empty_csv:{name}")
            elif name in CSV_REQUIRED_COLUMNS:
                header_set = set(header)
                missing_cols = sorted(
                    col for col in CSV_REQUIRED_COLUMNS[name]
                    if col not in header_set
                )
                if missing_cols:
                    missing_required.append(
                        f"csv_missing_columns:{name}:"
                        + ",".join(missing_cols)
                    )
            if name == "derived_competence_demands.csv":
                dict_reader = csv.DictReader(text.splitlines())
                for row_index, row in enumerate(dict_reader, start=2):
                    evidence_ids = str(row.get("evidence_ids", "")).strip()
                    if evidence_ids and evidence_ids.lower() != "unavailable":
                        continue
                    demand_id = str(
                        row.get("competence_demand_id", "")
                    ).strip() or f"row_{row_index}"
                    missing_required.append(
                        f"derived_demand_missing_supporting_evidence_ids:{demand_id}"
                    )
        except (OSError, csv.Error) as exc:
            missing_required.append(f"malformed_csv:{name}:{exc}")

    # JSONL scientific-content checks (non-empty, parseable, and structurally linked).
    jsonl_rows: Dict[str, List[Dict[str, Any]]] = {}
    for name in JSONL_FILES:
        rows, errors = _load_jsonl_rows(database_dir / name)
        jsonl_rows[name] = rows
        missing_required.extend(errors)

    fragment_rows = jsonl_rows.get("hypothesis_semantic_fragments.jsonl", [])
    for row_index, row in enumerate(fragment_rows, start=1):
        for field_name in (
            "hypothesis_id",
            "signal_id",
            "evidence_id",
            "matched_hypothesis_phrase",
            "indicator_family",
            "semantic_fragment",
            "evidence_surface",
        ):
            if str(row.get(field_name, "")).strip():
                continue
            missing_required.append(
                f"hypothesis_fragment_missing_field:L{row_index}:{field_name}"
            )

    evidence_ids_from_fragments = {
        str(row.get("evidence_id", "")).strip()
        for row in fragment_rows
        if str(row.get("evidence_id", "")).strip()
    }

    demand_rows: List[Dict[str, str]] = []
    try:
        with (database_dir / "derived_competence_demands.csv").open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            demand_rows = list(csv.DictReader(handle))
    except OSError as exc:
        missing_required.append(f"unreadable_csv:derived_competence_demands.csv:{exc}")

    learning_rows: List[Dict[str, str]] = []
    try:
        with (database_dir / "learning_outcomes.csv").open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            learning_rows = list(csv.DictReader(handle))
    except OSError as exc:
        missing_required.append(f"unreadable_csv:learning_outcomes.csv:{exc}")

    demand_ids = {
        str(row.get("competence_demand_id", "")).strip()
        for row in demand_rows
        if str(row.get("competence_demand_id", "")).strip()
    }
    linked_outcomes = {
        str(row.get("competence_demand_id", "")).strip()
        for row in learning_rows
        if str(row.get("competence_demand_id", "")).strip()
    }
    missing_outcome_links = sorted(demand_ids - linked_outcomes)
    if missing_outcome_links:
        missing_required.append(
            "learning_outcome_missing_demand_links:"
            + ",".join(missing_outcome_links[:20])
        )

    for row in demand_rows:
        demand_id = str(row.get("competence_demand_id", "")).strip()
        for evidence_id in [
            item.strip()
            for item in str(row.get("evidence_ids", "")).split("|")
            if item.strip()
        ]:
            if evidence_id.lower() == "unavailable":
                continue
            if evidence_id in evidence_ids_from_fragments:
                continue
            missing_required.append(
                f"demand_evidence_not_in_hypothesis_fragments:{demand_id}:{evidence_id}"
            )

    # Report structural checks (required sections + declared hypothesis completeness).
    report_path = reports_dir / "morskamary_statistical_report.html"
    if report_path.is_file():
        missing_sections = _report_has_required_sections(report_path)
        if missing_sections:
            missing_required.append(
                "report_missing_sections:" + ",".join(sorted(missing_sections))
            )

    layer5_manifest = _load_json_required(database_dir / "layer5_manifest.json") or {}
    hypotheses = layer5_manifest.get("hypothesis_results", {})
    if not isinstance(hypotheses, dict):
        missing_required.append("layer5_manifest_missing_hypothesis_results")
    else:
        for hypothesis_id in ("H1", "H2", "H3"):
            if hypothesis_id not in hypotheses:
                missing_required.append(
                    f"layer5_manifest_missing_declared_hypothesis:{hypothesis_id}"
                )
    if expected_run_id:
        run_guard_failures: List[str] = []
        for name in (
            "run_novelty_metrics.json",
            "layer4_manifest.json",
            "layer5_manifest.json",
        ):
            payload = _load_json_required(database_dir / name)
            run_id = str(payload.get("current_run_id", "")).strip() if payload else ""
            if not run_id:
                run_guard_failures.append(f"{name}:missing_current_run_id")
            elif run_id != expected_run_id:
                run_guard_failures.append(f"{name}:{run_id}")
        if raw_acquisition_index is not None:
            normalized_raw_path = str(raw_acquisition_index).replace("\\", "/")
            # Validate the exact path contract: the path must contain
            # the sequence live_runs/<run_id>/raw/raw_acquisition_index.csv
            # as contiguous directory components.
            expected_suffix = (
                f"outputs/live_runs/{expected_run_id}/raw/raw_acquisition_index.csv"
            )
            if (
                normalized_raw_path != expected_suffix
                and not normalized_raw_path.endswith(f"/{expected_suffix}")
            ):
                run_guard_failures.append(
                    "raw_acquisition_index_path_contract_violation"
                )
        if run_guard_failures:
            missing_required.extend(
                f"current-run-guard:{entry}" for entry in run_guard_failures
            )

    if missing_required:
        print(
            f"error: {len(missing_required)} required Layer 0-5 artifact(s) "
            "missing; release ZIP was not created:",
            file=sys.stderr,
        )
        for missing_path in missing_required:
            print(f"  {missing_path}", file=sys.stderr)
        return 1

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

    # Database manifests, novelty results, and internal checksums.
    for name in DATABASE_METADATA_FILES:
        blob = _read_bytes_if_exists(database_dir / name)
        if blob is not None:
            entries.append((f"metadata/{name}", blob))

    # Layer 4 statistical tables.
    for name in LAYER4_STAT_FILES:
        blob = _read_bytes_if_exists(stats_dir / name)
        if blob is not None:
            entries.append((f"statistics/{name}", blob))

    # Authoritative protocol, executable projection, and acquisition provenance.
    source_files = (
        (protocol_path, "protocol/live_query_protocol.yml"),
        (projection_path, "protocol/research_queries_from_protocol.yml"),
        (constraints_path, "protocol/query_protocol_constraints.json"),
        (query_execution_log, "provenance/query_execution_log.csv"),
        (
            raw_acquisition_index,
            "provenance/raw_acquisition_index.csv",
        ),
    )
    for source_path, archive_name in source_files:
        if source_path is not None:
            entries.append((archive_name, source_path.read_bytes()))

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

    # Finalize the manifest, then checksum every package member except the
    # checksum file itself. This makes RELEASE_MANIFEST.json verifiable.
    entries.sort(key=lambda entry: entry[0])
    final_names = sorted(
        [name for name, _ in entries]
        + ["RELEASE_MANIFEST.json", "CHECKSUMS.sha256"]
    )
    manifest = {
        "package_name": "morskamary_live_cumulative",
        "version_tag": args.version_tag,
        "generated_at_utc": generated_at,
        "demand_strength_formula": DEMAND_STRENGTH_FORMULA,
        "file_count": len(final_names),
        "files": final_names,
        "checksum_scope": (
            "all package members including RELEASE_MANIFEST.json; "
            "CHECKSUMS.sha256 explicitly excluded"
        ),
        **sqlite_status,
    }
    manifest_text = (
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2)
        + "\n"
    )
    entries.append(
        ("RELEASE_MANIFEST.json", manifest_text.encode("utf-8"))
    )
    entries.sort(key=lambda entry: entry[0])
    checksums_text = "".join(
        f"{_sha256_bytes(blob)}  {name}\n"
        for name, blob in entries
    )
    entries.append(
        ("CHECKSUMS.sha256", checksums_text.encode("utf-8"))
    )
    entries.sort(key=lambda entry: entry[0])

    # Write ZIP with a fixed timestamp so repeated builds are byte-identical.
    fixed_ts = (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, blob in entries:
            info = zipfile.ZipInfo(name, date_time=fixed_ts)
            info.external_attr = (0o644 & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
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
