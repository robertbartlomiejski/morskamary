"""Executable regressions for scripts.check_budget_ceiling.

These tests exercise the deterministic offline-testable validator directly,
verifying that it fails closed on every specified anomaly and passes only on
a valid budget/log pair.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_budget_ceiling import check_budget_ceiling


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_budget(path: Path, value: object) -> None:
    """Write a minimal api_budget_plan.json with the given ceiling value."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"maximum_total_logical_requests": value}), encoding="utf-8"
    )


def _write_log(path: Path, rows: list[str] | None = None) -> None:
    """Write a query_execution_log.csv with the given data rows.

    ``rows`` is a list of raw ``logical_pages_attempted`` cell values.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["logical_pages_attempted"]
    for r in (rows or []):
        lines.append(str(r))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


class TestBudgetCeilingHappyPath:
    def test_zero_actual_under_ceiling(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        _write_log(log, [])
        actual = check_budget_ceiling(budget, log)
        assert actual == 0

    def test_actual_equals_ceiling_passes(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 3)
        _write_log(log, ["1", "2"])
        actual = check_budget_ceiling(budget, log)
        assert actual == 3

    def test_multiple_rows_summed(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 50)
        _write_log(log, ["10", "20", "5"])
        actual = check_budget_ceiling(budget, log)
        assert actual == 35


# ---------------------------------------------------------------------------
# Over-budget: must exit non-zero
# ---------------------------------------------------------------------------


class TestBudgetCeilingExceeded:
    def test_actual_exceeds_ceiling_exits_nonzero(self, tmp_path):
        """The validator must call sys.exit(1) when actual > ceiling."""
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 5)
        _write_log(log, ["3", "3"])  # actual=6 > ceiling=5
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_single_row_over_ceiling(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 0)
        _write_log(log, ["1"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Missing required column
# ---------------------------------------------------------------------------


class TestMissingLogColumn:
    def test_csv_with_different_header_fails(self, tmp_path):
        """A CSV with no logical_pages_attempted column must fail closed,
        not silently pass as actual=0."""
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        log.parent.mkdir(parents=True, exist_ok=True)
        # Write a CSV with a different header
        log.write_text("other_column\n5\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_empty_csv_no_header_fails(self, tmp_path):
        """A completely empty CSV (no header) must fail closed."""
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Malformed row values
# ---------------------------------------------------------------------------


class TestMalformedRowValues:
    def test_blank_value_fails(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        log.parent.mkdir(parents=True, exist_ok=True)
        # Write a row with an empty-string value (properly quoted so DictReader sees it)
        import csv as _csv
        with log.open("w", newline="", encoding="utf-8") as fh:
            writer = _csv.DictWriter(fh, fieldnames=["logical_pages_attempted"])
            writer.writeheader()
            writer.writerow({"logical_pages_attempted": ""})
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_negative_value_fails(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        _write_log(log, ["-1"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_float_value_fails(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        _write_log(log, ["2.5"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_nonnumeric_value_fails(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        _write_log(log, ["abc"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_scientific_notation_fails(self, tmp_path):
        """Float expressed in scientific notation must be rejected."""
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        _write_log(log, ["1e2"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_plus_prefixed_value_fails(self, tmp_path):
        """'+1' is not a canonical integer token and must be rejected."""
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        _write_log(log, ["+1"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_underscore_separated_value_fails(self, tmp_path):
        """'1_0' is not a canonical integer token and must be rejected."""
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, 100)
        _write_log(log, ["1_0"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Malformed ceiling value
# ---------------------------------------------------------------------------


class TestMalformedCeiling:
    def test_bool_ceiling_fails(self, tmp_path):
        """maximum_total_logical_requests as JSON bool must fail closed."""
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        # JSON true is a bool, not int
        budget.parent.mkdir(parents=True, exist_ok=True)
        budget.write_text(
            json.dumps({"maximum_total_logical_requests": True}), encoding="utf-8"
        )
        _write_log(log, ["1"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_float_ceiling_fails(self, tmp_path):
        """maximum_total_logical_requests as float must fail closed."""
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        budget.parent.mkdir(parents=True, exist_ok=True)
        budget.write_text(
            json.dumps({"maximum_total_logical_requests": 10.5}), encoding="utf-8"
        )
        _write_log(log, ["1"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_string_ceiling_fails(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        budget.parent.mkdir(parents=True, exist_ok=True)
        budget.write_text(
            json.dumps({"maximum_total_logical_requests": "100"}), encoding="utf-8"
        )
        _write_log(log, ["1"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_negative_ceiling_fails(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        _write_budget(budget, -1)
        _write_log(log, ["1"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_missing_ceiling_key_fails(self, tmp_path):
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        budget.parent.mkdir(parents=True, exist_ok=True)
        budget.write_text(json.dumps({"other_key": 5}), encoding="utf-8")
        _write_log(log, ["1"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_non_object_budget_fails(self, tmp_path):
        """Budget JSON that is not an object (list, string, etc.) must fail."""
        budget = tmp_path / "budget.json"
        log = tmp_path / "log.csv"
        budget.parent.mkdir(parents=True, exist_ok=True)
        budget.write_text(json.dumps([100]), encoding="utf-8")
        _write_log(log, ["1"])
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Missing files
# ---------------------------------------------------------------------------


class TestMissingFiles:
    def test_missing_budget_file_fails(self, tmp_path):
        log = tmp_path / "log.csv"
        _write_log(log, ["1"])
        budget = tmp_path / "nonexistent_budget.json"
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0

    def test_missing_log_file_fails(self, tmp_path):
        budget = tmp_path / "budget.json"
        _write_budget(budget, 100)
        log = tmp_path / "nonexistent_log.csv"
        with pytest.raises(SystemExit) as exc_info:
            check_budget_ceiling(budget, log)
        assert exc_info.value.code != 0
