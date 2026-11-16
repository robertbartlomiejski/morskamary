"""New MOR-26 offline twenty-case regression, NOT the original RED suite."""
import copy
import json
import sqlite3
from pathlib import Path

import pytest

from src.scientific_sources import attempt_budget as ab
from src.scientific_sources.attempt_audit_validator import verify_audit_file
from src.scientific_sources.attempt_postgres_ledger import PostgresAttemptLedger
from src.scientific_sources.attempt_route_inventory import (
    find_unverified_network_routes,
    validate_route_dispositions,
)


def _raw():
    return {
        "schema_version": "physical_attempt_budget/2",
        "acquisition_id": "offline-acquisition",
        "budget_id": "approved-one",
        "plan_sha256": "a" * 64,
        "workflow_run_id": "runner-A",
        "run_attempt": 1,
        "unit": "physical_http_attempt",
        "maximum_total_physical_attempts": 7,
        "provider_ceilings": {"openalex": 7},
    }


@pytest.mark.parametrize("change", [
    {"schema_version": "physical_attempt_budget/1"},
    {"plan_sha256": "invalid"},
    {"acquisition_id": ""},
    {"budget_id": "space token"},
    {"maximum_total_physical_attempts": -1},
])
def test_v2_invalid_contract_rejected(change):
    data = _raw()
    data.update(change)
    with pytest.raises(ab.BudgetConfigurationError):
        ab.parse_budget(data)


def test_stable_digest_ignores_workflow_provenance():
    a = _raw()
    b = {**a, "workflow_run_id": "runner-B", "run_attempt": 2}
    assert ab.parse_budget(a).sha256() == ab.parse_budget(b).sha256()


@pytest.mark.parametrize("payload", [
    "import subprocess\nsubprocess.run(argv)\n",
    "import subprocess\nsubprocess.Popen(argv)\n",
    "import subprocess\nsubprocess.check_output(argv)\n",
    "import subprocess\nsubprocess.run(['curl', target])\n",
    "import os\nos.system(cmd)\n",
    "import importlib\nimportlib.import_module(target)\n",
])
def test_dynamic_process_route_reported_unverified(tmp_path, payload):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "route.py").write_text(payload, encoding="utf-8")
    hits = find_unverified_network_routes(tmp_path)
    assert hits and all("src/route.py" in hit for hit in hits)


def _audit(tmp_path):
    budget = ab.parse_budget(_raw())
    gov = ab.AttemptGovernor(budget, tmp_path / "ledger.sqlite")
    gov.ledger.initialize()
    gov.ledger.reserve("openalex", "acquisition")
    return ab.build_audit(gov, repo_root=tmp_path)


@pytest.mark.parametrize("tamper", [
    ("schema_version", "legacy"),
    ("budget_sha256", "f" * 64),
    ("counters.reserved_total", 4),
    ("counters.by_provider.openalex.reserved", 99),
    ("ledger_path", "/tmp/secret-postgresql-url"),
])
def test_written_audit_tampering_detected(tmp_path, tamper):
    payload = copy.deepcopy(_audit(tmp_path))
    key, value = tamper
    root = payload
    parts = key.split(".")
    for p in parts[:-1]:
        root = root[p]
    root[parts[-1]] = value
    file = tmp_path / "audit.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    assert verify_audit_file(file)


def test_written_audit_malformed_utf8_rejected(tmp_path):
    file = tmp_path / "invalid.json"
    file.write_bytes(b'{"bad": "\xff"}')
    assert verify_audit_file(file)


def test_missing_pg_dsn_refuses_before_governed_dispatch(tmp_path, monkeypatch):
    budget = ab.parse_budget(_raw())
    budget_path = tmp_path / "budget.json"
    budget_path.write_text(json.dumps(budget.to_dict()), encoding="utf-8")
    monkeypatch.setenv(ab.ENV_BUDGET_FILE, str(budget_path))
    monkeypatch.setenv(ab.ENV_LEDGER_BACKEND, "postgres")
    monkeypatch.setenv(ab.ENV_LEDGER_DSN, "")
    ab.reset_governor_cache()
    calls = []
    monkeypatch.setattr(
        ab, "_dispatch_request",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    with pytest.raises(ab.LedgerUnavailableError):
        ab.governed_urlopen(
            "https://example.invalid", timeout=1, provider="openalex"
        )
    assert calls == []


def test_valid_sanitized_audit_accepted(tmp_path):
    file = tmp_path / "ok.json"
    file.write_text(json.dumps(_audit(tmp_path)), encoding="utf-8")
    assert verify_audit_file(file) == []


def test_repository_dynamic_routes_are_fully_dispositioned():
    repo_root = Path(__file__).resolve().parents[1]
    errors = validate_route_dispositions(repo_root)
    assert errors == []


def test_route_disposition_manifest_fails_closed_on_unknown_finding(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "src" / "route.py").write_text(
        "import subprocess\nsubprocess.run(argv)\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "mor26_route_dispositions.json").write_text(
        json.dumps({
            "schema_version": "mor26_route_dispositions/1",
            "dispositions": [],
        }),
        encoding="utf-8",
    )
    errors = validate_route_dispositions(tmp_path)
    assert any(item.startswith("UNDISPOSITIONED:") for item in errors)


def test_mor26_workflow_cannot_be_green_when_shared_acceptance_is_skipped():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "mor26-runner-acceptance.yml"
    ).read_text(encoding="utf-8")
    assert "acceptance-status:" in workflow
    assert "G2_NOT_APPROVED_EXTERNAL_BLOCK" in workflow
    assert 'RUNNER_A_RESULT: ${{ needs.runner-a.result }}' in workflow
    assert 'VERIFY_RESULT: ${{ needs.verify.result }}' in workflow
    assert '"$RUNNER_A_RESULT" == "skipped"' in workflow
    assert '"$VERIFY_RESULT" == "skipped"' in workflow


def test_mor26_route_audit_checks_exact_pull_request_head() -> None:
    text = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "mor26-runner-acceptance.yml"
    ).read_text(encoding="utf-8")
    route = text.split("  route-audit:", 1)[1].split("  outage-fail-closed:", 1)[0]
    assert "MOR26_HEAD: ${{ github.event.pull_request.head.sha }}" in route
    assert "ref: ${{ env.MOR26_HEAD }}" in route
    assert '"commit_sha": "${{ env.MOR26_HEAD }}"' in route


def test_mor26_race_requires_shared_rendezvous() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "mor26-runner-acceptance.yml"
    ).read_text(encoding="utf-8")
    fixture = (
        Path(__file__).resolve().parents[1] / "scripts" / "mor26_runner_fixture.py"
    ).read_text(encoding="utf-8")
    assert "MOR26_RACE_CONTENDER" in workflow
    assert 'all(d["rendezvous_count"] == 2 for d in race)' in workflow
    assert "mor26_private.rendezvous" in fixture
    assert "race contenders did not rendezvous" in fixture


def test_audit_rejects_undeclared_nested_reservation_fields(tmp_path):
    payload = _audit(tmp_path)
    payload["reservations"][0]["headers"] = {"Authorization": "Basic YWJj"}
    file = tmp_path / "audit-extra.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    assert "audit reservation schema mismatch" in verify_audit_file(file)


def test_audit_rejects_impossible_global_refusal_counts(tmp_path):
    payload = _audit(tmp_path)
    payload["refusals"] = [{
        "provider": "openalex",
        "purpose": "acquisition",
        "stop_reason": ab.REFUSAL_GLOBAL,
        "refused_at_utc": "2026-11-16T00:00:00+00:00",
        "global_count": 0,
        "provider_count": 0,
    }]
    payload["counters"]["refused_total"] = 1
    payload["counters"]["by_provider"]["openalex"]["refused"] = 1
    payload["stop_reasons"] = {ab.REFUSAL_GLOBAL: 1}
    payload["status"] = "ceiling_reached"
    file = tmp_path / "audit-refusal.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    errors = verify_audit_file(file)
    assert "audit global refusal does not show exhausted ceiling" in errors


def test_sqlite_same_named_ineffective_trigger_is_rejected(tmp_path):
    approved = ab.parse_budget(_raw())
    path = tmp_path / "ledger.sqlite"
    ledger = ab.AttemptLedger(path, approved)
    ledger.initialize()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TRIGGER attempts_no_delete")
        conn.execute(
            "CREATE TRIGGER attempts_no_delete BEFORE DELETE ON attempts "
            "BEGIN SELECT 1; END"
        )
    with pytest.raises(ab.LedgerCorruptError):
        ledger.verify()


def test_sqlite_reservation_revalidates_protections_after_prior_success(tmp_path):
    approved = ab.parse_budget(_raw())
    path = tmp_path / "ledger.sqlite"
    ledger = ab.AttemptLedger(path, approved)
    ledger.initialize()
    ledger.reserve("openalex", "acquisition")
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TRIGGER attempts_no_delete")
    with pytest.raises(ab.LedgerCorruptError):
        ledger.reserve("openalex", "acquisition")


def test_postgres_snapshot_declares_repeatable_read_and_authorization_lock() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "scientific_sources" / "attempt_postgres_ledger.py"
    ).read_text(encoding="utf-8")
    snapshot = source.split("    def snapshot(", 1)[1]
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" in snapshot
    assert "self._check_authorization(cur, lock=True)" in snapshot
