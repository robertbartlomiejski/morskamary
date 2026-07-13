#!/usr/bin/env python3
"""Compute live novelty metrics and evaluate quality gates A-E (PR-190 Task C).

This CLI reads the ``run_novelty_metrics.json`` produced by Layer 2-3
and evaluates deterministic quality gates over the current run:

* Gate A — Provider contribution: warn/fail if a requested provider is
  ``health.status == ok`` but returned zero records.
* Gate B — Novelty: warn if both ``new_unique_doi_count == 0`` and
  ``semantic_new_signal_count == 0``. Fail after two consecutive
  zero-novelty runs (or immediately in strict mode).
* Gate C — Jaccard repetition: warn when Jaccard > 0.90; fail in strict
  mode when Jaccard > 0.98 AND ``semantic_new_signal_count == 0``.
* Gate D — Static baseline contamination: fail if a run reports static
  baseline supply as live availability.
* Gate E — Provider/query concentration: warn if all records come from
  one provider or one query family unless ``provider_bias_warning`` is
  explicit.

Gate failures always return a non-zero exit code. Warnings are always
written to the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data


def _load_optional_json(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return _load_json(path)


def evaluate_gates(
    *,
    metrics: Dict[str, Any],
    provider_health: Optional[Dict[str, Any]] = None,
    previous_metrics: Optional[Dict[str, Any]] = None,
    static_baseline_field_in_live: bool = False,
    strict: bool = False,
) -> Dict[str, Any]:
    """Evaluate quality gates and return a serializable report."""
    provider_health = provider_health or {}
    previous_metrics = previous_metrics or {}
    gates: List[Dict[str, Any]] = []
    fail = False

    new_doi = int(metrics.get("new_unique_doi_count", 0) or 0)
    sem_new = int(metrics.get("semantic_new_signal_count", 0) or 0)
    jaccard = float(metrics.get("jaccard_similarity_with_previous_run", 0.0) or 0.0)
    provider_counts = metrics.get("provider_record_count_by_provider", {}) or {}
    crossref_dom = float(metrics.get("crossref_dominance_ratio", 0.0) or 0.0)

    # Gate A
    provider_counts_normalized = {
        str(name).strip().lower(): int(count or 0)
        for name, count in provider_counts.items()
    }
    provider_health_map: Dict[str, Any] = {}
    statuses = provider_health.get("statuses")
    if isinstance(statuses, list):
        for health in statuses:
            if isinstance(health, dict):
                provider = str(health.get("provider", "")).strip().lower()
                if provider:
                    provider_health_map[provider] = health
    else:
        entries = provider_health.get("providers") or provider_health
        if isinstance(entries, dict):
            provider_health_map = entries
    zero_but_ok = []
    for prov, health in provider_health_map.items():
        status = ""
        if isinstance(health, dict):
            status = str(health.get("status", "")).lower()
        elif isinstance(health, str):
            status = health.lower()
        prov_count = provider_counts_normalized.get(str(prov).lower(), 0)
        if status == "ok" and prov_count == 0:
            zero_but_ok.append(prov)
    gate_a_status = "pass" if not zero_but_ok else ("fail" if strict else "warn")
    gates.append({
        "gate_id": "A",
        "name": "Provider contribution",
        "status": gate_a_status,
        "detail": {"providers_ok_zero_records": sorted(zero_but_ok)},
    })
    if gate_a_status == "fail":
        fail = True

    # Gate B
    prev_zero = (int(previous_metrics.get("new_unique_doi_count", -1)) == 0
                 and int(previous_metrics.get("semantic_new_signal_count", -1)) == 0)
    cur_zero = new_doi == 0 and sem_new == 0
    gate_b_status = "pass"
    if cur_zero:
        gate_b_status = "warn"
        if strict or prev_zero:
            gate_b_status = "fail"
    gates.append({
        "gate_id": "B",
        "name": "Novelty",
        "status": gate_b_status,
        "detail": {
            "current_zero_novelty": cur_zero,
            "previous_zero_novelty": prev_zero,
        },
    })
    if gate_b_status == "fail":
        fail = True

    # Gate C
    if jaccard > 0.98 and sem_new == 0:
        gate_c_status = "fail" if strict else "warn"
    elif jaccard > 0.90:
        gate_c_status = "warn"
    else:
        gate_c_status = "pass"
    gates.append({
        "gate_id": "C",
        "name": "Jaccard repetition",
        "status": gate_c_status,
        "detail": {"jaccard": jaccard, "semantic_new_signal_count": sem_new},
    })
    if gate_c_status == "fail":
        fail = True

    # Gate D
    gate_d_status = "fail" if static_baseline_field_in_live else "pass"
    gates.append({
        "gate_id": "D",
        "name": "Static baseline contamination",
        "status": gate_d_status,
        "detail": {
            "static_baseline_reported_as_live_availability":
                static_baseline_field_in_live,
        },
    })
    if gate_d_status == "fail":
        fail = True

    # Gate E
    active_providers = [p for p, c in provider_counts.items() if int(c or 0) > 0]
    active_families = metrics.get("query_families_seen") or []
    if isinstance(active_families, str):
        active_families = [f for f in active_families.split("|") if f]
    single_provider = len(active_providers) <= 1 and sum(provider_counts.values()) > 0
    single_family = len(active_families) <= 1 and metrics.get("query_diversity_score", 0) == 0
    single_bias = single_provider or single_family or crossref_dom >= 0.98
    explicit_flag = any("provider_bias_warning" in str(w)
                        for w in metrics.get("validity_warnings", []) or [])
    if single_bias and not explicit_flag:
        gate_e_status = "warn"
    else:
        gate_e_status = "pass"
    gates.append({
        "gate_id": "E",
        "name": "Provider/query concentration",
        "status": gate_e_status,
        "detail": {
            "active_providers": sorted(active_providers),
            "crossref_dominance_ratio": crossref_dom,
        },
    })

    return {
        "current_run_id": str(metrics.get("current_run_id", "")),
        "previous_run_id": str(metrics.get("previous_run_id", "")),
        "gates": gates,
        "overall_status": "fail" if fail else "pass",
    }


def _detect_static_baseline_leak(current_run_dir: Path) -> bool:
    """Return True if any live-labelled file reports static baseline as live."""
    live = current_run_dir / "research_sources" / "live_records.json"
    if not live.exists():
        return False
    try:
        data = json.loads(live.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    records = data if isinstance(data, list) else data.get("records", [])
    for r in records:
        if not isinstance(r, dict):
            continue
        if r.get("record_origin") in ("static_baseline", "baseline"):
            return True
        provider = str(r.get("provider", "")).lower()
        if provider in ("baseline", "static_baseline"):
            return True
    return False


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--metrics",
                        default="outputs/cumulative_database/run_novelty_metrics.json",
                        help="Path to run_novelty_metrics.json (Layer 2-3 output).")
    parser.add_argument("--provider-health",
                        default="outputs/research_api_health.json")
    parser.add_argument("--previous-metrics", default=None)
    parser.add_argument("--current-run", default="outputs")
    parser.add_argument("--output",
                        default="outputs/cumulative_database/novelty_gate_report.json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    metrics_path = Path(args.metrics)
    if not metrics_path.exists():
        print(f"ERROR: metrics file not found: {metrics_path}", file=sys.stderr)
        return 2
    metrics = _load_json(metrics_path)
    provider_health = _load_optional_json(Path(args.provider_health))
    previous_metrics = _load_optional_json(
        Path(args.previous_metrics) if args.previous_metrics else None
    )
    baseline_leak = _detect_static_baseline_leak(Path(args.current_run))
    report = evaluate_gates(
        metrics=metrics,
        provider_health=provider_health,
        previous_metrics=previous_metrics,
        static_baseline_field_in_live=baseline_leak,
        strict=args.strict,
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"overall_status": report["overall_status"]}, sort_keys=True))
    if report["overall_status"] == "fail":
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
