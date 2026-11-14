"""Fail-closed, run-scoped budget for physical outgoing HTTP attempts.

This is the only module allowed to open an outgoing network connection to a
scientific provider. Every provider client and health probe calls
:func:`governed_urlopen`, which reserves one attempt in a shared transactional
SQLite ledger *before* the request is dispatched. Failed, timed-out and
rate-limited attempts are never refunded: the ledger is append-only and
enforced with triggers.

The control is distinct from the post-acquisition logical-page budget checked by
``scripts/check_budget_ceiling.py``. A logical page may need several physical
attempts (retries, Scopus chunks, Graph token + search).

Budget and ledger failures derive from ``BaseException`` on purpose: provider
clients contain broad ``except Exception`` handlers that convert transport errors
into soft provider warnings, and a budget stop must never be swallowed there.

Nothing in the ledger or audit carries URLs, headers, credentials or payloads.
"""
from __future__ import annotations

import ast
import contextlib
import contextvars
import hashlib
import json
import os
import re
import socket
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

BUDGET_SCHEMA_VERSION = "physical_attempt_budget/1"
LEDGER_SCHEMA_VERSION = "physical_attempt_ledger/1"
AUDIT_SCHEMA_VERSION = "physical_attempt_audit/1"

ENV_BUDGET_FILE = "ATTEMPT_BUDGET_FILE"
ENV_LEDGER_PATH = "ATTEMPT_LEDGER_PATH"
ENV_RUN_ID = "CURRENT_RUN_ID"

PURPOSES = ("health", "acquisition", "retry")
OUTCOMES = (
    "success",
    "rate_limited",
    "http_error",
    "timeout",
    "network_error",
    "error",
    "aborted",
)
REFUSAL_GLOBAL = "global_ceiling_exhausted"
REFUSAL_PROVIDER = "provider_ceiling_exhausted"

# Registered provider routes. Unknown provider labels are still bounded by the
# global ceiling, but only these names may carry a per-provider ceiling.
KNOWN_PROVIDERS = (
    "crossref",
    "google_drive",
    "microsoft_graph",
    "openalex",
    "scival",
    "scopus",
    "wos",
)

# The single module that may reach the network.
GOVERNED_MODULE_PATH = "src/scientific_sources/attempt_budget.py"

_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_BUSY_TIMEOUT_SECONDS = 30.0


class AttemptBudgetError(BaseException):
    """Base class for budget stops; intentionally not an ``Exception``."""

    code = "attempt_budget_error"


class BudgetConfigurationError(AttemptBudgetError):
    code = "budget_configuration_invalid"


class LedgerUnavailableError(AttemptBudgetError):
    code = "ledger_unavailable"


class LedgerCorruptError(AttemptBudgetError):
    code = "ledger_corrupt"


class AttemptBudgetExhausted(AttemptBudgetError):
    code = "attempt_budget_exhausted"

    def __init__(self, reason: str, provider: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.provider = provider


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strict_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BudgetConfigurationError(
            f"{label} must be a non-negative integer, got {value!r}"
        )
    return value


@dataclass(frozen=True)
class PhysicalAttemptBudget:
    """Versioned run-scoped physical-attempt quota."""

    run_id: str
    maximum_total_physical_attempts: int
    provider_ceilings: Mapping[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": BUDGET_SCHEMA_VERSION,
            "run_id": self.run_id,
            "unit": "physical_http_attempt",
            "maximum_total_physical_attempts": self.maximum_total_physical_attempts,
            "provider_ceilings": dict(sorted(self.provider_ceilings.items())),
        }

    def sha256(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_BUDGET_KEYS = {
    "schema_version",
    "run_id",
    "unit",
    "maximum_total_physical_attempts",
    "provider_ceilings",
}


def parse_budget(raw: object) -> PhysicalAttemptBudget:
    """Validate a budget object; any anomaly is a configuration error."""
    if not isinstance(raw, dict):
        raise BudgetConfigurationError("attempt budget must be a JSON object")
    unknown = sorted(set(raw) - _BUDGET_KEYS)
    if unknown:
        raise BudgetConfigurationError(f"unknown attempt budget keys: {unknown}")
    if raw.get("schema_version") != BUDGET_SCHEMA_VERSION:
        raise BudgetConfigurationError(
            f"schema_version must be {BUDGET_SCHEMA_VERSION!r}"
        )
    if raw.get("unit", "physical_http_attempt") != "physical_http_attempt":
        raise BudgetConfigurationError("unit must be 'physical_http_attempt'")
    run_id = raw.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", run_id):
        raise BudgetConfigurationError("run_id must be a non-empty safe token")
    if "maximum_total_physical_attempts" not in raw:
        raise BudgetConfigurationError("maximum_total_physical_attempts is required")
    maximum = _strict_count(
        raw["maximum_total_physical_attempts"], "maximum_total_physical_attempts"
    )
    ceilings_raw = raw.get("provider_ceilings", {})
    if not isinstance(ceilings_raw, dict):
        raise BudgetConfigurationError("provider_ceilings must be an object")
    ceilings: Dict[str, int] = {}
    for name, value in ceilings_raw.items():
        if name not in KNOWN_PROVIDERS:
            raise BudgetConfigurationError(f"unknown provider ceiling: {name!r}")
        ceilings[name] = _strict_count(value, f"provider_ceilings[{name}]")
    return PhysicalAttemptBudget(run_id, maximum, ceilings)


def load_budget(path: str | os.PathLike[str]) -> PhysicalAttemptBudget:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise BudgetConfigurationError(
            f"attempt budget file is not readable: {type(exc).__name__}"
        ) from None
    try:
        return parse_budget(json.loads(text))
    except json.JSONDecodeError:
        raise BudgetConfigurationError("attempt budget file is not valid JSON") from None


_LEDGER_DDL = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE attempts(
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK(purpose IN ('health','acquisition','retry')),
    status TEXT NOT NULL CHECK(status IN ('reserved','completed')),
    outcome TEXT,
    http_status INTEGER,
    reserved_at TEXT NOT NULL,
    completed_at TEXT,
    global_count_after INTEGER NOT NULL,
    provider_count_after INTEGER NOT NULL
);
CREATE TABLE refusals(
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    purpose TEXT NOT NULL,
    reason TEXT NOT NULL,
    refused_at TEXT NOT NULL,
    global_count INTEGER NOT NULL,
    provider_count INTEGER NOT NULL
);
CREATE TRIGGER attempts_no_delete BEFORE DELETE ON attempts
BEGIN SELECT RAISE(ABORT, 'attempts are append-only: no refunds'); END;
CREATE TRIGGER attempts_immutable_identity
BEFORE UPDATE OF seq, attempt_id, provider, purpose, reserved_at,
    global_count_after, provider_count_after ON attempts
BEGIN SELECT RAISE(ABORT, 'attempt reservation fields are immutable'); END;
CREATE TRIGGER attempts_no_reopen BEFORE UPDATE ON attempts
WHEN OLD.status = 'completed'
BEGIN SELECT RAISE(ABORT, 'completed attempts are immutable'); END;
"""

_EXPECTED_TRIGGERS = {
    "attempts_no_delete",
    "attempts_immutable_identity",
    "attempts_no_reopen",
}


@dataclass(frozen=True)
class Reservation:
    attempt_id: str
    provider: str
    purpose: str
    global_count: int
    provider_count: int


def _connect(path: Path, *, create: bool) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode={'rwc' if create else 'rw'}"
    try:
        conn = sqlite3.connect(
            uri, uri=True, timeout=_BUSY_TIMEOUT_SECONDS, isolation_level=None
        )
        conn.execute("PRAGMA synchronous=FULL")
    except sqlite3.Error as exc:
        raise LedgerUnavailableError(
            f"attempt ledger store is unavailable: {type(exc).__name__}"
        ) from None
    return conn


class AttemptLedger:
    """Shared transactional ledger; each operation uses a short-lived connection."""

    def __init__(self, path: str | os.PathLike[str], budget: PhysicalAttemptBudget):
        self.path = Path(path)
        self.budget = budget
        self._verified = False

    def initialize(self) -> None:
        """Create the ledger for the budget, or verify an existing one."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LedgerUnavailableError(
                f"attempt ledger directory is unavailable: {type(exc).__name__}"
            ) from None
        conn = _connect(self.path, create=True)
        try:
            conn.execute("BEGIN IMMEDIATE")
            has_meta = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='meta'"
            ).fetchone()
            if not has_meta:
                for statement in _split_ddl(_LEDGER_DDL):
                    conn.execute(statement)
                conn.executemany(
                    "INSERT INTO meta(key, value) VALUES (?, ?)",
                    [
                        ("schema_version", LEDGER_SCHEMA_VERSION),
                        ("run_id", self.budget.run_id),
                        ("budget_sha256", self.budget.sha256()),
                        ("created_at", _utc_now()),
                    ],
                )
            conn.execute("COMMIT")
        except sqlite3.Error:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise LedgerCorruptError("attempt ledger is corrupt or unreadable") from None
        finally:
            conn.close()
        self.verify()

    def verify(self) -> None:
        """Fail closed unless the ledger is present, intact and bound to the budget."""
        if not self.path.is_file():
            raise LedgerUnavailableError("attempt ledger store does not exist")
        conn = _connect(self.path, create=False)
        try:
            try:
                self._verify_connection(conn)
            except sqlite3.DatabaseError:
                raise LedgerCorruptError("attempt ledger is corrupt or unreadable") from None
        finally:
            conn.close()
        self._verified = True

    def _verify_connection(self, conn: sqlite3.Connection) -> None:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise LedgerCorruptError("attempt ledger failed integrity_check")
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','trigger')"
            )
        }
        required = {"meta", "attempts", "refusals"} | _EXPECTED_TRIGGERS
        if not required <= names:
            raise LedgerCorruptError("attempt ledger schema is incomplete")
        self._check_meta(conn)
        rows = conn.execute(
            "SELECT seq, provider, purpose, status, outcome, global_count_after,"
            " provider_count_after FROM attempts ORDER BY seq"
        ).fetchall()
        per_provider: Dict[str, int] = {}
        for index, (seq, provider, purpose, status, outcome, gca, pca) in enumerate(
            rows, start=1
        ):
            per_provider[provider] = per_provider.get(provider, 0) + 1
            if (
                seq != index
                or gca != index
                or pca != per_provider[provider]
                or purpose not in PURPOSES
                or status not in ("reserved", "completed")
                or (status == "completed" and outcome not in OUTCOMES)
            ):
                raise LedgerCorruptError("attempt ledger rows are inconsistent")
        if len(rows) > self.budget.maximum_total_physical_attempts:
            raise LedgerCorruptError("attempt ledger exceeds the global ceiling")
        for provider, count in per_provider.items():
            ceiling = self.budget.provider_ceilings.get(provider)
            if ceiling is not None and count > ceiling:
                raise LedgerCorruptError("attempt ledger exceeds a provider ceiling")

    def _check_meta(self, conn: sqlite3.Connection) -> None:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        if meta.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise LedgerCorruptError("attempt ledger schema version mismatch")
        if meta.get("run_id") != self.budget.run_id:
            raise LedgerCorruptError("attempt ledger run_id does not match the budget")
        if meta.get("budget_sha256") != self.budget.sha256():
            raise LedgerCorruptError("attempt ledger is bound to a different budget")

    def reserve(self, provider: str, purpose: str) -> Reservation:
        """Atomically reserve one physical attempt or raise without dispatching."""
        if purpose not in PURPOSES:
            raise BudgetConfigurationError(f"unknown attempt purpose: {purpose!r}")
        if not _PROVIDER_RE.fullmatch(provider):
            raise BudgetConfigurationError("attempt provider label is invalid")
        if not self._verified:
            self.verify()
        conn = _connect(self.path, create=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._check_meta(conn)
                total = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
                used = conn.execute(
                    "SELECT COUNT(*) FROM attempts WHERE provider=?", (provider,)
                ).fetchone()[0]
                ceiling = self.budget.provider_ceilings.get(provider)
                reason = None
                if total >= self.budget.maximum_total_physical_attempts:
                    reason = REFUSAL_GLOBAL
                elif ceiling is not None and used >= ceiling:
                    reason = REFUSAL_PROVIDER
                if reason is not None:
                    conn.execute(
                        "INSERT INTO refusals(provider, purpose, reason, refused_at,"
                        " global_count, provider_count) VALUES (?,?,?,?,?,?)",
                        (provider, purpose, reason, _utc_now(), total, used),
                    )
                    conn.execute("COMMIT")
                    raise AttemptBudgetExhausted(
                        reason,
                        provider,
                        f"physical attempt refused for {provider}: {reason} "
                        f"(global={total}/{self.budget.maximum_total_physical_attempts})",
                    )
                attempt_id = f"{self.budget.run_id}:{total + 1:06d}"
                conn.execute(
                    "INSERT INTO attempts(attempt_id, provider, purpose, status,"
                    " reserved_at, global_count_after, provider_count_after)"
                    " VALUES (?,?,?,'reserved',?,?,?)",
                    (attempt_id, provider, purpose, _utc_now(), total + 1, used + 1),
                )
                conn.execute("COMMIT")
            except AttemptBudgetError:
                raise
            except sqlite3.DatabaseError:
                with contextlib.suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise LedgerCorruptError("attempt ledger reservation failed") from None
        except sqlite3.Error as exc:
            raise LedgerUnavailableError(
                f"attempt ledger is unavailable: {type(exc).__name__}"
            ) from None
        finally:
            conn.close()
        return Reservation(attempt_id, provider, purpose, total + 1, used + 1)

    def complete(
        self, reservation: Reservation, outcome: str, http_status: Optional[int]
    ) -> None:
        """Record the actual outcome. Never changes counters."""
        if outcome not in OUTCOMES:
            outcome = "error"
        conn = _connect(self.path, create=False)
        try:
            conn.execute(
                "UPDATE attempts SET status='completed', outcome=?, http_status=?,"
                " completed_at=? WHERE attempt_id=? AND status='reserved'",
                (outcome, http_status, _utc_now(), reservation.attempt_id),
            )
        except sqlite3.Error as exc:
            raise LedgerUnavailableError(
                f"attempt outcome could not be recorded: {type(exc).__name__}"
            ) from None
        finally:
            conn.close()

    def snapshot(self) -> Dict[str, Any]:
        """Return all ledger rows for the sanitized audit."""
        self.verify()
        conn = _connect(self.path, create=False)
        try:
            attempts = conn.execute(
                "SELECT attempt_id, provider, purpose, status, outcome, http_status,"
                " reserved_at, completed_at, global_count_after, provider_count_after"
                " FROM attempts ORDER BY seq"
            ).fetchall()
            refusals = conn.execute(
                "SELECT provider, purpose, reason, refused_at, global_count,"
                " provider_count FROM refusals ORDER BY seq"
            ).fetchall()
        except sqlite3.DatabaseError:
            raise LedgerCorruptError("attempt ledger is corrupt or unreadable") from None
        finally:
            conn.close()
        return {"attempts": attempts, "refusals": refusals}


def _split_ddl(ddl: str) -> List[str]:
    """Split the DDL script, keeping trigger bodies (terminated by END;) intact."""
    statements: List[str] = []
    buffer = ""
    for line in ddl.strip().splitlines():
        buffer += line + "\n"
        stripped = line.strip()
        in_trigger = "CREATE TRIGGER" in buffer
        if stripped.endswith(";") and (not in_trigger or stripped.endswith("END;")):
            statements.append(buffer.strip())
            buffer = ""
    return statements


class AttemptGovernor:
    """Binds a budget to its ledger and exposes reserve/complete."""

    def __init__(self, budget: PhysicalAttemptBudget, ledger_path: Path) -> None:
        self.budget = budget
        self.ledger = AttemptLedger(ledger_path, budget)

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AttemptGovernor":
        env = os.environ if env is None else env
        budget_file = env.get(ENV_BUDGET_FILE, "").strip()
        if not budget_file:
            raise BudgetConfigurationError(
                f"{ENV_BUDGET_FILE} is not set: no physical-attempt budget is configured"
            )
        ledger_path = env.get(ENV_LEDGER_PATH, "").strip()
        if not ledger_path:
            raise LedgerUnavailableError(f"{ENV_LEDGER_PATH} is not set")
        budget = load_budget(budget_file)
        expected_run = env.get(ENV_RUN_ID, "").strip()
        if expected_run and expected_run != budget.run_id:
            raise BudgetConfigurationError(
                "budget run_id does not match the current workflow run identity"
            )
        governor = cls(budget, Path(ledger_path))
        governor.ledger.verify()
        return governor


_governor_cache: Dict[tuple[str, str], AttemptGovernor] = {}
_cache_lock_pid = os.getpid()


def reset_governor_cache() -> None:
    _governor_cache.clear()


def require_governor() -> AttemptGovernor:
    """Return the verified governor for this process or raise before any request."""
    key = (os.environ.get(ENV_BUDGET_FILE, ""), os.environ.get(ENV_LEDGER_PATH, ""))
    global _cache_lock_pid
    if _cache_lock_pid != os.getpid():
        _governor_cache.clear()
        _cache_lock_pid = os.getpid()
    cached = _governor_cache.get(key)
    if cached is not None:
        return cached
    governor = AttemptGovernor.from_env()
    _governor_cache[key] = governor
    return governor


_provider_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "attempt_provider", default=None
)
_purpose_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "attempt_purpose", default="acquisition"
)


@contextlib.contextmanager
def attempt_context(
    *, provider: Optional[str] = None, purpose: Optional[str] = None
) -> Iterator[None]:
    """Attribute requests made inside the block to a provider and purpose."""
    provider_token = _provider_ctx.set(provider) if provider is not None else None
    purpose_token = _purpose_ctx.set(purpose) if purpose is not None else None
    try:
        yield
    finally:
        if purpose_token is not None:
            _purpose_ctx.reset(purpose_token)
        if provider_token is not None:
            _provider_ctx.reset(provider_token)


def current_provider() -> Optional[str]:
    return _provider_ctx.get()


def _classify(exc: BaseException) -> tuple[str, Optional[int]]:
    if isinstance(exc, urllib.error.HTTPError):
        return ("rate_limited" if exc.code == 429 else "http_error"), exc.code
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout", None
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "timeout", None
        return "network_error", None
    if isinstance(exc, Exception):
        return "error", None
    return "aborted", None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never issue a second HTTP request using the first hop's reservation."""

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int,
        msg: str, headers: Any, newurl: str,
    ) -> None:
        # Fail closed on any HTTP 30x: even a same-host hop requires a new
        # physical-attempt reservation before the next network dispatch.
        return None


def _dispatch_request(
    request: urllib.request.Request | str, *, timeout: float,
) -> Any:
    """Make one bounded HTTP request; never follow redirects implicitly."""
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


def governed_urlopen(
    request: urllib.request.Request | str,
    *,
    timeout: float,
    provider: Optional[str] = None,
    purpose: Optional[str] = None,
) -> Any:
    """Reserve one physical attempt, then dispatch the request.

    Raises an :class:`AttemptBudgetError` subclass, with zero network I/O, when
    the budget, ledger or ceiling does not permit the attempt. The returned
    object is the ``urlopen`` response and is usable as a context manager.
    """
    governor = require_governor()
    label = provider or current_provider()
    if not label:
        raise BudgetConfigurationError("network route has no provider attribution")
    reservation = governor.ledger.reserve(label, purpose or _purpose_ctx.get())
    try:
        response = _dispatch_request(request, timeout=timeout)
    except BaseException as exc:
        outcome, status = _classify(exc)
        _complete_quietly(governor, reservation, outcome, status)
        raise
    status_code = getattr(response, "status", None)
    _complete_quietly(
        governor,
        reservation,
        "success",
        status_code if isinstance(status_code, int) else None,
    )
    return response


def _complete_quietly(
    governor: AttemptGovernor,
    reservation: Reservation,
    outcome: str,
    status: Optional[int],
) -> None:
    # The attempt is already counted; a failed outcome write must not mask the
    # request result. It stays visible as an unresolved reservation in the audit.
    with contextlib.suppress(AttemptBudgetError):
        governor.ledger.complete(reservation, outcome, status)


def _redact_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except (ValueError, OSError):
        return "[redacted-out-of-repository]"


def build_audit(
    governor: AttemptGovernor, *, repo_root: Path, requested_providers: Sequence[str] = ()
) -> Dict[str, Any]:
    """Return the sanitized audit of reservations, outcomes, counters and stops."""
    budget = governor.budget
    snap = governor.ledger.snapshot()
    reservations = [
        {
            "attempt_id": a[0],
            "provider": a[1],
            "purpose": a[2],
            "status": a[3],
            "outcome": a[4],
            "http_status": a[5],
            "reserved_at_utc": a[6],
            "completed_at_utc": a[7],
            "global_count_after": a[8],
            "provider_count_after": a[9],
        }
        for a in snap["attempts"]
    ]
    refusals = [
        {
            "provider": r[0],
            "purpose": r[1],
            "stop_reason": r[2],
            "refused_at_utc": r[3],
            "global_count": r[4],
            "provider_count": r[5],
        }
        for r in snap["refusals"]
    ]
    providers = sorted(
        set(budget.provider_ceilings)
        | {r["provider"] for r in reservations}
        | {r["provider"] for r in refusals}
        | set(requested_providers)
    )
    by_provider: Dict[str, Any] = {}
    for name in providers:
        mine = [r for r in reservations if r["provider"] == name]
        outcomes: Dict[str, int] = {}
        for row in mine:
            key = row["outcome"] or "unresolved"
            outcomes[key] = outcomes.get(key, 0) + 1
        by_provider[name] = {
            "ceiling": budget.provider_ceilings.get(name),
            "reserved": len(mine),
            "refused": sum(1 for r in refusals if r["provider"] == name),
            "outcomes": dict(sorted(outcomes.items())),
        }
    stop_reasons: Dict[str, int] = {}
    for refusal in refusals:
        stop_reasons[refusal["stop_reason"]] = stop_reasons.get(refusal["stop_reason"], 0) + 1
    total = len(reservations)
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "run_id": budget.run_id,
        "budget": budget.to_dict(),
        "budget_sha256": budget.sha256(),
        "ledger_path": _redact_path(governor.ledger.path, repo_root),
        "counters": {
            "reserved_total": total,
            "remaining_global": budget.maximum_total_physical_attempts - total,
            "completed": sum(1 for r in reservations if r["status"] == "completed"),
            "unresolved": sum(1 for r in reservations if r["status"] != "completed"),
            "refused_total": len(refusals),
            "by_provider": by_provider,
        },
        "stop_reasons": dict(sorted(stop_reasons.items())),
        "status": (
            "ceiling_reached" if refusals else "within_budget"
        ),
        "reservations": reservations,
        "refusals": refusals,
        "separate_controls": {
            "logical_page_budget": "scripts/check_budget_ceiling.py (unchanged, post-acquisition)",
            "attempts_are_never_refunded": True,
        },
        "evidence_boundary": (
            "Operational acquisition-control audit only; contains no query text, "
            "URLs, headers, credentials or provider payloads and makes no "
            "empirical H1-H3 claim."
        ),
    }


_NETWORK_MODULES = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "http.client",
    "httplib2",
    "googleapiclient",
}
_NETWORK_CALLS = {"urlopen", "urlretrieve", "create_connection"}


def find_ungoverned_network_routes(
    repo_root: Path, roots: Iterable[str] = ("src", "scripts")
) -> List[str]:
    """Return repo-relative ``path:line`` entries that reach the network directly.

    Includes top-level ``*.py`` files. Only :data:`GOVERNED_MODULE_PATH` is exempt.
    """
    files: List[Path] = sorted(repo_root.glob("*.py"))
    for root in roots:
        files.extend(sorted((repo_root / root).rglob("*.py")))
    findings: List[str] = []
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        if rel == GOVERNED_MODULE_PATH:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            findings.append(f"{rel}:0 unparseable")
            continue
        for node in ast.walk(tree):
            hit = None
            if isinstance(node, ast.Import):
                hit = next(
                    (a.name for a in node.names if a.name in _NETWORK_MODULES), None
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in _NETWORK_MODULES or node.module.split(".")[0] in {
                    "requests",
                    "httpx",
                    "aiohttp",
                    "urllib3",
                }:
                    hit = node.module
                elif node.module in ("urllib.request", "socket"):
                    hit = next(
                        (a.name for a in node.names if a.name in _NETWORK_CALLS), None
                    )
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else (
                    func.id if isinstance(func, ast.Name) else ""
                )
                if name in _NETWORK_CALLS:
                    hit = name
            if hit:
                findings.append(f"{rel}:{getattr(node, 'lineno', 0)} {hit}")
    return findings
