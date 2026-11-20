"""Prepare the exact-commit G2 plan or acquire it in the protected workflow."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from scripts.check_research_api_health import probe_openalex
from scripts.manage_physical_attempt_budget import derive_budget
from src.scientific_sources.attempt_audit_validator import verify_audit_file
from src.scientific_sources.attempt_budget import (
    AttemptBudgetError, attempt_context, build_audit, find_ungoverned_network_routes, require_governor,
)
from src.scientific_sources.attempt_route_inventory import validate_route_dispositions
from src.scientific_sources.live_query_protocol import load_live_query_protocol
from src.scientific_sources.retrieval_trace import RetrievalTrace
from src.scientific_sources.source_registry import SourceRegistry

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "config/live_query_protocol.yml"
PROTOCOL_SHA = "2ce250b3a1f67006db7e659e58f8c0b798733484946148866f8e46d6ce602151"
IDS = ("Q_PORT_ACTIVITIES_COMP_001", "Q_PORT_ACTIVITIES_COMP_002")


def encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def plan_for(sha: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{40}", sha) or hashlib.sha256(PROTOCOL.read_bytes()).hexdigest() != PROTOCOL_SHA:
        raise ValueError("invalid candidate SHA or changed authoritative protocol")
    queries = {q.query_id: q for q in load_live_query_protocol(PROTOCOL).all_queries()}
    return {
        "schema": "mor25_openalex_pilot/1", "candidate_sha": sha, "protocol_sha256": PROTOCOL_SHA,
        "acquisition_id": "mor25-openalex-port-pilot-v1", "budget_id": "mor25-openalex-port-budget-v1",
        "selection": [{"query_id": key, "query_text": queries[key].query_text} for key in IDS],
        "from_year": 2019, "to_year": 2026, "provider": "openalex", "endpoint": "https://api.openalex.org/works",
        "sort": "default relevance", "logical_pages": 1, "rows_per_page": 5, "health_attempts": 1,
        "attempts_per_query": 3, "maximum_total_physical_attempts": 7,
    }


def acquire(plan: dict[str, Any], out: Path, run_id: str) -> None:
    governor = require_governor()
    if governor.ledger.snapshot()["attempts"]:
        raise ValueError("this pilot already has reservations; inspect the retained attempt before replay")
    pairs = [(q["query_id"], q["query_text"], "openalex", 5) for q in plan["selection"]]
    registry = SourceRegistry()
    with RetrievalTrace(out / "retrieval.sqlite3", run_id, pairs).activate() as trace:
        try:
            with attempt_context(provider="openalex", purpose="health"):
                health = probe_openalex()
            (out / "health.json").write_bytes(encode({"status": health.status, "http_status": health.http_status}))
            if health.status != "ok":
                raise ValueError("OpenAlex health check did not succeed")
            for _, query, _, _ in pairs:
                result, = registry.search_paginated(
                    query, providers=["openalex"], pages=1, rows_per_page=5,
                    time_window={"from_year": 2019, "to_year": 2026},
                )
                if result.errors:
                    raise ValueError("OpenAlex page request failed")
            checks = trace.db.execute(
                "SELECT count(*) FROM query_results WHERE status='completed' "
                "AND api_reported_hits IS NOT NULL AND fetched_records<=5 "
                "AND (api_reported_hits=0 OR fetched_records>0)"
            ).fetchone()
            unidentified = trace.db.execute("SELECT count(*) FROM work_occurrences WHERE source_id IS NULL").fetchone()
            if checks != (2,) or unidentified != (0,):
                raise ValueError("incomplete or inconsistent OpenAlex query responses")
        finally:
            audit = build_audit(governor, repo_root=ROOT)
            audit_path = out / "attempt_audit.json"
            audit_path.write_bytes(encode(audit))
            ids = {x[0] for x in trace.db.execute("SELECT attempt_id FROM reservations")}
            if (verify_audit_file(audit_path) or audit["counters"]["unresolved"]
                    or ids != {a["attempt_id"] for a in audit["reservations"]}):
                raise ValueError("reservation audit mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan = plan_for(args.commit)
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    plan_bytes = encode(plan)
    digest = hashlib.sha256(plan_bytes).hexdigest()
    (out / "plan.json").write_bytes(plan_bytes)
    run_id = os.getenv("CURRENT_RUN_ID", "")
    budget = derive_budget(
        acquisition_id=plan["acquisition_id"], budget_id=plan["budget_id"], plan_sha256=digest,
        workflow_run_id=run_id, run_attempt=int(os.getenv("GITHUB_RUN_ATTEMPT", "0")),
        providers=["openalex"], queries=2, logical_pages=1, rows_per_page=5,
    )
    if budget.maximum_total_physical_attempts != 7 or budget.provider_ceilings["openalex"] != 7:
        raise ValueError("provider retry contract exceeds the pilot plan")
    budget_file = out / "physical_attempt_budget.json"
    budget_file.write_bytes(encode(budget.to_dict()))
    print(f"plan_sha256={digest} budget_sha256={budget.sha256()}")
    if not args.execute:
        return
    if not (os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and args.commit == os.getenv("GITHUB_SHA") == os.getenv("MOR25_G2_APPROVED_SHA")
            and digest == os.getenv("MOR25_G2_APPROVED_PLAN_SHA256")
            and os.getenv("ATTEMPT_LEDGER_BACKEND") == "postgres" and run_id):
        raise ValueError("protected pilot approval, run identity or PostgreSQL binding missing")
    if find_ungoverned_network_routes(ROOT) or validate_route_dispositions(ROOT):
        raise ValueError("unreviewed provider route")
    prior_budget_file = os.environ.get("ATTEMPT_BUDGET_FILE")
    os.environ["ATTEMPT_BUDGET_FILE"] = str(budget_file)
    try:
        acquire(plan, out, run_id)
    finally:
        if prior_budget_file is None:
            os.environ.pop("ATTEMPT_BUDGET_FILE", None)
        else:
            os.environ["ATTEMPT_BUDGET_FILE"] = prior_budget_file
        sums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in sorted(out.iterdir()) if p.is_file()]
        (out / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, AttemptBudgetError) as exc:
        raise SystemExit(str(exc)) from None
