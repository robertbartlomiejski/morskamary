# MOR-26 — staged PostgreSQL atomic ledger (NOT G2 approval)

This implementation deliberately separates **approved authorization creation**
from **runtime reservation**. A runner cannot create or enlarge a quota:
PostgresAttemptLedger.initialize() only verifies a pre-provisioned record.

## Required infrastructure

- Independent PostgreSQL server accessible to both GitHub-hosted runners; TLS,
  least-privileged runtime account and tightly restricted network ingress.
- Apply sql/mor26_private_attempt_ledger.sql as a **private schema**. The
  permission profile is documented at the start of the migration.
- Separately provision the exact acquisition_id, budget_id, stable plan SHA,
  immutable budget SHA, maximum and provider_ceilings_json in
  mor26_private.authorizations with an **authorizer** role, not the runner role.
- Install psycopg 3 only in the dedicated environment that uses this backend.
- Do not place the DSN in YAML, JSON artifacts, logs, comments or repository.
- Configure the authorized secret ATTEMPT_LEDGER_DSN privately; opt in via
  ATTEMPT_LEDGER_BACKEND=postgres. An unset/missing DSN fails closed.
- This code does not activate live providers; G2 freeze remains in all existing
  live-provider workflows. No production secret has been provisioned.

## Semantics

Both runners lock mor26_private.authorizations using SELECT ... FOR UPDATE
inside one PostgreSQL transaction. Count validation, reservation-or-refusal
insertion and COMMIT happen under that lock; only then may the fake or real
transport be called. Workflow run ID and attempt are excluded from stable
budget sha256. A timeout, abort or 429 never refunds a counted attempt.

## Acceptance evidence missing

The original 20-case RED source tests/test_physical_attempt_budget_v2.py
(8116 bytes, SHA-256
e94774bc07c0eda1403ea966dd0ff47de0c3cc0e11e17210af644d3429d1f3cf)
is **not** present in accessible attached ZIP, PR or recovery commit.
It must not be replaced silently with newly authored tests.

No PostgreSQL DSN or shared hosted-runner acceptance evidence is yet
available. Until independently hosted runner A (N=7,K=3), hosted runner B
(N-K=4, attempt 8 refused), a concurrent N-1 race, provider ceilings,
unavailable-store fail-closed, and exact-SHA sanitized audit are verified,
status is MOR-26 IN PROGRESS; PR #297 DRAFT; G2 NOT APPROVED.
