"""Post-acquisition logical-request budget ceiling validator.

Reads ``outputs/governance/api_budget_plan.json`` and
``outputs/research_sources/query_execution_log.csv``, then exits non-zero
when the actual sum of ``logical_pages_attempted`` exceeds
``maximum_total_logical_requests``.

All validation is strict:

- The budget plan must be a JSON object.
- ``maximum_total_logical_requests`` must exist, be exactly ``int`` (not
  ``bool``), and be ``>= 0``.
- The execution-log CSV must have a header row that explicitly contains
  ``logical_pages_attempted``.
- Every data row must supply a canonical non-negative base-10 integer value
  for that column; blank, negative, float-like, bool-like, or otherwise
  malformed values cause an immediate non-zero exit.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Optional

# Canonical non-negative integer token: ASCII digits only, no sign, no underscores.
_CANONICAL_DIGITS_RE = re.compile(r"^[0-9]+$")


def _validate_ceiling(raw: object) -> int:
    """Return the ceiling as a strict ``int``, failing closed on any anomaly."""
    if raw is None:
        print(
            "[ERROR] maximum_total_logical_requests missing from api_budget_plan.json",
            file=sys.stderr,
        )
        sys.exit(1)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(raw, bool):
        print(
            f"[ERROR] maximum_total_logical_requests must be int, got bool: {raw!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(raw, int):
        print(
            f"[ERROR] maximum_total_logical_requests must be int, "
            f"got {type(raw).__name__}: {raw!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    if raw < 0:
        print(
            f"[ERROR] maximum_total_logical_requests must be non-negative, got {raw}",
            file=sys.stderr,
        )
        sys.exit(1)
    return raw


def _parse_row_value(raw: Optional[str], row_num: int) -> int:
    """Parse one ``logical_pages_attempted`` cell, failing closed on any anomaly."""
    if raw is None or raw == "":
        print(
            f"[ERROR] Row {row_num}: logical_pages_attempted is blank or missing",
            file=sys.stderr,
        )
        sys.exit(1)
    # Reject surrounding whitespace — must be a clean integer token.
    if raw != raw.strip():
        print(
            f"[ERROR] Row {row_num}: logical_pages_attempted has surrounding "
            f"whitespace: {raw!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    # Require strictly canonical ASCII digits: no sign, no underscore, no dot, no e.
    if not _CANONICAL_DIGITS_RE.match(raw):
        print(
            f"[ERROR] Row {row_num}: logical_pages_attempted is not a canonical "
            f"non-negative integer (digits only, no sign or separator): {raw!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    return int(raw)


def check_budget_ceiling(
    budget_path: Path,
    log_path: Path,
) -> int:
    """Validate that actual logical requests do not exceed the declared ceiling.

    Returns the actual total on success.  Prints to ``stderr`` and calls
    ``sys.exit(1)`` on any validation failure.
    """
    if not budget_path.exists():
        print(
            f"[ERROR] api_budget_plan.json missing at {budget_path}; "
            "cannot enforce budget ceiling.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not log_path.exists():
        print(
            f"[ERROR] query_execution_log.csv missing at {log_path}; "
            "cannot enforce budget ceiling.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        raw_budget = json.loads(budget_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[ERROR] api_budget_plan.json unreadable: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(raw_budget, dict):
        print("[ERROR] api_budget_plan.json must be a JSON object", file=sys.stderr)
        sys.exit(1)

    maximum = _validate_ceiling(raw_budget.get("maximum_total_logical_requests"))

    try:
        handle = log_path.open(newline="", encoding="utf-8")
    except OSError as exc:
        print(
            f"[ERROR] query_execution_log.csv unreadable: {exc}", file=sys.stderr
        )
        sys.exit(1)

    with handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            print(
                "[ERROR] query_execution_log.csv has no header row; "
                "logical_pages_attempted column required.",
                file=sys.stderr,
            )
            sys.exit(1)
        if "logical_pages_attempted" not in fieldnames:
            print(
                "[ERROR] query_execution_log.csv is missing required column "
                f"'logical_pages_attempted'. Present columns: {list(fieldnames)}",
                file=sys.stderr,
            )
            sys.exit(1)
        actual = 0
        for row_num, row in enumerate(reader, start=2):
            raw = row.get("logical_pages_attempted")
            actual += _parse_row_value(raw, row_num)

    print(f"[INFO] Logical requests: actual={actual} maximum={maximum}")
    if actual > maximum:
        print(
            f"[ERROR] Budget exceeded: {actual} logical requests > ceiling {maximum}. "
            "Aborting before downstream analysis.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("[OK] Budget ceiling respected.")
    return actual


if __name__ == "__main__":
    _budget = Path("outputs/governance/api_budget_plan.json")
    _log = Path("outputs/research_sources/query_execution_log.csv")
    check_budget_ceiling(_budget, _log)
