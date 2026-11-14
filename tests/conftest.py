"""Shared pytest fixtures.

FIXTURE ONLY: the default attempt budget below lets deterministic unit tests that
mock ``urllib.request.urlopen`` exercise provider logic. It proves software
behaviour only and is not live-provider evidence. Budget-specific tests override
the environment explicitly.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Iterator

import pytest

from src.scientific_sources.attempt_budget import (
    AttemptLedger,
    ENV_BUDGET_FILE,
    ENV_LEDGER_PATH,
    ENV_RUN_ID,
    KNOWN_PROVIDERS,
    parse_budget,
    reset_governor_cache,
)


@pytest.fixture(scope="session", autouse=True)
def fixture_attempt_budget(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    # Session scope so class/module-scoped fixtures that mock network calls are covered.
    monkeypatch = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("fixture_attempt_budget")
    budget = parse_budget(
        {
            "schema_version": "physical_attempt_budget/1",
            "run_id": "fixture-run-1",
            "maximum_total_physical_attempts": 1_000_000,
            "provider_ceilings": {name: 1_000_000 for name in KNOWN_PROVIDERS},
        }
    )
    budget_file = base / "budget.json"
    budget_file.write_text(json.dumps(budget.to_dict()), encoding="utf-8")
    AttemptLedger(base / "ledger.sqlite", budget).initialize()
    monkeypatch.setenv(ENV_BUDGET_FILE, str(budget_file))
    monkeypatch.setenv(ENV_LEDGER_PATH, str(Path(base / "ledger.sqlite")))
    monkeypatch.delenv(ENV_RUN_ID, raising=False)
    reset_governor_cache()
    # Session-scoped provider fixtures run before function fixtures. Adapt the
    # legacy urlopen mocks at session scope, before any module-scoped acquisition
    # fixture can inadvertently reach a real HTTP transport.
    from src.scientific_sources import attempt_budget as budget_module

    monkeypatch.setattr(
        budget_module, "_dispatch_request",
        lambda request, *, timeout: urllib.request.urlopen(request, timeout=timeout),
    )
    yield
    reset_governor_cache()
    monkeypatch.undo()

