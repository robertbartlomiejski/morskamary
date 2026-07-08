#!/usr/bin/env python3
"""Build cross-run longitudinal evidence tables from archived methodological runs."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INDEX_CSV_FILENAME = "cumulative_runs_index.csv"
RUNS_DIRNAME = "runs"
DEFAULT_DEDUPE_KEY = "doi,source_id,title"
DEFAULT_MANUAL_LEDGER = "outputs/manual_sources/manual_sources_ledger.jsonl"

LIVE_RECORDS_REL = Path("research_sources/live_records.json")
TRIANGULATED_REL = Path("research_sources/live_records_triangulated.json")
CUMULATIVE_REL = Path("analysis_outputs/cumulative_qmbd_records.json")
MANIFEST_REL = Path("manifest.json")

RUN_SUMMARY_COLUMNS: tuple[str, ...] = (
    "run_id",
    "run_path",
    "timestamp_utc",
    "manifest_timestamp_utc",
    "live_records_count",
    "triangulated_records_count",
    "cumulative_qmbd_records_count",
    "evidence_rows_total",
    "evidence_rows_dedupable",
    "unique_dedupe_values",
)

EVIDENCE_OCCURRENCE_COLUMNS: tuple[str, ...] = (
    "run_id",
    "run_path",
    "timestamp_utc",
    "manifest_timestamp_utc",
    "dataset",
    "record_index",
    "dedupe_value",
    "dedupe_field_used",
    "doi",
    "source_id",
    "title",
    "record_origin",
    "axis_name",
)

EVIDENCE_INDEX_COLUMNS: tuple[str, ...] = (
    "dedupe_value",
    "first_seen_timestamp_utc",
    "first_seen_run_id",
    "last_seen_timestamp_utc",
    "last_seen_run_id",
    "run_count",
    "occurrence_count",
    "datasets",
    "record_origins",
    "axis_names",
    "dois",
    "source_ids",
    "titles",
)


@dataclass(frozen=True)
class RunContext:
    """Metadata required for extracting one run's evidence records."""

    run_id: str
    run_path: str
    timestamp_utc: str
    manifest_timestamp_utc: str
    run_dir: Path


@dataclass(frozen=True)
class EvidenceOccurrence:
    """One evidence occurrence row emitted to the longitudinal table."""

    run_id: str
    run_path: str
    timestamp_utc: str
    manifest_timestamp_utc: str
    dataset: str
    record_index: int
    dedupe_value: str
    dedupe_field_used: str
    doi: str
    source_id: str
    title: str
    record_origin: str
    axis_name: str


def _to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _parse_dedupe_keys(value: str) -> tuple[str, ...]:
    keys = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    if not keys:
        raise ValueError("dedupe-key must include at least one field")
    allowed = {"doi", "source_id", "title"}
    unknown = sorted(set(keys) - allowed)
    if unknown:
        raise ValueError(f"unsupported dedupe-key fields: {', '.join(unknown)}")
    return keys


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    return str(value).strip()


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("records"), list):
            return [item for item in payload["records"] if isinstance(item, dict)]
        if isinstance(payload.get("items"), list):
            return [item for item in payload["items"] if isinstance(item, dict)]
    return []


def _pick_dedupe_value(
    record: dict[str, Any], dedupe_keys: tuple[str, ...]
) -> tuple[str, str]:
    for field in dedupe_keys:
        value = _normalize_string(record.get(field))
        if value:
            return value.casefold(), field
    return "", ""


def _parse_timestamp(value: str) -> tuple[int, str]:
    token = value.strip()
    if not token:
        return (1, "")
    return (0, token)


def _load_run_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / MANIFEST_REL
    payload = _read_json(manifest_path)
    if not isinstance(payload, dict):
        raise ValueError(f"{manifest_path}: manifest root must be an object")
    return payload


def _resolve_run_dir(archive_root: Path, run_path: str, run_id: str) -> Path:
    candidate = (archive_root / run_path).resolve()
    if candidate.is_dir():
        return candidate
    fallback = archive_root / RUNS_DIRNAME / run_id
    if fallback.is_dir():
        return fallback
    raise FileNotFoundError(
        f"run directory missing for run_id={run_id}, run_path={run_path}"
    )


def _write_csv(
    path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _load_manual_ledger_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            payload = line.strip()
            if not payload:
                continue
            try:
                item = json.loads(payload)
            except json.JSONDecodeError:
                print(
                    f"WARNING: skipping malformed manual ledger row {line_number} in {path}",
                    file=sys.stderr,
                )
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def build_cross_run_evidence_index(
    *,
    archive_root: Path,
    output_dir: Path,
    dedupe_keys: tuple[str, ...],
    fail_on_invalid: bool,
    manual_ledger_path: Path | None = None,
) -> int:
    """Build longitudinal run/evidence tables from archived runs."""
    index_path = archive_root / INDEX_CSV_FILENAME
    if not index_path.is_file():
        print(f"ERROR: missing {index_path}", file=sys.stderr)
        return 1

    with index_path.open("r", encoding="utf-8-sig", newline="") as handle:
        run_rows = list(csv.DictReader(handle))
    if not run_rows:
        print(f"ERROR: {index_path} has no run rows", file=sys.stderr)
        return 1

    contexts: list[RunContext] = []
    for row in run_rows:
        run_id = _normalize_string(row.get("run_id"))
        run_path = _normalize_string(row.get("run_path"))
        timestamp_utc = _normalize_string(row.get("timestamp_utc"))
        if not run_id or not run_path:
            message = f"Invalid cumulative index row: run_id={run_id!r}, run_path={run_path!r}"
            if fail_on_invalid:
                print(f"ERROR: {message}", file=sys.stderr)
                return 1
            print(f"WARNING: {message}", file=sys.stderr)
            continue
        try:
            run_dir = _resolve_run_dir(archive_root, run_path, run_id)
            manifest = _load_run_manifest(run_dir)
        except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError) as exc:
            if fail_on_invalid:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            print(f"WARNING: skipping invalid run {run_id}: {exc}", file=sys.stderr)
            continue
        contexts.append(
            RunContext(
                run_id=run_id,
                run_path=run_path,
                timestamp_utc=timestamp_utc,
                manifest_timestamp_utc=_normalize_string(manifest.get("timestamp_utc")),
                run_dir=run_dir,
            )
        )

    if not contexts:
        print("ERROR: no valid runs available after validation", file=sys.stderr)
        return 1

    contexts.sort(key=lambda item: (_parse_timestamp(item.timestamp_utc), item.run_id))

    occurrences: list[EvidenceOccurrence] = []
    run_summaries: list[dict[str, str]] = []
    invalid_runs = 0

    for context in contexts:
        dataset_payloads = (
            ("live_records", context.run_dir / LIVE_RECORDS_REL),
            ("live_records_triangulated", context.run_dir / TRIANGULATED_REL),
            ("cumulative_qmbd_records", context.run_dir / CUMULATIVE_REL),
        )
        run_records: list[EvidenceOccurrence] = []
        run_unique_values: set[str] = set()
        missing_or_invalid = False

        for dataset_name, dataset_path in dataset_payloads:
            try:
                payload = _read_json(dataset_path)
            except (OSError, json.JSONDecodeError) as exc:
                missing_or_invalid = True
                if fail_on_invalid:
                    print(
                        f"ERROR: failed to read {dataset_path} for run {context.run_id}: {exc}",
                        file=sys.stderr,
                    )
                    return 1
                print(
                    f"WARNING: skipping run {context.run_id}; invalid dataset {dataset_path}: {exc}",
                    file=sys.stderr,
                )
                break

            records = _extract_records(payload)
            for index, record in enumerate(records, start=1):
                dedupe_value, dedupe_field = _pick_dedupe_value(record, dedupe_keys)
                occurrence = EvidenceOccurrence(
                    run_id=context.run_id,
                    run_path=context.run_path,
                    timestamp_utc=context.timestamp_utc,
                    manifest_timestamp_utc=context.manifest_timestamp_utc,
                    dataset=dataset_name,
                    record_index=index,
                    dedupe_value=dedupe_value,
                    dedupe_field_used=dedupe_field,
                    doi=_normalize_string(record.get("doi")),
                    source_id=_normalize_string(record.get("source_id")),
                    title=_normalize_string(record.get("title")),
                    record_origin=_normalize_string(record.get("record_origin")),
                    axis_name=_normalize_string(record.get("axis_name")),
                )
                if occurrence.dedupe_value:
                    run_unique_values.add(occurrence.dedupe_value)
                run_records.append(occurrence)

        if missing_or_invalid:
            invalid_runs += 1
            continue

        occurrences.extend(run_records)

        summary_row = {
            "run_id": context.run_id,
            "run_path": context.run_path,
            "timestamp_utc": context.timestamp_utc,
            "manifest_timestamp_utc": context.manifest_timestamp_utc,
            "live_records_count": str(
                sum(1 for item in run_records if item.dataset == "live_records")
            ),
            "triangulated_records_count": str(
                sum(
                    1
                    for item in run_records
                    if item.dataset == "live_records_triangulated"
                )
            ),
            "cumulative_qmbd_records_count": str(
                sum(
                    1
                    for item in run_records
                    if item.dataset == "cumulative_qmbd_records"
                )
            ),
            "evidence_rows_total": str(len(run_records)),
            "evidence_rows_dedupable": str(
                sum(1 for item in run_records if item.dedupe_value)
            ),
            "unique_dedupe_values": str(len(run_unique_values)),
        }
        run_summaries.append(summary_row)

    occurrence_rows = [
        {
            "run_id": item.run_id,
            "run_path": item.run_path,
            "timestamp_utc": item.timestamp_utc,
            "manifest_timestamp_utc": item.manifest_timestamp_utc,
            "dataset": item.dataset,
            "record_index": str(item.record_index),
            "dedupe_value": item.dedupe_value,
            "dedupe_field_used": item.dedupe_field_used,
            "doi": item.doi,
            "source_id": item.source_id,
            "title": item.title,
            "record_origin": item.record_origin,
            "axis_name": item.axis_name,
        }
        for item in sorted(
            occurrences,
            key=lambda row: (
                row.dedupe_value,
                row.timestamp_utc,
                row.run_id,
                row.dataset,
            ),
        )
    ]

    manual_rows = (
        _load_manual_ledger_rows(manual_ledger_path) if manual_ledger_path else []
    )
    manual_occurrences = 0
    for index, row in enumerate(manual_rows, start=1):
        title = _normalize_string(row.get("title") or row.get("file_name"))
        source_id = _normalize_string(row.get("source_id") or row.get("id"))
        synthetic_record = {
            "doi": _normalize_string(row.get("doi")),
            "source_id": source_id,
            "title": title,
        }
        dedupe_value, dedupe_field = _pick_dedupe_value(synthetic_record, dedupe_keys)
        occurrence_rows.append(
            {
                "run_id": "manual-ledger",
                "run_path": "outputs/manual_sources",
                "timestamp_utc": _normalize_string(row.get("ingested_at_utc")),
                "manifest_timestamp_utc": "",
                "dataset": "manual_supporting_sources",
                "record_index": str(index),
                "dedupe_value": dedupe_value,
                "dedupe_field_used": dedupe_field,
                "doi": synthetic_record["doi"],
                "source_id": synthetic_record["source_id"],
                "title": synthetic_record["title"],
                "record_origin": "manual_supporting_source",
                "axis_name": _normalize_string(row.get("axis_name")),
            }
        )
        manual_occurrences += 1

    grouped: dict[str, list[EvidenceOccurrence]] = {}
    for row in occurrence_rows:
        dedupe_value = row.get("dedupe_value", "")
        if not dedupe_value:
            continue
        grouped.setdefault(dedupe_value, []).append(
            EvidenceOccurrence(
                run_id=row.get("run_id", ""),
                run_path=row.get("run_path", ""),
                timestamp_utc=row.get("timestamp_utc", ""),
                manifest_timestamp_utc=row.get("manifest_timestamp_utc", ""),
                dataset=row.get("dataset", ""),
                record_index=int(row.get("record_index", "0") or 0),
                dedupe_value=dedupe_value,
                dedupe_field_used=row.get("dedupe_field_used", ""),
                doi=row.get("doi", ""),
                source_id=row.get("source_id", ""),
                title=row.get("title", ""),
                record_origin=row.get("record_origin", ""),
                axis_name=row.get("axis_name", ""),
            )
        )

    evidence_index_rows: list[dict[str, str]] = []
    for dedupe_value, items in sorted(grouped.items(), key=lambda kv: kv[0]):
        sorted_items = sorted(
            items, key=lambda row: (_parse_timestamp(row.timestamp_utc), row.run_id)
        )
        first = sorted_items[0]
        last = sorted_items[-1]
        evidence_index_rows.append(
            {
                "dedupe_value": dedupe_value,
                "first_seen_timestamp_utc": first.timestamp_utc,
                "first_seen_run_id": first.run_id,
                "last_seen_timestamp_utc": last.timestamp_utc,
                "last_seen_run_id": last.run_id,
                "run_count": str(len({item.run_id for item in items})),
                "occurrence_count": str(len(items)),
                "datasets": "|".join(
                    sorted({item.dataset for item in items if item.dataset})
                ),
                "record_origins": "|".join(
                    sorted({item.record_origin for item in items if item.record_origin})
                ),
                "axis_names": "|".join(
                    sorted({item.axis_name for item in items if item.axis_name})
                ),
                "dois": "|".join(sorted({item.doi for item in items if item.doi})),
                "source_ids": "|".join(
                    sorted({item.source_id for item in items if item.source_id})
                ),
                "titles": "|".join(
                    sorted({item.title for item in items if item.title})
                ),
            }
        )

    run_summaries_sorted = sorted(
        run_summaries,
        key=lambda row: (_parse_timestamp(row["timestamp_utc"]), row["run_id"]),
    )
    _write_csv(
        output_dir / "cross_run_run_summary.csv",
        RUN_SUMMARY_COLUMNS,
        run_summaries_sorted,
    )
    _write_csv(
        output_dir / "cross_run_evidence_occurrences.csv",
        EVIDENCE_OCCURRENCE_COLUMNS,
        occurrence_rows,
    )
    _write_csv(
        output_dir / "cross_run_evidence_index.csv",
        EVIDENCE_INDEX_COLUMNS,
        evidence_index_rows,
    )

    report_payload = {
        "archive_root": archive_root.as_posix(),
        "output_dir": output_dir.as_posix(),
        "runs_total": len(contexts),
        "runs_processed": len(run_summaries_sorted),
        "runs_skipped_invalid": invalid_runs,
        "dedupe_keys": list(dedupe_keys),
        "occurrences_total": len(occurrence_rows),
        "manual_occurrences_total": manual_occurrences,
        "dedupe_groups_total": len(evidence_index_rows),
    }
    (output_dir / "cross_run_evidence_build_report.json").write_text(
        json.dumps(report_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {output_dir / 'cross_run_run_summary.csv'}")
    print(f"Wrote {output_dir / 'cross_run_evidence_occurrences.csv'}")
    print(f"Wrote {output_dir / 'cross_run_evidence_index.csv'}")
    print(
        f"Processed runs: {len(run_summaries_sorted)} (skipped invalid: {invalid_runs})"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the cross-run index build."""
    parser = argparse.ArgumentParser(
        description="Build cross-run cumulative evidence index from archived run outputs."
    )
    parser.add_argument(
        "--archive-root",
        default="outputs/run_archive",
        help="Archive root containing runs/ and cumulative_runs_index.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/run_archive",
        help="Output directory for cross-run evidence tables.",
    )
    parser.add_argument(
        "--dedupe-key",
        default=DEFAULT_DEDUPE_KEY,
        help="Comma-separated dedupe key order; each of doi,source_id,title.",
    )
    parser.add_argument(
        "--fail-on-invalid",
        default="true",
        help="Whether to fail (true) or skip (false) invalid runs.",
    )
    parser.add_argument(
        "--manual-ledger",
        default=DEFAULT_MANUAL_LEDGER,
        help=(
            "Optional JSONL ledger with manually uploaded supporting sources. "
            "Set to empty string to disable."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        dedupe_keys = _parse_dedupe_keys(str(args.dedupe_key))
        fail_on_invalid = _to_bool(str(args.fail_on_invalid))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    repo_root = Path(".").resolve()
    archive_root = (repo_root / str(args.archive_root)).resolve()
    output_dir = (repo_root / str(args.output_dir)).resolve()
    manual_ledger_arg = str(args.manual_ledger).strip()
    manual_ledger_path = (
        (repo_root / manual_ledger_arg).resolve() if manual_ledger_arg else None
    )
    return build_cross_run_evidence_index(
        archive_root=archive_root,
        output_dir=output_dir,
        dedupe_keys=dedupe_keys,
        fail_on_invalid=fail_on_invalid,
        manual_ledger_path=manual_ledger_path,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
