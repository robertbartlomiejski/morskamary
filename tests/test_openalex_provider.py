"""Contract tests for the OpenAlex scientific source provider."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
from unittest.mock import patch

from scripts.export_live_research_records import (
    _lookup_provider_sort_strategy,
    normalize_provider_name,
)
from src.scientific_sources.openalex import OpenAlexProvider
from src.scientific_sources.source_registry import SourceRegistry


def _work(index: int, *, include_abstract_index: bool = False) -> dict:
    work = {
        "id": f"https://openalex.org/W{1000 + index}",
        "display_name": f"Test Article {index}",
        "publication_year": 2024,
        "publication_date": "2024-01-15",
        "doi": f"https://doi.org/10.5555/test.{index}",
        "authorships": [{"author": {"display_name": f"Author {index}"}}],
        "primary_location": {"source": {"display_name": f"Journal {index}"}},
        "cited_by_count": 10 + index,
        "topics": [{"display_name": "Marine Science"}],
        "keywords": [{"keyword": "maritime"}],
    }
    if include_abstract_index:
        work["abstract_inverted_index"] = {
            "Restricted": [0],
            "abstract": [1],
            "content": [2],
        }
    return work


def _response(
    start: int,
    count: int,
    next_cursor: str = "",
    *,
    include_abstract_index: bool = False,
) -> dict:
    return {
        "meta": {"count": 1000, "next_cursor": next_cursor},
        "results": [
            _work(start + index, include_abstract_index=include_abstract_index)
            for index in range(count)
        ],
    }


def _provider(monkeypatch) -> OpenAlexProvider:
    monkeypatch.setenv("OPENALEX_API_KEY", "test-key")
    return OpenAlexProvider()


def test_capability_requires_configured_openalex_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    provider = OpenAlexProvider()
    assert provider.capability.name == "openalex"
    assert provider.capability.configured is False
    assert provider.capability.requires_secret is True


def test_search_normalizes_work_and_sends_api_key(monkeypatch) -> None:
    provider = _provider(monkeypatch)
    captured: list[str] = []

    def mocked(*, url: str, context_label: str):
        del context_label
        captured.append(url)
        return _response(0, 2), [], None, None

    with patch.object(provider, "_request_json_with_backoff", side_effect=mocked):
        result = provider.search("blue economy", max_results=2)

    assert len(result.records) == 2
    assert result.records[0].provider == "OpenAlex"
    assert result.records[0].doi == "10.5555/test.0"
    assert result.records[0].source_id == "openalex:10.5555/test.0"
    assert "Marine Science" in result.records[0].subject_terms
    assert urllib.parse.parse_qs(
        urllib.parse.urlparse(captured[0]).query
    )["api_key"] == ["test-key"]


def test_paginated_search_uses_distinct_cursor_requests(monkeypatch) -> None:
    provider = _provider(monkeypatch)
    captured: list[str] = []
    responses = iter(
        [
            (_response(0, 2, "cursor-2"), [], None, None),
            (_response(2, 2, "cursor-3"), [], None, None),
            (_response(4, 1), [], None, None),
        ]
    )

    def mocked(*, url: str, context_label: str):
        del context_label
        captured.append(url)
        return next(responses)

    with patch.object(provider, "_request_json_with_backoff", side_effect=mocked):
        result = provider.search_paginated(
            "test query",
            pages=3,
            rows_per_page=2,
            time_window={"from_year": 2019, "to_year": 2026},
        )

    assert len(result.records) == 5
    assert len(result.page_diagnostics) == 3
    cursors = [
        urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["cursor"][0]
        for url in captured
    ]
    assert cursors == ["*", "cursor-2", "cursor-3"]
    assert "from_publication_date%3A2019" in captured[0]


def test_retained_payload_strips_abstract_index(monkeypatch) -> None:
    provider = _provider(monkeypatch)

    def mocked(*, url: str, context_label: str):
        del url, context_label
        return _response(0, 1, include_abstract_index=True), [], None, None

    with patch.object(provider, "_request_json_with_backoff", side_effect=mocked):
        result = provider.search("abstract governance", max_results=2)

    assert result.records[0].abstract_available is True
    assert result.records[0].abstract_stored is False
    assert result.raw_payload is not None
    assert result.raw_payload["payload_kind"] == (
        "redistribution_safe_metadata_envelope"
    )
    retained = json.dumps(result.raw_payload, sort_keys=True)
    assert "abstract_inverted_index" not in retained
    assert "Restricted" not in retained
    safe_result = result.raw_payload["pages"][0]["payload"]["results"][0]
    assert safe_result["abstract_available"] is True


def test_retained_payload_hashes_next_cursor(monkeypatch) -> None:
    provider = _provider(monkeypatch)

    def mocked(*, url: str, context_label: str):
        del url, context_label
        return _response(0, 1, "sensitive-cursor"), [], None, None

    with patch.object(provider, "_request_json_with_backoff", side_effect=mocked):
        result = provider.search_paginated(
            "cursor governance", pages=1, rows_per_page=1
        )

    retained = json.dumps(result.raw_payload, sort_keys=True)
    assert "sensitive-cursor" not in retained
    marker = result.raw_payload["pages"][0]["payload"]["meta"][
        "next_cursor_marker"
    ]
    assert marker.startswith("sha256:")


def test_terminal_page_failure_is_returned_as_provider_error(monkeypatch) -> None:
    provider = _provider(monkeypatch)

    def mocked(*, url: str, context_label: str):
        del url, context_label
        return None, ["retry warning"], "OpenAlex search failed", "rate-limited"

    with patch.object(provider, "_request_json_with_backoff", side_effect=mocked):
        result = provider.search("test", max_results=5)

    assert result.errors == ["OpenAlex search failed"]
    assert result.rate_limit_status == "rate-limited"
    assert result.page_diagnostics[0]["pagination_status"] == "failed"


def test_verify_doi_uses_api_key_and_normalizes_doi(monkeypatch) -> None:
    provider = _provider(monkeypatch)
    captured: list[str] = []

    def mocked(*, url: str, context_label: str):
        del context_label
        captured.append(url)
        return _work(1, include_abstract_index=True), [], None, None

    with patch.object(provider, "_request_json_with_backoff", side_effect=mocked):
        result = provider.verify_doi("10.1234/test")

    assert result.records[0].doi == "10.5555/test.1"
    assert "api_key=test-key" in captured[0]
    assert "abstract_inverted_index" not in json.dumps(result.raw_payload)
    assert result.raw_payload["payload"]["abstract_available"] is True


def test_transient_server_errors_are_retried(monkeypatch) -> None:
    provider = _provider(monkeypatch)
    http_error = urllib.error.HTTPError(
        "https://api.openalex.org/works",
        503,
        "Service Unavailable",
        hdrs=None,
        fp=None,
    )
    calls = iter([http_error, {"results": []}])

    def mocked_request(url: str):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    with patch.object(
        provider, "_request_json", side_effect=mocked_request
    ) as mocked, patch(
        "src.scientific_sources.openalex.time.sleep"
    ) as mocked_sleep:
        payload, warnings, error, rate_limit = (
            provider._request_json_with_backoff(
                url="https://api.openalex.org/works",
                context_label="search",
            )
        )

    assert payload == {"results": []}
    assert error is None
    assert rate_limit is None
    assert mocked.call_count == 2
    mocked_sleep.assert_called_once()
    assert any("http_status=503" in warning for warning in warnings)


def test_registry_and_sort_normalization_include_openalex(monkeypatch) -> None:
    _provider(monkeypatch)
    names = [cap.name for cap in SourceRegistry().list_capabilities()]
    assert "openalex" in names
    assert normalize_provider_name("OpenAlex") == "openalex"
    assert _lookup_provider_sort_strategy(
        {"crossref": "published-desc", "scopus": "date-desc"},
        "openalex",
    ) == "date-desc"
