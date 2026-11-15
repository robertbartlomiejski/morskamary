"""MOR-25: explicit G2 freeze and deliberately RED cross-runner acceptance.

The freeze and local subprocess tests do not validate independently hosted runners.
A separate durable transactional backend and runner-level acceptance are required.
No HTTP or third-party provider is contacted by this module.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    (".github/workflows/full-live-analysis.yml", "  live-analysis:"),
    (".github/workflows/research-api-smoke.yml", "  research-api-smoke:"),
    (".github/workflows/research-pipeline.yml", "  live-search-smoke:"),
)
GUARD = "- name: Enforce MOR-25 G2 shared-ledger freeze"
BUDGET_INIT = "- name: Initialize physical HTTP-attempt budget and ledger"


@pytest.mark.parametrize(("path", "job"), WORKFLOWS)
def test_live_workflows_refuse_provider_dispatch_before_budget_init(path, job):
    text = (ROOT / path).read_text(encoding="utf-8")
    start = text.index(job)
    guard = text.index(GUARD, start)
    init = text.index(BUDGET_INIT, start)
    assert start < guard < init
    block = text[guard:init]
    assert "MOR-25 G2 BLOCKED" in block
    assert "exit 1" in block


def test_hardening_dry_run_remains_available():
    text = (ROOT / WORKFLOWS[0][0]).read_text(encoding="utf-8")
    assert "if: inputs.execution_mode == 'hardening_dry_run'" in text
    assert text.index("  hardening-dry-run:") < text.index("  live-analysis:")


# All operations below are fixture-only, using a local SQLite file shared by
# two separately launched subprocesses. This is a necessary local regression,
# NOT sufficient proof that GitHub-hosted runners share a transactional store.
CHILD = r"""
import json
import sys
from pathlib import Path
from src.scientific_sources import attempt_budget as ab

budget = ab.parse_budget(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
ledger = ab.AttemptLedger(Path(sys.argv[2]), budget)
initial = sys.argv[3] == "initial"
if initial:
    ledger.initialize()
else:
    ledger.verify()
before = len(ledger.snapshot()["attempts"])
assert before == int(sys.argv[4]), (before, sys.argv[4])
reserved_here = int(sys.argv[5])
fake_dispatches = 0
for _ in range(reserved_here):
    ledger.reserve("openalex", "acquisition")
    fake_dispatches += 1  # No HTTP transport: dispatch only after reserve.
used = len(ledger.snapshot()["attempts"])
assert used == before + reserved_here
remaining = budget.maximum_total_physical_attempts - used
if sys.argv[6] == "exhaust":
    assert remaining == 0
    try:
        ledger.reserve("openalex", "acquisition")
    except ab.AttemptBudgetExhausted:
        pass
    else:
        raise AssertionError("attempt N+1 was not refused")
    assert fake_dispatches == reserved_here
print(json.dumps({"used": used, "remaining": remaining,
                  "fake_dispatches": fake_dispatches}))
"""


def _run_child(budget_file, ledger_file, mode, before, count, check):
    completed = subprocess.run(
        [
            sys.executable, "-c", CHILD, str(budget_file), str(ledger_file),
            mode, str(before), str(count), check,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_same_acquisition_new_workflow_provenance_keeps_n_minus_k(tmp_path):
    n, k = 7, 3
    ledger_file = tmp_path / "same-acquisition.sqlite"

    def budget(provenance, attempt):
        return {
            "schema_version": "physical_attempt_budget/2",
            "acquisition_id": "mor25-offline-fixture",
            "budget_id": "approved-quota-v1",
            "workflow_run_id": provenance,
            "run_attempt": attempt,
            "unit": "physical_http_attempt",
            "maximum_total_physical_attempts": n,
            "provider_ceilings": {"openalex": n},
        }

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps(budget("runner-one", 1)), encoding="utf-8")
    second.write_text(json.dumps(budget("runner-two", 2)), encoding="utf-8")
    first_result = _run_child(first, ledger_file, "initial", 0, k, "partial")
    assert first_result["remaining"] == n - k
    second_result = _run_child(
        second, ledger_file, "restart", k, n - k, "exhaust"
    )
    assert second_result["used"] == n
    assert second_result["remaining"] == 0
    assert second_result["fake_dispatches"] == n - k
