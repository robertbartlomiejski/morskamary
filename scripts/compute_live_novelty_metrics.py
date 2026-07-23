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
import csv
import hashlib
import json
import re
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


# Canonical provider aliases used for Gate A cross-referencing between the
# provider-health report and per-provider contribution counts.  Real-world
# provider labels vary ("wos", "Web of Science", "Web of Science
# (Clarivate)", "Clarivate WoS", ...); normalising both sides through the
# same map is required so a healthy provider with contributed records is
# never falsely flagged as zero-contribution.
_PROVIDER_ALIASES: Dict[str, str] = {
    "crossref": "crossref",
    "cr": "crossref",
    "scopus": "scopus",
    "elsevier scopus": "scopus",
    "wos": "wos",
    "web of science": "wos",
    "web of science clarivate": "wos",
    "web of science (clarivate)": "wos",
    "web_of_science": "wos",
    "web_of_science_clarivate": "wos",
    "clarivate": "wos",
    "clarivate wos": "wos",
    "clarivate web of science": "wos",
    "clarivate_web_of_science": "wos",
    "scival": "scival",
    "microsoft_graph": "microsoft_graph",
    "microsoft graph": "microsoft_graph",
    "google_drive": "google_drive",
    "google drive": "google_drive",
}
_OPTIONAL_NON_BLOCKING_PROVIDERS = {"wos"}


def _canonical_provider(name: Any) -> str:
    """Return the canonical provider slug for Gate A alias reconciliation.

    Normalisation lower-cases, strips whitespace, and looks up in
    ``_PROVIDER_ALIASES``.  Unknown labels fall through as their trimmed
    lower-cased form so they still compare correctly to themselves.
    """
    token = str(name or "").strip().lower()
    if not token:
        return ""
    normalized_space = re.sub(r"[^a-z0-9]+", " ", token).strip()
    normalized_underscore = re.sub(r"[^a-z0-9]+", "_", token).strip("_")
    for candidate in (token, normalized_space, normalized_underscore):
        if not candidate:
            continue
        if candidate in _PROVIDER_ALIASES:
            return _PROVIDER_ALIASES[candidate]
    return normalized_underscore or normalized_space or token


def _load_query_execution_summary(current_run_dir: Path) -> Dict[str, Dict[str, int]]:
    """Aggregate per-provider contribution outcomes from query_execution_log.csv."""
    summary: Dict[str, Dict[str, int]] = {}
    log_path = current_run_dir / "research_sources" / "query_execution_log.csv"
    if not log_path.is_file():
        return summary
    try:
        with log_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = csv.DictReader(handle)
            for row in rows:
                provider = _canonical_provider(
                    row.get("provider_canonical") or row.get("provider") or ""
                )
                if not provider:
                    continue
                slot = summary.setdefault(
                    provider,
                    {
                        "attempted_queries": 0,
                        "contributed_records": 0,
                        "returned_records": 0,
                        "queries_with_errors": 0,
                    },
                )
                slot["attempted_queries"] += 1
                try:
                    slot["contributed_records"] += int(row.get("contributed_record_count") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    slot["returned_records"] += int(row.get("returned_record_count") or 0)
                except (TypeError, ValueError):
                    pass
                status = str(row.get("execution_status", "")).strip().lower()
                errors = str(row.get("errors", "")).strip()
                if "error" in status or errors:
                    slot["queries_with_errors"] += 1
    except OSError:
        return {}
    return summary


def evaluate_gates(
    *,
    metrics: Dict[str, Any],
    provider_health: Optional[Dict[str, Any]] = None,
    previous_metrics: Optional[Dict[str, Any]] = None,
    static_baseline_field_in_live: bool = False,
    strict: bool = False,
    query_execution_summary: Optional[Dict[str, Dict[str, int]]] = None,
    execution_log_available: Optional[bool] = None,
) -> Dict[str, Any]:
    """Evaluate quality gates and return a serializable report.

    ``execution_log_available`` signals whether the per-query execution log
    was present and readable.  When ``strict=True`` and this is explicitly
    ``False``, Gate A fails closed: contribution evidence is required for
    strict publication gating and the gate cannot fall back to cumulative
    provider counts when the log is absent.
    """
    provider_health = provider_health or {}
    previous_metrics = previous_metrics or {}
    query_execution_summary = query_execution_summary or {}
    gates: List[Dict[str, Any]] = []
    fail = False

    new_doi = int(metrics.get("new_unique_doi_count", 0) or 0)
    sem_new = int(metrics.get("semantic_new_signal_count", 0) or 0)
    jaccard = float(metrics.get("jaccard_similarity_with_previous_run", 0.0) or 0.0)
    provider_counts = metrics.get("provider_record_count_by_provider", {}) or {}
    crossref_dom = float(metrics.get("crossref_dominance_ratio", 0.0) or 0.0)

    # Gate A
    # Canonicalise provider aliases on both sides so a healthy provider
    # (e.g. "Web of Science (Clarivate)") whose contribution counts are
    # reported under an alias (e.g. "wos") is not falsely flagged as
    # zero-contribution.  Accumulate counts because several raw labels may
    # canonicalise to the same slug.
    provider_counts_normalized: Dict[str, int] = {}
    for name, count in provider_counts.items():
        slug = _canonical_provider(name)
        if not slug:
            continue
        provider_counts_normalized[slug] = (
            provider_counts_normalized.get(slug, 0) + int(count or 0)
        )
    provider_health_map: Dict[str, Any] = {}
    statuses = provider_health.get("statuses")
    if isinstance(statuses, list):
        for health in statuses:
            if isinstance(health, dict):
                provider = _canonical_provider(health.get("provider", ""))
                if provider:
                    provider_health_map[provider] = health
    else:
        entries = provider_health.get("providers") or provider_health
        if isinstance(entries, dict):
            for raw_name, health in entries.items():
                slug = _canonical_provider(raw_name)
                if slug:
                    provider_health_map[slug] = health
    zero_but_ok_required = []
    zero_but_ok_optional = []
    provider_outcomes: Dict[str, Dict[str, Any]] = {}
    for prov, health in provider_health_map.items():
        status = ""
        if isinstance(health, dict):
            status = str(health.get("status", "")).lower()
        elif isinstance(health, str):
            status = health.lower()
        outcome = query_execution_summary.get(prov, {})
        contributed_records = int(
            outcome.get("contributed_records", provider_counts_normalized.get(prov, 0)) or 0
        )
        attempted_queries = int(outcome.get("attempted_queries", 0) or 0)
        queries_with_errors = int(outcome.get("queries_with_errors", 0) or 0)
        provider_outcomes[prov] = {
            "health_status": status,
            "attempted_queries": attempted_queries,
            "contributed_records": contributed_records,
            "queries_with_errors": queries_with_errors,
        }
        if status == "ok" and contributed_records == 0:
            if prov in _OPTIONAL_NON_BLOCKING_PROVIDERS:
                zero_but_ok_optional.append(prov)
            else:
                zero_but_ok_required.append(prov)
    gate_a_status = "pass"
    execution_log_missing_in_strict = strict and execution_log_available is False
    if execution_log_missing_in_strict:
        gate_a_status = "fail"
    elif zero_but_ok_required:
        gate_a_status = "fail" if strict else "warn"
    elif zero_but_ok_optional:
        gate_a_status = "warn"
    gates.append({
        "gate_id": "A",
        "name": "Provider contribution",
        "status": gate_a_status,
        "detail": {
            "providers_ok_zero_records": sorted(zero_but_ok_required + zero_but_ok_optional),
            "providers_ok_zero_records_required": sorted(zero_but_ok_required),
            "providers_ok_zero_records_optional": sorted(zero_but_ok_optional),
            "optional_non_blocking_providers": sorted(_OPTIONAL_NON_BLOCKING_PROVIDERS),
            "contribution_outcomes": provider_outcomes,
            "execution_log_available": execution_log_available,
        },
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
    contributed_by_provider: Dict[str, int] = {}
    for provider, count in provider_counts.items():
        slug = _canonical_provider(provider)
        if not slug:
            continue
        contributed_by_provider[slug] = contributed_by_provider.get(slug, 0) + int(count or 0)
    for provider, outcome in query_execution_summary.items():
        slug = _canonical_provider(provider)
        if not slug:
            continue
        contributed_by_provider[slug] = int(
            outcome.get("contributed_records", contributed_by_provider.get(slug, 0)) or 0
        )
    active_provider_set = {
        provider
        for provider, count in contributed_by_provider.items()
        if int(count or 0) > 0
    }
    active_providers = sorted(active_provider_set)
    raw_families = metrics.get("query_families_seen")
    family_field_present = "query_families_seen" in metrics
    if isinstance(raw_families, str):
        family_tokens: List[Any] = [item for item in raw_families.split("|")]
    elif isinstance(raw_families, list):
        family_tokens = raw_families
    else:
        family_tokens = []
    active_families = sorted(
        {
            str(family).strip()
            for family in family_tokens
            if str(family).strip()
        }
    )
    family_data_available = family_field_present and len(active_families) > 0
    total_contributed = sum(int(count or 0) for count in contributed_by_provider.values())
    single_provider = len(active_providers) <= 1 and total_contributed > 0
    single_family = family_data_available and len(active_families) == 1
    single_bias = single_provider or single_family or crossref_dom >= 0.98
    concentration_reasons: List[str] = []
    if single_provider:
        concentration_reasons.append("single_provider_contribution")
    if single_family:
        concentration_reasons.append("single_query_family_contribution")
    if crossref_dom >= 0.98:
        concentration_reasons.append("crossref_dominance_ratio>=0.98")
    if single_bias:
        gate_e_status = "fail" if strict else "warn"
    else:
        gate_e_status = "pass"
    gates.append({
        "gate_id": "E",
        "name": "Provider/query concentration",
        "status": gate_e_status,
        "detail": {
            "active_providers": sorted(active_providers),
            "active_families": active_families,
            "query_family_distribution_available": family_data_available,
            "warnings": ([] if family_data_available else ["query_family_distribution_unavailable"]),
            "crossref_dominance_ratio": crossref_dom,
            "provider_contributed_record_count_by_provider": dict(
                sorted(contributed_by_provider.items())
            ),
            "concentration_reasons": concentration_reasons,
        },
    })
    if gate_e_status == "fail":
        fail = True

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


def _refresh_checksum_entry_for_output(output_path: Path) -> None:
    checksum_path = output_path.parent / "_checksums.sha256"
    if not checksum_path.is_file():
        return

    entries: Dict[str, str] = {}
    hex64 = re.compile(r"^[0-9a-fA-F]{64}$")
    for line_no, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split("  ", 1)
        if len(parts) != 2 or not hex64.match(parts[0]):
            raise ValueError(f"malformed_checksum_line:{checksum_path.name}:L{line_no}")
        digest, relpath = parts[0].lower(), parts[1]
        if relpath in entries:
            raise ValueError(f"duplicate_checksum_entry:{checksum_path.name}:{relpath}")
        entries[relpath] = digest

    relpath = output_path.name
    entries[relpath] = hashlib.sha256(output_path.read_bytes()).hexdigest()
    with checksum_path.open("w", encoding="utf-8", newline="\n") as handle:
        for name in sorted(entries):
            handle.write(f"{entries[name]}  {name}\n")


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
    current_run_dir = Path(args.current_run)
    log_path = current_run_dir / "research_sources" / "query_execution_log.csv"
    execution_log_available: Optional[bool] = log_path.is_file()
    if args.strict and not execution_log_available:
        raise FileNotFoundError(
            f"Strict full-live path failed: Required query_execution_log.csv not found at {log_path}. "
            "Cannot evaluate Gate A without run-level contribution evidence."
        )
    query_execution_summary = _load_query_execution_summary(current_run_dir)
    if args.strict and not query_execution_summary:
        raise ValueError(
            f"Strict full-live path failed: query_execution_log.csv at {log_path} "
            "is empty, malformed, or contains no usable provider outcomes. "
            "Cannot evaluate Gate A without valid run-level contribution evidence."
        )
    report = evaluate_gates(
        metrics=metrics,
        provider_health=provider_health,
        previous_metrics=previous_metrics,
        static_baseline_field_in_live=baseline_leak,
        strict=args.strict,
        query_execution_summary=query_execution_summary,
        execution_log_available=execution_log_available,
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _refresh_checksum_entry_for_output(out_path)
    print(json.dumps({"overall_status": report["overall_status"]}, sort_keys=True))
    if report["overall_status"] == "fail":
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
