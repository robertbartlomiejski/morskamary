"""Read the existing G2 authorization using the pilot's runtime credentials."""

import os
import sys

ACQUISITION = "mor25-openalex-port-pilot-v1"
BUDGET = "mor25-openalex-port-budget-v1"
DIGEST = "28e1010f25b6f61f7b7f2265f773f6bd197e93b443aee8b4d65c2b2f0cda778c"
OPTIONS = "-c statement_timeout=10000 -c lock_timeout=5000"


def failed(stage, error):
    state = getattr(error, "sqlstate", None)
    state = state if isinstance(state, str) and len(state) == 5 and state.isalnum() else "unknown"
    print(f"stage={stage} error={type(error).__name__} sqlstate={state}")
    return 1


def diagnose(driver, dsn):
    if not dsn or not dsn.strip():
        print("stage=secret missing")
        return 1
    try:
        driver.conninfo.conninfo_to_dict(dsn)
    except Exception as error:
        return failed("parse", error)

    control = False
    try:
        conn = driver.connect(dsn, connect_timeout=5, options=OPTIONS)
    except Exception as error:
        failed("pilot_connect", error)
        control = True
        try:
            conn = driver.connect(dsn, connect_timeout=5)
        except Exception as error:
            return failed("control_connect", error)

    stage = "read_only_transaction"
    try:
        with conn:
            conn.execute("SET TRANSACTION READ ONLY")
            if control:
                stage = "control_set_timeouts"
                conn.execute("SET LOCAL statement_timeout = '10s'")
                conn.execute("SET LOCAL lock_timeout = '5s'")
            stage = "verify_session"
            session = conn.execute(
                "SELECT current_setting('transaction_read_only') = 'on', "
                "current_setting('statement_timeout')::interval = interval '10 seconds', "
                "current_setting('lock_timeout')::interval = interval '5 seconds', "
                "rolcanlogin AND (rolvaliduntil IS NULL OR rolvaliduntil > now()) "
                "FROM pg_catalog.pg_roles WHERE rolname = session_user"
            ).fetchone()
            if session != (True, True, True, True):
                raise ValueError()
            stage = "verify_authorization"
            row = conn.execute(
                "SELECT budget_sha256, maximum_total_physical_attempts, provider_ceilings_json "
                "FROM mor26_private.authorizations WHERE acquisition_id=%s AND budget_id=%s",
                (ACQUISITION, BUDGET),
            ).fetchone()
            if not row or row[:2] != (DIGEST, 7) or row[2].get("openalex") != 7:
                raise ValueError()
    except Exception as error:
        return failed(stage, error)
    print("control_read_ok" if control else "pilot_read_ok")
    return int(control)


if __name__ == "__main__":
    import psycopg  # type: ignore[import-not-found]  # Installed by the protected workflow.

    sys.exit(diagnose(psycopg, os.environ.get("ATTEMPT_LEDGER_DSN")))
