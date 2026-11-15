"""MOR-26: durable, pre-provisioned PostgreSQL physical-attempt ledger.

No provider traffic is performed here. An authorization must already exist in
the private PostgreSQL schema; this client cannot mint or enlarge a quota.
Different hosted runner VMs share one database and lock the same authorization
row before checking any attempt count. Secrets never enter errors or audits.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.scientific_sources.attempt_budget import (
    LEDGER_SCHEMA_VERSION,
    OUTCOMES,
    PURPOSES,
    REFUSAL_GLOBAL,
    REFUSAL_PROVIDER,
    AttemptBudgetError,
    AttemptBudgetExhausted,
    BudgetConfigurationError,
    LedgerCorruptError,
    LedgerUnavailableError,
    PhysicalAttemptBudget,
    Reservation,
    _PROVIDER_RE,
    _utc_now,
)


class PostgresAttemptLedger:
    """Fail-closed pre-approved quota; PostgreSQL row lock serializes reservations."""

    def __init__(self, dsn: str, budget: PhysicalAttemptBudget) -> None:
        self._dsn = dsn
        self.budget = budget
        # A deliberate non-secret sentinel. Audit never logs database DSNs.
        self.path = Path("[shared-postgresql-ledger]")
        self._verified = False

    def _open(self) -> Any:
        if not self._dsn or not self._dsn.strip():
            raise LedgerUnavailableError("shared ledger credentials are missing")
        try:
            driver = importlib.import_module("psycopg")
            return driver.connect(
                self._dsn,
                connect_timeout=5,
                options="-c statement_timeout=10000 -c lock_timeout=5000",
            )
        except Exception as exc:
            raise LedgerUnavailableError(
                f"shared ledger connection unavailable: {type(exc).__name__}"
            ) from None

    @property
    def _key(self) -> tuple[str, str]:
        return (self.budget.acquisition_id, self.budget.budget_id)

    def _check_authorization(self, cur: Any, *, lock: bool = False) -> None:
        query = (
            "SELECT schema_version, budget_sha256,"
            " maximum_total_physical_attempts, provider_ceilings_json"
            " FROM mor26_private.authorizations"
            " WHERE acquisition_id=%s AND budget_id=%s"
        )
        if lock:
            query += " FOR UPDATE"
        cur.execute(query, self._key)
        row = cur.fetchone()
        if row is None:
            raise LedgerCorruptError("pre-approved shared authorization is missing")
        schema, sha256, maximum, ceilings = row
        if (
            schema != LEDGER_SCHEMA_VERSION
            or sha256 != self.budget.sha256()
            or maximum != self.budget.maximum_total_physical_attempts
            or ceilings != dict(self.budget.provider_ceilings)
        ):
            raise LedgerCorruptError("shared ledger authorization mismatch")

    def _validated_counts(self, cur: Any) -> tuple[int, Dict[str, int]]:
        cur.execute(
            "SELECT seq, provider, purpose, status, outcome,"
            " global_count_after, provider_count_after"
            " FROM mor26_private.attempts"
            " WHERE acquisition_id=%s AND budget_id=%s ORDER BY seq",
            self._key,
        )
        rows = cur.fetchall()
        per_provider: Dict[str, int] = {}
        for index, row in enumerate(rows, 1):
            seq, provider, purpose, status, outcome, global_count, provider_count = row
            per_provider[provider] = per_provider.get(provider, 0) + 1
            if (
                seq != index
                or global_count != index
                or provider_count != per_provider[provider]
                or provider not in self.budget.provider_ceilings
                or purpose not in PURPOSES
                or status not in ("reserved", "completed")
                or (status == "completed" and outcome not in OUTCOMES)
                or (status == "reserved" and outcome is not None)
            ):
                raise LedgerCorruptError("shared ledger attempt rows are inconsistent")
        if len(rows) > self.budget.maximum_total_physical_attempts:
            raise LedgerCorruptError("shared ledger exceeds global ceiling")
        for provider, used in per_provider.items():
            if used > self.budget.provider_ceilings[provider]:
                raise LedgerCorruptError("shared ledger exceeds provider ceiling")
        return len(rows), per_provider

    def initialize(self) -> None:
        """Verify a pre-provisioned quota; never create one implicitly."""
        self.verify()

    def verify(self) -> None:
        try:
            with self._open() as conn:
                with conn.cursor() as cur:
                    self._check_authorization(cur, lock=True)
                    self._validated_counts(cur)
        except AttemptBudgetError:
            raise
        except Exception as exc:
            raise LedgerUnavailableError(
                f"shared ledger verify unavailable: {type(exc).__name__}"
            ) from None
        self._verified = True

    def reserve(self, provider: str, purpose: str) -> Reservation:
        """Commit a counted reservation before returning control to HTTP transport."""
        if purpose not in PURPOSES:
            raise BudgetConfigurationError("unknown physical attempt purpose")
        if (
            not _PROVIDER_RE.fullmatch(provider)
            or provider not in self.budget.provider_ceilings
        ):
            raise BudgetConfigurationError("provider lacks an approved ceiling")
        if not self._verified:
            self.verify()
        result: Optional[Reservation] = None
        refusal: Optional[tuple[str, int]] = None
        try:
            with self._open() as conn:
                with conn.cursor() as cur:
                    # This row is shared by runner A and B. Holding FOR UPDATE
                    # until transaction commit serializes the check-and-insert.
                    self._check_authorization(cur, lock=True)
                    total, per_provider = self._validated_counts(cur)
                    used = per_provider.get(provider, 0)
                    reason = None
                    if total >= self.budget.maximum_total_physical_attempts:
                        reason = REFUSAL_GLOBAL
                    elif used >= self.budget.provider_ceilings[provider]:
                        reason = REFUSAL_PROVIDER
                    if reason is not None:
                        cur.execute(
                            "INSERT INTO mor26_private.refusals"
                            " (acquisition_id,budget_id,provider,purpose,reason,"
                            " refused_at,global_count,provider_count)"
                            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (*self._key, provider, purpose, reason,
                             _utc_now(), total, used),
                        )
                        refusal = reason, total
                    else:
                        attempt_id = f"{self.budget.budget_id}:{total + 1:06d}"
                        cur.execute(
                            "INSERT INTO mor26_private.attempts"
                            " (acquisition_id,budget_id,seq,attempt_id,provider,"
                            " purpose,status,reserved_at,global_count_after,"
                            " provider_count_after)"
                            " VALUES (%s,%s,%s,%s,%s,%s,'reserved',%s,%s,%s)",
                            (*self._key, total + 1, attempt_id, provider, purpose,
                             _utc_now(), total + 1, used + 1),
                        )
                        result = Reservation(
                            attempt_id, provider, purpose, total + 1, used + 1
                        )
        except AttemptBudgetError:
            raise
        except Exception as exc:
            raise LedgerUnavailableError(
                f"shared reservation unavailable: {type(exc).__name__}"
            ) from None
        if refusal is not None:
            reason, total = refusal
            raise AttemptBudgetExhausted(
                reason, provider,
                f"physical attempt refused for {provider}: {reason} "
                f"(global={total}/{self.budget.maximum_total_physical_attempts})",
            )
        if result is None:
            raise LedgerCorruptError("shared ledger returned no reservation")
        return result

    def complete(
        self, reservation: Reservation, outcome: str, http_status: Optional[int]
    ) -> None:
        """Outcome update never changes the reserved count."""
        if outcome not in OUTCOMES:
            outcome = "error"
        try:
            with self._open() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE mor26_private.attempts SET"
                        " status='completed',outcome=%s,http_status=%s,"
                        " completed_at=%s"
                        " WHERE acquisition_id=%s AND budget_id=%s"
                        " AND attempt_id=%s AND status='reserved'",
                        (outcome, http_status, _utc_now(), *self._key,
                         reservation.attempt_id),
                    )
                    if cur.rowcount != 1:
                        raise LedgerCorruptError(
                            "shared ledger completion target is missing"
                        )
        except AttemptBudgetError:
            raise
        except Exception as exc:
            raise LedgerUnavailableError(
                f"shared ledger completion unavailable: {type(exc).__name__}"
            ) from None

    def snapshot(self) -> Dict[str, List[Any]]:
        """Return sanitized audit tuples in the same shape as the SQLite ledger."""
        self.verify()
        try:
            with self._open() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT attempt_id,provider,purpose,status,outcome,"
                        " http_status,reserved_at,completed_at,"
                        " global_count_after,provider_count_after"
                        " FROM mor26_private.attempts"
                        " WHERE acquisition_id=%s AND budget_id=%s ORDER BY seq",
                        self._key,
                    )
                    attempts = cur.fetchall()
                    cur.execute(
                        "SELECT provider,purpose,reason,refused_at,"
                        " global_count,provider_count"
                        " FROM mor26_private.refusals"
                        " WHERE acquisition_id=%s AND budget_id=%s ORDER BY id",
                        self._key,
                    )
                    refusals = cur.fetchall()
        except AttemptBudgetError:
            raise
        except Exception as exc:
            raise LedgerUnavailableError(
                f"shared ledger snapshot unavailable: {type(exc).__name__}"
            ) from None
        return {"attempts": attempts, "refusals": refusals}
