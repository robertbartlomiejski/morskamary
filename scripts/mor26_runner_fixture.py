"""Test-only MOR-26 shared PostgreSQL ledger on independent GitHub runners.

NO scientific-provider HTTP. The configured database is the only network I/O.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path

from src.scientific_sources.attempt_budget import (
    AttemptBudgetExhausted,
    parse_budget,
)
from src.scientific_sources.attempt_postgres_ledger import PostgresAttemptLedger


def budget(acq: str, runner: str, race: bool = False):
    n = 1 if race else 7
    return parse_budget({
        "schema_version": "physical_attempt_budget/2",
        "acquisition_id": acq + ("-race" if race else ""),
        "budget_id": "fixture-only",
        "plan_sha256": "a" * 64,
        "workflow_run_id": runner,
        "run_attempt": 2 if runner != "runner-a" else 1,
        "unit": "physical_http_attempt",
        "maximum_total_physical_attempts": n,
        "provider_ceilings": {"openalex": n},
    })


def seed(approval, auth_dsn: str) -> None:
    if not auth_dsn:
        raise RuntimeError("MOR26 test-only authorizer is not configured")
    psycopg = importlib.import_module("psycopg")
    with psycopg.connect(auth_dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO mor26_private.authorizations"
                " (acquisition_id,budget_id,schema_version,budget_sha256,"
                " maximum_total_physical_attempts,provider_ceilings_json)"
                " VALUES (%s,%s,%s,%s,%s,%s::jsonb)"
                " ON CONFLICT (acquisition_id,budget_id) DO NOTHING",
                (approval.acquisition_id, approval.budget_id,
                 "physical_attempt_ledger/2", approval.sha256(),
                 approval.maximum_total_physical_attempts,
                 json.dumps(dict(approval.provider_ceilings))),
            )


def run(phase: str, acq: str, head: str) -> dict:
    race = phase == "race"
    approval = budget(acq, "runner-b" if phase == "b" else "runner-a", race)
    if phase == "seed-a":
        authorizer = os.environ.get("MOR26_ACCEPTANCE_AUTH_DSN", "")
        seed(approval, authorizer)
        seed(budget(acq, "runner-a", True), authorizer)
    ledger = PostgresAttemptLedger(
        os.environ.get("MOR26_ACCEPTANCE_RUNTIME_DSN", ""), approval
    )
    ledger.initialize()  # Requires pre-approved immutable authorization.
    before = len(ledger.snapshot()["attempts"])
    grants = 0
    refused = False
    if phase == "seed-a":
        assert before == 0
        for _ in range(3):
            ledger.reserve("openalex", "acquisition")
            grants += 1
    elif phase == "b":
        assert before == 3, "runner B must inherit N-K=4"
        for _ in range(4):
            ledger.reserve("openalex", "acquisition")
            grants += 1
        try:
            ledger.reserve("openalex", "acquisition")
        except AttemptBudgetExhausted:
            refused = True
        assert refused, "attempt N+1 was not refused"
    elif phase == "race":
        assert before in (0, 1)
        try:
            ledger.reserve("openalex", "acquisition")
            grants += 1
        except AttemptBudgetExhausted:
            refused = True
    else:
        raise ValueError("invalid fixture phase")
    snap = ledger.snapshot()
    total = len(snap["attempts"])
    if phase == "b":
        assert total == 7 and grants == 4
    if phase == "race":
        assert total == 1
    return {
        "schema": "mor26_two_runner_acceptance/1",
        "phase": phase,
        "commit_sha": head,
        "github_job": os.environ.get("GITHUB_JOB", "offline"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", "offline"),
        "budget_sha256": approval.sha256(),
        "acquisition_id": approval.acquisition_id,
        "before": before,
        "reserved_now": grants,
        "fake_dispatches": grants,
        "reserved_total": total,
        "refused_total": len(snap["refusals"]),
        "attempt_n_plus_1_denied": refused if phase == "b" else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("seed-a", "b", "race"), required=True)
    parser.add_argument("--acquisition-id", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = run(args.phase, args.acquisition_id, args.head)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print("[MOR26] fake-dispatch-only ledger evidence saved")


if __name__ == "__main__":
    main()
