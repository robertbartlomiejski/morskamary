"""New MOR-26 offline twenty-case regression, NOT the original RED suite."""
import copy
import json

import pytest

from src.scientific_sources import attempt_budget as ab
from src.scientific_sources.attempt_audit_validator import verify_audit_file
from src.scientific_sources.attempt_postgres_ledger import PostgresAttemptLedger
from src.scientific_sources.attempt_route_inventory import (
    find_unverified_network_routes,
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
    ("stop_reasons", {"global_ceiling_exhausted": 2}),
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


def test_missing_pg_dsn_refuses_before_any_fake_dispatch():
    fake_dispatches = 0
    with pytest.raises(ab.LedgerUnavailableError):
        PostgresAttemptLedger("", ab.parse_budget(_raw())).reserve(
            "openalex", "acquisition"
        )
    assert fake_dispatches == 0


def test_valid_sanitized_audit_accepted(tmp_path):
    file = tmp_path / "ok.json"
    file.write_text(json.dumps(_audit(tmp_path)), encoding="utf-8")
    assert verify_audit_file(file) == []
