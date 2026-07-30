from __future__ import annotations

import pytest

from scripts.prepare_live_acquisition_plan import (
    ACTIVE_ACQUISITION_PROVIDERS,
    DEACTIVATED_ACQUISITION_PROVIDERS,
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


def test_all_expands_only_to_active_providers_before_budget_calculation() -> None:
    plan = build_plan(_constraints(), "all", "3", "50")
    assert REGISTERED_ACQUISITION_PROVIDERS == ACTIVE_ACQUISITION_PROVIDERS
    assert plan["providers"] == list(ACTIVE_ACQUISITION_PROVIDERS)
    assert "wos" not in plan["providers"]
    assert plan["deactivated_providers"] == sorted(DEACTIVATED_ACQUISITION_PROVIDERS)
    assert plan["maximum_total_logical_requests"] == (
        120 * 3 * len(ACTIVE_ACQUISITION_PROVIDERS)
    )


@pytest.mark.parametrize("providers", ["wos", "crossref,wos", "WOS"])
def test_wos_is_rejected_before_health_or_acquisition(providers: str) -> None:
    with pytest.raises(ValueError, match="deactivated provider requested: wos"):
        build_plan(_constraints(), providers, "3", "50")


def test_authoritative_shape_is_preserved() -> None:
    plan = build_plan(_constraints(), "crossref,openalex", "3", "50")
    assert plan["logical_pages"] == 3
    assert plan["rows_per_page"] == 50
    assert plan["max_results_per_query"] == 150
