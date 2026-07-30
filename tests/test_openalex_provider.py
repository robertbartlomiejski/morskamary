"""Tests for the OpenAlex scientific source provider."""

from __future__ import annotations

from unittest.mock import patch

from scripts.export_live_research_records import (
    _lookup_provider_sort_strategy,
    normalize_provider_name,
)
from src.scientific_sources.openalex import OpenAlexProvider
from src.scientific_sources.source_registry import SourceRegistry


def _mock_works_response(n: int = 5, page: int = 1) -> dict:
    """Build a mock OpenAlex works search response."""
    works = []
    for i in range(n):
        offset = (page - 1) * n + i
        works.append(
            {
                "id": f"https://openalex.org/W{1000 + offset}",
                "display_name": f"Test Article {offset}",
                "publication_year": 2024,
                "publication_date": "2024-01-15",
                "doi": f"https://doi.org/10.5555/test.{offset}",
                "authorships": [
                    {"author": {"display_name": f"Author {offset}"}},
                ],
                "primary_location": {
                    "source": {"display_name": f"Journal {offset}"},
                },
                "cited_by_count": 10 + offset,
                "topics": [
                    {"display_name": "Marine Science"},
                    {"display_name": "Blue Economy"},
                ],
                "keywords": [
                    {"keyword": "maritime"},
                ],
            }
        )
    return {
        "meta": {"count": 100, "page": page, "per_page": n},
        "results": works,
    }


class TestOpenAlexProviderCapability:
    def test_provider_name_is_openalex(self) -> None:
        provider = OpenAlexProvider()
        assert provider.capability.name == "openalex"

    def test_always_configured(self) -> None:
        provider = OpenAlexProvider()
        assert provider.capability.configured is True

    def test_does_not_require_secret(self) -> None:
        provider = OpenAlexProvider()
        assert provider.capability.requires_secret is False

    def test_licence_note_mentions_aggregator(self) -> None:
        provider = OpenAlexProvider()
        assert "aggregator" in provider.capability.licence_note.lower()


class TestOpenAlexSearch:
    def test_search_parses_works(self) -> None:
        provider = OpenAlexProvider()
        response = _mock_works_response(3)

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list[str], None]:
            del url, context_label
            return response, [], None

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            result = provider.search("blue economy", max_results=3)

        assert len(result.records) == 3
        assert result.records[0].provider == "OpenAlex"
        assert result.records[0].doi == "10.5555/test.0"
        assert result.records[0].source_id.startswith("openalex:")
        assert "Author 0" in result.records[0].authors

    def test_doi_prefix_stripped(self) -> None:
        provider = OpenAlexProvider()
        response = _mock_works_response(1)

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list[str], None]:
            del url, context_label
            return response, [], None

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            result = provider.search("test", max_results=1)

        assert not result.records[0].doi.startswith("https://")

    def test_subject_terms_populated(self) -> None:
        provider = OpenAlexProvider()
        response = _mock_works_response(1)

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list[str], None]:
            del url, context_label
            return response, [], None

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            result = provider.search("test", max_results=1)

        assert "Marine Science" in result.records[0].subject_terms
        assert "maritime" in result.records[0].subject_terms

    def test_error_returns_structured_result(self) -> None:
        provider = OpenAlexProvider()

        def mock_backoff(
            *,
            url: str,
            context_label: str,
        ) -> tuple[None, list[str], str]:
            del url, context_label
            return None, ["retry warning"], "OpenAlex search failed (terminal_status=http_500)"

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            result = provider.search("test", max_results=5)

        assert result.errors
        assert result.records == []


class TestOpenAlexPagination:
    def test_three_pages_use_distinct_page_params(self) -> None:
        provider = OpenAlexProvider()
        pages_requested: list[int] = []

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list[str], None]:
            import urllib.parse

            del context_label
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            page = int(params.get("page", [1])[0])
            pages_requested.append(page)
            return _mock_works_response(50, page=page), [], None

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            result, diagnostics = provider.search_paginated(
                "test query",
                logical_pages=3,
                rows_per_page=50,
            )

        assert pages_requested == [1, 2, 3]
        assert len(diagnostics) == 3
        assert all(d["pagination_method"] == "openalex_page" for d in diagnostics)
        assert len(result.records) == 150

    def test_stops_when_results_exhausted(self) -> None:
        provider = OpenAlexProvider()
        call_count = 0

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list[str], None]:
            nonlocal call_count
            del url, context_label
            call_count += 1
            if call_count == 1:
                return _mock_works_response(50), [], None
            return _mock_works_response(10), [], None

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            _, diagnostics = provider.search_paginated(
                "test",
                logical_pages=3,
                rows_per_page=50,
            )

        assert call_count == 2
        assert len(diagnostics) == 2

    def test_time_window_filter_included(self) -> None:
        provider = OpenAlexProvider()
        captured_url: list[str] = []

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list[str], None]:
            del context_label
            captured_url.append(url)
            return _mock_works_response(5), [], None

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            provider.search_paginated(
                "test",
                logical_pages=1,
                rows_per_page=50,
                time_window={"from_year": 2019, "to_year": 2026},
            )

        assert "publication_year" in captured_url[0]
        assert "2019" in captured_url[0]


class TestOpenAlexVerifyDoi:
    def test_verify_doi_returns_record(self) -> None:
        provider = OpenAlexProvider()
        work = {
            "id": "https://openalex.org/W123",
            "display_name": "Test Article",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1234/test",
            "authorships": [{"author": {"display_name": "Test Author"}}],
            "primary_location": {"source": {"display_name": "Test Journal"}},
            "cited_by_count": 5,
            "topics": [],
            "keywords": [],
        }

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list[str], None]:
            del url, context_label
            return work, [], None

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            result = provider.verify_doi("10.1234/test")

        assert len(result.records) == 1
        assert result.records[0].doi == "10.1234/test"


class TestOpenAlexAbstractRetentionContract:
    """Regression tests for PR-215: abstract_inverted_index must never be
    persisted in the provider's raw_payload."""

    def test_search_raw_payload_excludes_abstract_inverted_index(self) -> None:
        provider = OpenAlexProvider()
        response = _mock_works_response(2)
        response["results"][0]["abstract_inverted_index"] = {"the": [0], "sea": [1]}

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list[str], None]:
            del url, context_label
            return response, [], None

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            result = provider.search("blue economy", max_results=2)

        assert "abstract_inverted_index" not in result.raw_payload["results"][0]
        assert "abstract_inverted_index" not in result.raw_payload["results"][1]
        # Non-abstract fields must remain intact.
        assert result.raw_payload["results"][0]["display_name"] == "Test Article 0"

    def test_verify_doi_raw_payload_excludes_abstract_inverted_index(self) -> None:
        provider = OpenAlexProvider()
        work = {
            "id": "https://openalex.org/W123",
            "display_name": "Test Article",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1234/test",
            "authorships": [{"author": {"display_name": "Test Author"}}],
            "primary_location": {"source": {"display_name": "Test Journal"}},
            "cited_by_count": 5,
            "topics": [],
            "keywords": [],
            "abstract_inverted_index": {"ocean": [0], "science": [1]},
        }

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list[str], None]:
            del url, context_label
            return work, [], None

        with patch.object(
            provider,
            "_request_json_with_backoff",
            side_effect=mock_backoff,
        ):
            result = provider.verify_doi("10.1234/test")

        assert "abstract_inverted_index" not in result.raw_payload
        assert result.raw_payload["display_name"] == "Test Article"


class TestOpenAlexIntegration:
    def test_registry_lists_openalex_provider(self) -> None:
        registry = SourceRegistry()
        names = [cap.name for cap in registry.list_capabilities()]
        assert "openalex" in names

    def test_provider_name_normalization_handles_openalex(self) -> None:
        assert normalize_provider_name("OpenAlex") == "openalex"

    def test_sort_lookup_falls_back_to_wos_for_openalex(self) -> None:
        strategies = {
            "crossref": "published-desc",
            "scopus": "date-desc",
            "wos": "date-desc",
        }
        assert _lookup_provider_sort_strategy(strategies, "openalex") == "date-desc"
