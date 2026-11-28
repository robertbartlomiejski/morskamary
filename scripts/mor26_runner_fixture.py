"""Test-only MOR-26 shared PostgreSQL ledger on independent GitHub runners.

NO scientific-provider HTTP. The configured database is the only network I/O
except the explicit outage case, which targets an unreachable loopback port.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import time
from pathlib import Path

from src.scientific_sources.attempt_budget import (
    AttemptBudgetExhausted,
    LedgerUnavailableError,
    parse_budget,
)
from src.scientific_sources.attempt_postgres_ledger import PostgresAttemptLedger


def budget(acq: str, runner: str, profile: str = "global"):
    if profile == "race":
        n = 1
        ceilings = {"openalex": 1}
        acquisition_id = acq + "-race"
    elif profile == "provider":
        n = 7
        ceilings = {"openalex": 1, "crossref": 6}
        acquisition_id = acq + "-provider"
    else:
        n = 7
        ceilings = {"openalex": 7}
        acquisition_id = acq
    return parse_budget({
        "schema_version": "physical_attempt_budget/2",
        "acquisition_id": acquisition_id,
        "budget_id": "fixture-only",
        "plan_sha256": "a" * 64,
        "workflow_run_id": runner,
        "run_attempt": 2 if runner != "runner-a" else 1,
        "unit": "physical_http_attempt",
        "maximum_total_physical_attempts": n,
        "provider_ceilings": ceilings,
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


def runtime_privileges(dsn: str, acquisition_id: str) -> dict:
    """Exercise the runtime login on runner B's own fixture, with rollback."""
    driver = importlib.import_module("psycopg")
    key = (acquisition_id, "fixture-only")
    probes = {
        "create_budget": (
            "INSERT INTO mor26_private.authorizations"
            " (acquisition_id,budget_id,schema_version,budget_sha256,"
            " maximum_total_physical_attempts,provider_ceilings_json)"
            " VALUES (%s,%s || '-privilege-check','physical_attempt_ledger/2',"
            " repeat('0',64),0,'{}'::jsonb)"
        ),
        "increase_budget": (
            "UPDATE mor26_private.authorizations SET maximum_total_physical_attempts"
            " = maximum_total_physical_attempts + 1 WHERE acquisition_id=%s AND budget_id=%s"
        ),
        "delete_attempt": (
            "DELETE FROM mor26_private.attempts WHERE acquisition_id=%s AND budget_id=%s AND seq=1"
        ),
    }
    denials = {}
    try:
        with driver.connect(dsn, connect_timeout=5) as conn, conn.transaction(force_rollback=True):
            conn.execute("SET LOCAL statement_timeout = '10s'")
            version, matches_login, active_tables = conn.execute(
                "SELECT current_setting('server_version_num')::integer,"
                " session_user = 'mor26_runtime_login' AND current_user = session_user,"
                " (SELECT count(*) FROM unnest(ARRAY['mor26_private.authorizations',"
                " 'mor26_private.attempts','mor26_private.refusals','mor26_private.rendezvous']) t(rel)"
                " WHERE row_security_active(t.rel::regclass))"
            ).fetchone()
            if active_tables != 4:
                raise RuntimeError("expected effective runtime RLS on four ledger tables")
            for operation, sql in probes.items():
                try:
                    with conn.transaction(force_rollback=True):
                        conn.execute(sql, key)
                except driver.errors.InsufficientPrivilege:
                    denials[operation] = "42501"
                else:
                    raise RuntimeError(f"missing runtime privilege denial: {operation}")
    except driver.Error as exc:
        raise RuntimeError(f"runtime privilege check failed (SQLSTATE {exc.sqlstate})") from None
    return {
        "server_version_num": version,
        "matches_mor26_runtime_login": matches_login,
        "rls_active_tables": active_tables,
        "denied_sqlstates": denials,
    }


def _outage_result(acq: str, head: str) -> dict:
    approval = budget(acq, "outage-runner")
    fake_dispatches = 0
    denied = False
    ledger = PostgresAttemptLedger(
        "postgresql://invalid:invalid@127.0.0.1:9/invalid?sslmode=disable",
        approval,
    )
    try:
        ledger.reserve("openalex", "acquisition")
        fake_dispatches += 1
    except LedgerUnavailableError:
        denied = True
    assert denied, "unavailable shared store did not fail closed"
    assert fake_dispatches == 0, "transport executed after shared-store outage"
    return {
        "schema": "mor26_two_runner_acceptance/2",
        "phase": "outage",
        "commit_sha": head,
        "github_job": os.environ.get("GITHUB_JOB", "offline"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", "offline"),
        "budget_sha256": approval.sha256(),
        "acquisition_id": approval.acquisition_id,
        "before": 0,
        "reserved_now": 0,
        "fake_dispatches": 0,
        "reserved_total": 0,
        "refused_total": 0,
        "attempt_n_plus_1_denied": None,
        "provider_ceiling_denied": None,
        "unavailable_store_denied": True,
    }


def run(phase: str, acq: str, head: str) -> dict:
    if phase == "outage":
        return _outage_result(acq, head)

    profile = "race" if phase == "race" else "provider" if phase == "provider" else "global"
    runner = "runner-b" if phase == "b" else "runner-a"
    approval = budget(acq, runner, profile)
    if phase == "seed-a":
        authorizer = os.environ.get("MOR26_ACCEPTANCE_AUTH_DSN", "")
        seed(approval, authorizer)
        seed(budget(acq, "runner-a", "race"), authorizer)
        seed(budget(acq, "runner-a", "provider"), authorizer)

    runtime_dsn = os.environ.get("MOR26_ACCEPTANCE_RUNTIME_DSN", "")
    ledger = PostgresAttemptLedger(runtime_dsn, approval)
    ledger.initialize()
    before = len(ledger.snapshot()["attempts"])
    grants = 0
    refused = False
    provider_denied = False

    if phase == "seed-a":
        assert before == 0
        for _ in range(3):
            ledger.reserve("openalex", "acquisition")
            grants += 1
    elif phase == "b":
        assert before == 3, "runner B must inherit N-K=4"
        for _ in range(4):
            reservation = ledger.reserve("openalex", "acquisition")
            grants += 1
            ledger.complete(reservation, "success", 200)  # Fake transport outcome.
        try:
            ledger.reserve("openalex", "acquisition")
        except AttemptBudgetExhausted:
            refused = True
        assert refused, "attempt N+1 was not refused"
    elif phase == "race":
        contender = os.environ.get("MOR26_RACE_CONTENDER", "").strip()
        if contender not in {"one", "two"}:
            raise RuntimeError("MOR26_RACE_CONTENDER must identify one or two")
        psycopg = importlib.import_module("psycopg")
        dsn = os.environ.get("MOR26_ACCEPTANCE_RUNTIME_DSN", "")
        deadline = time.monotonic() + 20.0
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO mor26_private.rendezvous"
                    " (acquisition_id,budget_id,contender)"
                    " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (*ledger._key, contender),
                )
        rendezvous_count = 0
        while time.monotonic() < deadline:
            with psycopg.connect(dsn, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM mor26_private.rendezvous"
                        " WHERE acquisition_id=%s AND budget_id=%s",
                        ledger._key,
                    )
                    rendezvous_count = int(cur.fetchone()[0])
            if rendezvous_count == 2:
                break
            time.sleep(0.2)
        assert rendezvous_count == 2, "race contenders did not rendezvous"
        assert before == 0, "reservation occurred before both contenders arrived"
        try:
            ledger.reserve("openalex", "acquisition")
            grants += 1
        except AttemptBudgetExhausted:
            refused = True
    elif phase == "provider":
        assert before == 0
        ledger.reserve("openalex", "acquisition")
        grants += 1
        try:
            ledger.reserve("openalex", "acquisition")
        except AttemptBudgetExhausted:
            provider_denied = True
        assert provider_denied, "provider ceiling was not enforced"
    else:
        raise ValueError("invalid fixture phase")

    snap = ledger.snapshot()
    total = len(snap["attempts"])
    evidence = {}
    if phase == "b":
        assert total == 7 and grants == 4
        completed = sum(row[3] == "completed" for row in snap["attempts"])
        assert completed == grants
        evidence = {
            "fake_completions": completed,
            "runtime_privileges": runtime_privileges(runtime_dsn, acq),
        }
    if phase == "race":
        assert total == 1
    if phase == "provider":
        assert total == 1 and grants == 1

    return {
        "schema": "mor26_two_runner_acceptance/2",
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
        "provider_ceiling_denied": provider_denied if phase == "provider" else None,
        "unavailable_store_denied": None,
        "rendezvous_count": rendezvous_count if phase == "race" else None,
        **evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("seed-a", "b", "race", "provider", "outage"),
        required=True,
    )
    parser.add_argument("--acquisition-id", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = run(args.phase, args.acquisition_id, args.head)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("[MOR26] fake-dispatch-only ledger evidence saved")


if __name__ == "__main__":
    main()
