"""Simulated provider transport only. No scientific inference."""
import io
import json
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import mor25_openalex_pilot as pilot
from scripts.manage_physical_attempt_budget import derive_budget
from src.scientific_sources import attempt_budget as physical
from src.scientific_sources.retrieval_trace import RetrievalTrace, query_scope, record_page, record_reservation


class FakeResponse(io.BytesIO):
    status = 200


@pytest.mark.parametrize("empty", [False, True])
def test_governed_two_query_pilot(monkeypatch, tmp_path, empty):
    plan = pilot.plan_for("a" * 40)
    digest = pilot.hashlib.sha256(pilot.encode(plan)).hexdigest()
    budget = derive_budget(
        acquisition_id="fixture-port", budget_id="fixture-only", plan_sha256=digest, providers=["openalex"],
        queries=2, logical_pages=1, rows_per_page=5, workflow_run_id="fixture-port", run_attempt=1,
    )
    path = tmp_path / "budget.json"
    path.write_bytes(pilot.encode(budget.to_dict()))
    ledger = tmp_path / "fixture.sqlite"
    physical.AttemptLedger(ledger, budget).initialize()
    monkeypatch.setenv("ATTEMPT_BUDGET_FILE", str(path))
    monkeypatch.setenv("ATTEMPT_LEDGER_BACKEND", "sqlite")
    monkeypatch.setenv("ATTEMPT_LEDGER_PATH", str(ledger))
    monkeypatch.setenv("CURRENT_RUN_ID", "fixture-port")
    monkeypatch.setenv("OPENALEX_API_KEY", "fixture")
    monkeypatch.setattr("src.scientific_sources.openalex.time.sleep", lambda _: None)
    searches = [q["query_text"] for q in plan["selection"]]
    sends = []

    def fake_send(request, *, timeout):
        parts = urlsplit(request.full_url)
        assert (parts.scheme, parts.netloc, parts.path) == ("https", "api.openalex.org", "/works")
        params = parse_qs(parts.query)
        sends.append(params)
        if "search" not in params:
            assert params["filter"] == ["title.search:ocean"] and params["per_page"] == ["1"]
            return FakeResponse(b"{}")
        assert params["search"] == [searches[(len(sends) - 2) // 3]]
        assert params["per_page"] == ["5"] and params["cursor"] == ["*"] and "sort" not in params
        assert params["filter"] == ["from_publication_date:2019-01-01,to_publication_date:2026-12-31"]
        if len(sends) not in (4, 7):
            raise TimeoutError("simulated")
        items = [] if empty else [{"id": "W1", "doi": "https://doi.org/10.0000/FAKE", "title": "Synthetic work"},
                                  {"id": "W2"}]
        return FakeResponse(json.dumps({"meta": {"count": 0 if empty else 12}, "results": items}).encode())

    monkeypatch.setattr(physical, "_dispatch_request", fake_send)
    pilot.acquire(plan, tmp_path, "fixture-port")
    assert len(sends) == 7
    with pytest.raises(physical.AttemptBudgetExhausted):
        physical.governed_urlopen("https://api.openalex.org/works", provider="openalex", timeout=1)
    assert len(sends) == 7
    with sqlite3.connect(tmp_path / "retrieval.sqlite3") as db:
        expected = (0, 0, 0) if empty else (12, 2, 1)
        assert db.execute("SELECT api_reported_hits,fetched_records,has_more FROM query_results").fetchall() == [expected] * 2
        assert db.execute("SELECT count(*) FROM reservations WHERE query_id IS NULL AND purpose='health'").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM reservations WHERE purpose='retry'").fetchone() == (4,)
        assert db.execute("SELECT count(*) FROM responses WHERE attempt_id IS NOT NULL").fetchone() == (2,)
        assert db.execute("SELECT count(*) FROM works").fetchone() == (0 if empty else 2,)
        assert db.execute("SELECT count(*) FROM work_occurrences").fetchone() == (0 if empty else 4,)
        if not empty:
            assert db.execute("SELECT DISTINCT position FROM work_occurrences WHERE source_id='W2'").fetchall() == [(2,)]


def test_cross_provider_ids_scopus_chunk_and_unexecuted(tmp_path):
    pairs = [("Q1", "alpha", p, 50) for p in ("scopus", "openalex", "crossref", "wos")]
    trace = RetrievalTrace(tmp_path / "trace.db", "run-1", pairs)
    with trace.activate():
        with query_scope("alpha", "crossref"):
            record_reservation("A", "crossref", "acquisition")
            record_page("crossref", 1, 1, 50, 0, {"message": {"total-results": 1, "items": [{"DOI": "10.0000/TEST"}]}})
            trace.status("crossref", "completed")
        with query_scope("alpha", "scopus"):
            record_reservation("B", "scopus", "acquisition")
            record_page("scopus", 1, 2, 25, 25, {"search-results": {"opensearch:totalResults": "27", "entry": [
                {"eid": "2-s2.0-test", "prism:doi": "10.0000/test"}, {"eid": "2-s2.0-test"},
            ]}})
            trace.status("scopus", "completed")
        assert trace.db.execute("SELECT work_id,occurrence_count FROM works").fetchall() == [("doi:10.0000/test", 3)]
        unseen = trace.db.execute("SELECT status,api_reported_hits,has_more FROM query_results WHERE provider='openalex'")
        assert unseen.fetchone() == ("not_started", None, None)
        assert trace.db.execute("SELECT count(*) FROM pairs").fetchone() == (3,)
    with pytest.raises(FileExistsError):
        RetrievalTrace(tmp_path / "trace.db", "run-1", pairs)


def test_invalid_payload_not_zero(tmp_path):
    with RetrievalTrace(tmp_path / "trace.db", "r", [("Q", "test", "openalex", 5)]).activate() as trace:
        with pytest.raises(ValueError), query_scope("test", "openalex"):
            record_page("openalex", 1, 1, 5, 0, {"meta": {"count": 0}})
        assert trace.db.execute("SELECT status,api_reported_hits FROM query_results").fetchone() == ("stopped", None)


def test_wrong_plan_digest_stops_before_health(tmp_path, monkeypatch):
    import sys

    sha = "a" * 40
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_SHA", sha)
    monkeypatch.setenv("MOR25_G2_APPROVED_SHA", sha)
    monkeypatch.setenv("MOR25_G2_APPROVED_PLAN_SHA256", "0" * 64)
    monkeypatch.setenv("ATTEMPT_LEDGER_BACKEND", "postgres")
    monkeypatch.setenv("CURRENT_RUN_ID", "fixture")
    monkeypatch.setattr(sys, "argv", ["pilot", "--commit", sha, "--output", str(tmp_path / "pilot"), "--execute"])
    monkeypatch.setattr(pilot, "acquire", lambda *args: pytest.fail("unapproved pilot reached acquisition"))
    with pytest.raises(ValueError, match="approval"):
        pilot.main()


def test_postgres_pilot_entrypoint(tmp_path, monkeypatch):
    import os
    import sys

    if os.getenv("MOR25_TEST_POSTGRES") != "1":
        pytest.skip("requires the isolated rehearsal PostgreSQL service")
    import psycopg
    from scripts.mor26_runner_fixture import seed

    dsn = "postgresql://postgres@127.0.0.1:55432/mor25_fixture"
    sha = os.environ.get("MOR25_REHEARSAL_SHA", "f" * 40)
    plan = pilot.plan_for(sha)
    digest = pilot.hashlib.sha256(pilot.encode(plan)).hexdigest()
    budget = derive_budget(
        acquisition_id=plan["acquisition_id"], budget_id=plan["budget_id"], plan_sha256=digest, providers=["openalex"],
        queries=2, logical_pages=1, rows_per_page=5,
    )
    with psycopg.connect(dsn) as conn:
        conn.execute((pilot.ROOT / "sql/mor26_private_attempt_ledger.sql").read_text())
    seed(budget, dsn)
    for name, value in {
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": sha, "MOR25_G2_APPROVED_SHA": sha,
        "MOR25_G2_APPROVED_PLAN_SHA256": digest, "ATTEMPT_LEDGER_BACKEND": "postgres",
        "ATTEMPT_LEDGER_DSN": dsn, "CURRENT_RUN_ID": "fixture-pg", "GITHUB_RUN_ATTEMPT": "1",
        "OPENALEX_API_KEY": "fixture",
    }.items():
        monkeypatch.setenv(name, value)
    sent = []

    def fixture_send(request, *, timeout):
        parts = urlsplit(request.full_url)
        assert parts.hostname == "api.openalex.org" and parts.path == "/works"
        params = parse_qs(parts.query)
        sent.append(params)
        if "search" not in params:
            return FakeResponse(b"{}")
        items = [{"id": "Wfixture", "title": "Synthetic work", "doi": "10.0000/fixture", "publication_year": 2024}]
        return FakeResponse(json.dumps({"meta": {"count": 1}, "results": items}).encode())

    monkeypatch.setattr(physical, "_dispatch_request", fixture_send)
    out = tmp_path / "pilot"
    monkeypatch.setattr(sys, "argv", ["pilot", "--commit", sha, "--output", str(out), "--execute"])
    pilot.main()
    assert len(sent) == 3
    assert (out / "SHA256SUMS").is_file()
    assert json.loads((out / "attempt_audit.json").read_bytes())["ledger_path"] == "shared-postgresql-ledger"
    with sqlite3.connect(out / "retrieval.sqlite3") as db:
        assert db.execute("SELECT occurrence_count FROM works").fetchall() == [(2,)]
        assert db.execute("SELECT count(*) FROM responses WHERE attempt_id IS NOT NULL").fetchone() == (2,)
