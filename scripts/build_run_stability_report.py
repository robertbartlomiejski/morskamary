#!/usr/bin/env python3
"""Build a fail-closed cross-run comparability and saturation report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

RUNS_INDEX_REL = Path("_index/runs_index.jsonl")
CUMULATIVE_INDEX_FILENAME = "cumulative_runs_index.csv"
MANIFEST_FILES = ("manifest.json", "run_manifest.json")
LIVE_RECORDS_REL = Path("research_sources/live_records.json")
QMBD_REL = Path("analysis_outputs/cumulative_qmbd_records.json")
CONSTRAINTS_REL = Path("research_sources/query_protocol_constraints.json")
CANONICAL_AXES = ("MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION")
AXIS_CODE_MAP = {"M": "MARINE", "T": "MARITIME", "O": "OCEANIC", "H": "HYDRONIZATION"}


@dataclass(frozen=True)
class RunReference:
    run_id: str
    run_path: str
    timestamp_utc: str
    archived_at: str


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    run_path: str
    timestamp_utc: str
    doi_set: frozenset[str]
    axis_distribution: dict[str, int]
    comparability_fingerprint: str
    fingerprint_payload: dict[str, Any]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalise(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed archive index row {line_number}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"archive index row {line_number} must be an object")
        rows.append(payload)
    return rows


def load_run_references(archive_root: Path) -> list[RunReference]:
    merged: dict[str, dict[str, str]] = {}
    for row in _jsonl_rows(archive_root / RUNS_INDEX_REL):
        run_id = _normalise(row.get("run_id"))
        if not run_id:
            continue
        merged[run_id] = {
            "run_id": run_id,
            "run_path": _normalise(row.get("run_path")),
            "timestamp_utc": _normalise(row.get("timestamp_utc")),
            "archived_at": _normalise(row.get("archived_at")),
        }

    csv_path = archive_root / CUMULATIVE_INDEX_FILENAME
    if csv_path.is_file():
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                run_id = _normalise(row.get("run_id"))
                if not run_id:
                    continue
                slot = merged.setdefault(
                    run_id,
                    {
                        "run_id": run_id,
                        "run_path": "",
                        "timestamp_utc": "",
                        "archived_at": "",
                    },
                )
                slot["run_path"] = _normalise(row.get("run_path")) or slot["run_path"]
                slot["timestamp_utc"] = (
                    _normalise(row.get("timestamp_utc")) or slot["timestamp_utc"]
                )

    references = [
        RunReference(
            run_id=run_id,
            run_path=row["run_path"] or f"runs/{run_id}",
            timestamp_utc=row["timestamp_utc"] or row["archived_at"],
            archived_at=row["archived_at"],
        )
        for run_id, row in merged.items()
    ]
    references.sort(key=lambda item: (item.timestamp_utc or item.archived_at, item.run_id))
    return references


def _resolve_run_dir(archive_root: Path, reference: RunReference) -> Path:
    configured = archive_root / Path(reference.run_path)
    if configured.is_dir():
        return configured
    return archive_root / "runs" / reference.run_id


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    for filename in MANIFEST_FILES:
        path = run_dir / filename
        if path.is_file():
            payload = _read_json(path)
            if not isinstance(payload, dict):
                raise ValueError(f"run manifest must be an object: {path}")
            return payload
    return {}


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("records", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return _extract_records(_read_json(path))


def _load_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = _read_json(path)
    return payload if isinstance(payload, dict) else {}


def _normalise_doi(value: Any) -> str:
    token = _normalise(value).casefold()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if token.startswith(prefix):
            token = token[len(prefix):].strip()
            break
    return token.rstrip(".,; ")


def _canonical_axis(value: Any) -> str:
    token = _normalise(value).upper()
    if token in CANONICAL_AXES:
        return token
    return AXIS_CODE_MAP.get(token, "")


def _is_live_like_record(record: dict[str, Any]) -> bool:
    origin = _normalise(record.get("record_origin")).lower()
    if origin in {"static_baseline", "static_literature", "baseline", "literature"}:
        return False
    if origin.startswith("live") or origin.startswith("dynamic_api_"):
        return True
    source_id = _normalise(record.get("source_id")).lower()
    if source_id.startswith(("crossref:", "scopus:", "openalex:", "wos:")):
        return True
    return True


def _providers_from_manifest(manifest: dict[str, Any]) -> list[str]:
    raw_values = [
        manifest.get("provider_set"),
        manifest.get("providers"),
        (
            manifest.get("workflow", {}).get("inputs", {}).get("providers")
            if isinstance(manifest.get("workflow"), dict)
            else ""
        ),
    ]
    providers: set[str] = set()
    for raw in raw_values:
        for item in _normalise(raw).replace("|", ",").split(","):
            token = item.strip().lower()
            if token:
                providers.add(token)
    return sorted(providers)


def _split_provider_list(value: Any) -> list[str]:
    return sorted(
        {
            item.strip().lower()
            for item in _normalise(value).replace("|", ",").split(",")
            if item.strip()
        }
    )


def _normalise_query_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    queries = constraints.get("queries")
    if not isinstance(queries, list):
        queries = []
    time_windows: set[str] = set()
    sampling_strategies: set[str] = set()
    sort_strategies: set[str] = set()
    logical_pages: set[int] = set()
    rows_per_page: set[int] = set()
    query_ids: set[str] = set()
    for query in queries:
        if not isinstance(query, dict):
            continue
        query_id = _normalise(query.get("query_id"))
        if query_id:
            query_ids.add(query_id)
        for key, target in (
            ("time_window", time_windows),
            ("sampling_strategy", sampling_strategies),
            ("sort_strategy", sort_strategies),
        ):
            value = query.get(key)
            if isinstance(value, dict):
                target.add(json.dumps(value, sort_keys=True, separators=(",", ":")))
        sampling = query.get("sampling_strategy")
        if isinstance(sampling, dict):
            pages = sampling.get("pages")
            rows = sampling.get("rows_per_page")
            if isinstance(pages, int):
                logical_pages.add(pages)
            if isinstance(rows, int):
                rows_per_page.add(rows)
    query_id_hash = (
        hashlib.sha256(
            json.dumps(sorted(query_ids), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if query_ids
        else "unknown"
    )
    return {
        "query_protocol_version": _normalise(constraints.get("protocol_version")) or "unknown",
        "time_windows": sorted(time_windows),
        "sampling_strategies": sorted(sampling_strategies),
        "sort_strategy_contract": sorted(sort_strategies),
        "logical_pages": next(iter(logical_pages)) if len(logical_pages) == 1 else None,
        "rows_per_page": next(iter(rows_per_page)) if len(rows_per_page) == 1 else None,
        "query_id_hash": query_id_hash,
    }


def _extract_classifier_version(
    qmbd_records: Sequence[dict[str, Any]],
    manifest: dict[str, Any],
) -> str:
    for record in qmbd_records:
        analyses = record.get("qmbd_analysis")
        if isinstance(analyses, list):
            for analysis in analyses:
                if not isinstance(analysis, dict):
                    continue
                provenance = analysis.get("provenance")
                if isinstance(provenance, dict):
                    version = _normalise(provenance.get("classifier_version"))
                    if version:
                        return version
        version = _normalise(record.get("classifier_version"))
        if version:
            return version
    workflow = manifest.get("workflow")
    if isinstance(workflow, dict):
        version = _normalise(workflow.get("classifier_version"))
        if version:
            return version
    return _normalise(manifest.get("classifier_version")) or "unknown"


def build_comparability_fingerprint(
    *,
    providers_used: list[str],
    query_protocol_version: str,
    time_windows: list[str],
    sampling_strategies: list[str],
    classifier_version: str = "unknown",
    requested_provider_profile: list[str] | None = None,
    contributing_provider_profile: list[str] | None = None,
    logical_pages: int | None = None,
    rows_per_page: int | None = None,
    sort_strategy_contract: list[str] | None = None,
    query_id_hash: str = "unknown",
) -> tuple[str, dict[str, Any]]:
    payload = {
        "providers_used": sorted({item.strip().lower() for item in providers_used if item}),
        "query_protocol_version": _normalise(query_protocol_version) or "unknown",
        "time_windows": sorted({item for item in time_windows if item}),
        "sampling_strategies": sorted({item for item in sampling_strategies if item}),
        "classifier_version": _normalise(classifier_version) or "unknown",
        "requested_provider_profile": sorted(
            {item.strip().lower() for item in (requested_provider_profile or []) if item}
        ),
        "contributing_provider_profile": sorted(
            {item.strip().lower() for item in (contributing_provider_profile or []) if item}
        ),
        "logical_pages": logical_pages,
        "rows_per_page": rows_per_page,
        "sort_strategy_contract": sorted(
            {item for item in (sort_strategy_contract or []) if item}
        ),
        "query_id_hash": _normalise(query_id_hash) or "unknown",
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest, payload


def compute_jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def compute_axis_stability_score(
    axis_distribution_a: dict[str, int],
    axis_distribution_b: dict[str, int],
) -> float:
    total_a = sum(axis_distribution_a.get(axis, 0) for axis in CANONICAL_AXES)
    total_b = sum(axis_distribution_b.get(axis, 0) for axis in CANONICAL_AXES)
    if total_a <= 0 or total_b <= 0:
        return 0.0
    max_gap = max(
        abs(
            axis_distribution_a.get(axis, 0) / total_a
            - axis_distribution_b.get(axis, 0) / total_b
        )
        for axis in CANONICAL_AXES
    )
    return max(0.0, 1.0 - max_gap)


def _extract_axis(record: dict[str, Any]) -> str:
    for key in ("axis_name", "axis_group", "qmbd_axis", "axis", "axis_code"):
        axis = _canonical_axis(record.get(key))
        if axis:
            return axis
    classification = record.get("classification")
    if isinstance(classification, dict):
        for key in ("axis", "axis_name", "axis_code"):
            axis = _canonical_axis(classification.get(key))
            if axis:
                return axis
    return ""


def load_run_snapshot(
    archive_root: Path,
    reference: RunReference,
    classifier: Any = None,
) -> RunSnapshot | None:
    del classifier
    run_dir = _resolve_run_dir(archive_root, reference)
    if not run_dir.is_dir():
        return None
    manifest = _load_manifest(run_dir)
    if bool(manifest.get("is_static_recovery_mode")):
        return None

    live_records = [
        row
        for row in _load_records(run_dir / LIVE_RECORDS_REL)
        if _is_live_like_record(row)
    ]
    qmbd_records = [
        row
        for row in _load_records(run_dir / QMBD_REL)
        if _is_live_like_record(row)
    ]
    constraints = _load_object(run_dir / CONSTRAINTS_REL)
    doi_set = frozenset(
        doi
        for doi in (_normalise_doi(row.get("doi")) for row in live_records)
        if doi
    )
    axis_distribution = {axis: 0 for axis in CANONICAL_AXES}
    for row in qmbd_records if qmbd_records else live_records:
        axis = _extract_axis(row)
        if axis:
            axis_distribution[axis] += 1

    constraint_payload = _normalise_query_constraints(constraints)
    workflow = manifest.get("workflow")
    workflow_inputs = (
        workflow.get("inputs", {})
        if isinstance(workflow, dict) and isinstance(workflow.get("inputs"), dict)
        else {}
    )
    contributing = _split_provider_list(
        manifest.get("contributing_provider_profile")
        or manifest.get("provider_set")
        or manifest.get("providers")
        or ""
    )
    requested = _split_provider_list(
        workflow_inputs.get("providers")
        or manifest.get("requested_provider_profile")
        or ""
    )
    fingerprint, fingerprint_payload = build_comparability_fingerprint(
        providers_used=_providers_from_manifest(manifest),
        query_protocol_version=str(constraint_payload["query_protocol_version"]),
        time_windows=list(constraint_payload["time_windows"]),
        sampling_strategies=list(constraint_payload["sampling_strategies"]),
        classifier_version=_extract_classifier_version(qmbd_records, manifest),
        requested_provider_profile=requested,
        contributing_provider_profile=contributing,
        logical_pages=constraint_payload.get("logical_pages"),
        rows_per_page=constraint_payload.get("rows_per_page"),
        sort_strategy_contract=list(constraint_payload["sort_strategy_contract"]),
        query_id_hash=str(constraint_payload["query_id_hash"]),
    )
    timestamp = (
        reference.timestamp_utc
        or _normalise(manifest.get("analysis_timestamp_utc"))
        or _normalise(manifest.get("timestamp_utc"))
        or reference.archived_at
    )
    return RunSnapshot(
        run_id=reference.run_id,
        run_path=reference.run_path,
        timestamp_utc=timestamp,
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
    if not run_pairs:
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
                "fingerprint."
            ),
        }
    trailing = 0
    for pair in reversed(run_pairs):
        if pair.get("stable_transition"):
            trailing += 1
        else:
            break
    if trailing >= provisional_transitions + 1:
        status = "saturated"
    elif trailing >= provisional_transitions:
        status = "provisional_saturation"
    else:
        status = "not_saturated"
    return {
        "status": status,
        "consecutive_stable_transitions": trailing,
        "threshold_for_provisional": provisional_transitions,
        "rationale": (
            f"{trailing} trailing comparable transition(s) met the DOI-overlap, "
            "diminishing-return, and axis-stability thresholds."
        ),
    }


def build_run_stability_report(
    *,
    archive_root: Path,
    output_path: Path,
    jaccard_threshold: float,
    new_doi_threshold: float,
    axis_stability_threshold: float,
    provisional_transitions: int,
    fail_on_missing_runs: bool = False,
) -> dict[str, Any]:
    references = load_run_references(archive_root)
    snapshots: list[RunSnapshot] = []
    skipped: list[dict[str, str]] = []
    for reference in references:
        run_dir = _resolve_run_dir(archive_root, reference)
        snapshot = load_run_snapshot(archive_root, reference)
        if snapshot is None:
            manifest = _load_manifest(run_dir) if run_dir.is_dir() else {}
            reason = (
                "static_recovery_run_excluded"
                if run_dir.is_dir() and bool(manifest.get("is_static_recovery_mode"))
                else "archived_run_directory_missing"
            )
            skipped.append(
                {
                    "run_id": reference.run_id,
                    "expected_path": str(run_dir),
                    "reason": reason,
                }
            )
        else:
            snapshots.append(snapshot)
    missing = [row for row in skipped if row["reason"] == "archived_run_directory_missing"]
    if missing and fail_on_missing_runs:
        raise ValueError(
            "archive index references missing run directories: "
            + ", ".join(row["run_id"] for row in missing)
        )

    run_pairs: list[dict[str, Any]] = []
    seen_dois: set[str] = set()
    previous: RunSnapshot | None = None
    for snapshot in snapshots:
        seen_dois.update(snapshot.doi_set)
        if previous is None:
            previous = snapshot
            continue
        jaccard = compute_jaccard_similarity(set(previous.doi_set), set(snapshot.doi_set))
        new_unique = snapshot.doi_set - previous.doi_set
        new_ratio = (
            len(new_unique) / len(snapshot.doi_set)
            if snapshot.doi_set
            else 0.0
        )
        axis_stability = compute_axis_stability_score(
            previous.axis_distribution,
            snapshot.axis_distribution,
        )
        fingerprint_match = (
            previous.comparability_fingerprint == snapshot.comparability_fingerprint
        )
        stable = bool(
            fingerprint_match
            and jaccard > jaccard_threshold
            and new_ratio < new_doi_threshold
            and axis_stability > axis_stability_threshold
        )
        run_pairs.append(
            {
                "run_a": previous.run_id,
                "run_b": snapshot.run_id,
                "comparability_fingerprint_match": fingerprint_match,
                "comparability_fingerprint_a": previous.comparability_fingerprint,
                "comparability_fingerprint_b": snapshot.comparability_fingerprint,
                "jaccard_doi_similarity": round(jaccard, 6),
                "new_unique_dois": len(new_unique),
                "new_doi_ratio": round(new_ratio, 6),
                "cumulative_unique_dois": len(seen_dois),
                "axis_distribution_a": dict(previous.axis_distribution),
                "axis_distribution_b": dict(snapshot.axis_distribution),
                "axis_stability_score": round(axis_stability, 6),
                "stable_transition": stable,
            }
        )
        previous = snapshot

    report = {
        "schema_version": "1.1.0",
        "report_type": "cross_run_stability",
        "scope_note": (
            "This cross-run report is mutable comparative analysis and must remain "
            "outside immutable per-run archives."
        ),
        "timestamp_utc": _now_utc_iso(),
        "runs_referenced": len(references),
        "runs_analyzed": len(snapshots),
        "runs_skipped": skipped,
        "run_pairs": run_pairs,
        "saturation_assessment": assess_saturation(
            run_pairs=run_pairs,
            provisional_transitions=provisional_transitions,
        ),
        "saturation_thresholds": {
            "jaccard_stable_threshold": jaccard_threshold,
            "new_doi_diminishing_threshold": new_doi_threshold,
            "axis_stability_threshold": axis_stability_threshold,
            "provisional_transitions": provisional_transitions,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive-root", default="outputs/run_archive")
    parser.add_argument(
        "--output-path",
        default="outputs/cross_run_reports/run_stability_report.json",
    )
    parser.add_argument("--jaccard-threshold", type=float, default=0.90)
    parser.add_argument("--new-doi-threshold", type=float, default=0.05)
    parser.add_argument("--axis-stability-threshold", type=float, default=0.95)
    parser.add_argument("--provisional-transitions", type=int, default=2)
    parser.add_argument("--fail-on-missing-runs", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_run_stability_report(
            archive_root=Path(args.archive_root),
            output_path=Path(args.output_path),
            jaccard_threshold=float(args.jaccard_threshold),
            new_doi_threshold=float(args.new_doi_threshold),
            axis_stability_threshold=float(args.axis_stability_threshold),
            provisional_transitions=int(args.provisional_transitions),
            fail_on_missing_runs=bool(args.fail_on_missing_runs),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] Failed to build run stability report: {exc}", file=sys.stderr)
        return 1
    print(
        "[OK] Wrote run stability report "
        f"({report['runs_analyzed']} runs, "
        f"status={report['saturation_assessment']['status']})."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
