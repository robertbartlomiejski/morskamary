"""Negative regressions for paid-provider acquisition dispatch."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.export_live_research_records import (
    PaginatedDispatchContractError,
    _search_registry_paginated,
)


def _dispatch(registry: object) -> list[object]:
    return _search_registry_paginated(
        registry,
        query="blue economy skills",
        pages=3,
        rows_per_page=50,
        providers=["scopus"],
        sort_strategy_by_provider={"scopus": "date-desc"},
        time_window={"from_year": 2019, "to_year": 2026},
    )


def test_absent_paginated_method_fails_before_any_search_call() -> None:
    class Registry:
        def __init__(self) -> None:
            self.search_calls = 0

        def search(self, *args: object, **kwargs: object) -> list[object]:
            del args, kwargs
            self.search_calls += 1
            return []

    registry = Registry()
    with pytest.raises(PaginatedDispatchContractError, match="required"):
        _dispatch(registry)

    assert registry.search_calls == 0


def test_uninspectable_paginated_method_fails_before_call() -> None:
    class Registry:
        def __init__(self) -> None:
            self.calls = 0

        def search_paginated(self, *args: object, **kwargs: object) -> list[object]:
            del args, kwargs
            self.calls += 1
            return []

    registry = Registry()
    with patch(
        "scripts.export_live_research_records.inspect.signature",
        side_effect=ValueError("uninspectable"),
    ):
        with pytest.raises(PaginatedDispatchContractError, match="cannot be inspected"):
            _dispatch(registry)

    assert registry.calls == 0


def test_incompatible_paginated_signature_fails_before_call() -> None:
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
        ) -> list[object]:
            del query, pages, rows_per_page, providers
            self.calls += 1
            return []

    registry = Registry()
    with pytest.raises(PaginatedDispatchContractError, match="cannot bind"):
        _dispatch(registry)

    assert registry.calls == 0


def test_non_list_paginated_result_is_a_structural_failure_without_fallback() -> None:
    class Registry:
        def __init__(self) -> None:
            self.paginated_calls = 0
            self.search_calls = 0

        def search_paginated(
            self,
            query: str,
            *,
            pages: int,
            rows_per_page: int,
            providers: list[str],
            sort_strategy_by_provider: dict[str, str],
            time_window: dict[str, int],
        ) -> tuple[object, ...]:
            del query, pages, rows_per_page, providers, sort_strategy_by_provider, time_window
            self.paginated_calls += 1
            return ()

        def search(self, *args: object, **kwargs: object) -> list[object]:
            del args, kwargs
            self.search_calls += 1
            return []

    registry = Registry()
    with pytest.raises(PaginatedDispatchContractError, match="must return a list"):
        _dispatch(registry)

    assert registry.paginated_calls == 1
    assert registry.search_calls == 0


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
            self.calls += 1
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

    assert registry.received["query"] == "port-city competence"
    assert registry.received["pages"] == 2
    assert registry.received["rows_per_page"] == 25
    assert registry.received["providers"] == ["crossref", "openalex"]
    assert registry.received["sort_strategy_by_provider"] == {
        "crossref": "published-desc",
        "openalex": "date-desc",
    }
    assert registry.received["time_window"] == {
        "from_year": 2020,
        "to_year": 2026,
    }
    assert registry.calls == 1
