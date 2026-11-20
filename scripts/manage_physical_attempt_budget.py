"""Create, verify and audit the run-scoped physical HTTP-attempt budget.

``init`` derives a versioned budget from the authorised acquisition plan (or an
explicit shape), initialises the shared SQLite ledger, verifies that no network
route bypasses the governed boundary, and optionally exports the environment
variables consumed by provider entrypoints. ``audit`` writes the sanitized
audit. Neither subcommand performs any network request.

The physical budget is separate from, and does not replace, the post-acquisition
logical-page budget in ``scripts/check_budget_ceiling.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources import crossref, elsevier_scopus, openalex  # noqa: E402
from src.scientific_sources.attempt_budget import (  # noqa: E402
    BUDGET_SCHEMA_VERSION,
    ENV_BUDGET_FILE,
    ENV_LEDGER_PATH,
    ENV_LEDGER_BACKEND,
    ENV_LEDGER_DSN,
    KNOWN_PROVIDERS,
    AttemptBudgetError,
    AttemptGovernor,
    AttemptLedger,
    PhysicalAttemptBudget,
    build_audit,
    find_ungoverned_network_routes,
    load_budget,
    parse_budget,
)

# Mirrors scripts/prepare_live_acquisition_plan.py (equality is test-enforced);
# Web of Science acquisition stays deactivated and is pinned to a zero ceiling.
ACTIVE_ACQUISITION_PROVIDERS = tuple(p for p in KNOWN_PROVIDERS if p != "wos")

# Providers whose health probe dispatches one HTTP request.
_HEALTH_ATTEMPTS = {
    "crossref": 1,
    "scopus": 1,
    "openalex": 1,
    "scival": 1,
    "microsoft_graph": 1,
    "google_drive": 0,
}


def _attempts_per_logical_page(provider: str, rows_per_page: int) -> int:
    """Worst-case physical attempts for one logical page of one provider."""
    if provider == "crossref":
        return int(crossref._MAX_RETRY_ATTEMPTS)
    if provider == "openalex":
        return int(openalex._MAX_RETRY_ATTEMPTS)
    if provider == "scopus":
        return math.ceil(rows_per_page / elsevier_scopus._SCOPUS_MAX_COUNT)
    if provider == "microsoft_graph":
        return 2  # token request + search request
    if provider == "scival":
        return 1
    return 0


def derive_budget(
    *,
    acquisition_id: str,
    budget_id: str,
    plan_sha256: str,
    workflow_run_id: str = "",
    run_attempt: int = 0,
    providers: Sequence[str],
    queries: int,
    logical_pages: int,
    rows_per_page: int,
) -> PhysicalAttemptBudget:
    """Derive pinned ceilings from the approved, stable acquisition plan."""
    unknown = sorted(set(providers) - set(ACTIVE_ACQUISITION_PROVIDERS))
    if unknown or not providers or len(set(providers)) != len(providers):
        raise ValueError(f"providers must be unique active providers, got {providers!r}")
    ceilings = {name: 0 for name in KNOWN_PROVIDERS}
    for name in providers:
        ceilings[name] = _HEALTH_ATTEMPTS.get(name, 0) + (
            queries * logical_pages * _attempts_per_logical_page(name, rows_per_page)
        )
    return parse_budget(
        {
            "schema_version": BUDGET_SCHEMA_VERSION,
            "acquisition_id": acquisition_id,
            "budget_id": budget_id,
            "plan_sha256": plan_sha256,
            "workflow_run_id": workflow_run_id,
            "run_attempt": run_attempt,
            "unit": "physical_http_attempt",
            "maximum_total_physical_attempts": sum(ceilings.values()),
            "provider_ceilings": ceilings,
        }
    )


def _split(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def _cmd_init(args: argparse.Namespace) -> int:
    if args.plan:
        plan_bytes = Path(args.plan).read_bytes()
        plan: Dict[str, Any] = json.loads(plan_bytes.decode("utf-8"))
        providers = list(plan["providers"])
        queries = int(plan["queries"])
        pages = int(plan["logical_pages"])
        rows = int(plan["rows_per_page"])
        plan_sha256 = hashlib.sha256(plan_bytes).hexdigest()
    else:
        providers = _split(args.providers)
        if args.providers.strip().lower() == "all":
            providers = list(ACTIVE_ACQUISITION_PROVIDERS)
        queries, pages, rows = args.queries, args.logical_pages, args.rows_per_page
        synthetic_plan = {
            "providers": providers,
            "queries": queries,
            "logical_pages": pages,
            "rows_per_page": rows,
        }
        canonical = json.dumps(
            synthetic_plan, sort_keys=True, separators=(",", ":")
        )
        plan_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    budget = derive_budget(
        acquisition_id=args.acquisition_id,
        budget_id=args.budget_id,
        plan_sha256=plan_sha256,
        workflow_run_id=args.workflow_run_id,
        run_attempt=args.run_attempt,
        providers=providers,
        queries=queries,
        logical_pages=pages,
        rows_per_page=rows,
    )
    findings = find_ungoverned_network_routes(REPO_ROOT)
    if findings:
        print("[ERROR] ungoverned network routes: " + "; ".join(findings), file=sys.stderr)
        return 1
    budget_path = Path(args.budget_output)
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    budget_path.write_text(json.dumps(budget.to_dict(), indent=2) + "\n", encoding="utf-8")
    backend = os.environ.get(ENV_LEDGER_BACKEND, "sqlite").strip().lower()
    if backend == "postgres":
        from src.scientific_sources.attempt_postgres_ledger import PostgresAttemptLedger
        ledger: Any = PostgresAttemptLedger(os.environ.get(ENV_LEDGER_DSN, ""), budget)
    elif backend == "sqlite":
        if not args.ledger:
            raise ValueError("--ledger is required for SQLite backend")
        ledger = AttemptLedger(Path(args.ledger), budget)
    else:
        raise ValueError("unknown physical attempt ledger backend")
    ledger.initialize()
    if args.github_env:
        with Path(args.github_env).open("a", encoding="utf-8") as handle:
            handle.write(f"{ENV_BUDGET_FILE}={budget_path.as_posix()}\n")
            handle.write(f"{ENV_LEDGER_BACKEND}={backend}\n")
            if backend == "sqlite":
                handle.write(
                    f"{ENV_LEDGER_PATH}={Path(args.ledger).resolve().as_posix()}\n"
                )
    print(
        f"[OK] physical attempt budget initialised: "
        f"maximum_total_physical_attempts={budget.maximum_total_physical_attempts}"
    )
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    budget = load_budget(args.budget)
    backend = os.environ.get(ENV_LEDGER_BACKEND, "sqlite").strip().lower()
    governor = AttemptGovernor(budget, Path(args.ledger or "[shared-postgresql-ledger]"))
    if backend == "postgres":
        from src.scientific_sources.attempt_postgres_ledger import PostgresAttemptLedger
        governor.ledger = PostgresAttemptLedger(
            os.environ.get(ENV_LEDGER_DSN, ""), budget
        )
    elif backend != "sqlite" or not args.ledger:
        raise ValueError("unknown or unconfigured physical attempt ledger backend")
    audit = build_audit(governor, repo_root=REPO_ROOT)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    from src.scientific_sources.attempt_audit_validator import verify_audit_file
    problems = verify_audit_file(output)
    if problems:
        print("[ERROR] physical attempt audit validation failed: "
              + "; ".join(problems), file=sys.stderr)
        return 1
    counters = audit["counters"]
    print(
        f"[OK] physical attempt audit written: reserved={counters['reserved_total']} "
        f"refused={counters['refused_total']} status={audit['status']}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--acquisition-id", required=True)
    init.add_argument("--budget-id", required=True)
    init.add_argument("--workflow-run-id", default="")
    init.add_argument("--run-attempt", type=int, default=0)
    init.add_argument("--plan", help="api_budget_plan.json from prepare_live_acquisition_plan")
    init.add_argument("--providers", default="")
    init.add_argument("--queries", type=int, default=1)
    init.add_argument("--logical-pages", type=int, default=1)
    init.add_argument("--rows-per-page", type=int, default=1)
    init.add_argument("--budget-output", required=True)
    init.add_argument("--ledger", help="SQLite path; ignored for pre-approved PostgreSQL")
    init.add_argument("--github-env")
    audit = sub.add_parser("audit")
    audit.add_argument("--budget", required=True)
    audit.add_argument("--ledger", help="SQLite path; ignored for PostgreSQL")
    audit.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return _cmd_init(args)
        return _cmd_audit(args)
    except AttemptBudgetError as exc:
        print(f"[ERROR] {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
