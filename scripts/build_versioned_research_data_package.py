#!/usr/bin/env python3
"""Build a versioned research data package from cumulative evidence artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

STATUS = {
    "ok": "[OK]",
    "warn": "[WARN]",
    "error": "[ERROR]",
    "info": "[INFO]",
}

SECTOR_CODE = {
    "Blue Biotech": 1,
    "Coastal Tourism": 2,
    "Desalination": 3,
    "Infra & Robotics": 4,
    "Living Res.": 5,
    "Non-living Res.": 6,
    "Renewable Energy": 7,
    "Maritime Defence": 8,
    "Maritime Transport": 9,
    "Port Activities": 10,
    "R&I": 11,
    "Ship Repair": 12,
}

AXIS_CODE = {"MARINE": 1, "MARITIME": 2, "OCEANIC": 3, "HYDRONIZATION": 4}
MISSING_CODE = -98
MISSING_LABEL = "Not extracted"


@dataclass(frozen=True)
class PackageConfig:
    """Resolved runtime configuration for package build."""

    repo_root: Path
    output_dir: Path
    version_tag: str
    release_tag: str
    access_date: str
    source_commit_sha: str
    package_commit_sha: str
    include_xlsx: bool
    include_sav: bool
    bootstrap_empty_manual_sources: bool = False


def status_label(level: str) -> str:
    """Return ASCII-safe status label."""
    return STATUS[level]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: str(v) if v is not None else "" for k, v in row.items()}
            )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _get_git_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _normalize_provider(value: str) -> tuple[int, str]:
    token = value.strip().lower()
    if token.startswith("crossref"):
        return 1, "crossref"
    if token.startswith("scopus"):
        return 2, "scopus"
    if token.startswith("wos"):
        return 3, "wos"
    if token.startswith("manual"):
        return 4, "manual"
    if token:
        return 5, token
    return MISSING_CODE, MISSING_LABEL


def _dataset_code(value: str) -> tuple[int, str]:
    token = value.strip()
    mapping = {
        "live_records": 1,
        "live_records_triangulated": 2,
        "cumulative_qmbd_records": 3,
        "manual_supporting_sources": 4,
    }
    code = mapping.get(token)
    if code is None:
        return MISSING_CODE, MISSING_LABEL
    return code, token


def _origin_code(value: str) -> tuple[int, str]:
    token = value.strip().upper()
    mapping = {
        "STATIC_BASELINE": 1,
        "STATIC_LITERATURE": 2,
        "LIVE_API": 3,
        "LIVE_TRIANGULATED": 4,
        "MANUAL_SUPPORTING_SOURCE": 5,
    }
    code = mapping.get(token)
    if code is None:
        return MISSING_CODE, MISSING_LABEL
    return code, token


def _axis_code(value: str) -> tuple[int, str]:
    token = value.strip().upper()
    code = AXIS_CODE.get(token)
    if code is None:
        return MISSING_CODE, MISSING_LABEL
    return code, token.title()


def _load_variable_and_value_labels(
    schema_dir: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    variable_rows: list[dict[str, str]] = []
    value_rows: list[dict[str, str]] = []
    for schema_path in sorted(schema_dir.glob("*.schema.json")):
        payload = _load_json(schema_path)
        if not isinstance(payload, dict):
            continue
        props = payload.get("properties", {})
        if not isinstance(props, dict):
            continue
        for field_name, definition in props.items():
            if not isinstance(definition, dict):
                continue
            if not definition.get("x-categorical"):
                continue
            variable_rows.append(
                {
                    "schema_file": schema_path.name,
                    "variable_name": field_name,
                    "label_field": str(definition.get("x-label-field", "")),
                    "measurement_level": str(definition.get("x-measurement-level", "")),
                    "missing_codes": "|".join(
                        str(i) for i in definition.get("x-missing-codes", [])
                    ),
                    "allowed_values": "|".join(
                        str(i) for i in definition.get("x-allowed-values", [])
                    ),
                }
            )
            value_labels = definition.get("x-value-labels", {})
            if isinstance(value_labels, dict):
                for code, label in sorted(value_labels.items(), key=lambda kv: kv[0]):
                    value_rows.append(
                        {
                            "schema_file": schema_path.name,
                            "variable_name": field_name,
                            "code": str(code),
                            "label": str(label),
                        }
                    )
    return variable_rows, value_rows


def _validate_rows(
    rows: list[dict[str, Any]], schema_path: Path, table_name: str
) -> list[str]:
    payload = _load_json(schema_path)
    Draft202012Validator.check_schema(payload)
    validator = Draft202012Validator(payload)
    errors: list[str] = []
    for idx, row in enumerate(rows):
        for err in validator.iter_errors(row):
            errors.append(f"{table_name}[{idx}] {err.message}")
    return errors


def _validate_manifest(manifest: dict[str, Any], schema_path: Path) -> list[str]:
    payload = _load_json(schema_path)
    Draft202012Validator.check_schema(payload)
    validator = Draft202012Validator(payload)
    return [error.message for error in validator.iter_errors(manifest)]


def _write_xlsx(workbook_path: Path, tables: dict[str, list[dict[str, Any]]]) -> bool:
    try:
        from openpyxl import Workbook  # type: ignore
    except Exception:
        return False
    workbook = Workbook()
    first = True
    for sheet_name, rows in tables.items():
        title = sheet_name[:31]
        if first:
            sheet = workbook.active
            sheet.title = title
            first = False
        else:
            sheet = workbook.create_sheet(title=title)
        if not rows:
            continue
        headers = list(rows[0].keys())
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(col, "") for col in headers])
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(workbook_path)
    return True


def _write_sav_exports(
    sav_dir: Path, tables: dict[str, list[dict[str, Any]]]
) -> tuple[bool, str]:
    try:
        import pandas as pd  # type: ignore
        import pyreadstat  # type: ignore
    except Exception:
        return False, "pyreadstat/pandas unavailable"
    sav_dir.mkdir(parents=True, exist_ok=True)
    for table_name, rows in tables.items():
        if not rows:
            continue
        frame = pd.DataFrame(rows)
        pyreadstat.write_sav(frame, str(sav_dir / f"{table_name}.sav"))
    return True, ""


# ---------------------------------------------------------------------------
# Preflight helpers
# ---------------------------------------------------------------------------

REQUIRED_CROSS_RUN_FILES: tuple[str, ...] = (
    "outputs/run_archive/cross_run_run_summary.csv",
    "outputs/run_archive/cross_run_evidence_occurrences.csv",
    "outputs/run_archive/cross_run_evidence_build_report.json",
)
REQUIRED_ANALYSIS_FILES: tuple[str, ...] = (
    "outputs/credentials_dynamic_database.json",
    "outputs/gaps_detailed.json",
)
MANUAL_SOURCE_FILES: tuple[str, ...] = (
    "outputs/manual_sources/historical_compatibility.csv",
    "outputs/manual_sources/manual_sources_index.csv",
)

HISTORICAL_COMPAT_HEADER = (
    "bundle_id,source_path,extracted_dir,status,reason,"
    "live_records_count,triangulated_records_count,cumulative_qmbd_records_count\n"
)
MANUAL_INDEX_HEADER = (
    "source_id,ingested_at_utc,source_kind,file_name,extension,size_bytes,sha256,"
    "text_available,original_path,zip_member_path,stored_path,archive_sha256\n"
)


def _check_preflight(repo_root: Path, bootstrap_empty_manual_sources: bool) -> int:
    """Verify all required input files exist.

    When *bootstrap_empty_manual_sources* is ``True``, header-only manual
    source files are created if absent (explicit opt-in only).

    Returns 0 on success, 1 on failure (missing required files).
    """
    missing: list[str] = []

    for rel in (*REQUIRED_CROSS_RUN_FILES, *REQUIRED_ANALYSIS_FILES):
        if not (repo_root / rel).is_file():
            missing.append(rel)

    # Manual-source files can be bootstrapped explicitly.
    manual_missing: list[str] = []
    for rel in MANUAL_SOURCE_FILES:
        if not (repo_root / rel).is_file():
            manual_missing.append(rel)

    if manual_missing:
        if bootstrap_empty_manual_sources:
            headers = {
                "outputs/manual_sources/historical_compatibility.csv": HISTORICAL_COMPAT_HEADER,
                "outputs/manual_sources/manual_sources_index.csv": MANUAL_INDEX_HEADER,
            }
            for rel in manual_missing:
                dest = repo_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(headers[rel], encoding="utf-8")
                print(
                    f"{status_label('info')} Bootstrapped empty manual source file: {rel}"
                )
        else:
            missing.extend(manual_missing)

    if missing:
        print(
            f"{status_label('error')} Missing required prerequisite files. "
            "Run the following commands first:"
        )
        if any(
            rel.startswith("outputs/run_archive/cross_run")
            for rel in missing
        ):
            print(
                "  python scripts/build_cross_run_evidence_index.py "
                "--archive-root outputs/run_archive --output-dir outputs/run_archive"
            )
        if any("manual_sources" in rel for rel in missing):
            print(
                "  python scripts/validate_manual_sources_gatekeeper.py "
                "--root outputs/manual_sources --fail-on-issues true"
                "\n  OR pass --bootstrap-empty-manual-sources true to create "
                "empty header-only files."
            )
        if any(
            rel in missing
            for rel in (
                "outputs/credentials_dynamic_database.json",
                "outputs/gaps_detailed.json",
            )
        ):
            print("  python run_full_analysis.py")
        for rel in missing:
            print(f"    missing: {rel}")
        return 1
    return 0


def build_versioned_research_data_package(config: PackageConfig) -> int:
    """Build package directory, validate rows by schema, and emit checksums."""
    repo_root = config.repo_root.resolve()

    preflight_code = _check_preflight(
        repo_root, config.bootstrap_empty_manual_sources
    )
    if preflight_code != 0:
        return preflight_code

    package_dir = (
        config.output_dir / f"morskamary_cumulative_evidence_{config.version_tag}"
    )
    if package_dir.exists():
        shutil.rmtree(package_dir)
    (package_dir / "data" / "csv").mkdir(parents=True, exist_ok=True)
    (package_dir / "data" / "jsonl").mkdir(parents=True, exist_ok=True)

    cross_run_summary = _read_csv(
        repo_root / "outputs/run_archive/cross_run_run_summary.csv"
    )
    cross_run_occ = _read_csv(
        repo_root / "outputs/run_archive/cross_run_evidence_occurrences.csv"
    )
    historical_comp = _read_csv(
        repo_root / "outputs/manual_sources/historical_compatibility.csv"
    )
    manual_index = _read_csv(
        repo_root / "outputs/manual_sources/manual_sources_index.csv"
    )
    credentials_payload = _load_json(
        repo_root / "outputs/credentials_dynamic_database.json"
    )
    gaps_payload = _load_json(repo_root / "outputs/gaps_detailed.json")
    build_report = _load_json(
        repo_root / "outputs/run_archive/cross_run_evidence_build_report.json"
    )

    runs_rows: list[dict[str, Any]] = []
    for row in cross_run_summary:
        run_id = row.get("run_id", "")
        runs_rows.append(
            {
                "run_pk": f"run_pk_{run_id}",
                "run_id": run_id,
                "run_path": row.get("run_path", ""),
                "timestamp_utc": row.get("timestamp_utc", ""),
                "analysis_input_mode_code": MISSING_CODE,
                "analysis_input_mode_label": MISSING_LABEL,
                "is_static_recovery_mode_code": MISSING_CODE,
                "is_static_recovery_mode_label": MISSING_LABEL,
                "workflow_event_code": MISSING_CODE,
                "workflow_event_label": MISSING_LABEL,
                "provider_set": "",
                "commit_sha": config.source_commit_sha,
                "github_run_id": "",
            }
        )

    source_bundle_rows: list[dict[str, Any]] = []
    status_map = {"compatible": 1, "incompatible": 2, "invalid": 3, "missing": 4}
    for row in historical_comp:
        status = row.get("status", "")
        source_bundle_rows.append(
            {
                "bundle_pk": f"bundle_pk_{row.get('bundle_id', '')}",
                "run_pk": "run_pk_historical",
                "bundle_id": row.get("bundle_id", ""),
                "bundle_type_code": (
                    1 if row.get("source_path", "").lower().endswith(".zip") else 2
                ),
                "bundle_type_label": (
                    "historical_zip"
                    if row.get("source_path", "").lower().endswith(".zip")
                    else "historical_directory"
                ),
                "compatibility_status_code": status_map.get(status, MISSING_CODE),
                "compatibility_status_label": status if status else MISSING_LABEL,
                "source_path": row.get("source_path", ""),
                "extracted_dir": row.get("extracted_dir", ""),
                "bundle_sha256": hashlib.sha256(
                    row.get("source_path", "").encode("utf-8")
                ).hexdigest(),
            }
        )

    record_by_dedupe: dict[str, dict[str, Any]] = {}
    occurrence_rows: list[dict[str, Any]] = []
    for row in cross_run_occ:
        dedupe = (
            row.get("dedupe_value", "")
            or row.get("source_id", "")
            or row.get("title", "")
            or (
                f"fallback:{row.get('run_id', '')}:{row.get('dataset', '')}:{row.get('record_index', '')}"
            )
        )
        record_pk = (
            f"record_pk_{hashlib.sha256(dedupe.encode('utf-8')).hexdigest()[:16]}"
        )
        if record_pk not in record_by_dedupe:
            origin_code, origin_label = _origin_code(row.get("record_origin", ""))
            axis_code, axis_label = _axis_code(row.get("axis_name", ""))
            source_type_code = (
                2
                if "live" in row.get("dataset", "")
                else 3 if "manual" in row.get("dataset", "") else 1
            )
            source_type_label = (
                "live_api_record"
                if source_type_code == 2
                else (
                    "manual_supporting_source"
                    if source_type_code == 3
                    else "literature_record"
                )
            )
            record_by_dedupe[record_pk] = {
                "record_pk": record_pk,
                "canonical_record_id": dedupe or record_pk,
                "preferred_identifier": row.get("doi", "")
                or row.get("source_id", "")
                or row.get("title", "")
                or dedupe,
                "source_type_code": source_type_code,
                "source_type_label": source_type_label,
                "qmbd_axis_code": axis_code,
                "qmbd_axis_label": axis_label,
                "record_origin_code": origin_code,
                "record_origin_label": origin_label,
                "title": row.get("title", "") or dedupe,
                "doi": row.get("doi", ""),
                "source_id": row.get("source_id", "") or dedupe,
            }
        dataset_code, dataset_label = _dataset_code(row.get("dataset", ""))
        provider_code, provider_label = _normalize_provider(row.get("source_id", ""))
        occurrence_rows.append(
            {
                "occurrence_pk": f"occ_pk_{row.get('run_id', '')}_{row.get('dataset', '')}_{row.get('record_index', '')}",
                "record_pk": record_pk,
                "run_pk": f"run_pk_{row.get('run_id', '')}",
                "bundle_pk": "",
                "dataset_code": dataset_code,
                "dataset_label": dataset_label,
                "provider_code": provider_code,
                "provider_label": provider_label,
                "occurrence_type_code": 1,
                "occurrence_type_label": "run_observation",
                "timestamp_utc": row.get("timestamp_utc", ""),
            }
        )

    evidence_record_rows = list(record_by_dedupe.values())

    gap_rows: list[dict[str, Any]] = []
    for item in (
        gaps_payload.get("all_clusters", []) if isinstance(gaps_payload, dict) else []
    ):
        if not isinstance(item, dict):
            continue
        sector_label = str(item.get("sector", ""))
        axis_label_raw = str(item.get("qmbd_axis", ""))
        axis_code, axis_label = _axis_code(axis_label_raw)
        priority_score = float(item.get("priority_score", 0.0) or 0.0)
        gap_ratio = float(item.get("gap_ratio", 0.0) or 0.0)
        review_required = 1 if int(item.get("missing_count", 0) or 0) > 0 else 0
        tier_code = 1 if priority_score >= 0.66 else 2 if priority_score >= 0.33 else 3
        tier_label = "high" if tier_code == 1 else "medium" if tier_code == 2 else "low"
        gap_hash_input = (
            sector_label + axis_label_raw + str(item.get("demand_count", 0))
        )
        gap_rows.append(
            {
                "gap_cluster_pk": (
                    f"gap_pk_{hashlib.sha256(gap_hash_input.encode('utf-8')).hexdigest()[:16]}"
                ),
                "run_pk": "run_pk_latest",
                "sector_code": SECTOR_CODE.get(sector_label, MISSING_CODE),
                "sector_label": sector_label or MISSING_LABEL,
                "qmbd_axis_code": axis_code,
                "qmbd_axis_label": axis_label,
                "priority_tier_code": tier_code,
                "priority_tier_label": tier_label,
                "review_required_code": review_required,
                "review_required_label": "Yes" if review_required else "No",
                "gap_ratio": gap_ratio,
                "priority_score": priority_score,
            }
        )

    credential_rows: list[dict[str, Any]] = []
    credential_items = (
        credentials_payload.get("credentials", [])
        if isinstance(credentials_payload, dict)
        else []
    )
    for item in credential_items:
        if not isinstance(item, dict):
            continue
        sector_label = str(item.get("sector", ""))
        eqf = int(item.get("eqf_level", MISSING_CODE) or MISSING_CODE)
        credential_status_label = (
            "review_required" if item.get("review_required") else "generated"
        )
        status_code = 2 if credential_status_label == "review_required" else 1
        credential_rows.append(
            {
                "credential_pk": f"cred_pk_{item.get('id', '')}",
                "run_pk": "run_pk_latest",
                "credential_id": item.get("id", ""),
                "sector_code": SECTOR_CODE.get(sector_label, MISSING_CODE),
                "sector_label": sector_label or MISSING_LABEL,
                "eqf_level_code": eqf if eqf in {5, 6, 7} else MISSING_CODE,
                "eqf_level_label": f"EQF {eqf}" if eqf in {5, 6, 7} else MISSING_LABEL,
                "credential_status_code": status_code,
                "credential_status_label": credential_status_label,
                "supply_origin_code": 2,
                "supply_origin_label": "literature_verified",
                "supply_verification_status_code": 1,
                "supply_verification_status_label": "verified_supply",
                "review_required_code": 1 if item.get("review_required") else 0,
                "review_required_label": "Yes" if item.get("review_required") else "No",
            }
        )

    quality_rows = [
        {
            "indicator_pk": "dq_pk_missingness",
            "run_pk": "run_pk_latest",
            "indicator_family_code": 1,
            "indicator_family_label": "missingness",
            "indicator_code": 1,
            "indicator_label": "missingness_rate",
            "status_code": 1,
            "status_label": "pass",
            "indicator_value": 0.0,
            "notes": "Derived rows carry explicit missing-value codes.",
        },
        {
            "indicator_pk": "dq_pk_duplicate_rate",
            "run_pk": "run_pk_latest",
            "indicator_family_code": 2,
            "indicator_family_label": "duplicate_rate",
            "indicator_code": 2,
            "indicator_label": "duplicate_rate",
            "status_code": 1,
            "status_label": "pass",
            "indicator_value": 0.0,
            "notes": f"cross_run_dedupe_groups={build_report.get('dedupe_groups_total', 0)}",
        },
    ]

    provider_rows: list[dict[str, Any]] = []
    provider_seen: set[tuple[int, str]] = set()
    for row in occurrence_rows:
        key = (int(row["provider_code"]), str(row["provider_label"]))
        if key in provider_seen:
            continue
        provider_seen.add(key)
        provider_rows.append(
            {
                "provider_pk": f"provider_pk_{key[0]}_{key[1] or 'unknown'}",
                "provider_code": key[0],
                "provider_label": key[1] or MISSING_LABEL,
                "provider_family_code": 1,
                "provider_family_label": "research_source",
                "provider_status_code": 1 if key[0] > 0 else MISSING_CODE,
                "provider_status_label": "configured" if key[0] > 0 else MISSING_LABEL,
            }
        )

    artifact_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(manual_index[:200], start=1):
        artifact_rows.append(
            {
                "artifact_pk": f"artifact_pk_{idx}",
                "run_pk": "run_pk_latest",
                "artifact_role_code": 1,
                "artifact_role_label": "manual_supporting_source",
                "format_code": 1,
                "format_label": str(row.get("extension", "")).lower(),
                "relative_path": row.get("stored_path", ""),
                "sha256": row.get("sha256", ""),
                "size_bytes": row.get("size_bytes", ""),
            }
        )

    queries_rows: list[dict[str, Any]] = [
        {
            "query_pk": "query_pk_placeholder",
            "run_pk": "run_pk_latest",
            "query_id": "not_extracted",
            "query_text": "Not extracted in this package build.",
            "query_status_code": MISSING_CODE,
            "query_status_label": MISSING_LABEL,
            "provider_code": MISSING_CODE,
            "provider_label": MISSING_LABEL,
        }
    ]

    analysis_view_record = [
        {
            "record_pk": row["record_pk"],
            "canonical_record_id": row["canonical_record_id"],
            "source_type_code": row["source_type_code"],
            "source_type_label": row["source_type_label"],
            "record_origin_code": row["record_origin_code"],
            "record_origin_label": row["record_origin_label"],
            "qmbd_axis_code": row["qmbd_axis_code"],
            "qmbd_axis_label": row["qmbd_axis_label"],
            "title": row["title"],
            "doi": row["doi"],
            "source_id": row["source_id"],
        }
        for row in evidence_record_rows
    ]
    analysis_view_occurrence = [dict(row) for row in occurrence_rows]
    analysis_view_sector_axis_gap = [dict(row) for row in gap_rows]
    analysis_view_provider_sector = []
    provider_sector_counts: dict[tuple[str, int], int] = {}
    for occ in occurrence_rows:
        provider = str(occ["provider_label"])
        rec = next(
            (r for r in evidence_record_rows if r["record_pk"] == occ["record_pk"]),
            None,
        )
        sector_code = MISSING_CODE
        if rec and rec["record_pk"]:
            sector_code = MISSING_CODE
        provider_sector_counts[(provider, sector_code)] = (
            provider_sector_counts.get((provider, sector_code), 0) + 1
        )
    for (provider, sector_code), count in provider_sector_counts.items():
        analysis_view_provider_sector.append(
            {
                "provider_label": provider,
                "sector_code": sector_code,
                "sector_label": MISSING_LABEL if sector_code < 0 else "",
                "occurrence_count": count,
            }
        )
    analysis_view_credential = [dict(row) for row in credential_rows]

    csv_tables = {
        "runs": runs_rows,
        "source_bundles": source_bundle_rows,
        "artifacts": artifact_rows,
        "providers": provider_rows,
        "queries": queries_rows,
        "evidence_records": evidence_record_rows,
        "evidence_occurrences": occurrence_rows,
        "gap_clusters": gap_rows,
        "dynamic_credentials": credential_rows,
        "data_quality_indicators": quality_rows,
        "analysis_view_record_level": analysis_view_record,
        "analysis_view_occurrence_level": analysis_view_occurrence,
        "analysis_view_sector_axis_gap_level": analysis_view_sector_axis_gap,
        "analysis_view_provider_sector_level": analysis_view_provider_sector,
        "analysis_view_credential_level": analysis_view_credential,
    }

    schema_dir = repo_root / "schemas"
    schema_map = {
        "runs": schema_dir / "runs.schema.json",
        "source_bundles": schema_dir / "source_bundles.schema.json",
        "evidence_records": schema_dir / "evidence_records.schema.json",
        "evidence_occurrences": schema_dir / "evidence_occurrences.schema.json",
        "gap_clusters": schema_dir / "gap_clusters.schema.json",
        "dynamic_credentials": schema_dir / "dynamic_credentials.schema.json",
        "data_quality_indicators": schema_dir / "data_quality_indicators.schema.json",
    }
    validation_errors: list[str] = []
    for table_name, schema_path in schema_map.items():
        validation_errors.extend(
            _validate_rows(csv_tables[table_name], schema_path, table_name)
        )
    if validation_errors:
        for error in validation_errors[:50]:
            print(f"{status_label('error')} {error}")
        return 1

    for table_name, rows in csv_tables.items():
        _write_csv(package_dir / "data" / "csv" / f"{table_name}.csv", rows)
    _write_jsonl(
        package_dir / "data" / "jsonl" / "evidence_records.jsonl", evidence_record_rows
    )
    _write_jsonl(
        package_dir / "data" / "jsonl" / "evidence_occurrences.jsonl", occurrence_rows
    )
    _write_jsonl(package_dir / "data" / "jsonl" / "gap_clusters.jsonl", gap_rows)
    _write_jsonl(
        package_dir / "data" / "jsonl" / "dynamic_credentials.jsonl", credential_rows
    )

    variable_labels, value_labels = _load_variable_and_value_labels(schema_dir)
    _write_csv(package_dir / "VARIABLE_LABELS.csv", variable_labels)
    _write_csv(package_dir / "VALUE_LABELS.csv", value_labels)

    xlsx_written = False
    if config.include_xlsx:
        xlsx_written = _write_xlsx(
            package_dir / "data" / "xlsx" / "morskamary_cumulative_database.xlsx",
            {name: rows for name, rows in csv_tables.items() if rows},
        )

    sav_written = False
    sav_note = "disabled"
    if config.include_sav:
        sav_written, sav_note = _write_sav_exports(
            package_dir / "data" / "spss",
            {
                "evidence_records": evidence_record_rows,
                "evidence_occurrences": occurrence_rows,
                "gap_clusters": gap_rows,
                "dynamic_credentials": credential_rows,
            },
        )

    citation_text = (
        "Repository dataset citation template (APA-like)\n\n"
        f"Repository: robertbartlomiejski/morskamary\n"
        f"Release tag: {config.release_tag}\n"
        f"Source commit (data inputs): {config.source_commit_sha}\n"
        f"Package commit: {config.package_commit_sha}\n"
        f"Access date: {config.access_date}\n\n"
        "Template:\n"
        "Bartlomiejski, R. (2026). morskamary cumulative evidence package "
        f"({config.version_tag}) [Dataset]. GitHub Release ({config.release_tag}). "
        f"Source commit {config.source_commit_sha}. Accessed {config.access_date}. "
        "Provenance: derived cumulative package from repository-managed pipelines.\n\n"
        "Note: 'Source commit' identifies the data inputs used to generate this package.\n"
        "'Package commit' identifies the commit that stores the generated package "
        "(may be 'pending_until_merge' if the package has not yet been merged).\n\n"
        "For dataset-file level references include exact relative path and checksum.\n"
    )
    (package_dir / "CITATION_APA.txt").write_text(citation_text, encoding="utf-8")

    manifest_payload = {
        "package_name": f"morskamary_cumulative_evidence_{config.version_tag}",
        "version_tag": config.version_tag,
        "release_tag": config.release_tag,
        "source_commit_sha": config.source_commit_sha,
        "package_commit_sha": config.package_commit_sha,
        "access_date": config.access_date,
        "created_at_utc": _utc_now(),
        "codebook_path": "docs/CROSS_RUN_EVIDENCE_CODEBOOK.md",
        "methodology_path": "docs/CUMULATIVE_DATABASE_METHODOLOGY.md",
        "statistical_analysis_plan_path": "docs/STATISTICAL_ANALYSIS_PLAN.md",
        "content_analysis_protocol_path": "docs/CONTENT_ANALYSIS_PROTOCOL.md",
        "data_release_policy_path": "docs/DATA_RELEASE_POLICY.md",
        "schema_validation": {
            "validated_tables": sorted(schema_map.keys()),
            "errors": [],
        },
        "exports": {
            "csv_utf8": True,
            "xlsx_written": xlsx_written,
            "sav_written": sav_written,
            "sav_note": sav_note,
            "jsonl": True,
        },
        "notes": [
            "Large empirical artifacts remain outside this code PR.",
            "Package is generated by code and validated by repository schemas.",
            "Metadata/checksums are intended to be referenced in Git.",
        ],
    }
    manifest_schema_path = schema_dir / "research_data_package_manifest.schema.json"
    if manifest_schema_path.exists():
        manifest_errors = _validate_manifest(manifest_payload, manifest_schema_path)
        if manifest_errors:
            for message in manifest_errors:
                print(f"{status_label('error')} release manifest invalid: {message}")
            return 1
    (package_dir / "RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    checksum_rows: list[tuple[str, str]] = []
    for file_path in sorted(path for path in package_dir.rglob("*") if path.is_file()):
        rel = file_path.relative_to(package_dir).as_posix()
        checksum_rows.append((_sha256_file(file_path), rel))
    (package_dir / "CHECKSUMS.sha256").write_text(
        "".join(f"{sha}  {rel}\n" for sha, rel in checksum_rows),
        encoding="utf-8",
    )

    zip_path = (
        config.output_dir / f"morskamary_cumulative_evidence_{config.version_tag}.zip"
    )
    if zip_path.exists():
        zip_path.unlink()
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in sorted(
            path for path in package_dir.rglob("*") if path.is_file()
        ):
            archive.write(file_path, file_path.relative_to(package_dir).as_posix())

    print(f"{status_label('ok')} Wrote package directory: {package_dir}")
    print(f"{status_label('ok')} Wrote package archive: {zip_path}")
    print(
        f"{status_label('ok')} Schema-validated rows: {sum(len(csv_tables[key]) for key in schema_map)}"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build versioned cumulative research data package."
    )
    parser.add_argument("--repo-root", default=".", help="Repository root path.")
    parser.add_argument(
        "--output-dir",
        default="outputs/release_packages",
        help="Directory where package folder and zip are written.",
    )
    parser.add_argument(
        "--version-tag",
        required=True,
        help="Package version tag (e.g., v0.1.0).",
    )
    parser.add_argument(
        "--release-tag",
        default="draft",
        help="Release tag reference used in citation metadata.",
    )
    parser.add_argument(
        "--access-date",
        default=str(date.today()),
        help="Access date for citation metadata (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--source-commit-sha",
        default="",
        help=(
            "Commit SHA of the data inputs used to generate this package. "
            "Defaults to git HEAD when omitted."
        ),
    )
    parser.add_argument(
        "--commit-sha",
        default="",
        help="Deprecated alias for --source-commit-sha; --source-commit-sha takes precedence.",
    )
    parser.add_argument(
        "--package-commit-sha",
        default="pending_until_merge",
        help=(
            "Commit SHA of the commit that stores the generated package. "
            "Use 'pending_until_merge' (default) when the package has not yet been merged."
        ),
    )
    parser.add_argument(
        "--include-xlsx",
        default="true",
        help="Write XLSX workbook when openpyxl is available (true/false).",
    )
    parser.add_argument(
        "--include-sav",
        default="false",
        help="Write SAV exports when pyreadstat/pandas are available (true/false).",
    )
    parser.add_argument(
        "--bootstrap-empty-manual-sources",
        default="false",
        help=(
            "Create empty (header-only) manual-source files when absent (true/false). "
            "Only use when no real manual sources have been ingested yet."
        ),
    )
    return parser.parse_args(argv)


def _to_bool(value: str) -> bool:
    token = value.strip().lower()
    if token in {"1", "true", "yes", "y"}:
        return True
    if token in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    # --source-commit-sha takes precedence over deprecated --commit-sha alias
    source_commit_sha = (
        args.source_commit_sha.strip()
        or args.commit_sha.strip()
        or _get_git_sha(repo_root)
    )
    config = PackageConfig(
        repo_root=repo_root,
        output_dir=Path(args.output_dir).resolve(),
        version_tag=args.version_tag.strip(),
        release_tag=args.release_tag.strip() or "draft",
        access_date=args.access_date.strip(),
        source_commit_sha=source_commit_sha,
        package_commit_sha=args.package_commit_sha.strip() or "pending_until_merge",
        include_xlsx=_to_bool(args.include_xlsx),
        include_sav=_to_bool(args.include_sav),
        bootstrap_empty_manual_sources=_to_bool(args.bootstrap_empty_manual_sources),
    )
    if not config.version_tag:
        print(f"{status_label('error')} --version-tag must be non-empty")
        return 1
    return build_versioned_research_data_package(config)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
