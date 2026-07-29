from __future__ import annotations

import pytest

from scripts.prepare_live_acquisition_plan import (
    REGISTERED_ACQUISITION_PROVIDERS,
    build_plan,
)


def _constraints(pages: int = 3, rows: int = 50) -> dict[str, object]:
    return {
        "queries": [
            {"sampling_strategy": {"pages": pages, "rows_per_page": rows}}
            for _ in range(120)
        ]
    }


@pytest.mark.parametrize(("pages", "rows"), [("2", "25"), ("4", "50"), ("3", "25")])
def test_mismatched_sampling_shape_fails_before_acquisition(pages: str, rows: str) -> None:
    with pytest.raises(ValueError, match="sampling shape"):
        build_plan(_constraints(), "crossref", pages, rows)


def test_all_expands_before_budget_calculation() -> None:
    plan = build_plan(_constraints(), "all", "3", "50")
    assert plan["providers"] == list(REGISTERED_ACQUISITION_PROVIDERS)
    assert plan["maximum_total_logical_requests"] == (
        120 * 3 * len(REGISTERED_ACQUISITION_PROVIDERS)
    )


def test_authoritative_shape_is_preserved() -> None:
    plan = build_plan(_constraints(), "crossref,openalex", "3", "50")
    assert plan["logical_pages"] == 3
    assert plan["rows_per_page"] == 50
    assert plan["max_results_per_query"] == 150
