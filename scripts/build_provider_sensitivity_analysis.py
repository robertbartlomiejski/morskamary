"""Build provider-sensitivity diagnostics from archived/cumulative data.

This script performs no provider API acquisition. It filters already persisted
Layer 2-5 artifacts into deterministic provider subsets and writes compact JSON
and Markdown summaries suitable for methodological sensitivity reporting.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set

DEFAULT_SUBSETS = {
    "all_canonical": ("crossref", "scopus", "openalex"),
    "direct_crossref_excluded": ("scopus", "openalex"),
    "scopus_only": ("scopus",),
    "openalex_only": ("openalex",),
}


def _split(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(item).strip().lower() for item in raw if str(item).strip()]
    text = str(raw or "")
    parts: List[str] = []
    for chunk in text.replace(",", "|").split("|"):
        value = chunk.strip().lower()
        if value:
            parts.append(value)
    return parts


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _providers_for_row(row: Mapping[str, Any]) -> Set[str]:
    providers: Set[str] = set()
    for key in ("providers_seen", "supporting_providers", "provider", "source_provider"):
        providers.update(_split(row.get(key)))
    normalized: Set[str] = set()
    for provider in providers:
        if "crossref" in provider:
            normalized.add("crossref")
        elif "scopus" in provider:
            normalized.add("scopus")
        elif "openalex" in provider:
            normalized.add("openalex")
        elif "wos" in provider or "web of science" in provider:
            normalized.add("wos")
        elif provider:
            normalized.add(provider)
    return normalized


def _doi_for_row(row: Mapping[str, Any]) -> str:
    for key in ("canonical_doi", "doi", "DOI"):
        value = str(row.get(key, "") or "").strip().lower()
        if value:
            return value.removeprefix("https://doi.org/")
    return ""


def _evidence_id(row: Mapping[str, Any]) -> str:
    for key in ("evidence_id", "record_id", "source_id"):
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    doi = _doi_for_row(row)
    return f"doi:{doi}" if doi else ""


def _axis(row: Mapping[str, Any]) -> str:
    return str(row.get("axis_group") or row.get("qmbd_axis") or "UNASSIGNED").strip().upper()


def _sector(row: Mapping[str, Any]) -> str:
    value = str(row.get("sector") or row.get("sector_slug") or "").strip()
    if value:
        return value
    sectors = _split(row.get("sector_candidates"))
    return sectors[0] if sectors else "unknown"


def _share_map(counts: Mapping[str, int]) -> Dict[str, float]:
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {key: round(value / total, 6) for key, value in sorted(counts.items())}


def _cohens_d(maritime_scores: List[float], oceanic_scores: List[float]) -> float | None:
    n_m, n_o = len(maritime_scores), len(oceanic_scores)
    if n_m <= 1 or n_o <= 1:
        return None
    mean_m = sum(maritime_scores) / n_m
    mean_o = sum(oceanic_scores) / n_o
    var_m = sum((value - mean_m) ** 2 for value in maritime_scores) / (n_m - 1)
    var_o = sum((value - mean_o) ** 2 for value in oceanic_scores) / (n_o - 1)
    pooled = (((n_m - 1) * var_m) + ((n_o - 1) * var_o)) / (n_m + n_o - 2)
    if pooled <= 0:
        return None
    return round((mean_m - mean_o) / math.sqrt(pooled), 6)


def _h1_from_demands(demands: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    maritime = [
        float(row.get("demand_strength_score", 0) or 0)
        for row in demands
        if _axis(row) == "MARITIME"
    ]
    oceanic = [
        float(row.get("demand_strength_score", 0) or 0)
        for row in demands
        if _axis(row) == "OCEANIC"
    ]
    effect = _cohens_d(maritime, oceanic)
    if effect is None:
        interpretation = "not_computable"
    elif effect >= 0.5:
        interpretation = "supported_maritime_dominance"
    elif effect >= 0.2:
        interpretation = "partially_supported_maritime"
    else:
        interpretation = "not_supported"
    return {
        "effect_size_cohens_d": effect,
        "interpretation": interpretation,
        "sample_size_maritime": len(maritime),
        "sample_size_oceanic": len(oceanic),
    }


def _h2_from_demands(
    demands: Sequence[Mapping[str, Any]],
    validated_supply_map: Mapping[str, Sequence[int]] | None,
) -> Dict[str, Any]:
    hydro_ids = {
        str(row.get("competence_demand_id", "")).strip()
        for row in demands
        if _axis(row) == "HYDRONIZATION" and str(row.get("competence_demand_id", "")).strip()
    }
    if validated_supply_map is None:
        return {
            "interpretation": "not_computable",
            "hydronization_demand_count": len(hydro_ids),
            "validated_covered_demand_count": 0,
            "validated_supply_map_provided": False,
        }
    covered = {
        demand_id
        for demand_id, levels in validated_supply_map.items()
        if demand_id in hydro_ids
        and any(int(level) in {6, 7} for level in levels if str(level).strip().isdigit())
    }
    missing = len(hydro_ids) - len(covered)
    ratio = missing / len(hydro_ids) if hydro_ids else None
    if ratio is None:
        interpretation = "not_computable"
    elif ratio >= 0.5:
        interpretation = "supported"
    elif ratio >= 0.25:
        interpretation = "partially_supported"
    else:
        interpretation = "not_supported"
    return {
        "interpretation": interpretation,
        "hydronization_demand_count": len(hydro_ids),
        "validated_covered_demand_count": len(covered),
        "validated_supply_map_provided": True,
        "association_metric_missing_ratio": round(ratio, 6) if ratio is not None else None,
    }


def _h3_from_fragments(fragments: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    marine = [row for row in fragments if _axis(row) == "MARINE"]
    oceanic = [row for row in fragments if _axis(row) == "OCEANIC"]
    total = len(marine) + len(oceanic)
    balance = round(1.0 - abs(len(marine) - len(oceanic)) / total, 6) if total else None
    marine_keys = {
        str(row.get("evidence_id", "") or row.get("signal_id", "")).strip()
        for row in marine
        if str(row.get("evidence_id", "") or row.get("signal_id", "")).strip()
    }
    oceanic_keys = {
        str(row.get("evidence_id", "") or row.get("signal_id", "")).strip()
        for row in oceanic
        if str(row.get("evidence_id", "") or row.get("signal_id", "")).strip()
    }
    bridge_count = len(marine_keys & oceanic_keys)
    return {
        "marine_fragment_count": len(marine),
        "oceanic_fragment_count": len(oceanic),
        "balance_score": balance,
        "semantic_bridge_count": bridge_count,
        "bridge_status": "bridged" if bridge_count else "no_semantic_bridges",
    }


def _load_validated_supply(path: Path | None) -> Dict[str, List[int]] | None:
    if path is None or not path.is_file():
        return None
    payload = _read_json(path)
    rows = payload.get("validated_supply_by_demand_id")
    if not isinstance(rows, dict):
        return None
    output: Dict[str, List[int]] = {}
    for demand_id, entry in rows.items():
        levels = entry.get("eqf_levels", []) if isinstance(entry, dict) else entry
        if isinstance(levels, (str, int)):
            levels = [levels]
        if isinstance(levels, list):
            output[str(demand_id)] = [int(level) for level in levels if str(level).isdigit()]
    return output


def _filter_rows_by_provider(
    rows: Sequence[Mapping[str, Any]], providers: Set[str]
) -> List[Mapping[str, Any]]:
    return [row for row in rows if _providers_for_row(row) & providers]


def build_provider_sensitivity_analysis(
    *,
    evidence_path: Path,
    signals_path: Path,
    derived_demands_path: Path,
    hypothesis_fragments_path: Path | None,
    validated_supply_map_path: Path | None,
    output_json_path: Path,
    output_markdown_path: Path,
    subsets: Mapping[str, Sequence[str]] | None = None,
) -> Dict[str, Any]:
    evidence = _read_jsonl(evidence_path)
    signals = _read_jsonl(signals_path)
    demands = _read_csv(derived_demands_path)
    fragments = _read_jsonl(hypothesis_fragments_path) if hypothesis_fragments_path else []
    validated_supply = _load_validated_supply(validated_supply_map_path)
    subset_config = subsets or DEFAULT_SUBSETS
    subset_results: Dict[str, Any] = {}

    for label, provider_values in subset_config.items():
        providers = {provider.lower() for provider in provider_values}
        subset_evidence = _filter_rows_by_provider(evidence, providers)
        evidence_ids = {_evidence_id(row) for row in subset_evidence if _evidence_id(row)}
        subset_signals = [
            row for row in signals
            if str(row.get("evidence_id", "")).strip() in evidence_ids
            or _providers_for_row(row) & providers
        ]
        subset_demands = [
            row for row in demands
            if set(_split(row.get("evidence_ids"))) & evidence_ids
            or _providers_for_row(row) & providers
        ]
        subset_fragments = [
            row for row in fragments
            if str(row.get("evidence_id", "")).strip() in evidence_ids
            or _providers_for_row(row) & providers
        ]
        doi_count = len({_doi_for_row(row) for row in subset_evidence if _doi_for_row(row)})
        axis_counts = Counter(_axis(row) for row in subset_demands if _axis(row))
        sector_axis_counts = Counter(
            f"{_sector(row)}::{_axis(row)}" for row in subset_demands
        )
        competence_counts = Counter(
            str(row.get("competence_label", "unknown")).strip() or "unknown"
            for row in subset_demands
        )
        provider_counts = Counter(
            provider for row in subset_evidence for provider in _providers_for_row(row)
            if provider in providers
        )
        provider_total = sum(provider_counts.values())
        max_provider_share = (
            round(max(provider_counts.values()) / provider_total, 6)
            if provider_total else 0.0
        )
        subset_results[label] = {
            "providers": sorted(providers),
            "evidence_record_count": len(subset_evidence),
            "unique_doi_count": doi_count,
            "semantic_signal_count": len(subset_signals),
            "derived_demand_count": len(subset_demands),
            "qmbd_axis_shares": _share_map(axis_counts),
            "sector_axis_distribution": dict(sorted(sector_axis_counts.items())),
            "competence_family_shares": _share_map(competence_counts),
            "h1": _h1_from_demands(subset_demands),
            "h2": _h2_from_demands(subset_demands, validated_supply),
            "h3": _h3_from_fragments(subset_fragments),
            "provider_concentration": {
                "provider_counts": dict(sorted(provider_counts.items())),
                "max_provider_share": max_provider_share,
            },
        }

    result = {
        "schema_version": "1.0.0",
        "api_calls_performed": 0,
        "sensitivity_note": (
            "direct_crossref_excluded is not Crossref-independent because OpenAlex "
            "may contain upstream metadata from overlapping DOI infrastructures."
        ),
        "subsets": subset_results,
    }
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    output_markdown_path.write_text(_markdown_summary(result), encoding="utf-8")
    return result


def _markdown_summary(result: Mapping[str, Any]) -> str:
    lines = ["# Provider Sensitivity Analysis", "", str(result["sensitivity_note"]), ""]
    lines.append("| subset | evidence | unique DOI | signals | demands | max provider share | H1 | H2 | H3 bridges |")
    lines.append("|---|---:|---:|---:|---:|---:|---|---|---:|")
    for label, metrics in result["subsets"].items():
        lines.append(
            "| {label} | {evidence} | {doi} | {signals} | {demands} | {share} | {h1} | {h2} | {bridges} |".format(
                label=label,
                evidence=metrics["evidence_record_count"],
                doi=metrics["unique_doi_count"],
                signals=metrics["semantic_signal_count"],
                demands=metrics["derived_demand_count"],
                share=metrics["provider_concentration"]["max_provider_share"],
                h1=metrics["h1"]["interpretation"],
                h2=metrics["h2"]["interpretation"],
                bridges=metrics["h3"]["semantic_bridge_count"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
    try:
        build_provider_sensitivity_analysis(
            evidence_path=Path(args.evidence_records),
            signals_path=Path(args.signals),
            derived_demands_path=Path(args.derived_demands),
            hypothesis_fragments_path=Path(args.hypothesis_fragments),
            validated_supply_map_path=(
                Path(args.validated_supply_map)
                if args.validated_supply_map
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
