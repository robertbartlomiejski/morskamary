#!/usr/bin/env python3
"""Compute offline leave-one-out provider sensitivity metrics from live records."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.axis_classifier import AxisClassifier
from src.core import BlueDynamicsAxis

DEFAULT_INPUT_DIR = Path("outputs") / "research_sources"
DEFAULT_OUTPUT_DIR = Path("outputs") / "research_sources"
REPORT_FILENAME = "provider_sensitivity_report.json"
TRIANGULATED_FILENAME = "live_records_triangulated.json"
LIVE_RECORDS_FILENAME = "live_records.json"
QUERY_LOG_FILENAME = "query_execution_log.csv"


@dataclass(frozen=True)
class ProviderMetadata:
    """Provider label reconciliation metadata sourced from the query log."""

    canonical_labels: dict[str, str]
    providers: list[str]


def _utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute H1/H3 fragment metrics from immutable live-acquisition "
            "snapshots using leave-one-out provider subsets."
        )
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Directory containing live_records*.json and query_execution_log.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where provider_sensitivity_report.json will be written.",
    )
    parser.add_argument(
        "--providers",
        default="",
        help="Comma-separated provider list. Default: auto-detect from inputs.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _choose_input_file(input_dir: Path) -> Path:
    triangulated_path = input_dir / TRIANGULATED_FILENAME
    if triangulated_path.is_file():
        return triangulated_path
    records_path = input_dir / LIVE_RECORDS_FILENAME
    if records_path.is_file():
        return records_path
    raise FileNotFoundError(
        "No live records snapshot found. Expected either "
        f"{triangulated_path.as_posix()} or {records_path.as_posix()}."
    )


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise ValueError("Live records snapshot must be a list or dict payload.")

    for key in ("records", "items", "live_records", "triangulated_records"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]

    raise ValueError("Could not locate record list in live records snapshot.")


def _normalize_provider_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return token


def _load_provider_metadata(input_dir: Path) -> ProviderMetadata:
    path = input_dir / QUERY_LOG_FILENAME
    if not path.is_file():
        return ProviderMetadata(canonical_labels={}, providers=[])

    labels: dict[str, str] = {}
    providers: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_provider = str(row.get("provider") or "").strip()
            canonical_provider = str(
                row.get("provider_canonical") or row.get("provider") or ""
            ).strip()
            canonical_token = _normalize_provider_token(canonical_provider)
            if raw_provider and canonical_token:
                labels[_normalize_provider_token(raw_provider)] = canonical_token
            if canonical_token and canonical_token not in seen:
                seen.add(canonical_token)
                providers.append(canonical_token)
    return ProviderMetadata(canonical_labels=labels, providers=providers)


def _canonical_provider(
    provider_value: Any, provider_metadata: ProviderMetadata
) -> str:
    raw = str(provider_value or "").strip()
    if not raw:
        return ""
    raw_token = _normalize_provider_token(raw)
    if not raw_token:
        return ""
    return provider_metadata.canonical_labels.get(raw_token, raw_token)


def _detect_providers(
    records: Iterable[dict[str, Any]],
    provider_metadata: ProviderMetadata,
    explicit_providers: str,
) -> list[str]:
    if explicit_providers.strip():
        parsed = [
            _canonical_provider(item, provider_metadata)
            for item in explicit_providers.split(",")
        ]
        return [item for item in parsed if item]

    if provider_metadata.providers:
        return provider_metadata.providers

    discovered: list[str] = []
    seen: set[str] = set()
    for record in records:
        provider = _primary_provider(record, provider_metadata)
        if provider and provider not in seen:
            seen.add(provider)
            discovered.append(provider)
    return discovered


def _primary_provider(
    record: dict[str, Any], provider_metadata: ProviderMetadata
) -> str:
    provider = _canonical_provider(record.get("provider"), provider_metadata)
    if provider:
        return provider

    supporting = record.get("supporting_providers")
    if isinstance(supporting, list):
        for item in supporting:
            candidate = _canonical_provider(item, provider_metadata)
            if candidate:
                return candidate
    return ""


def _record_fragments(record: dict[str, Any]) -> list[str]:
    fragments: list[str] = []

    title = str(record.get("title") or "").strip()
    if title:
        fragments.append(title)

    subject_terms = record.get("subject_terms")
    if isinstance(subject_terms, list):
        for term in subject_terms:
            normalized = str(term or "").strip()
            if normalized:
                fragments.append(normalized)

    return fragments


def _empty_axis_counts() -> dict[str, int]:
    return {axis.name: 0 for axis in BlueDynamicsAxis}


def _compute_axis_fragment_counts(
    records: Iterable[dict[str, Any]], classifier: AxisClassifier
) -> dict[str, int]:
    counts = _empty_axis_counts()
    for record in records:
        for fragment in _record_fragments(record):
            axis = classifier.classify_axis(fragment)
            counts[axis.name] += 1
    return counts


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _direction_from_counts(numerator: int, denominator: int) -> str:
    if numerator == 0 and denominator == 0:
        return "not_computable"
    if numerator > denominator:
        return "numerator_gt_denominator"
    if numerator < denominator:
        return "numerator_lt_denominator"
    return "balanced"


def _build_summary(
    records: list[dict[str, Any]], classifier: AxisClassifier
) -> tuple[dict[str, Any], dict[str, str]]:
    counts = _compute_axis_fragment_counts(records, classifier)
    maritime = counts["MARITIME"]
    oceanic = counts["OCEANIC"]
    marine = counts["MARINE"]

    h1_ratio = _safe_ratio(maritime, oceanic)
    h3_ratio = _safe_ratio(marine, oceanic)
    directions = {
        "h1": _direction_from_counts(maritime, oceanic),
        "h3": _direction_from_counts(marine, oceanic),
    }
    return (
        {
            "total_records": len(records),
            "axis_fragment_counts": counts,
            "h1_maritime_oceanic_ratio": h1_ratio,
            "h3_marine_oceanic_balance": h3_ratio,
        },
        directions,
    )


def analyze_provider_sensitivity(
    *,
    input_dir: Path,
    providers_argument: str = "",
) -> dict[str, Any]:
    """Return an offline leave-one-out provider sensitivity report."""
    input_path = _choose_input_file(input_dir)
    records = _extract_records(_load_json(input_path))
    provider_metadata = _load_provider_metadata(input_dir)
    providers = _detect_providers(records, provider_metadata, providers_argument)
    classifier = AxisClassifier()

    full_sample, full_directions = _build_summary(records, classifier)
    leave_one_out: dict[str, Any] = {}
    sensitive_providers: list[str] = []

    for provider in providers:
        remaining = [
            record
            for record in records
            if _primary_provider(record, provider_metadata) != provider
        ]
        excluded = len(records) - len(remaining)
        subset_summary, subset_directions = _build_summary(remaining, classifier)
        h1_changed = subset_directions["h1"] != full_directions["h1"]
        h3_changed = subset_directions["h3"] != full_directions["h3"]
        if h1_changed or h3_changed:
            sensitive_providers.append(provider)
        leave_one_out[provider] = {
            "excluded_records": excluded,
            "remaining_records": len(remaining),
            "axis_fragment_counts": subset_summary["axis_fragment_counts"],
            "h1_maritime_oceanic_ratio": subset_summary["h1_maritime_oceanic_ratio"],
            "h3_marine_oceanic_balance": subset_summary["h3_marine_oceanic_balance"],
            "h1_direction_changed": h1_changed,
            "h3_direction_changed": h3_changed,
        }

    verdict = "stable"
    if sensitive_providers:
        verdict = f"sensitive_to_{sensitive_providers[0]}"

    return {
        "analysis_type": "leave_one_out_provider_sensitivity",
        "timestamp_utc": _utc_now_iso(),
        "full_sample": full_sample,
        "leave_one_out": leave_one_out,
        "sensitivity_verdict": verdict,
    }


def write_report(report: dict[str, Any], output_dir: Path) -> Path:
    """Persist the provider sensitivity report to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / REPORT_FILENAME
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> int:
    args = _parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    report = analyze_provider_sensitivity(
        input_dir=input_dir,
        providers_argument=str(args.providers or ""),
    )
    output_path = write_report(report, output_dir)
    print(f"[OK] Wrote provider sensitivity report to {output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
