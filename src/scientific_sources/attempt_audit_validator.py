"""Strict, fail-closed validation of sanitized physical-attempt audit artifacts."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List

from src.scientific_sources.attempt_budget import (
    AUDIT_SCHEMA_VERSION,
    OUTCOMES,
    PURPOSES,
    REFUSAL_GLOBAL,
    REFUSAL_PROVIDER,
    parse_budget,
    AttemptBudgetError,
)


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def verify_audit_file(path: str | os.PathLike[str]) -> List[str]:
    """Return human-readable errors only, never raw or secret-bearing content."""
    try:
        raw = Path(path).read_bytes()
        text = raw.decode("utf-8", errors="strict")
        audit = json.loads(text)
    except (OSError, UnicodeError, ValueError):
        return ["audit missing, malformed UTF-8, or invalid JSON"]
    if not isinstance(audit, dict):
        return ["audit must be a JSON object"]
    errors: List[str] = []
    expected_keys = {
        "schema_version", "acquisition_id", "budget_id", "workflow_run_id",
        "run_attempt", "budget", "budget_sha256", "ledger_path", "counters",
        "stop_reasons", "status", "reservations", "refusals",
        "separate_controls", "evidence_boundary",
    }
    if set(audit) != expected_keys:
        errors.append("audit top-level keys mismatch")
    if audit.get("schema_version") != AUDIT_SCHEMA_VERSION:
        errors.append("audit schema mismatch")
    forbidden = (
        "bearer ", "authorization:", "api_key", "apikey", "client_secret",
        "x-els-apikey", "password=", "token=", "/home/", "/tmp/",
        "/runner/", "/users/", "c:\\",
    )
    lowered = text.lower()
    if any(s in lowered for s in forbidden):
        errors.append("audit may contain credentials or absolute paths")
    try:
        budget = parse_budget(audit.get("budget"))
    except AttemptBudgetError:
        errors.append("audit budget is invalid")
        return errors
    if (
        audit.get("acquisition_id") != budget.acquisition_id
        or audit.get("budget_id") != budget.budget_id
        or audit.get("workflow_run_id") != budget.workflow_run_id
        or audit.get("run_attempt") != budget.run_attempt
        or audit.get("budget_sha256") != budget.sha256()
    ):
        errors.append("audit identity or authorization digest mismatch")
    location = audit.get("ledger_path")
    if (
        not isinstance(location, str)
        or location.startswith(("/", "\\"))
        or ".." in location.split("/")
    ):
        errors.append("audit ledger path is invalid")
    reservations = audit.get("reservations")
    refusals = audit.get("refusals")
    counters = audit.get("counters")
    if not isinstance(reservations, list) or not isinstance(refusals, list):
        errors.append("audit rows must be arrays")
        return errors
    if not isinstance(counters, dict):
        errors.append("audit counters must be an object")
        return errors
    used_by_provider: dict[str, int] = {}
    outcomes_by_provider: dict[str, dict[str, int]] = {}
    seen_ids: set[str] = set()
    completed = 0
    for idx, row in enumerate(reservations, 1):
        if not isinstance(row, dict):
            errors.append("audit reservation is not an object")
            continue
        provider = row.get("provider")
        purpose = row.get("purpose")
        status = row.get("status")
        attempt_id = row.get("attempt_id")
        if (
            not isinstance(provider, str)
            or provider not in budget.provider_ceilings
            or purpose not in PURPOSES
            or status not in ("reserved", "completed")
            or not isinstance(attempt_id, str)
            or not attempt_id
            or attempt_id in seen_ids
        ):
            errors.append("audit reservation identity or status invalid")
            continue
        seen_ids.add(attempt_id)
        used_by_provider[provider] = used_by_provider.get(provider, 0) + 1
        if (
            row.get("global_count_after") != idx
            or row.get("provider_count_after") != used_by_provider[provider]
        ):
            errors.append("audit reservation sequence inconsistent")
        outcome = row.get("outcome")
        if status == "completed":
            completed += 1
            if outcome not in OUTCOMES:
                errors.append("audit completed outcome invalid")
        elif outcome is not None:
            errors.append("audit unresolved reservation contains outcome")
        key = outcome or "unresolved"
        by_outcome = outcomes_by_provider.setdefault(provider, {})
        by_outcome[key] = by_outcome.get(key, 0) + 1
    if len(reservations) > budget.maximum_total_physical_attempts:
        errors.append("audit exceeds global ceiling")
    for provider, used in used_by_provider.items():
        if used > budget.provider_ceilings[provider]:
            errors.append("audit exceeds provider ceiling")
    counted = (
        ("reserved_total", len(reservations)),
        ("remaining_global",
         budget.maximum_total_physical_attempts - len(reservations)),
        ("completed", completed),
        ("unresolved", len(reservations) - completed),
        ("refused_total", len(refusals)),
    )
    for name, expected in counted:
        if not _count(counters.get(name)) or counters[name] != expected:
            errors.append(f"audit counter {name} mismatch")
    stop_reasons: dict[str, int] = {}
    refused_by_provider: dict[str, int] = {}
    for row in refusals:
        if not isinstance(row, dict):
            errors.append("audit refusal is not an object")
            continue
        provider = row.get("provider")
        reason = row.get("stop_reason")
        if (
            not isinstance(provider, str)
            or provider not in budget.provider_ceilings
            or row.get("purpose") not in PURPOSES
            or reason not in (REFUSAL_GLOBAL, REFUSAL_PROVIDER)
            or not _count(row.get("global_count"))
            or not _count(row.get("provider_count"))
        ):
            errors.append("audit refusal record invalid")
            continue
        stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
        refused_by_provider[provider] = refused_by_provider.get(provider, 0) + 1
    if audit.get("stop_reasons") != stop_reasons:
        errors.append("audit stop reasons mismatch")
    if audit.get("status") != (
        "ceiling_reached" if refusals else "within_budget"
    ):
        errors.append("audit status mismatch")
    by_provider = counters.get("by_provider")
    if not isinstance(by_provider, dict):
        errors.append("audit provider counters missing")
    else:
        for provider, row in by_provider.items():
            if not isinstance(row, dict) or provider not in budget.provider_ceilings:
                errors.append("audit provider row invalid")
                continue
            if (
                row.get("ceiling") != budget.provider_ceilings[provider]
                or row.get("reserved") != used_by_provider.get(provider, 0)
                or row.get("refused") != refused_by_provider.get(provider, 0)
                or row.get("outcomes") != outcomes_by_provider.get(provider, {})
            ):
                errors.append("audit per-provider counters mismatch")
        if set(by_provider) != set(budget.provider_ceilings):
            errors.append("audit provider enumeration mismatch")
    controls = audit.get("separate_controls")
    if not isinstance(controls, dict) or (
        controls.get("attempts_are_never_refunded") is not True
    ):
        errors.append("audit no-refund control missing")
    return errors
