#!/usr/bin/env python3
"""Revalidate local historical live-analysis outputs and build cumulative records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZipFile

DEFAULT_OUTPUT_DIR = Path("outputs/manual_sources")
REQUIRED_LIVE_PATHS = (
    "outputs/research_sources/live_records.json",
    "outputs/research_sources/live_records_triangulated.json",
    "outputs/cumulative_qmbd_records.json",
)


@dataclass(frozen=True)
class BundleCheck:
    """Compatibility and count summary for one bundle."""

    bundle_id: str
    source_path: str
    extracted_dir: str
    status: str
    reason: str
    live_records_count: int
    triangulated_records_count: int
    cumulative_qmbd_records_count: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    return str(value).strip()


def _sha256_text(value: str) -> str:
    digest = hashlib.sha256()
    digest.update(value.encode("utf-8"))
    return digest.hexdigest()


def _canonical_record_id(record: dict[str, Any]) -> str:
    doi = _normalize_text(record.get("doi")).casefold()
    source_id = _normalize_text(record.get("source_id")).casefold()
    title = _normalize_text(record.get("title")).casefold()
    token = doi or source_id or title
    if not token:
        token = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return f"hist_{_sha256_text(token)[:16]}"


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("records"), list):
            return [item for item in payload["records"] if isinstance(item, dict)]
        if isinstance(payload.get("items"), list):
            return [item for item in payload["items"] if isinstance(item, dict)]
    return []


def _extract_bundle(source: Path, workspace: Path) -> Path:
    if source.is_dir():
        return source
    target = workspace / source.stem
    target.mkdir(parents=True, exist_ok=True)
    with ZipFile(source, "r") as archive:
        archive.extractall(target)
    return target


def _resolve_required_paths(root: Path) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for rel in REQUIRED_LIVE_PATHS:
        direct = root / rel
        nested = root / "live-enriched-analysis-outputs" / rel
        if direct.exists():
            resolved[rel] = direct
        elif nested.exists():
            resolved[rel] = nested
    return resolved


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_rows(
    bundle_id: str, dataset: str, records: Iterable[dict[str, Any]]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, record in enumerate(records, start=1):
        canonical_id = _canonical_record_id(record)
        rows.append(
            {
                "bundle_id": bundle_id,
                "dataset": dataset,
                "record_index": str(index),
                "canonical_record_id": canonical_id,
                "doi": _normalize_text(record.get("doi")),
                "source_id": _normalize_text(record.get("source_id")),
                "title": _normalize_text(record.get("title")),
                "record_origin": _normalize_text(record.get("record_origin")),
                "axis_name": _normalize_text(record.get("axis_name")),
            }
        )
    return rows


def _write_csv(
    path: Path, rows: list[dict[str, str]], fieldnames: tuple[str, ...]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _append_unique_jsonl(path: Path, rows: list[dict[str, str]]) -> tuple[int, int]:
    existing_keys: set[tuple[str, str, str]] = set()
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                payload = line.strip()
                if not payload:
                    continue
                row = json.loads(payload)
                if not isinstance(row, dict):
                    continue
                existing_keys.add(
                    (
                        _normalize_text(row.get("bundle_id")),
                        _normalize_text(row.get("dataset")),
                        _normalize_text(row.get("canonical_record_id")),
                    )
                )

    inserted = 0
    duplicates = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            key = (row["bundle_id"], row["dataset"], row["canonical_record_id"])
            if key in existing_keys:
                duplicates += 1
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            inserted += 1
            existing_keys.add(key)
    return inserted, duplicates


def revalidate_historical_outputs(
    *,
    inputs: list[Path],
    output_dir: Path,
) -> int:
    output_dir = output_dir.resolve()
    compatibility_csv = output_dir / "historical_compatibility.csv"
    report_json = output_dir / "historical_revalidation_report.json"
    cumulative_jsonl = output_dir / "historical_cumulative_records.jsonl"

    checks: list[BundleCheck] = []
    extracted_rows: list[dict[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="morskamary-historical-") as temp_dir:
        workspace = Path(temp_dir)
        for source in inputs:
            resolved = source.expanduser().resolve()
            if not resolved.exists():
                checks.append(
                    BundleCheck(
                        bundle_id=f"bundle_{_sha256_text(str(resolved))[:12]}",
                        source_path=resolved.as_posix(),
                        extracted_dir="",
                        status="missing",
                        reason="input_path_not_found",
                        live_records_count=0,
                        triangulated_records_count=0,
                        cumulative_qmbd_records_count=0,
                    )
                )
                continue

            extracted_dir = _extract_bundle(resolved, workspace)
            bundle_id = f"bundle_{_sha256_text(resolved.as_posix())[:12]}"
            required = _resolve_required_paths(extracted_dir)
            missing_required = [
                rel for rel in REQUIRED_LIVE_PATHS if rel not in required
            ]
            if missing_required:
                checks.append(
                    BundleCheck(
                        bundle_id=bundle_id,
                        source_path=resolved.as_posix(),
                        extracted_dir=extracted_dir.as_posix(),
                        status="incompatible",
                        reason=f"missing_required:{'|'.join(missing_required)}",
                        live_records_count=0,
                        triangulated_records_count=0,
                        cumulative_qmbd_records_count=0,
                    )
                )
                continue

            try:
                live_records = _extract_records(
                    _load_json(required[REQUIRED_LIVE_PATHS[0]])
                )
                triangulated = _extract_records(
                    _load_json(required[REQUIRED_LIVE_PATHS[1]])
                )
                cumulative = _extract_records(
                    _load_json(required[REQUIRED_LIVE_PATHS[2]])
                )
            except (OSError, json.JSONDecodeError) as exc:
                checks.append(
                    BundleCheck(
                        bundle_id=bundle_id,
                        source_path=resolved.as_posix(),
                        extracted_dir=extracted_dir.as_posix(),
                        status="invalid",
                        reason=f"json_parse_error:{exc}",
                        live_records_count=0,
                        triangulated_records_count=0,
                        cumulative_qmbd_records_count=0,
                    )
                )
                continue

            extracted_rows.extend(_to_rows(bundle_id, "live_records", live_records))
            extracted_rows.extend(
                _to_rows(bundle_id, "live_records_triangulated", triangulated)
            )
            extracted_rows.extend(
                _to_rows(bundle_id, "cumulative_qmbd_records", cumulative)
            )

            checks.append(
                BundleCheck(
                    bundle_id=bundle_id,
                    source_path=resolved.as_posix(),
                    extracted_dir=extracted_dir.as_posix(),
                    status="compatible",
                    reason="ok",
                    live_records_count=len(live_records),
                    triangulated_records_count=len(triangulated),
                    cumulative_qmbd_records_count=len(cumulative),
                )
            )

    inserted_rows, duplicate_rows = _append_unique_jsonl(
        cumulative_jsonl, extracted_rows
    )
    compatibility_rows = [
        {
            "bundle_id": check.bundle_id,
            "source_path": check.source_path,
            "extracted_dir": check.extracted_dir,
            "status": check.status,
            "reason": check.reason,
            "live_records_count": str(check.live_records_count),
            "triangulated_records_count": str(check.triangulated_records_count),
            "cumulative_qmbd_records_count": str(check.cumulative_qmbd_records_count),
        }
        for check in checks
    ]
    _write_csv(
        compatibility_csv,
        compatibility_rows,
        (
            "bundle_id",
            "source_path",
            "extracted_dir",
            "status",
            "reason",
            "live_records_count",
            "triangulated_records_count",
            "cumulative_qmbd_records_count",
        ),
    )

    report_payload = {
        "captured_at_utc": _utc_now(),
        "inputs_total": len(inputs),
        "compatible_bundles": sum(
            1 for check in checks if check.status == "compatible"
        ),
        "incompatible_bundles": sum(
            1
            for check in checks
            if check.status in {"incompatible", "invalid", "missing"}
        ),
        "records_scanned": len(extracted_rows),
        "records_inserted": inserted_rows,
        "records_skipped_duplicates": duplicate_rows,
        "compatibility_csv": compatibility_csv.as_posix(),
        "historical_cumulative_jsonl": cumulative_jsonl.as_posix(),
    }
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(
        json.dumps(report_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {compatibility_csv}")
    print(f"Wrote {report_json}")
    print(f"Updated {cumulative_jsonl}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Revalidate historical live-analysis bundles and recalculate cumulative IDs/counts."
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Input ZIP file or unpacked directory (repeatable).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for compatibility and cumulative artifacts.",
    )
    return parser.parse_args([] if argv is None else argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return revalidate_historical_outputs(
        inputs=[Path(token) for token in args.input],
        output_dir=Path(str(args.output_dir)),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
