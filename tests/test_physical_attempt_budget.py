"""Negative tests for the fail-closed physical HTTP-attempt budget (MOR-25).

FIXTURE ONLY: every network call here is a local fake; nothing contacts a
provider. Each exhaustion test asserts that the fake network saw no call after
the ceiling was reached.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest

from scripts import check_research_api_health as health
from scripts import manage_physical_attempt_budget as manage
from scripts.prepare_live_acquisition_plan import ACTIVE_ACQUISITION_PROVIDERS
from src.scientific_sources import attempt_budget as ab
from src.scientific_sources.attempt_budget import (
    AttemptBudgetExhausted,
    AttemptLedger,
    BudgetConfigurationError,
    LedgerCorruptError,
    LedgerUnavailableError,
    governed_urlopen,
    reset_governor_cache,
)
from src.scientific_sources.crossref import CrossrefProvider
from src.scientific_sources.openalex import OpenAlexProvider

from tests.test_openalex_provider import _response  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
_STRICT_DISPATCH = ab._dispatch_request  # Capture production dispatcher before pytest fixtures.


def _budget_dict(
    maximum: Any, ceilings: Optional[Dict[str, int]] = None, run_id: str = "run-1"
) -> Dict[str, Any]:
    return {
        "schema_version": "physical_attempt_budget/1",
        "run_id": run_id,
        "maximum_total_physical_attempts": maximum,
        "provider_ceilings": ceilings or {},
    }


def _configure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    maximum: int,
    ceilings: Optional[Dict[str, int]] = None,
) -> Path:
    budget = ab.parse_budget(_budget_dict(maximum, ceilings))
    budget_file = tmp_path / "budget.json"
    ledger_path = tmp_path / "ledger.sqlite"
    budget_file.write_text(json.dumps(budget.to_dict()), encoding="utf-8")
    AttemptLedger(ledger_path, budget).initialize()
    monkeypatch.setenv(ab.ENV_BUDGET_FILE, str(budget_file))
    monkeypatch.setenv(ab.ENV_LEDGER_PATH, str(ledger_path))
    reset_governor_cache()
    return ledger_path


class _Network:
    """Counts requests that actually reach the (fake) network."""

    def __init__(self, behaviour: Callable[[int], Any]) -> None:
        self.calls = 0
        self._behaviour = behaviour
        self._lock = threading.Lock()

    def __call__(self, request: Any, timeout: float = 0) -> Any:
        with self._lock:
            self.calls += 1
            index = self.calls
        return self._behaviour(index)


class _Response:
    status = 200

    def __init__(self, payload: Any = None) -> None:
        self._payload = payload if payload is not None else {}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def _install(
    monkeypatch: pytest.MonkeyPatch, behaviour: Callable[[int], Any]
) -> _Network:
    network = _Network(behaviour)
    monkeypatch.setattr(urllib.request, "urlopen", network)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    return network


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example.invalid", code, "x", {}, None)  # type: ignore[arg-type]


def _get(provider: str = "crossref") -> Any:
    return governed_urlopen(
        urllib.request.Request("https://example.invalid/?api_key=SECRETKEY"),
        timeout=1,
        provider=provider,
    )


def _audit(tmp_path: Path) -> Dict[str, Any]:
    governor = ab.require_governor()
    return ab.build_audit(governor, repo_root=REPO_ROOT)


def test_zero_budget_dispatches_nothing(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, 0)
    network = _install(monkeypatch, lambda i: _Response())
    with pytest.raises(AttemptBudgetExhausted) as info:
        _get()
    assert info.value.reason == ab.REFUSAL_GLOBAL
    assert network.calls == 0
    audit = _audit(tmp_path)
    assert audit["counters"]["reserved_total"] == 0
    assert audit["stop_reasons"] == {ab.REFUSAL_GLOBAL: 1}


@pytest.mark.parametrize("limit", [1, 3, 7])
def test_n_succeed_and_n_plus_one_is_refused(tmp_path, monkeypatch, limit):
    _configure(tmp_path, monkeypatch, limit)
    network = _install(monkeypatch, lambda i: _Response())
    for _ in range(limit):
        _get()
    assert network.calls == limit
    with pytest.raises(AttemptBudgetExhausted):
        _get()
    assert network.calls == limit
    assert _audit(tmp_path)["counters"]["reserved_total"] == limit


def test_provider_ceiling_is_enforced_independently(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, 10, {"crossref": 1, "openalex": 5})
    network = _install(monkeypatch, lambda i: _Response())
    _get("crossref")
    with pytest.raises(AttemptBudgetExhausted) as info:
        _get("crossref")
    assert info.value.reason == ab.REFUSAL_PROVIDER
    assert network.calls == 1
    _get("openalex")
    assert network.calls == 2


@pytest.mark.parametrize("code", [429, 500, 503])
def test_retries_after_http_errors_consume_budget_without_refund(
    tmp_path, monkeypatch, code
):
    _configure(tmp_path, monkeypatch, 2)

    def behaviour(index: int) -> Any:
        raise _http_error(code)

    network = _install(monkeypatch, behaviour)
    with pytest.raises(AttemptBudgetExhausted):
        CrossrefProvider().search("blue economy", max_results=1)
    assert network.calls == 2
    audit = _audit(tmp_path)
    assert audit["counters"]["reserved_total"] == 2
    assert [r["purpose"] for r in audit["reservations"]] == ["acquisition", "retry"]
    expected = "rate_limited" if code == 429 else "http_error"
    assert {r["outcome"] for r in audit["reservations"]} == {expected}


@pytest.mark.parametrize(
    "error",
    [TimeoutError("t"), urllib.error.URLError(socket.timeout("t"))],
)
def test_timeouts_are_counted_and_not_refunded(tmp_path, monkeypatch, error):
    _configure(tmp_path, monkeypatch, 1)

    def behaviour(index: int) -> Any:
        raise error

    network = _install(monkeypatch, behaviour)
    with pytest.raises((TimeoutError, urllib.error.URLError)):
        _get()
    with pytest.raises(AttemptBudgetExhausted):
        _get()
    assert network.calls == 1
    assert _audit(tmp_path)["reservations"][0]["outcome"] == "timeout"


def test_pagination_stops_at_ceiling_with_zero_further_calls(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, 2)
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")

    def behaviour(index: int) -> Any:
        return _Response(_response(index * 2, 2, f"cursor-{index + 1}"))

    network = _install(monkeypatch, behaviour)
    with pytest.raises(AttemptBudgetExhausted):
        OpenAlexProvider().search_paginated("q", pages=3, rows_per_page=2)
    assert network.calls == 2


def test_concurrent_workers_never_exceed_the_ceiling(tmp_path, monkeypatch):
    limit = 25
    _configure(tmp_path, monkeypatch, limit, {"crossref": limit})
    network = _install(monkeypatch, lambda i: _Response())
    refused = []

    def worker() -> None:
        for _ in range(10):
            try:
                _get()
            except AttemptBudgetExhausted:
                refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert network.calls == limit
    assert len(refused) == 80 - limit
    audit = _audit(tmp_path)
    assert audit["counters"]["reserved_total"] == limit
    ids = [r["attempt_id"] for r in audit["reservations"]]
    assert len(set(ids)) == limit


def test_separate_processes_share_one_ledger(tmp_path, monkeypatch):
    limit = 17
    _configure(tmp_path, monkeypatch, limit)
    code = (
        "from src.scientific_sources import attempt_budget as ab\n"
        "g = ab.AttemptGovernor.from_env()\n"
        "ok = 0\n"
        "for _ in range(10):\n"
        "    try:\n"
        "        g.ledger.reserve('crossref', 'acquisition'); ok += 1\n"
        "    except ab.AttemptBudgetExhausted:\n"
        "        pass\n"
        "print(ok)\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    granted = sum(int(p.communicate()[0]) for p in processes)
    assert granted == limit
    assert _audit(tmp_path)["counters"]["reserved_total"] == limit


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.write_bytes(b"not a sqlite database" * 100),
        lambda p: p.write_bytes(p.read_bytes()[:50]),
    ],
)
def test_corrupted_ledger_blocks_before_any_request(tmp_path, monkeypatch, mutate):
    ledger = _configure(tmp_path, monkeypatch, 5)
    mutate(ledger)
    network = _install(monkeypatch, lambda i: _Response())
    with pytest.raises((LedgerCorruptError, LedgerUnavailableError)):
        _get()
    assert network.calls == 0


def test_tampered_ledger_rows_and_binding_are_rejected(tmp_path, monkeypatch):
    import sqlite3

    ledger = _configure(tmp_path, monkeypatch, 5)
    network = _install(monkeypatch, lambda i: _Response())
    _get()
    conn = sqlite3.connect(ledger)
    with pytest.raises(sqlite3.DatabaseError):  # refund by delete is impossible
        conn.execute("DELETE FROM attempts")
    with pytest.raises(sqlite3.DatabaseError):  # reservation fields are immutable
        conn.execute("UPDATE attempts SET provider='openalex'")
    conn.execute("UPDATE meta SET value='other-run' WHERE key='run_id'")
    conn.commit()
    conn.close()
    reset_governor_cache()
    with pytest.raises(LedgerCorruptError):
        _get()
    assert network.calls == 1


def test_unavailable_store_and_missing_configuration_block(tmp_path, monkeypatch):
    network = _install(monkeypatch, lambda i: _Response())
    _configure(tmp_path, monkeypatch, 5)
    monkeypatch.setenv(ab.ENV_LEDGER_PATH, str(tmp_path / "absent" / "ledger.sqlite"))
    reset_governor_cache()
    with pytest.raises(LedgerUnavailableError):
        _get()
    monkeypatch.delenv(ab.ENV_LEDGER_PATH)
    reset_governor_cache()
    with pytest.raises(LedgerUnavailableError):
        _get()
    monkeypatch.delenv(ab.ENV_BUDGET_FILE)
    reset_governor_cache()
    with pytest.raises(BudgetConfigurationError):
        _get()
    assert network.calls == 0


@pytest.mark.parametrize(
    "raw",
    [
        _budget_dict(True),
        _budget_dict(-1),
        _budget_dict("5"),
        _budget_dict(2.0),
        _budget_dict(None),
        _budget_dict(5, {"crossref": -1}),
        _budget_dict(5, {"not_a_provider": 1}),
        {**_budget_dict(5), "schema_version": "v0"},
        {**_budget_dict(5), "surprise": 1},
        {k: v for k, v in _budget_dict(5).items() if k != "maximum_total_physical_attempts"},
        [],
    ],
)
def test_invalid_budgets_are_rejected(raw):
    with pytest.raises(BudgetConfigurationError):
        ab.parse_budget(raw)


def test_run_identity_mismatch_blocks(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, 5)
    monkeypatch.setenv(ab.ENV_RUN_ID, "a-different-run")
    reset_governor_cache()
    network = _install(monkeypatch, lambda i: _Response())
    with pytest.raises(BudgetConfigurationError):
        _get()
    assert network.calls == 0


def test_unattributed_route_is_refused(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, 5)
    network = _install(monkeypatch, lambda i: _Response())
    with pytest.raises(BudgetConfigurationError):
        governed_urlopen("https://example.invalid", timeout=1)
    assert network.calls == 0


def test_budget_stop_is_not_swallowed_by_broad_except(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, 0)
    network = _install(monkeypatch, lambda i: _Response())
    with pytest.raises(AttemptBudgetExhausted):
        try:
            CrossrefProvider().search("q", max_results=1)
        except Exception:  # noqa: BLE001 - mirrors provider-level handlers
            pytest.fail("budget stop was swallowed by except Exception")
    assert network.calls == 0


def test_repository_has_no_ungoverned_network_route():
    assert ab.find_ungoverned_network_routes(REPO_ROOT) == []


def test_route_scanner_detects_bypass_attempts(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        "import urllib.request\nurllib.request.urlopen('x')\n", encoding="utf-8"
    )
    (tmp_path / "src" / "b.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "scripts" / "c.py").write_text(
        "from urllib.request import urlopen\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "d.py").write_text(
        "import socket\nsocket.create_connection(('h', 1))\n", encoding="utf-8"
    )
    found = " ".join(ab.find_ungoverned_network_routes(tmp_path))
    for name in ("src/a.py", "src/b.py", "scripts/c.py", "scripts/d.py"):
        assert name in found


def test_health_probes_are_attributed_and_budgeted(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, 1, {"crossref": 1})
    network = _install(monkeypatch, lambda i: _Response())
    monkeypatch.setenv("OPENALEX_API_KEY", "k")
    out = tmp_path / "health.json"
    monkeypatch.setattr(
        sys, "argv", ["h", "--providers", "crossref,openalex", "--output", str(out)]
    )
    assert health.main() == 1  # openalex probe is refused: global ceiling reached
    assert network.calls == 1
    audit = _audit(tmp_path)
    assert audit["reservations"][0]["provider"] == "crossref"
    assert audit["reservations"][0]["purpose"] == "health"
    assert audit["stop_reasons"] == {ab.REFUSAL_GLOBAL: 1}


def test_health_script_fails_closed_without_budget(tmp_path, monkeypatch, capsys):
    network = _install(monkeypatch, lambda i: _Response())
    monkeypatch.delenv(ab.ENV_BUDGET_FILE)
    reset_governor_cache()
    monkeypatch.setattr(
        sys, "argv", ["h", "--providers", "crossref", "--output", str(tmp_path / "o.json")]
    )
    assert health.main() == 1
    assert network.calls == 0
    assert "[ERROR]" in capsys.readouterr().err


def test_exporter_live_mode_fails_closed_without_budget(tmp_path, monkeypatch, capsys):
    from scripts import export_live_research_records as exporter

    network = _install(monkeypatch, lambda i: _Response())
    monkeypatch.delenv(ab.ENV_BUDGET_FILE)
    reset_governor_cache()
    monkeypatch.setattr(
        sys,
        "argv",
        ["e", "--providers", "crossref", "--offline", "false", "--output-dir", str(tmp_path)],
    )
    assert exporter.main() == 1
    assert network.calls == 0
    assert "physical attempt budget stop" in capsys.readouterr().err


def test_audit_is_sanitized(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, 2)
    request = urllib.request.Request(
        "https://example.invalid/?api_key=SECRETKEY",
        headers={"Authorization": "Bearer SECRETTOKEN", "X-ELS-APIKey": "SECRETKEY"},
    )
    _install(monkeypatch, lambda i: _Response({"restricted": "PAYLOADTEXT"}))
    with governed_urlopen(request, timeout=1, provider="scopus"):
        pass
    text = json.dumps(_audit(tmp_path))
    for forbidden in ("SECRET", "PAYLOADTEXT", "example.invalid", "Bearer", str(tmp_path)):
        assert forbidden not in text
    assert '"ledger_path": "[redacted-out-of-repository]"' in text


def test_derived_budget_pins_unrequested_providers_to_zero():
    budget = manage.derive_budget(
        run_id="r", providers=["openalex"], queries=120, logical_pages=2, rows_per_page=25
    )
    assert budget.provider_ceilings["openalex"] == 1 + 120 * 2 * 3
    for name in ab.KNOWN_PROVIDERS:
        if name != "openalex":
            assert budget.provider_ceilings[name] == 0
    assert budget.maximum_total_physical_attempts == 721
    assert set(manage.ACTIVE_ACQUISITION_PROVIDERS) == set(ACTIVE_ACQUISITION_PROVIDERS)


def test_init_and_audit_cli_round_trip(tmp_path, monkeypatch):
    env_file = tmp_path / "env.txt"
    argv = [
        "init", "--run-id", "cli-run", "--providers", "crossref", "--queries", "2",
        "--logical-pages", "1", "--rows-per-page", "5",
        "--budget-output", str(tmp_path / "budget.json"),
        "--ledger", str(tmp_path / "ledger.sqlite"), "--github-env", str(env_file),
    ]
    assert manage.main(argv) == 0
    env = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    monkeypatch.setenv(ab.ENV_BUDGET_FILE, env[ab.ENV_BUDGET_FILE])
    monkeypatch.setenv(ab.ENV_LEDGER_PATH, env[ab.ENV_LEDGER_PATH])
    reset_governor_cache()
    _install(monkeypatch, lambda i: _Response())
    _get("crossref")
    out = tmp_path / "audit.json"
    assert manage.main(
        ["audit", "--budget", env[ab.ENV_BUDGET_FILE], "--ledger", env[ab.ENV_LEDGER_PATH],
         "--output", str(out)]
    ) == 0
    audit = json.loads(out.read_text())
    assert audit["run_id"] == "cli-run"
    assert audit["counters"]["reserved_total"] == 1
    assert audit["budget"]["maximum_total_physical_attempts"] == 1 + 2 * 1 * 4
    assert manage.main(["audit", "--budget", str(tmp_path / "missing.json"),
                        "--ledger", env[ab.ENV_LEDGER_PATH], "--output", str(out)]) == 1


# --- workflow wiring ---------------------------------------------------------


def _workflow_steps(name: str) -> list[str]:
    import yaml

    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps: list[str] = []
    for job in data["jobs"].values():
        for step in job.get("steps", []):
            steps.append(step.get("name", "") + "\n" + str(step.get("run", "")))
    return steps


def _index(steps: list[str], needle: str) -> int:
    for i, step in enumerate(steps):
        if needle in step:
            return i
    raise AssertionError(f"step containing {needle!r} not found")


@pytest.mark.parametrize(
    ("workflow", "first_network"),
    [
        ("full-live-analysis.yml", "check_research_api_health.py"),
        ("research-api-smoke.yml", "--live-if-secrets-present"),
        ("research-pipeline.yml", "check_research_api_health.py"),
    ],
)
def test_workflows_initialise_budget_before_network_steps(workflow: str, first_network: str) -> None:
    steps = _workflow_steps(workflow)
    init = _index(steps, "manage_physical_attempt_budget.py init")
    assert init < _index(steps, first_network)


def test_full_live_keeps_logical_budget_and_audits_after_export() -> None:
    steps = _workflow_steps("full-live-analysis.yml")
    export = _index(steps, "export_live_research_records.py")
    assert export < _index(steps, "manage_physical_attempt_budget.py audit")
    assert _index(steps, "check_budget_ceiling.py") > export

# --- hardening regressions for review threads on PR #297 ---------------------


def test_http_redirect_cannot_consume_unreserved_second_hop(
    tmp_path, monkeypatch
):
    """Use urllib's actual redirect/error handlers with a fake transport."""
    import io
    import urllib.response
    from email.message import Message

    _configure(tmp_path, monkeypatch, 1, {"crossref": 1})

    class _RedirectTransport(urllib.request.HTTPHandler):
        calls = 0

        def http_open(self, request):
            self.calls += 1
            headers = Message()
            headers["Location"] = "http://example.invalid/redirected"
            response = urllib.response.addinfourl(
                io.BytesIO(b""), headers, request.full_url, code=302
            )
            response.msg = "Found"
            return response

    transport = _RedirectTransport()
    real_build_opener = urllib.request.build_opener
    # The fixture redirects legacy mocks to urlopen. Explicitly restore the
    # production path, allowing only the fake HTTP transport to be injected.
    monkeypatch.setattr(
        urllib.request, "build_opener",
        lambda *handlers: real_build_opener(*handlers, transport),
    )
    monkeypatch.setattr(ab, "_dispatch_request", _STRICT_DISPATCH)
    with pytest.raises(urllib.error.HTTPError) as caught:
        governed_urlopen("http://example.invalid/start", timeout=1, provider="crossref")
    assert caught.value.code == 302
    assert transport.calls == 1
    with pytest.raises(AttemptBudgetExhausted):
        governed_urlopen("http://example.invalid/second", timeout=1, provider="crossref")
    assert transport.calls == 1
    assert _audit(tmp_path)["counters"]["reserved_total"] == 1


def test_smoke_skips_deactivated_provider_before_dispatch(
    tmp_path, monkeypatch, capsys
):
    from types import SimpleNamespace
    from scripts import smoke_scientific_bridge as smoke

    _configure(tmp_path, monkeypatch, 2, {"wos": 0})

    class _Registry:
        def list_capabilities(self):
            return [SimpleNamespace(name="wos", provider="wos", live_test_allowed=True)]

        def search(self, *args, **kwargs):
            pytest.fail("zero-quota provider dispatched")

    monkeypatch.setattr(smoke, "SourceRegistry", _Registry)
    assert smoke.run_live_checks() == []
    assert "physical attempt quota is zero" in capsys.readouterr().out
    assert _audit(tmp_path)["counters"]["reserved_total"] == 0


def test_legacy_export_workflow_blocks_unbudgeted_live_dispatch() -> None:
    import yaml

    path = REPO_ROOT / ".github/workflows/export-research-records.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = next(iter(data["jobs"].values()))["steps"]
    guard_index = next(
        i for i, step in enumerate(steps)
        if step.get("name") == "Reject unbudgeted legacy live export"
    )
    guard = steps[guard_index]
    assert guard["if"] == "github.event.inputs.offline != 'true'"
    assert "exit 1" in guard["run"]
    assert guard_index < next(
        i for i, step in enumerate(steps)
        if step.get("name") == "Research API preflight health check"
    )
    assert guard_index < next(
        i for i, step in enumerate(steps)
        if step.get("name") == "Export live research records"
    )


def test_full_live_always_run_audit_keeps_budget_refusal_evidence() -> None:
    import yaml

    path = REPO_ROOT / ".github/workflows/full-live-analysis.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = next(iter(data["jobs"].values()))["steps"]
    audit = next(step for step in steps if step.get("name") == "Upload current-run audit")
    release = next(step for step in steps if step.get("name") == "Upload curated release")
    assert audit["if"] == "always()"
    assert release["if"] == "success()"
    artifact_paths = audit["with"]["path"]
    assert "outputs/governance/physical_attempt_budget.json" in artifact_paths
    assert "outputs/governance/physical_attempt_audit.json" in artifact_paths
