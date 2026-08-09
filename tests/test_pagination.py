from __future__ import annotations

"""Tests for genuine multi-page pagination."""

from unittest.mock import patch

from src.scientific_sources.base import BaseProvider
from src.scientific_sources.crossref import CrossrefProvider
from src.scientific_sources.elsevier_scopus import ElsevierScopusProvider
from src.scientific_sources.models import LiteratureRecord, ProviderResult, SourceCapability


def _mock_record(
    title: str = "Test", doi: str = "10.1234/test", provider: str = "Crossref"
) -> LiteratureRecord:
    return LiteratureRecord(
        title=title,
        authors="Author",
        year="2024",
        doi=doi,
        source_id=f"{provider.lower()}:{doi}",
        provider=provider,
    )


class TestCrossrefPagination:
    def test_three_pages_make_three_distinct_requests(self) -> None:
        provider = CrossrefProvider()
        offsets_seen: list[int] = []

        def mock_backoff(*, url: str, context_label: str, jitter_seed: str):
            del context_label, jitter_seed
            import urllib.parse

            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            offset = int(params.get("offset", [0])[0])
            offsets_seen.append(offset)
            items = [
                {"title": [f"Record {offset + index}"], "DOI": f"10.1/{offset + index}"}
                for index in range(50)
            ]
            return {"message": {"items": items}}, [], None, 1

        with patch.object(
            provider, "_request_json_with_backoff", side_effect=mock_backoff
        ):
            result, diagnostics = provider.search_paginated(
                "test query", logical_pages=3, rows_per_page=50
            )

        assert len(result.records) == 150
        assert result.physical_request_count == 3
        assert offsets_seen == [0, 50, 100]
        assert len(diagnostics) == 3
        for index, diagnostic in enumerate(diagnostics):
            assert diagnostic["logical_page"] == index + 1
            assert diagnostic["offset"] == index * 50

    def test_single_page_fallback_works(self) -> None:
        provider = CrossrefProvider()

        def mock_backoff(*, url: str, context_label: str, jitter_seed: str):
            del url, context_label, jitter_seed
            return (
                {"message": {"items": [{"title": ["Test"], "DOI": "10.1/1"}]}},
                [],
                None,
                1,
            )

        with patch.object(
            provider, "_request_json_with_backoff", side_effect=mock_backoff
        ):
            result, diagnostics = provider.search_paginated(
                "test", logical_pages=1, rows_per_page=50
            )

        assert len(result.records) == 1
        assert result.physical_request_count == 1
        assert len(diagnostics) == 1
        assert diagnostics[0]["logical_page"] == 1


class TestScopusPagination:
    def test_logical_page_composes_physical_requests(self) -> None:
        provider = ElsevierScopusProvider()
        provider._api_key = "test-key"
        start_indices: list[int] = []

        def mock_json(url: str):
            import urllib.parse

            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            start = int(params.get("start", [0])[0])
            start_indices.append(start)
            entries = [
                {"dc:title": f"Record {start + index}", "prism:doi": f"10.2/{start + index}"}
                for index in range(25)
            ]
            return {"search-results": {"entry": entries}}

        with patch.object(provider, "_request_json", side_effect=mock_json):
            result, diagnostics = provider.search_paginated(
                "test query", logical_pages=1, rows_per_page=50
            )

        assert len(result.records) == 50
        assert len(start_indices) == 2
        assert start_indices == [0, 25]
        assert result.physical_request_count == 2
        assert diagnostics[0]["physical_requests"] == 2
        assert diagnostics[0]["returned_rows"] == 50

    def test_three_pages_with_scopus(self) -> None:
        provider = ElsevierScopusProvider()
        provider._api_key = "test-key"
        call_count = 0

        def mock_json(url: str):
            del url
            nonlocal call_count
            call_count += 1
            entries = [
                {"dc:title": f"Record {call_count}_{index}", "prism:doi": f"10.2/{call_count}_{index}"}
                for index in range(25)
            ]
            return {"search-results": {"entry": entries}}

        with patch.object(provider, "_request_json", side_effect=mock_json):
            result, diagnostics = provider.search_paginated(
                "test query", logical_pages=3, rows_per_page=50
            )

        assert call_count == 6
        assert len(diagnostics) == 3
        assert len(result.records) == 150
        assert result.physical_request_count == 6


class TestPaginationSamplingStatus:
    def test_missing_pagination_cannot_satisfy_3page_protocol(self) -> None:
        class DummyProvider(BaseProvider):
            @property
            def capability(self) -> SourceCapability:
                return SourceCapability(
                    name="dummy",
                    provider="Dummy",
                    requires_secret=False,
                    configured=True,
                    live_test_allowed=False,
                    allowed_metadata_fields=[],
                    licence_note="test",
                )

            def search(self, query: str, max_results: int = 5) -> ProviderResult:
                del query, max_results
                return ProviderResult(records=[_mock_record(provider="Dummy")])

            def verify_doi(self, doi: str) -> ProviderResult:
                del doi
                return ProviderResult()

        provider = DummyProvider()
        _, diagnostics = provider.search_paginated(
            "test", logical_pages=3, rows_per_page=50
        )
        assert diagnostics[0]["pagination_method"] == "single_request_fallback"
