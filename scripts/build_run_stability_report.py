#!/usr/bin/env python3
"""Build a cross-run comparability and saturation report from archived runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.axis_classifier import AxisClassifier

RUNS_INDEX_REL = Path("_index/runs_index.jsonl")
CUMULATIVE_INDEX_FILENAME = "cumulative_runs_index.csv"
MANIFEST_FILES: tuple[str, ...] = ("manifest.json", "run_manifest.json")
LIVE_RECORDS_REL = Path("research_sources/live_records.json")
QMBD_REL = Path("analysis_outputs/cumulative_qmbd_records.json")
CONSTRAINTS_REL = Path("research_sources/query_protocol_constraints.json")
CANONICAL_AXES: tuple[str, ...] = (
    "MARINE",
    "MARITIME",
    "OCEANIC",
    "HYDRONIZATION",
)
AXIS_CODE_MAP = {
    "M": "MARINE",
    "T": "MARITIME",
    "O": "OCEANIC",
    "H": "HYDRONIZATION",
}


@dataclass(frozen=True)
class RunReference:
    """One archived run located via the archive indexes."""

    run_id: str
    run_path: str
    timestamp_utc: str
    archived_at: str


@dataclass(frozen=True)
class RunSnapshot:
    """Normalized metrics extracted for one archived run."""

    run_id: str
    run_path: str
    timestamp_utc: str
    doi_set: frozenset[str]
    axis_distribution: dict[str, int]
    comparability_fingerprint: str
    fingerprint_payload: dict[str, Any]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    return str(value).strip()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("records", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _normalize_doi(value: Any) -> str:
    token = _normalize_string(value).casefold()
    if not token:
        return ""
    prefixes = (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    )
    for prefix in prefixes:
        if token.startswith(prefix):
            token = token[len(prefix) :].strip()
            break
    return token.rstrip(".,; ")


def _canonical_axis(value: Any) -> str:
    token = _normalize_string(value).upper()
    if not token:
        return ""
    if token in CANONICAL_AXES:
        return token
    return AXIS_CODE_MAP.get(token, "")


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            payload = line.strip()
            if not payload:
                continue
            try:
                row = json.loads(payload)
            except json.JSONDecodeError as exc:
                print(
                    f"[WARN] Skipping malformed JSONL row {line_number} in {path}: {exc}",
                    file=sys.stderr,
                )
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def load_run_references(archive_root: Path) -> list[RunReference]:
    """Load and merge archived run references from both archive indexes."""

    jsonl_rows = _jsonl_rows(archive_root / RUNS_INDEX_REL)
    csv_path = archive_root / CUMULATIVE_INDEX_FILENAME
    csv_rows: list[dict[str, str]] = []
    if csv_path.is_file():
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            csv_rows = list(csv.DictReader(handle))

    merged: dict[str, dict[str, str]] = {}
    for row in jsonl_rows:
        run_id = _normalize_string(row.get("run_id"))
        if not run_id:
            continue
        merged[run_id] = {
            "run_id": run_id,
            "run_path": _normalize_string(row.get("run_path")),
            "timestamp_utc": _normalize_string(row.get("timestamp_utc")),
            "archived_at": _normalize_string(row.get("archived_at")),
        }
    for row in csv_rows:
        run_id = _normalize_string(row.get("run_id"))
        if not run_id:
            continue
        slot = merged.setdefault(
            run_id,
            {"run_id": run_id, "run_path": "", "timestamp_utc": "", "archived_at": ""},
        )
        slot["run_path"] = _normalize_string(row.get("run_path")) or slot["run_path"]
        slot["timestamp_utc"] = (
            _normalize_string(row.get("timestamp_utc")) or slot["timestamp_utc"]
        )

    references: list[RunReference] = []
    for run_id, row in merged.items():
        run_path = _normalize_string(row.get("run_path")) or f"runs/{run_id}"
        timestamp = _normalize_string(row.get("timestamp_utc")) or _normalize_string(
            row.get("archived_at")
        )
        references.append(
            RunReference(
                run_id=run_id,
                run_path=run_path,
                timestamp_utc=timestamp,
                archived_at=row.get("archived_at", ""),
            )
        )
    references.sort(key=lambda item: (item.timestamp_utc or item.archived_at, item.run_id))
    return references


def _resolve_run_dir(archive_root: Path, reference: RunReference) -> Path:
    candidate = archive_root / Path(reference.run_path)
    if candidate.is_dir():
        return candidate
    fallback = archive_root / "runs" / reference.run_id
    return fallback


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    for filename in MANIFEST_FILES:
        path = run_dir / filename
        if path.is_file():
            payload = _read_json(path)
            if isinstance(payload, dict):
                return payload
    return {}


def _load_optional_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = _read_json(path)
    return _extract_records(payload)


def _load_optional_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = _read_json(path)
    return payload if isinstance(payload, dict) else {}


def _providers_from_manifest(manifest: dict[str, Any]) -> list[str]:
    raw_values = [
        manifest.get("provider_set"),
        manifest.get("providers"),
        manifest.get("workflow", {}).get("inputs", {}).get("providers")
        if isinstance(manifest.get("workflow"), dict)
        else "",
    ]
    providers: set[str] = set()
    for raw in raw_values:
        for item in _normalize_string(raw).split(","):
            token = item.strip().lower()
            if token:
                providers.add(token)
    return sorted(providers)


def _normalize_query_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    protocol_version = _normalize_string(constraints.get("protocol_version"))
    queries = constraints.get("queries")
    time_windows: set[str] = set()
    sampling_strategies: set[str] = set()
    if isinstance(queries, list):
        for query in queries:
            if not isinstance(query, dict):
                continue
            time_window = query.get("time_window")
            if isinstance(time_window, dict):
                time_windows.add(json.dumps(time_window, sort_keys=True, separators=(",", ":")))
            sampling_strategy = query.get("sampling_strategy")
            if isinstance(sampling_strategy, dict):
                sampling_strategies.add(
                    json.dumps(sampling_strategy, sort_keys=True, separators=(",", ":"))
                )
    query_ids: set[str] = set()
    if isinstance(queries, list):
        for query in queries:
            if not isinstance(query, dict):
                continue
            qid = _normalize_string(query.get("query_id"))
            if qid:
                query_ids.add(qid)
    return {
        "query_protocol_version": protocol_version or "unknown",
        "time_windows": sorted(time_windows),
        "sampling_strategies": sorted(sampling_strategies),
        "query_ids": sorted(query_ids),
    }


def build_comparability_fingerprint(
    *,
    providers_used: list[str],
    query_protocol_version: str,
    time_windows: list[str],
    sampling_strategies: list[str],
    query_ids: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return the canonical comparability fingerprint and its source payload."""

    payload = {
        "providers_used": sorted({item.strip().lower() for item in providers_used if item}),
        "query_ids": sorted({item for item in (query_ids or []) if item}),
        "query_protocol_version": _normalize_string(query_protocol_version) or "unknown",
        "time_windows": sorted({item for item in time_windows if item}),
        "sampling_strategies": sorted({item for item in sampling_strategies if item}),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest, payload


def compute_jaccard_similarity(left: set[str], right: set[str]) -> float:
    """Return DOI-set Jaccard similarity with an empty-set guard."""

    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def compute_axis_stability_score(
    axis_distribution_a: dict[str, int], axis_distribution_b: dict[str, int]
) -> float:
    """Return 1 - max absolute ratio gap across the four canonical axes."""

    total_a = sum(axis_distribution_a.get(axis, 0) for axis in CANONICAL_AXES)
    total_b = sum(axis_distribution_b.get(axis, 0) for axis in CANONICAL_AXES)
    if total_a <= 0 or total_b <= 0:
        return 0.0
    max_gap = 0.0
    for axis in CANONICAL_AXES:
        ratio_a = axis_distribution_a.get(axis, 0) / total_a
        ratio_b = axis_distribution_b.get(axis, 0) / total_b
        max_gap = max(max_gap, abs(ratio_a - ratio_b))
    return max(0.0, 1.0 - max_gap)


def _text_for_axis_classification(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "title",
        "abstract",
        "summary",
        "description",
        "context_sentence",
        "evidence_text",
    ):
        value = _normalize_string(record.get(key))
        if value:
            parts.append(value)
    subject_terms = record.get("subject_terms")
    if isinstance(subject_terms, list):
        parts.extend(_normalize_string(item) for item in subject_terms if _normalize_string(item))
    return " ".join(item for item in parts if item)


def _extract_axis_name(record: dict[str, Any], classifier: AxisClassifier) -> str:
    for key in ("axis_name", "qmbd_axis", "axis"):
        axis = _canonical_axis(record.get(key))
        if axis:
            return axis
    axis_code = _canonical_axis(record.get("axis_code") or record.get("qmbd_axis_code"))
    if axis_code:
        return axis_code
    classification = record.get("classification")
    if isinstance(classification, dict):
        axis = _canonical_axis(classification.get("axis") or classification.get("axis_name"))
        if axis:
            return axis

    text = _text_for_axis_classification(record)
    if not text:
        return ""
    return classifier.classify_axis(text).name


def load_run_snapshot(
    archive_root: Path, reference: RunReference, classifier: AxisClassifier
) -> RunSnapshot | None:
    """Load one archived run's DOI set, axis distribution, and fingerprint."""

    run_dir = _resolve_run_dir(archive_root, reference)
    if not run_dir.is_dir():
        print(
            f"[WARN] Skipping missing archived run directory for {reference.run_id}: {run_dir}",
            file=sys.stderr,
        )
        return None

    manifest = _load_manifest(run_dir)

    if manifest.get("is_static_recovery_mode"):
        print(
            f"[INFO] Skipping static-recovery run {reference.run_id} from stability analysis.",
            file=sys.stderr,
        )
        return None

    live_records = _load_optional_records(run_dir / LIVE_RECORDS_REL)
    qmbd_records = _load_optional_records(run_dir / QMBD_REL)
    constraints = _load_optional_object(run_dir / CONSTRAINTS_REL)

    doi_set = frozenset(
        doi for doi in (_normalize_doi(record.get("doi")) for record in live_records) if doi
    )

    axis_distribution = {axis: 0 for axis in CANONICAL_AXES}
    axis_records = qmbd_records if qmbd_records else live_records
    for record in axis_records:
        axis_name = _extract_axis_name(record, classifier)
        if axis_name:
            axis_distribution[axis_name] += 1

    constraint_payload = _normalize_query_constraints(constraints)
    fingerprint, fingerprint_payload = build_comparability_fingerprint(
        providers_used=_providers_from_manifest(manifest),
        query_protocol_version=str(constraint_payload["query_protocol_version"]),
        time_windows=list(constraint_payload["time_windows"]),
        sampling_strategies=list(constraint_payload["sampling_strategies"]),
        query_ids=list(constraint_payload["query_ids"]),
    )

    timestamp_utc = (
        reference.timestamp_utc
        or _normalize_string(manifest.get("analysis_timestamp_utc"))
        or _normalize_string(manifest.get("timestamp_utc"))
        or reference.archived_at
    )

    return RunSnapshot(
        run_id=reference.run_id,
        run_path=reference.run_path,
        timestamp_utc=timestamp_utc,
        doi_set=doi_set,
        axis_distribution=axis_distribution,
        comparability_fingerprint=fingerprint,
        fingerprint_payload=fingerprint_payload,
    )


def assess_saturation(
    *,
    run_pairs: list[dict[str, Any]],
    provisional_transitions: int,
) -> dict[str, Any]:
    """Derive the report-level saturation status from ordered run pairs."""

    if len(run_pairs) < 1:
        return {
            "status": "not_assessable",
            "consecutive_stable_transitions": 0,
            "threshold_for_provisional": provisional_transitions,
            "rationale": "Fewer than two archived runs were available for comparison.",
        }

    if any(not pair["comparability_fingerprint_match"] for pair in run_pairs):
        return {
            "status": "not_assessable",
            "consecutive_stable_transitions": 0,
            "threshold_for_provisional": provisional_transitions,
            "rationale": (
                "At least one consecutive run pair used a non-matching comparability "
                "fingerprint, so saturation cannot be interpreted across changing "
                "acquisition conditions."
            ),
        }

    trailing_stable = 0
    for pair in reversed(run_pairs):
        if pair.get("stable_transition"):
            trailing_stable += 1
            continue
        break

    saturated_threshold = provisional_transitions + 1
    if trailing_stable >= saturated_threshold:
        status = "saturated"
        rationale = (
            f"The latest {trailing_stable} comparable transitions all met the DOI "
            "overlap, diminishing-return, and axis-stability thresholds."
        )
    elif trailing_stable >= provisional_transitions:
        status = "provisional_saturation"
        rationale = (
            f"The latest {trailing_stable} comparable transitions met the stability "
            "thresholds, indicating provisional saturation."
        )
    else:
        status = "not_saturated"
        rationale = (
            "Comparable runs remain below the consecutive stable-transition threshold "
            "required to claim saturation."
        )

    return {
        "status": status,
        "consecutive_stable_transitions": trailing_stable,
        "threshold_for_provisional": provisional_transitions,
        "rationale": rationale,
    }


def build_run_stability_report(
    *,
    archive_root: Path,
    output_path: Path,
    jaccard_threshold: float,
    new_doi_threshold: float,
    axis_stability_threshold: float,
    provisional_transitions: int,
) -> dict[str, Any]:
    """Build, persist, and return the cross-run stability report."""

    references = load_run_references(archive_root)
    classifier = AxisClassifier()
    snapshots = [
        snapshot
        for snapshot in (
            load_run_snapshot(archive_root, reference, classifier) for reference in references
        )
        if snapshot is not None
    ]

    seen_dois: set[str] = set()
    run_pairs: list[dict[str, Any]] = []
    previous_snapshot: RunSnapshot | None = None
    for snapshot in snapshots:
        seen_dois.update(snapshot.doi_set)
        if previous_snapshot is None:
            previous_snapshot = snapshot
            continue

        jaccard = compute_jaccard_similarity(set(previous_snapshot.doi_set), set(snapshot.doi_set))
        new_unique = snapshot.doi_set - previous_snapshot.doi_set
        current_doi_count = len(snapshot.doi_set)
        new_ratio = len(new_unique) / current_doi_count if current_doi_count else 0.0
        axis_stability = compute_axis_stability_score(
            previous_snapshot.axis_distribution, snapshot.axis_distribution
        )
        fingerprint_match = (
            previous_snapshot.comparability_fingerprint == snapshot.comparability_fingerprint
        )
        stable_transition = bool(
            fingerprint_match
            and jaccard > jaccard_threshold
            and new_ratio < new_doi_threshold
            and axis_stability > axis_stability_threshold
        )
        run_pairs.append(
            {
                "run_a": previous_snapshot.run_id,
                "run_b": snapshot.run_id,
                "comparability_fingerprint_match": fingerprint_match,
                "comparability_fingerprint_a": previous_snapshot.comparability_fingerprint,
                "comparability_fingerprint_b": snapshot.comparability_fingerprint,
                "jaccard_doi_similarity": round(jaccard, 6),
                "new_unique_dois": len(new_unique),
                "new_doi_ratio": round(new_ratio, 6),
                "cumulative_unique_dois": len(seen_dois),
                "axis_distribution_a": dict(previous_snapshot.axis_distribution),
                "axis_distribution_b": dict(snapshot.axis_distribution),
                "axis_stability_score": round(axis_stability, 6),
                "stable_transition": stable_transition,
            }
        )
        previous_snapshot = snapshot

    saturation = assess_saturation(
        run_pairs=run_pairs,
        provisional_transitions=provisional_transitions,
    )
    report = {
        "report_type": "cross_run_stability",
        "timestamp_utc": _now_utc_iso(),
        "runs_analyzed": len(snapshots),
        "run_pairs": run_pairs,
        "saturation_assessment": saturation,
        "saturation_thresholds": {
            "jaccard_stable_threshold": jaccard_threshold,
            "new_doi_diminishing_threshold": new_doi_threshold,
            "axis_stability_threshold": axis_stability_threshold,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a cross-run comparability and saturation report."
    )
    parser.add_argument(
        "--archive-root",
        default="outputs/run_archive",
        help="Archive root containing _index/ and runs/ (default: outputs/run_archive).",
    )
    parser.add_argument(
        "--output-path",
        default="outputs/run_stability_report.json",
        help="JSON report output path (default: outputs/run_stability_report.json).",
    )
    parser.add_argument(
        "--jaccard-threshold",
        type=float,
        default=0.85,
        help="Stable-transition DOI Jaccard threshold (default: 0.85).",
    )
    parser.add_argument(
        "--new-doi-threshold",
        type=float,
        default=0.05,
        help="Stable-transition diminishing-return threshold (default: 0.05).",
    )
    parser.add_argument(
        "--axis-stability-threshold",
        type=float,
        default=0.90,
        help="Stable-transition axis stability threshold (default: 0.90).",
    )
    parser.add_argument(
        "--provisional-transitions",
        type=int,
        default=2,
        help="Stable transitions needed for provisional saturation (default: 2).",
    )
    return parser.parse_args([] if argv is None else argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_run_stability_report(
            archive_root=Path(args.archive_root),
            output_path=Path(args.output_path),
            jaccard_threshold=float(args.jaccard_threshold),
            new_doi_threshold=float(args.new_doi_threshold),
            axis_stability_threshold=float(args.axis_stability_threshold),
            provisional_transitions=int(args.provisional_transitions),
        )
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"[ERROR] Failed to build run stability report: {exc}", file=sys.stderr)
        return 1

    print(
        "[OK] Wrote run stability report "
        f"({report['runs_analyzed']} runs, status="
        f"{report['saturation_assessment']['status']})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
