"""Validate and materialize the authorized live-acquisition request plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

ACTIVE_ACQUISITION_PROVIDERS = (
    "crossref",
    "scopus",
    "openalex",
    "scival",
    "google_drive",
    "microsoft_graph",
)
DEACTIVATED_ACQUISITION_PROVIDERS = {
    "wos": (
        "Web of Science acquisition is temporarily deactivated until the "
        "scientific hardening plan and provider contract are completed"
    )
}
REGISTERED_ACQUISITION_PROVIDERS = ACTIVE_ACQUISITION_PROVIDERS


def _positive_int(value: str, label: str) -> int:
    if not value.isascii() or not value.isdigit() or int(value) < 1:
        raise ValueError(f"{label} must be a canonical positive integer")
    return int(value)


def build_plan(
    constraints: dict[str, Any], providers_text: str, pages_text: str, rows_text: str
) -> dict[str, Any]:
    """Return a plan only when operator and authoritative sampling shapes agree."""
    queries = constraints.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("authoritative projection must contain non-empty queries")
    pages = _positive_int(pages_text, "logical_pages")
    rows = _positive_int(rows_text, "rows_per_page")
    for query in queries:
        if not isinstance(query, dict):
            raise ValueError("authoritative projection query must be an object")
        sampling = query.get("sampling_strategy")
        if not isinstance(sampling, dict):
            raise ValueError("authoritative query lacks sampling_strategy")
        if sampling.get("pages") != pages or sampling.get("rows_per_page") != rows:
            raise ValueError(
                "selected sampling shape does not match authoritative projection"
            )
    requested = [item.strip().lower() for item in providers_text.split(",") if item.strip()]
    if requested == ["all"]:
        providers = list(ACTIVE_ACQUISITION_PROVIDERS)
    else:
        providers = requested
    if not providers or "all" in providers or len(providers) != len(set(providers)):
        raise ValueError("providers must be a non-empty unique provider profile")
    deactivated = sorted(set(providers) & set(DEACTIVATED_ACQUISITION_PROVIDERS))
    if deactivated:
        reasons = "; ".join(
            f"{name}: {DEACTIVATED_ACQUISITION_PROVIDERS[name]}" for name in deactivated
        )
        raise ValueError(f"deactivated provider requested: {reasons}")
    unknown = sorted(set(providers) - set(ACTIVE_ACQUISITION_PROVIDERS))
    if unknown:
        raise ValueError(f"unknown providers: {unknown}")
    expected = len(queries) * pages * len(providers)
    return {
        "queries": len(queries),
        "providers": providers,
        "deactivated_providers": sorted(DEACTIVATED_ACQUISITION_PROVIDERS),
        "logical_pages": pages,
        "rows_per_page": rows,
        "max_results_per_query": pages * rows,
        "expected_logical_requests": expected,
        "maximum_total_logical_requests": expected,
        "abort_on_budget_exceeded": True,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--constraints", required=True)
    parser.add_argument("--providers", required=True)
    parser.add_argument("--logical-pages", required=True)
    parser.add_argument("--rows-per-page", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--github-env")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = json.loads(Path(args.constraints).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("authoritative projection must be a JSON object")
    plan = build_plan(payload, args.providers, args.logical_pages, args.rows_per_page)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    if args.github_env:
        with Path(args.github_env).open("a", encoding="utf-8") as handle:
            handle.write(f"REQUESTED_PROVIDERS={','.join(plan['providers'])}\n")
            handle.write(f"MAX_RESULTS_PER_QUERY={plan['max_results_per_query']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
