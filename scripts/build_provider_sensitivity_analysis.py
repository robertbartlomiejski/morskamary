#!/usr/bin/env python3
"""Build fail-closed provider-sensitivity diagnostics without new API calls."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

GROWTH_ELIGIBLE_STATUSES = {
    "new_record",
    "updated_metadata",
    "provider_enriched",
    "semantic_enriched",
}
AXIS_CODES = {
    "MARINE": "M",
    "MARITIME": "T",
    "OCEANIC": "O",
    "HYDRONIZATION": "H",
}


def _split(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "")
    for separator in ("||", "|", ";", ","):
        if separator in text:
            return [part.strip() for part in text.split(separator) if part.strip()]
    return [text.strip()] if text.strip() else []


def _normalise_provider(value: Any) -> str:
    token = str(value or "").strip().lower()
    if "crossref" in token:
        return "crossref"
    if "scopus" in token or "elsevier" in token:
        return "scopus"
    if "openalex" in token:
        return "openalex"
    if token == "wos" or "web of science" in token:
        return "wos"
    return token


def _providers(row: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("providers_seen", "supporting_providers", "provider", "source_provider"):
        values.update(_normalise_provider(item) for item in _split(row.get(key)))
    values.discard("")
    return values


def _axis(row: Mapping[str, Any]) -> str:
    return str(row.get("axis_group") or row.get("qmbd_axis") or "").strip().upper()


def _sector(row: Mapping[str, Any]) -> str:
    value = str(row.get("sector") or row.get("sector_slug") or "").strip()
    if value:
        return value
    candidates = _split(row.get("sector_candidates"))
    return candidates[0] if candidates else "_unassigned"


def _evidence_id(row: Mapping[str, Any]) -> str:
    return str(
        row.get("evidence_id")
        or row.get("record_id")
        or row.get("source_id")
        or ""
    ).strip()


def _doi(row: Mapping[str, Any]) -> str:
    value = str(row.get("canonical_doi") or row.get("doi") or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    return value.rstrip(".,; ")


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read_jsonl_required(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"required {label} file does not exist: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid {label} JSONL row {line_number}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"invalid {label} JSONL row {line_number}: object required")
        rows.append(payload)
    if not rows:
        raise ValueError(f"required {label} file contains no rows: {path}")
    return rows


def _read_csv_required(path: Path, label: str) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"required {label} file does not exist: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"required {label} CSV has no header: {path}")
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError(f"required {label} file contains no rows: {path}")
    return rows


def _parse_timestamp_strict(value: str) -> datetime:
    """Parse an ISO-8601 timestamp string; raise ValueError on malformed input."""
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result
    except ValueError as exc:
        raise ValueError(f"malformed timestamp: {value!r}") from exc


def _recency_score(latest_at: str, reference: datetime) -> float:
    if not latest_at:
        return 0.0
    try:
        observed = datetime.fromisoformat(latest_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    days = max(0.0, (reference - observed).total_seconds() / 86400.0)
    return math.exp(-days / 365.0)


def _demand_id(label: str, sector: str, axis: str) -> str:
    digest = hashlib.sha256(f"{sector}|{axis}|{label}".encode("utf-8")).hexdigest()[:16]
    return f"cd_{digest}"


_REPO_ROOT_SENSITIVITY = Path(__file__).resolve().parents[1]


def _to_repo_relative_posix(path: Path) -> str:
    """Return repo-relative POSIX path, or redact if outside the repository."""
    try:
        return path.resolve().relative_to(_REPO_ROOT_SENSITIVITY).as_posix()
    except ValueError:
        return "[redacted-out-of-tree-path]"


def _load_analysis_timestamp(derived_demands_path: Path) -> datetime:
    """Load the fixed analysis timestamp from layer4_manifest.json.

    Raises ValueError when the manifest is missing, not a JSON object, or
    missing/malformed ``analysis_timestamp_utc``.  Never falls back to the
    wall clock so that scientific scoring is fully deterministic.
    """
    manifest = derived_demands_path.parent / "layer4_manifest.json"
    if not manifest.is_file():
        raise ValueError(
            f"layer4_manifest.json is required for deterministic scoring "
            f"but was not found: {manifest}"
        )
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"layer4_manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"layer4_manifest.json must be a JSON object: {manifest}")
    ts_value = str(payload.get("analysis_timestamp_utc") or "").strip()
    if not ts_value:
        raise ValueError(
            "layer4_manifest.json is missing required field 'analysis_timestamp_utc'"
        )
    return _parse_timestamp_strict(ts_value)


def _load_validated_supply(path: Path | None) -> dict[str, list[int]] | None:
    if path is None:
        return None
    if not path.is_file():
        raise ValueError(f"explicit validated supply map does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("validated supply map must be a JSON object")
    status = str(payload.get("validation_status", "")).strip()
    has_supply = bool(payload.get("has_validated_supply"))
    rows = payload.get("validated_supply_by_demand_id")
    if status == "not_computable" and not has_supply:
        if rows not in ({}, None):
            raise ValueError("not_computable supply map must not contain validated rows")
        return None
    if status != "validated" or not has_supply or not isinstance(rows, dict):
        raise ValueError(
            "explicit supply map must be validated, or a not_computable empty map"
        )
    output: dict[str, list[int]] = {}
    for demand_id, entry in rows.items():
        if not isinstance(entry, dict):
            raise ValueError(f"validated supply entry must be an object: {demand_id}")
        if str(entry.get("validation_status", "validated")).strip() != "validated":
            raise ValueError(f"unvalidated supply entry: {demand_id}")
        levels = entry.get("eqf_levels", [])
        if isinstance(levels, (str, int)):
            levels = [levels]
        parsed = sorted(
            {
                int(level)
                for level in levels
                if str(level).strip().isdigit() and 4 <= int(level) <= 7
            }
        )
        evidence_ids = _split(entry.get("validation_evidence_ids"))
        if not parsed or not evidence_ids:
            raise ValueError(
                f"validated supply entry lacks EQF levels or validation evidence: {demand_id}"
            )
        output[str(demand_id)] = parsed
    if not output:
        raise ValueError("validated supply map declares supply but contains no valid entries")
    return output


def _dynamic_subsets(contributing: set[str]) -> dict[str, tuple[str, ...]]:
    if not contributing:
        raise ValueError("no contributing providers found in evidence records")
    ordered = tuple(sorted(contributing))
    subsets: dict[str, tuple[str, ...]] = {"all_canonical": ordered}
    if len(ordered) > 1:
        for excluded in ordered:
            remaining = tuple(provider for provider in ordered if provider != excluded)
            label = (
                "direct_crossref_excluded"
                if excluded == "crossref"
                else f"{excluded}_excluded"
            )
            subsets[label] = remaining
    for provider in ordered:
        subsets[f"{provider}_only"] = (provider,)
    return subsets


def _recompute_demands(
    evidence: Sequence[Mapping[str, Any]],
    signals: Sequence[Mapping[str, Any]],
    original_demands: Sequence[Mapping[str, Any]],
    active_providers: set[str],
    reference_time: datetime,
) -> list[dict[str, Any]]:
    evidence_by_id = {
        _evidence_id(row): row
        for row in evidence
        if _evidence_id(row)
        and (
            not str(row.get("record_novelty_status", "")).strip()
            or str(row.get("record_novelty_status", "")) in GROWTH_ELIGIBLE_STATUSES
        )
    }
    demand_id_lookup = {
        (
            str(row.get("competence_label", "")).strip(),
            _sector(row),
            _axis(row),
        ): str(row.get("competence_demand_id", "")).strip()
        for row in original_demands
    }
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for signal in signals:
        evidence_id = str(signal.get("evidence_id", "")).strip()
        if evidence_id not in evidence_by_id:
            continue
        label = str(signal.get("competence_label", "")).strip()
        axis = _axis(signal)
        sector = _sector(signal)
        if not label or not axis:
            continue
        groups.setdefault((label, sector, axis), []).append(signal)

    provider_universe = {
        provider
        for row in evidence_by_id.values()
        for provider in _providers(row)
        if provider in active_providers
    }
    family_universe = {
        str(signal.get("query_family", "")).strip()
        for grouped in groups.values()
        for signal in grouped
        if str(signal.get("query_family", "")).strip()
    }

    output: list[dict[str, Any]] = []
    for (label, sector, axis), grouped_signals in sorted(groups.items()):
        evidence_ids = sorted(
            {
                str(signal.get("evidence_id", "")).strip()
                for signal in grouped_signals
                if str(signal.get("evidence_id", "")).strip() in evidence_by_id
            }
        )
        rows = [evidence_by_id[evidence_id] for evidence_id in evidence_ids]
        providers = sorted(
            {
                provider
                for row in rows
                for provider in _providers(row)
                if provider in active_providers
            }
        )
        if not providers:
            continue
        dois = sorted({_doi(row) for row in rows if _doi(row)})
        families = sorted(
            {
                family
                for signal in grouped_signals
                for family in (
                    _split(signal.get("query_families_seen"))
                    or [str(signal.get("query_family", "")).strip()]
                )
                if family
            }
        )
        confidences = [_safe_float(signal.get("confidence_score")) for signal in grouped_signals]
        confidence_mean = sum(confidences) / len(confidences) if confidences else 0.0
        latest_at = max(
            (
                str(row.get("latest_seen_at_utc", "")).strip()
                for row in rows
                if str(row.get("latest_seen_at_utc", "")).strip()
            ),
            default="",
        )
        provider_diversity = len(providers) / max(1, len(provider_universe))
        query_diversity = len(families) / max(1, len(family_universe))
        score = round(
            0.30 * min(1.0, len(dois) / 10.0)
            + 0.20 * provider_diversity
            + 0.20 * _recency_score(latest_at, reference_time)
            + 0.15 * query_diversity
            + 0.15 * confidence_mean,
            6,
        )
        output.append(
            {
                "competence_demand_id": demand_id_lookup.get(
                    (label, sector, axis), _demand_id(label, sector, axis)
                ),
                "competence_label": label,
                "sector": sector,
                "axis_group": axis,
                "axis_code": AXIS_CODES.get(axis, ""),
                "demand_strength_score": score,
                "evidence_record_count": len(rows),
                "unique_doi_count": len(dois),
                "provider_count": len(providers),
                "providers_seen": "|".join(providers),
                "query_families_seen": "|".join(families),
                "semantic_confidence_mean": round(confidence_mean, 6),
                "evidence_ids": "|".join(evidence_ids),
            }
        )
    return output


def _cohens_d(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) <= 1 or len(right) <= 1:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_var = sum((value - left_mean) ** 2 for value in left) / (len(left) - 1)
    right_var = sum((value - right_mean) ** 2 for value in right) / (len(right) - 1)
    pooled = (
        (len(left) - 1) * left_var + (len(right) - 1) * right_var
    ) / (len(left) + len(right) - 2)
    if pooled <= 0:
        return None
    return round((left_mean - right_mean) / math.sqrt(pooled), 6)


def _h1(demands: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    maritime = [
        _safe_float(row.get("demand_strength_score"))
        for row in demands
        if _axis(row) == "MARITIME"
    ]
    oceanic = [
        _safe_float(row.get("demand_strength_score"))
        for row in demands
        if _axis(row) == "OCEANIC"
    ]
    effect = _cohens_d(maritime, oceanic)
    if not maritime or not oceanic or effect is None:
        interpretation = "not_computable"
    elif effect >= 0.5:
        interpretation = "supported_maritime_dominance"
    elif effect >= 0.2:
        interpretation = "partially_supported_maritime"
    else:
        interpretation = "not_supported"
    warnings: list[str] = []
    if min(len(maritime), len(oceanic)) < 5:
        warnings.append("small_cell_stability")
    if effect is None and maritime and oceanic:
        warnings.append("zero_or_undefined_pooled_sd")
    return {
        "hypothesis_id": "H1",
        "hypothesis_label": "Maritimisation Shift",
        "test_used": "Cohen's d (signed) on recomputed demand_strength_score by axis group",
        "sample_size_maritime": len(maritime),
        "sample_size_oceanic": len(oceanic),
        "mean_maritime": round(sum(maritime) / len(maritime), 6) if maritime else None,
        "mean_oceanic": round(sum(oceanic) / len(oceanic), 6) if oceanic else None,
        "effect_size_cohens_d": effect,
        "interpretation": interpretation,
        "validity_warning": "|".join(warnings),
    }


def _h2(
    demands: Sequence[Mapping[str, Any]],
    supply: Mapping[str, Sequence[int]] | None,
) -> dict[str, Any]:
    hydro_ids = {
        str(row.get("competence_demand_id", "")).strip()
        for row in demands
        if _axis(row) == "HYDRONIZATION"
        and str(row.get("competence_demand_id", "")).strip()
    }
    covered = {
        demand_id
        for demand_id in hydro_ids
        if supply is not None and set(supply.get(demand_id, ())) & {6, 7}
    }
    missing = len(hydro_ids) - len(covered)
    if supply is None or not hydro_ids:
        ratio = None
        interpretation = "not_computable"
    else:
        ratio = missing / len(hydro_ids)
        if ratio >= 0.5:
            interpretation = "supported"
        elif ratio >= 0.25:
            interpretation = "partially_supported"
        else:
            interpretation = "not_supported"
    return {
        "hypothesis_id": "H2",
        "hypothesis_label": "Hydronization Lag",
        "unit_of_analysis": "competence_demand_id",
        "hydronization_demand_count": len(hydro_ids),
        "validated_covered_demand_count": len(covered),
        "validated_missing_demand_count": missing,
        "validated_supply_map_provided": supply is not None,
        "association_metric_missing_ratio": round(ratio, 6) if ratio is not None else None,
        "effect_size": round(ratio, 6) if ratio is not None else None,
        "interpretation": interpretation,
        "validity_warning": "" if supply is not None else "no_validated_supply_map",
    }


def _h3(fragments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    h3_rows = [
        row
        for row in fragments
        if str(row.get("hypothesis_id", "")).strip() == "H3"
    ]
    marine = [row for row in h3_rows if _axis(row) == "MARINE"]
    oceanic = [row for row in h3_rows if _axis(row) == "OCEANIC"]
    total = len(marine) + len(oceanic)
    balance = 1.0 - abs(len(marine) - len(oceanic)) / total if total else 0.0

    bridges = 0
    interpretation = "not_computable"
    warnings: list[str] = []
    if min(len(marine), len(oceanic)) < 5:
        warnings.append("small_cell_stability")
    warnings.append("no_validated_bridge_relation")
    return {
        "hypothesis_id": "H3",
        "hypothesis_label": "MARINE vs OCEANIC Differential Coverage",
        "marine_fragment_count": len(marine),
        "oceanic_fragment_count": len(oceanic),
        "matched_fragment_count": len(h3_rows),
        "balance_score": round(balance, 6),
        "semantic_bridge_count": bridges,
        "interpretation": interpretation,
        "validity_warning": "|".join(warnings),
    }


def _share_map(counter: Mapping[str, int]) -> dict[str, float]:
    total = sum(counter.values())
    if total <= 0:
        return {}
    return {
        key: round(value / total, 6)
        for key, value in sorted(counter.items())
    }


def build_provider_sensitivity_analysis(
    *,
    evidence_path: Path,
    signals_path: Path,
    derived_demands_path: Path,
    hypothesis_fragments_path: Path,
    validated_supply_map_path: Path | None,
    output_json_path: Path,
    output_markdown_path: Path,
) -> dict[str, Any]:
    evidence = _read_jsonl_required(evidence_path, "evidence")
    # Duplicate evidence_id values are a Layer 2 structural violation: each
    # canonical evidence row must have a unique stable identifier.  Merging
    # duplicates would conceal data-quality defects; fail closed instead.
    _seen_evidence_ids: set[str] = set()
    _duplicate_evidence_ids: list[str] = []
    for _row in evidence:
        _eid = _evidence_id(_row)
        if _eid:
            if _eid in _seen_evidence_ids:
                _duplicate_evidence_ids.append(_eid)
            else:
                _seen_evidence_ids.add(_eid)
    if _duplicate_evidence_ids:
        raise ValueError(
            f"evidence_records.jsonl contains {len(_duplicate_evidence_ids)} duplicate "
            "evidence_id values (Layer 2 structural violation — deduplicate before "
            "provider sensitivity analysis): "
            + ", ".join(sorted(set(_duplicate_evidence_ids))[:10])
        )
    signals = _read_jsonl_required(signals_path, "signals")
    original_demands = _read_csv_required(derived_demands_path, "derived demands")
    fragments = _read_jsonl_required(hypothesis_fragments_path, "hypothesis fragments")
    supply = _load_validated_supply(validated_supply_map_path)
    reference_time = _load_analysis_timestamp(derived_demands_path)

    contributing = {
        provider
        for row in evidence
        for provider in _providers(row)
    }
    subsets = _dynamic_subsets(contributing)
    subset_results: dict[str, Any] = {}

    for label, provider_values in subsets.items():
        active = set(provider_values)
        subset_evidence = [
            row for row in evidence if _providers(row) & active
        ]
        evidence_ids = {
            _evidence_id(row) for row in subset_evidence if _evidence_id(row)
        }
        subset_signals = [
            row
            for row in signals
            if str(row.get("evidence_id", "")).strip() in evidence_ids
        ]
        subset_fragments = [
            row
            for row in fragments
            if str(row.get("evidence_id", "")).strip() in evidence_ids
        ]
        subset_demands = _recompute_demands(
            subset_evidence,
            subset_signals,
            original_demands,
            active,
            reference_time,
        )
        axis_counts = Counter(_axis(row) for row in subset_demands if _axis(row))
        provider_counts = Counter(
            provider
            for row in subset_evidence
            for provider in _providers(row)
            if provider in active
        )
        provider_total = sum(provider_counts.values())
        subset_results[label] = {
            "providers": sorted(active),
            "evidence_record_count": len(subset_evidence),
            "unique_doi_count": len({_doi(row) for row in subset_evidence if _doi(row)}),
            "semantic_signal_count": len(subset_signals),
            "derived_demand_count": len(subset_demands),
            "qmbd_axis_shares": _share_map(axis_counts),
            "provider_concentration": {
                "provider_counts": dict(sorted(provider_counts.items())),
                "max_provider_share": (
                    round(max(provider_counts.values()) / provider_total, 6)
                    if provider_total
                    else 0.0
                ),
            },
            "h1": _h1(subset_demands),
            "h2": _h2(subset_demands, supply),
            "h3": _h3(subset_fragments),
            "top_demands": sorted(
                subset_demands,
                key=lambda row: (
                    -_safe_float(row.get("demand_strength_score")),
                    str(row.get("competence_demand_id", "")),
                ),
            )[:10],
        }

    result = {
        "schema_version": "1.1.0",
        "api_calls_performed": 0,
        "analysis_timestamp_utc": reference_time.replace(microsecond=0).isoformat(),
        "contributing_providers": sorted(contributing),
        "subset_policy": "all contributing, dynamic leave-one-provider-out, and provider-only",
        "sensitivity_note": (
            "direct_crossref_excluded is not Crossref-independent because OpenAlex "
            "and Crossref are not fully bibliographically independent; provider-subset "
            "differences diagnose dependence, not causal provider effects."
        ),
        "subsets": subset_results,
    }
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines: list[str] = [
        "# Provider Sensitivity Analysis",
        "",
        str(result["sensitivity_note"]),
        "",
        "| subset | providers | evidence | DOI | signals | demands | max share | H1 | H2 | H3 | bridges |",
        "|---|---|---:|---:|---:|---:|---:|---|---|---|---:|",
    ]
    for label, metrics in subset_results.items():
        lines.append(
            "| {label} | {providers} | {evidence} | {doi} | {signals} | {demands} | "
            "{share} | {h1} | {h2} | {h3} | {bridges} |".format(
                label=label,
                providers=", ".join(metrics["providers"]),
                evidence=metrics["evidence_record_count"],
                doi=metrics["unique_doi_count"],
                signals=metrics["semantic_signal_count"],
                demands=metrics["derived_demand_count"],
                share=metrics["provider_concentration"]["max_provider_share"],
                h1=metrics["h1"]["interpretation"],
                h2=metrics["h2"]["interpretation"],
                h3=metrics["h3"]["interpretation"],
                bridges=metrics["h3"]["semantic_bridge_count"],
            )
        )
    output_markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--evidence-records",
        default="outputs/cumulative_database/evidence_records.jsonl",
    )
    parser.add_argument(
        "--signals",
        default="outputs/cumulative_database/competence_demand_signals.jsonl",
    )
    parser.add_argument(
        "--derived-demands",
        default="outputs/cumulative_database/derived_competence_demands.csv",
    )
    parser.add_argument(
        "--hypothesis-fragments",
        default="outputs/cumulative_database/hypothesis_semantic_fragments.jsonl",
    )
    parser.add_argument("--validated-supply-map", default="")
    parser.add_argument(
        "--output-json",
        default="outputs/cumulative_database/provider_sensitivity_analysis.json",
    )
    parser.add_argument(
        "--output-markdown",
        default="outputs/cumulative_database/provider_sensitivity_analysis.md",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        build_provider_sensitivity_analysis(
            evidence_path=Path(args.evidence_records),
            signals_path=Path(args.signals),
            derived_demands_path=Path(args.derived_demands),
            hypothesis_fragments_path=Path(args.hypothesis_fragments),
            validated_supply_map_path=(
                Path(args.validated_supply_map)
                if str(args.validated_supply_map).strip()
                else None
            ),
            output_json_path=Path(args.output_json),
            output_markdown_path=Path(args.output_markdown),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
