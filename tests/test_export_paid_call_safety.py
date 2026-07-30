"""Negative regressions for paid-provider acquisition dispatch."""

from __future__ import annotations

import pytest

from scripts.export_live_research_records import _search_registry_paginated


def test_internal_provider_typeerror_is_not_retried_as_legacy_signature() -> None:
    class Registry:
        def __init__(self) -> None:
            self.calls = 0

        def search_paginated(
            self,
            query: str,
            *,
            pages: int,
            rows_per_page: int,
            providers: list[str],
            sort_strategy_by_provider: dict[str, str],
            time_window: dict[str, int],
        ) -> list[object]:
            del (
                query,
                pages,
                rows_per_page,
                providers,
                sort_strategy_by_provider,
                time_window,
            )
            self.calls += 1
            raise TypeError("provider failed after acquisition began")

    registry = Registry()
    with pytest.raises(TypeError, match="after acquisition began"):
        _search_registry_paginated(
            registry,
            query="blue economy skills",
            pages=3,
            rows_per_page=50,
            providers=["scopus"],
            sort_strategy_by_provider={"scopus": "date-desc"},
            time_window={"from_year": 2019, "to_year": 2026},
        )

    assert registry.calls == 1


def test_extended_arguments_are_bound_before_first_call() -> None:
    class Registry:
        def __init__(self) -> None:
            self.received: dict[str, object] = {}

        def search_paginated(
            self,
            query: str,
            *,
            pages: int,
            rows_per_page: int,
            providers: list[str],
            sort_strategy_by_provider: dict[str, str],
            time_window: dict[str, int],
        ) -> list[object]:
            self.received = {
                "query": query,
                "pages": pages,
                "rows_per_page": rows_per_page,
                "providers": providers,
                "sort_strategy_by_provider": sort_strategy_by_provider,
                "time_window": time_window,
            }
            return []

    registry = Registry()
    _search_registry_paginated(
        registry,
        query="port-city competence",
        pages=2,
        rows_per_page=25,
        providers=["crossref", "openalex"],
        sort_strategy_by_provider={
            "crossref": "published-desc",
            "openalex": "date-desc",
        },
        time_window={"from_year": 2020, "to_year": 2026},
    )

    assert registry.received["pages"] == 2
    assert registry.received["rows_per_page"] == 25
    assert registry.received["time_window"] == {
        "from_year": 2020,
        "to_year": 2026,
    }
