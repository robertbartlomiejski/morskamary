"""Run-local bibliographic provenance. The PostgreSQL quota ledger owns authorization."""
from __future__ import annotations

import contextlib
import contextvars
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

PROVIDERS = {"crossref", "scopus", "openalex"}
_SCHEMA = """
CREATE TABLE pairs (
    run_id TEXT NOT NULL, query_id TEXT NOT NULL, query_text TEXT NOT NULL,
    provider TEXT NOT NULL, page_limit INTEGER NOT NULL, status TEXT NOT NULL,
    PRIMARY KEY (run_id, query_id, provider), UNIQUE(query_text, provider)
);
CREATE TABLE reservations (
    attempt_id TEXT PRIMARY KEY, query_id TEXT, provider TEXT NOT NULL, purpose TEXT NOT NULL
);
CREATE TABLE responses (
    response_id INTEGER PRIMARY KEY, query_id TEXT NOT NULL, provider TEXT NOT NULL,
    logical_page INTEGER NOT NULL, chunk INTEGER NOT NULL, page_limit INTEGER NOT NULL,
    result_offset INTEGER NOT NULL, retrieved_utc TEXT NOT NULL, reported_hits INTEGER, more_results INTEGER,
    attempt_id TEXT UNIQUE REFERENCES reservations(attempt_id),
    UNIQUE(query_id,provider,logical_page,chunk)
);
CREATE TABLE entries (
    response_id INTEGER REFERENCES responses, position INTEGER NOT NULL,
    source_id TEXT, doi TEXT, title TEXT, PRIMARY KEY(response_id,position)
);
CREATE INDEX entries_source ON entries(source_id);
CREATE VIEW query_results AS
SELECT p.*,
    (SELECT reported_hits FROM responses r WHERE r.query_id=p.query_id AND r.provider=p.provider
        ORDER BY response_id LIMIT 1) AS api_reported_hits,
    (SELECT count(*) FROM entries e JOIN responses r USING(response_id)
        WHERE r.query_id=p.query_id AND r.provider=p.provider) AS fetched_records,
    (SELECT more_results FROM responses r WHERE r.query_id=p.query_id AND r.provider=p.provider
        ORDER BY response_id DESC LIMIT 1) AS has_more
FROM pairs p;
CREATE VIEW work_occurrences AS
WITH aliases AS (
    SELECT r.provider,e.source_id,min(e.doi) AS doi FROM entries e JOIN responses r USING(response_id)
    WHERE e.source_id IS NOT NULL AND e.doi IS NOT NULL GROUP BY r.provider,e.source_id
    HAVING count(DISTINCT e.doi)=1
)
SELECT p.run_id,r.query_id,r.provider,r.response_id,r.logical_page,r.chunk,e.position,
    r.result_offset+e.position AS result_position,r.retrieved_utc,r.attempt_id,e.source_id,e.doi,e.title,
    coalesce('doi:' || coalesce(e.doi,a.doi), r.provider || ':' || e.source_id) AS work_id
FROM entries e JOIN responses r USING(response_id) JOIN pairs p USING(query_id,provider)
LEFT JOIN aliases a ON a.provider=r.provider AND a.source_id=e.source_id;
CREATE VIEW works AS SELECT work_id,min(title) AS title,count(*) AS occurrence_count
FROM work_occurrences WHERE work_id IS NOT NULL GROUP BY work_id;
"""

_active: contextvars.ContextVar[RetrievalTrace | None] = contextvars.ContextVar("retrieval_trace", default=None)


class RetrievalTrace:
    def __init__(self, path: Path, run_id: str, plan: Iterable[tuple[str, str, str, int]], *, offline: bool = False):
        if not run_id.strip():
            raise ValueError("retrieval trace requires a run_id")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=False)  # A retry cannot overwrite previous evidence.
        self.db = sqlite3.connect(path)
        self.query_id: str | None = None
        self.last_attempt: dict[str, str] = {}
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.executescript(_SCHEMA)
            with self.db:
                self.db.executemany("INSERT INTO pairs VALUES (?,?,?,?,?,?)", (
                    (run_id, qid, query, provider, limit, "offline_not_executed" if offline else "not_started")
                    for qid, query, provider, limit in plan if provider in PROVIDERS
                ))
        except BaseException:
            self.db.close()
            raise

    @contextlib.contextmanager
    def activate(self) -> Iterator[RetrievalTrace]:
        token = _active.set(self)
        try:
            yield self
        finally:
            _active.reset(token)
            self.db.close()

    def status(self, provider: str, value: str) -> None:
        if value == "completed":
            missing = self.db.execute(
                "SELECT 1 FROM entries e JOIN responses r USING(response_id) "
                "WHERE r.query_id=? AND r.provider=? AND e.doi IS NULL AND e.source_id IS NULL LIMIT 1",
                (self.query_id, provider),
            ).fetchone()
            if missing:
                value = "incomplete_identity"
        with self.db:
            self.db.execute("UPDATE pairs SET status=? WHERE query_id=? AND provider=?", (value, self.query_id, provider))


@contextlib.contextmanager
def query_scope(query: str, provider: str) -> Iterator[RetrievalTrace | None]:
    trace = _active.get()
    if trace is None or provider not in PROVIDERS:
        yield None
        return
    row = trace.db.execute("SELECT query_id FROM pairs WHERE query_text=? AND provider=?", (query, provider)).fetchone()
    if row is None:
        raise ValueError("query/provider outside retrieval plan")
    trace.query_id = row[0]
    trace.status(provider, "started")
    try:
        yield trace
    except BaseException:
        trace.status(provider, "stopped")
        raise
    finally:
        trace.query_id = None


def record_reservation(attempt_id: str, provider: str, purpose: str) -> None:
    trace = _active.get()
    if trace is None or provider not in PROVIDERS:
        return
    with trace.db:
        trace.db.execute("INSERT INTO reservations VALUES (?,?,?,?)", (attempt_id, trace.query_id, provider, purpose))
    trace.last_attempt[provider] = attempt_id


def _identity(provider: str, item: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    # Route inventories run on bare Python; load scientific dependencies only for received works.
    from src.scientific_sources.cumulative_scientific_database import _normalize_doi

    if provider == "scopus":
        source, doi, title = item.get("eid") or item.get("dc:identifier"), item.get("prism:doi"), item.get("dc:title")
    elif provider == "openalex":
        source, doi, title = item.get("id"), item.get("doi"), item.get("display_name") or item.get("title")
    else:
        source = doi = item.get("DOI")
        titles = item.get("title")
        title = titles[0] if isinstance(titles, list) and titles else None
    return str(source or "").strip() or None, _normalize_doi(doi) or None, str(title or "").strip() or None


def record_page(provider: str, page: int, chunk: int, limit: int, offset: int, payload: dict[str, Any]) -> None:
    """Capture original array positions and totals before normalization or time filtering."""
    trace = _active.get()
    if trace is None:
        return
    if provider == "openalex":
        items, total = payload.get("results"), payload.get("meta", {}).get("count")
    elif provider == "crossref":
        message = payload.get("message", {})
        items, total = message.get("items"), message.get("total-results")
    else:
        message = payload.get("search-results", {})
        items, total = message.get("entry"), message.get("opensearch:totalResults")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("provider returned a malformed results array")
    hits = int(total) if isinstance(total, (int, str)) and str(total).isascii() and str(total).isdecimal() else None
    if provider == "scopus" and any("error" in item for item in items):
        if hits == 0 and len(items) == 1 and str(items[0].get("error", "")).lower() == "result set was empty":
            items = []
        else:
            raise ValueError("Scopus returned an error entry")
    if len(items) > limit or (items and hits is not None and hits < len(items)):
        raise ValueError("page size or zero-hit response inconsistent with entries")
    if trace.query_id is None:
        raise ValueError("provider page outside a planned query")
    more: bool | None = (hits > offset + len(items)) if hits is not None else None
    if more is None and provider == "openalex" and payload.get("meta", {}).get("next_cursor"):
        more = True
    attempt = trace.last_attempt.pop(provider, None)
    if attempt is None:
        raise ValueError("response has no physical reservation")
    with trace.db:
        response = trace.db.execute("INSERT INTO responses VALUES(NULL,?,?,?,?,?,?,?,?,?,?)", (
            trace.query_id, provider, page, chunk, limit, offset, datetime.now(timezone.utc).isoformat(), hits, more, attempt,
        ))
        trace.db.executemany("INSERT INTO entries VALUES (?,?,?,?,?)", (
            (response.lastrowid, pos, *_identity(provider, item)) for pos, item in enumerate(items, 1)
        ))
