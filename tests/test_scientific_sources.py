"""
Tests for the src/scientific_sources provider package.

Covers:
- LiteratureRecord / SourceCapability / ProviderResult models
- CrossrefProvider (mocked HTTP)
- Stub providers returning "not configured" when keys absent
- SourceRegistry aggregation and deduplication
- provenance helpers
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from src.scientific_sources.models import (
    LiteratureRecord,
    ProviderResult,
    SourceEvidence,
)
from src.scientific_sources.crossref import CrossrefProvider
from src.scientific_sources.elsevier_scopus import ElsevierScopusProvider
from src.scientific_sources.web_of_science import WebOfScienceProvider
from src.scientific_sources.scival import SciValProvider
from src.scientific_sources.google_drive import GoogleDriveProvider
from src.scientific_sources.microsoft_graph import MicrosoftGraphProvider
from src.scientific_sources.source_registry import SourceRegistry
from src.scientific_sources.provenance import (
    compute_record_hash,
    build_provenance_summary,
    export_provenance_json,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_record(**kwargs) -> LiteratureRecord:
    """Return a minimal LiteratureRecord with overridable fields."""
    defaults: dict[str, Any] = dict(
        title="Blue Economy Governance",
        authors="Ada Lovelace",
        year="2024",
        doi="10.1234/blue",
        source_id="crossref:10.1234/blue",
        provider="Crossref",
        journal="Ocean Studies",
        url="https://example.org/paper",
        abstract_available=False,
        abstract_stored=False,
        citation_count=None,
        subject_terms=[],
    )
    defaults.update(kwargs)
    return LiteratureRecord(**defaults)


class _DummyResponse:
    """Minimal context-manager mimicking urllib response."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


_CROSSREF_PAYLOAD = {
    "message": {
        "items": [
            {
                "title": ["Blue Economy Governance"],
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "URL": "https://example.org/paper",
                "DOI": "10.1234/blue",
                "published": {"date-parts": [[2024, 1, 1]]},
                "container-title": ["Ocean Studies"],
            }
        ]
    }
}


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestLiteratureRecord:
    def test_to_dict_round_trip(self):
        rec = _make_record()
        d = rec.to_dict()
        assert d["title"] == "Blue Economy Governance"
        assert d["provider"] == "Crossref"
        assert d["doi"] == "10.1234/blue"
        assert isinstance(d["subject_terms"], list)
        assert "abstract" not in d
        assert "abstract_available" not in d
        assert "abstract_stored" not in d

    def test_to_dict_can_include_restricted_fields_explicitly(self):
        rec = _make_record(
            abstract="Licensed internal abstract",
            abstract_available=True,
            abstract_stored=True,
            citation_count=7,
        )

        d = rec.to_dict(include_restricted=True)

        assert d["abstract"] == "Licensed internal abstract"
        assert d["abstract_available"] is True
        assert d["abstract_stored"] is True
        assert d["citation_count"] == 7

    def test_default_retrieval_timestamp_is_set(self):
        rec = _make_record()
        assert rec.retrieval_timestamp  # non-empty


class TestProviderResult:
    def test_is_empty_when_no_records(self):
        result = ProviderResult(warnings=["not configured"])
        assert result.is_empty

    def test_is_not_empty_when_records_present(self):
        result = ProviderResult(records=[_make_record()])
        assert not result.is_empty

    def test_to_dict_contains_expected_keys(self):
        result = ProviderResult(
            records=[_make_record()],
            errors=["err1"],
            warnings=["warn1"],
        )
        d = result.to_dict()
        assert "records" in d
        assert "errors" in d
        assert "warnings" in d
        assert d["errors"] == ["err1"]


class TestSourceEvidence:
    def test_to_dict(self):
        ev = SourceEvidence(
            record_id="crossref:10.1234/blue",
            source_provider="Crossref",
            retrieval_mode="live",
            query="blue economy",
            api_endpoint_label="crossref/works",
            timestamp="2024-01-01T00:00:00Z",
            confidence_score=0.9,
            provenance_hash="abc123",
        )
        d = ev.to_dict()
        assert d["confidence_score"] == 0.9
        assert d["retrieval_mode"] == "live"


# ---------------------------------------------------------------------------
# CrossrefProvider tests
# ---------------------------------------------------------------------------


class TestCrossrefProvider:
    def test_capability_is_always_configured(self):
        provider = CrossrefProvider()
        cap = provider.capability
        assert cap.name == "crossref"
        assert cap.configured is True
        assert cap.requires_secret is False

    def test_search_parses_results(self, monkeypatch):
        def fake_urlopen(req, timeout=10):
            return _DummyResponse(_CROSSREF_PAYLOAD)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = CrossrefProvider()
        result = provider.search("blue economy", max_results=1)

        assert not result.is_empty
        assert len(result.records) == 1
        rec = result.records[0]
        assert rec.title == "Blue Economy Governance"
        assert rec.authors == "Ada Lovelace"
        assert rec.doi == "10.1234/blue"
        assert rec.provider == "Crossref"
        assert len(result.provenance) == 1

    def test_search_does_not_store_crossref_abstract_text(self, monkeypatch):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Blue Economy Governance"],
                        "author": [{"given": "Ada", "family": "Lovelace"}],
                        "URL": "https://example.org/paper",
                        "DOI": "10.1234/blue",
                        "published": {"date-parts": [[2024, 1, 1]]},
                        "container-title": ["Ocean Studies"],
                        "abstract": "<jats:p>Publisher abstract text</jats:p>",
                    }
                ]
            }
        }

        def fake_urlopen(req, timeout=10):
            return _DummyResponse(payload)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = CrossrefProvider()
        result = provider.search("blue economy", max_results=1)

        rec = result.records[0]
        assert rec.abstract == ""
        assert rec.abstract_available is False
        assert rec.abstract_stored is False

    def test_search_does_not_request_crossref_abstract_field(self, monkeypatch):
        captured_url = {}

        def fake_urlopen(req, timeout=10):
            captured_url["url"] = req.full_url
            return _DummyResponse(_CROSSREF_PAYLOAD)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = CrossrefProvider()
        provider.search("blue economy", max_results=1)

        assert "&select=" in captured_url["url"]
        assert (
            "abstract"
            not in captured_url["url"].split("&select=", 1)[1].split("&rows=", 1)[0]
        )

    def test_search_returns_error_on_network_failure(self, monkeypatch):
        def fake_urlopen(req, timeout=10):
            raise OSError("network down")

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = CrossrefProvider()
        result = provider.search("anything")

        assert result.is_empty
        assert result.errors
        assert "Crossref search error" in result.errors[0]

    def test_verify_doi_parses_result(self, monkeypatch):
        doi_payload = {
            "message": {
                "title": ["Blue Economy Governance"],
                "author": [{"given": "Ada", "family": "Lovelace"}],
                "URL": "https://example.org/paper",
                "DOI": "10.1234/blue",
                "published": {"date-parts": [[2024, 1, 1]]},
                "container-title": ["Ocean Studies"],
            }
        }

        def fake_urlopen(req, timeout=10):
            return _DummyResponse(doi_payload)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = CrossrefProvider()
        result = provider.verify_doi("10.1234/blue")

        assert not result.is_empty
        assert result.records[0].doi == "10.1234/blue"

    def test_mailto_env_var_included_in_user_agent(self, monkeypatch):
        monkeypatch.setenv("CROSSREF_MAILTO", "test@example.edu")
        provider = CrossrefProvider()
        ua = provider._user_agent()
        assert "test@example.edu" in ua

    def test_live_test_allowed_false_by_default(self):
        provider = CrossrefProvider()
        assert provider.capability.live_test_allowed is False

    def test_live_test_allowed_true_when_env_set(self, monkeypatch):
        monkeypatch.setenv("LIVE_RESEARCH_API_TESTS", "true")
        provider = CrossrefProvider()
        assert provider.capability.live_test_allowed is True


# ---------------------------------------------------------------------------
# Stub provider tests (not-configured behavior)
# ---------------------------------------------------------------------------


class TestElsevierScopusProvider:
    def test_not_configured_without_key(self, monkeypatch):
        monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
        monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
        provider = ElsevierScopusProvider()
        assert provider.capability.configured is False
        result = provider.search("blue economy")
        assert result.is_empty
        assert result.warnings

    def test_configured_with_elsevier_key(self, monkeypatch):
        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")
        provider = ElsevierScopusProvider()
        assert provider.capability.configured is True

    def test_configured_with_scopus_key(self, monkeypatch):
        monkeypatch.setenv("SCOPUS_API_KEY", "testkey")
        provider = ElsevierScopusProvider()
        assert provider.capability.configured is True

    def test_verify_doi_not_configured(self, monkeypatch):
        monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
        monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
        provider = ElsevierScopusProvider()
        result = provider.verify_doi("10.1234/x")
        assert result.is_empty
        assert result.warnings

    def test_headers_include_api_key(self, monkeypatch):
        monkeypatch.setenv("ELSEVIER_API_KEY", "abc")
        provider = ElsevierScopusProvider()
        assert provider._headers() == {
            "X-ELS-APIKey": "abc",
            "Accept": "application/json",
        }

    def test_parse_helpers_cover_fallback_branches(self):
        provider = ElsevierScopusProvider()
        assert (
            provider._parse_year(
                {"prism:coverDate": "N/A", "prism:coverDisplayDate": "May 2022"}
            )
            == "2022"
        )
        assert provider._parse_subject_terms({"authkeywords": "a|b|c"}) == [
            "a",
            "b",
            "c",
        ]
        assert provider._parse_subject_terms({"authkeywords": "a;b"}) == ["a", "b"]
        assert provider._parse_subject_terms({"authkeywords": "single"}) == ["single"]
        assert (
            provider._parse_authors({"author": [{"preferred-name": "Jane Doe"}]})
            == "Jane Doe"
        )
        assert provider._parse_authors({"author": []}) == "Unknown"

    def test_parse_entry_fallback_source_id_and_invalid_citation(self):
        provider = ElsevierScopusProvider()
        record = provider._parse_entry(
            {
                "dc:title": "Blue ports",
                "author": [{"authname": "A B"}],
                "prism:coverDate": "",
                "prism:doi": "",
                "prism:publicationName": "Journal",
                "prism:url": "",
                "citedby-count": "not-int",
                "authkeywords": "blue | economy",
                "eid": "",
            },
            "query",
        )
        assert record.source_id.startswith("scopus:Blue ports")
        assert record.citation_count is None
        assert record.subject_terms == ["blue", "economy"]

    def test_http_error_result_branches(self):
        rate_limited = ElsevierScopusProvider._http_error_result(
            "search",
            urllib.error.HTTPError("https://x", 429, "too many", None, None),
        )
        assert rate_limited.rate_limit_status == "rate-limited"
        unauthorized = ElsevierScopusProvider._http_error_result(
            "search",
            urllib.error.HTTPError("https://x", 401, "unauthorized", None, None),
        )
        assert "unauthorized" in unauthorized.errors[0].lower()
        generic = ElsevierScopusProvider._http_error_result(
            "search",
            urllib.error.HTTPError("https://x", 500, "server", None, None),
        )
        assert "failed (http 500)" in generic.errors[0].lower()

    def test_search_handles_non_list_entry_payload(self, monkeypatch):
        monkeypatch.setenv("ELSEVIER_API_KEY", "abc")
        provider = ElsevierScopusProvider()
        monkeypatch.setattr(
            provider,
            "_request_json",
            lambda _url: {"search-results": {"entry": {"not": "a-list"}}},
        )
        result = provider.search("blue economy")
        assert result.records == []


class TestWebOfScienceProvider:
    def test_not_configured_without_key(self, monkeypatch):
        monkeypatch.delenv("WOS_API_KEY", raising=False)
        provider = WebOfScienceProvider()
        assert provider.capability.configured is False
        result = provider.search("maritime transport")
        assert result.is_empty
        assert result.warnings

    def test_configured_with_key(self, monkeypatch):
        monkeypatch.setenv("WOS_API_KEY", "woskey")
        provider = WebOfScienceProvider()
        assert provider.capability.configured is True

    def test_headers_include_api_key(self, monkeypatch):
        monkeypatch.setenv("WOS_API_KEY", "woskey")
        provider = WebOfScienceProvider()
        assert provider._headers() == {
            "X-ApiKey": "woskey",
            "Accept": "application/json",
        }

    def test_extract_subject_terms_and_citations_branches(self):
        provider = WebOfScienceProvider()
        terms = provider._extract_subject_terms(
            {
                "keywords": {
                    "authorKeywords": ["Ports", "Ports"],
                    "keywordsPlus": "Governance",
                    "keyword": "Ocean",
                }
            }
        )
        assert terms == ["Ports", "Governance", "Ocean"]
        assert provider._extract_subject_terms({"keywords": "invalid"}) == []

        assert provider._extract_citation_count({"timesCited": 7}) == 7
        assert provider._extract_citation_count({"citations": [{"count": "x"}]}) is None

    def test_parse_hit_fallback_source_id_and_author_branches(self):
        provider = WebOfScienceProvider()
        record = provider._parse_hit(
            {
                "title": "",
                "authors": {"authors": [{"fullName": "Legacy Author"}]},
                "source": {},
                "identifiers": {"doi": ""},
                "links": {},
                "citations": [],
                "keywords": {"authorKeywords": ["blue"], "keywordsPlus": ["ports"]},
                "uid": "",
            },
            "query",
        )
        assert record.title == "Unknown Title"
        assert record.authors == "Legacy Author"
        assert record.source_id.startswith("wos:Unknown Title")
        assert record.subject_terms == ["blue", "ports"]

    def test_parse_hits_filters_non_dict_items(self):
        provider = WebOfScienceProvider()
        records = provider._parse_hits([{"title": "T", "source": {}}, "x"], "q")
        assert len(records) == 1

    def test_http_error_result_branches(self):
        rate_limited = WebOfScienceProvider._http_error_result(
            "search",
            urllib.error.HTTPError("https://x", 429, "too many", None, None),
        )
        assert rate_limited.rate_limit_status == "rate-limited"
        unauthorized = WebOfScienceProvider._http_error_result(
            "search",
            urllib.error.HTTPError("https://x", 403, "forbidden", None, None),
        )
        assert "unauthorized" in unauthorized.errors[0].lower()
        generic = WebOfScienceProvider._http_error_result(
            "search",
            urllib.error.HTTPError("https://x", 500, "server", None, None),
        )
        assert "failed (http 500)" in generic.errors[0].lower()

    def test_search_handles_non_list_hits_payload(self, monkeypatch):
        monkeypatch.setenv("WOS_API_KEY", "woskey")
        provider = WebOfScienceProvider()
        monkeypatch.setattr(
            provider, "_request_json", lambda _url: {"hits": {"not": "list"}}
        )
        result = provider.search("blue economy")
        assert result.records == []


class TestSciValProvider:
    def test_not_configured_without_key(self, monkeypatch):
        monkeypatch.delenv("SCIVAL_API_KEY", raising=False)
        provider = SciValProvider()
        assert provider.capability.configured is False
        result = provider.search("ocean governance")
        assert result.is_empty
        assert result.warnings

    def test_configured_with_key(self, monkeypatch):
        monkeypatch.setenv("SCIVAL_API_KEY", "scivalkey")
        provider = SciValProvider()
        assert provider.capability.configured is True
        assert "url" in provider.capability.allowed_metadata_fields


class TestGoogleDriveProvider:
    def test_not_configured_without_credentials(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_DRIVE_OAUTH_CREDENTIALS", raising=False)
        provider = GoogleDriveProvider()
        assert provider.capability.configured is False
        result = provider.search("blue economy")
        assert result.is_empty
        assert result.warnings

    def test_doi_verification_not_supported(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_DRIVE_OAUTH_CREDENTIALS", raising=False)
        provider = GoogleDriveProvider()
        result = provider.verify_doi("10.1234/x")
        assert result.warnings


class TestMicrosoftGraphProvider:
    def test_not_configured_without_credentials(self, monkeypatch):
        monkeypatch.delenv("MICROSOFT_TENANT_ID", raising=False)
        monkeypatch.delenv("MICROSOFT_CLIENT_ID", raising=False)
        monkeypatch.delenv("MICROSOFT_CLIENT_SECRET", raising=False)
        provider = MicrosoftGraphProvider()
        assert provider.capability.configured is False
        result = provider.search("ports")
        assert result.is_empty
        assert result.warnings

    def test_configured_when_all_env_vars_set(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_TENANT_ID", "tid")
        monkeypatch.setenv("MICROSOFT_CLIENT_ID", "cid")
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "csecret")
        provider = MicrosoftGraphProvider()
        assert provider.capability.configured is True


# ---------------------------------------------------------------------------
# SourceRegistry tests
# ---------------------------------------------------------------------------


class TestSourceRegistry:
    def test_list_capabilities_returns_all_providers(self):
        registry = SourceRegistry()
        caps = registry.list_capabilities()
        names = {c.name for c in caps}
        assert "crossref" in names
        assert "scopus" in names
        assert "wos" in names
        assert "scival" in names
        assert "google_drive" in names
        assert "microsoft_graph" in names

    def test_capabilities_dict_is_serialisable(self):
        registry = SourceRegistry()
        d = registry.capabilities_dict()
        assert "crossref" in d
        assert d["crossref"]["configured"] is True

    def test_search_with_provider_filter(self, monkeypatch):
        def fake_urlopen(req, timeout=10):
            return _DummyResponse(_CROSSREF_PAYLOAD)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        registry = SourceRegistry()
        results = registry.search("blue", max_results=1, providers=["crossref"])
        assert len(results) == 1
        assert results[0].records[0].provider == "Crossref"

    def test_flat_records_deduplicates_by_doi(self):
        rec1 = _make_record(doi="10.1234/x", source_id="a")
        rec2 = _make_record(doi="10.1234/x", source_id="b")
        r1 = ProviderResult(records=[rec1])
        r2 = ProviderResult(records=[rec2])
        registry = SourceRegistry()
        flat = registry.flat_records([r1, r2])
        assert len(flat) == 1

    def test_flat_records_keeps_distinct_dois(self):
        rec1 = _make_record(doi="10.1234/a", source_id="a")
        rec2 = _make_record(doi="10.1234/b", source_id="b")
        r1 = ProviderResult(records=[rec1])
        r2 = ProviderResult(records=[rec2])
        registry = SourceRegistry()
        flat = registry.flat_records([r1, r2])
        assert len(flat) == 2

    def test_verify_doi_returns_list(self, monkeypatch):
        doi_payload = {
            "message": {
                "title": ["Test Title"],
                "author": [{"given": "J", "family": "Smith"}],
                "URL": "https://x.org",
                "DOI": "10.x/y",
                "published": {"date-parts": [[2023]]},
                "container-title": ["Journal"],
            }
        }

        def fake_urlopen(req, timeout=10):
            return _DummyResponse(doi_payload)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        registry = SourceRegistry()
        results = registry.verify_doi("10.x/y")
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Provenance tests
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_compute_record_hash_is_deterministic(self):
        rec = _make_record()
        h1 = compute_record_hash(rec)
        h2 = compute_record_hash(rec)
        assert h1 == h2
        assert len(h1) == 16

    def test_compute_record_hash_differs_for_different_records(self):
        rec1 = _make_record(doi="10.1/a")
        rec2 = _make_record(doi="10.1/b")
        assert compute_record_hash(rec1) != compute_record_hash(rec2)

    def test_build_provenance_summary_counts_correctly(self):
        results = [
            ProviderResult(records=[_make_record(provider="Crossref")]),
            ProviderResult(
                records=[_make_record(doi="10.2/x", source_id="b", provider="Scopus")]
            ),
            ProviderResult(warnings=["not configured"]),
        ]
        summary = build_provenance_summary(results)
        assert summary["total_records"] == 2
        assert summary["provider_counts"]["Crossref"] == 1
        assert summary["provider_counts"]["Scopus"] == 1
        assert "not configured" in summary["warnings"]

    def test_export_provenance_json_is_valid_json(self):
        results = [ProviderResult(records=[_make_record()])]
        json_str = export_provenance_json(results)
        parsed = json.loads(json_str)
        assert "total_records" in parsed
        assert parsed["total_records"] == 1


# ---------------------------------------------------------------------------
# Additional coverage for configured-but-unimplemented stub paths and
# Crossref verify_doi network failure (crossref.py lines 187-188,
# elsevier_scopus.py lines 77/89, google_drive.py line 74,
# microsoft_graph.py line 74, scival.py lines 70/81,
# web_of_science.py lines 71/82)
# ---------------------------------------------------------------------------


class TestCrossrefVerifyDoiNetworkFailure:
    def test_verify_doi_returns_error_on_network_failure(self, monkeypatch):
        def fake_urlopen(req, timeout=10):
            raise OSError("network down")

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = CrossrefProvider()
        result = provider.verify_doi("10.1234/x")
        assert result.is_empty
        assert result.errors
        assert "Crossref DOI verification error" in result.errors[0]


class TestElsevierScopusConfiguredPaths:
    def test_search_with_key_returns_parsed_records(self, monkeypatch):
        payload = {
            "search-results": {
                "entry": [
                    {
                        "dc:title": "Scopus Blue Economy Paper",
                        "dc:creator": "Ada Lovelace",
                        "prism:doi": "10.2000/scopus",
                        "prism:url": "https://example.org/scopus",
                        "prism:publicationName": "Scopus Journal",
                        "prism:coverDate": "2025-03-11",
                        "citedby-count": "12",
                        "authkeywords": "blue economy|governance",
                    }
                ]
            }
        }

        def fake_urlopen(req, timeout=12):
            return _DummyResponse(payload)

        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")

    """Tests for ElsevierScopusProvider when an API key is present."""

    # Minimal synthetic Scopus search-results payload.
    _SCOPUS_PAYLOAD = {
        "search-results": {
            "entry": [
                {
                    "dc:title": "Blue Maritime Governance",
                    "dc:creator": "Kowalski, A.",
                    "author": [{"authname": "Kowalski A."}],
                    "prism:coverDate": "2023-06-01",
                    "prism:doi": "10.9999/scopus-test",
                    "prism:publicationName": "Ocean Policy",
                    "prism:url": "https://api.elsevier.com/content/abstract/scopus_id/123",
                    "eid": "2-s2.0-123456789",
                    "citedby-count": "7",
                    "authkeywords": "maritime | governance | blue economy",
                }
            ]
        }
    }

    def test_search_with_key_parses_records(self, monkeypatch):
        """When key present, search must return a parsed LiteratureRecord."""
        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")

        def fake_urlopen(req, timeout=15):
            return _DummyResponse(self._SCOPUS_PAYLOAD)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = ElsevierScopusProvider()
        result = provider.search("blue economy")
        assert not result.is_empty
        assert result.records[0].provider == "Scopus"
        assert result.records[0].doi == "10.9999/scopus-test"
        assert result.records[0].citation_count == 7
        assert result.records[0].subject_terms == [
            "maritime",
            "governance",
            "blue economy",
        ]
        assert result.provenance

    def test_verify_doi_with_key_returns_parsed_records(self, monkeypatch):
        payload = {
            "search-results": {
                "entry": [
                    {
                        "dc:title": "Scopus DOI Result",
                        "dc:creator": "A. Researcher",
                        "prism:doi": "10.1234/x",
                        "prism:url": "https://example.org/doi",
                        "prism:publicationName": "DOI Journal",
                        "prism:coverDate": "2024-02-01",
                    }
                ]
            }
        }

        def fake_urlopen(req, timeout=12):
            return _DummyResponse(payload)

        import urllib.request

        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = ElsevierScopusProvider()
        result = provider.verify_doi("10.1234/x")
        assert not result.is_empty
        assert result.records[0].doi == "10.1234/x"
        assert result.provenance

    def test_search_without_dois_has_distinct_provenance_hashes(self, monkeypatch):
        payload = {
            "search-results": {
                "entry": [
                    {
                        "dc:title": "Scopus Record One",
                        "dc:creator": "Ada Lovelace",
                        "prism:url": "https://example.org/scopus-1",
                        "prism:publicationName": "Scopus Journal",
                        "prism:coverDate": "2023-05-01",
                        "authkeywords": "maritime|governance",
                    },
                    {
                        "dc:title": "Scopus Record Two",
                        "dc:creator": "Grace Hopper",
                        "prism:url": "https://example.org/scopus-2",
                        "prism:publicationName": "Scopus Journal",
                        "prism:coverDate": "2024-02-10",
                        "authkeywords": "ports|resilience",
                    },
                ]
            }
        }

        def fake_urlopen(req, timeout=12):
            return _DummyResponse(payload)

        import urllib.request

        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = ElsevierScopusProvider()
        result = provider.search("blue economy")
        hashes = [ev.provenance_hash for ev in result.provenance]
        assert len(hashes) == 2
        assert len(set(hashes)) == 2
        rec = result.records[0]
        assert rec.title == "Scopus Record One"
        assert "Ada" in rec.authors
        assert rec.year == "2023"
        assert rec.doi == ""
        assert rec.journal == "Scopus Journal"
        assert rec.provider == "Scopus"
        assert rec.subject_terms == ["maritime", "governance"]
        assert len(result.provenance) == 2

    def test_search_sets_stage1_compliance_flags(self, monkeypatch):
        """Scopus records must never store abstract content (Stage 1 governance)."""
        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")

        def fake_urlopen(req, timeout=15):
            return _DummyResponse(self._SCOPUS_PAYLOAD)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = ElsevierScopusProvider()
        result = provider.search("blue economy")
        rec = result.records[0]
        assert rec.abstract_available is False
        assert rec.abstract_stored is False

    def test_search_returns_error_on_network_failure(self, monkeypatch):
        """Network errors must surface as errors, not exceptions."""
        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")

        def fake_urlopen(req, timeout=15):
            raise OSError("network down")

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = ElsevierScopusProvider()
        result = provider.search("blue economy")
        assert result.is_empty
        assert result.errors
        assert "Scopus search error" in result.errors[0]

    def test_verify_doi_with_key_parses_record(self, monkeypatch):
        """verify_doi must parse a Scopus entry into a LiteratureRecord."""
        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")

        def fake_urlopen(req, timeout=15):
            return _DummyResponse(self._SCOPUS_PAYLOAD)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = ElsevierScopusProvider()
        result = provider.verify_doi("10.9999/scopus-test")
        assert not result.is_empty
        assert result.records[0].doi == "10.9999/scopus-test"

    def test_verify_doi_returns_error_on_network_failure(self, monkeypatch):
        """Network errors in verify_doi must surface as errors, not exceptions."""
        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")

        def fake_urlopen(req, timeout=15):
            raise OSError("timeout")

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = ElsevierScopusProvider()
        result = provider.verify_doi("10.9999/x")
        assert result.is_empty
        assert result.errors
        assert "Scopus DOI verification error" in result.errors[0]

    def test_scopus_skips_error_entries(self, monkeypatch):
        """Scopus error-sentinel entries ({"error": ...}) must be silently skipped."""
        monkeypatch.setenv("ELSEVIER_API_KEY", "testkey")
        payload = {"search-results": {"entry": [{"error": "RESOURCE_NOT_FOUND"}]}}

        def fake_urlopen(req, timeout=15):
            return _DummyResponse(payload)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = ElsevierScopusProvider()
        result = provider.search("nothing")
        assert result.is_empty


class TestGoogleDriveConfiguredPath:
    def test_search_with_credentials_returns_not_implemented_warning(
        self, monkeypatch, tmp_path
    ):
        cred_file = tmp_path / "creds.json"
        cred_file.write_text("{}")
        monkeypatch.setenv("GOOGLE_DRIVE_OAUTH_CREDENTIALS", str(cred_file))
        provider = GoogleDriveProvider()
        result = provider.search("blue economy")
        assert result.warnings
        assert "not yet implemented" in result.warnings[0].lower()


class TestMicrosoftGraphConfiguredPath:
    def test_search_with_credentials_returns_not_implemented_warning(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_TENANT_ID", "tid")
        monkeypatch.setenv("MICROSOFT_CLIENT_ID", "cid")
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "csecret")
        provider = MicrosoftGraphProvider()
        result = provider.search("ports")
        assert result.warnings
        assert "not yet implemented" in result.warnings[0].lower()

    def test_search_with_site_scope_parses_graph_records(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_TENANT_ID", "tid")
        monkeypatch.setenv("MICROSOFT_CLIENT_ID", "cid")
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "csecret")
        monkeypatch.setenv("MICROSOFT_GRAPH_SITE_ID", "site-1")

        token_payload = {"access_token": "graph-token"}
        search_payload = {
            "value": [
                {
                    "id": "doc-1",
                    "name": "Blue economy note 10.5555/graph-doi",
                    "webUrl": "https://example.org/graph/doc-1",
                    "createdDateTime": "2026-01-03T10:00:00Z",
                    "createdBy": {"user": {"displayName": "Researcher A"}},
                }
            ]
        }

        def fake_urlopen(req, timeout=12):
            url = req.full_url
            if "oauth2/v2.0/token" in url:
                return _DummyResponse(token_payload)
            return _DummyResponse(search_payload)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = MicrosoftGraphProvider()
        result = provider.search("blue economy")
        assert not result.is_empty
        assert result.records[0].provider == "Microsoft Graph (OneDrive/SharePoint)"
        assert result.records[0].doi == "10.5555/graph-doi"
        assert result.provenance

    def test_search_url_escapes_single_quotes_for_odata(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_TENANT_ID", "tid")
        monkeypatch.setenv("MICROSOFT_CLIENT_ID", "cid")
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "csecret")
        monkeypatch.setenv("MICROSOFT_GRAPH_SITE_ID", "site-1")
        provider = MicrosoftGraphProvider()

        url = provider._search_url("ocean's justice", max_results=5)

        assert "search(q='ocean%27%27s%20justice')" in url

    def test_parse_items_fallback_source_id_is_prefixed_once(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_TENANT_ID", "tid")
        monkeypatch.setenv("MICROSOFT_CLIENT_ID", "cid")
        monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "csecret")
        monkeypatch.setenv("MICROSOFT_GRAPH_SITE_ID", "site-1")
        provider = MicrosoftGraphProvider()

        payload = {
            "value": [
                {
                    "name": "Doc without id",
                    "webUrl": "https://example.org/doc",
                    "createdDateTime": "2026-01-03T10:00:00Z",
                }
            ]
        }

        records = provider._parse_items(payload, "blue economy")

        assert len(records) == 1
        assert records[0].source_id.startswith("graph:")
        assert records[0].source_id.count("graph:") == 1


class TestSciValConfiguredPaths:
    def test_search_with_key_returns_topic_records(self, monkeypatch):
        payload = {
            "results": [
                {
                    "id": "topic-1",
                    "topicName": "Ocean governance analytics",
                    "year": 2025,
                    "keywords": ["ocean", "governance"],
                }
            ]
        }

        def fake_urlopen(req, timeout=12):
            return _DummyResponse(payload)

        import urllib.request

        monkeypatch.setenv("SCIVAL_API_KEY", "scivalkey")
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = SciValProvider()
        result = provider.search("ocean governance")
        assert not result.is_empty
        assert result.records[0].provider == "SciVal"
        assert "SciVal topic" in result.records[0].title
        assert result.records[0].authors == ""
        assert result.records[0].journal == ""
        assert result.provenance

    def test_verify_doi_with_key_uses_search(self, monkeypatch):
        payload = {"results": [{"id": "topic-2", "name": "DOI topic"}]}

        def fake_urlopen(req, timeout=12):
            return _DummyResponse(payload)

        import urllib.request

        monkeypatch.setenv("SCIVAL_API_KEY", "scivalkey")
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = SciValProvider()
        result = provider.verify_doi("10.1234/x")
        assert not result.is_empty
        assert result.records[0].provider == "SciVal"


class TestWebOfScienceConfiguredPaths:
    def test_search_with_key_returns_parsed_records(self, monkeypatch):
        payload = {
            "hits": [
                {
                    "title": "Web of Science Maritime Paper",
                    "source": {"sourceTitle": "WoS Journal", "publishYear": 2023},
                    "identifiers": {"doi": "10.3000/wos"},
                    "links": {"record": "https://example.org/wos"},
                    "names": {"authors": [{"displayName": "Grace Hopper"}]},
                    "keywords": {"authorKeywords": ["maritime", "transport"]},
                    "timesCited": 7,
                }
            ]
        }

        def fake_urlopen(req, timeout=12):
            return _DummyResponse(payload)

        import urllib.request

        monkeypatch.setenv("WOS_API_KEY", "woskey")
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = WebOfScienceProvider()
        result = provider.search("maritime transport")
        assert not result.is_empty
        assert result.records[0].provider == "Web of Science (Clarivate)"
        assert result.records[0].doi == "10.3000/wos"
        assert result.records[0].citation_count == 7
        assert result.provenance
        assert result.provenance[0].source_provider == "Web of Science (Clarivate)"

    def test_verify_doi_with_key_returns_parsed_records(self, monkeypatch):
        payload = {
            "hits": [
                {
                    "title": "WoS DOI Paper",
                    "source": {"sourceTitle": "DOI Journal", "publishYear": 2024},
                    "identifiers": {"doi": "10.1234/x"},
                    "links": {"record": "https://example.org/wos-doi"},
                }
            ]
        }

        def fake_urlopen(req, timeout=12):
            return _DummyResponse(payload)

        import urllib.request

        monkeypatch.setenv("WOS_API_KEY", "woskey")
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = WebOfScienceProvider()
        result = provider.verify_doi("10.1234/x")
        assert not result.is_empty
        assert result.records[0].doi == "10.1234/x"
        assert result.provenance

    def test_search_without_dois_has_distinct_provenance_hashes(self, monkeypatch):
        payload = {
            "hits": [
                {
                    "title": "WoS Record One",
                    "source": {"sourceTitle": "WoS Journal", "publishYear": 2023},
                    "links": {"record": "https://example.org/wos-1"},
                },
                {
                    "title": "WoS Record Two",
                    "source": {"sourceTitle": "WoS Journal", "publishYear": 2024},
                    "links": {"record": "https://example.org/wos-2"},
                },
            ]
        }

        def fake_urlopen(req, timeout=12):
            return _DummyResponse(payload)

        import urllib.request

        monkeypatch.setenv("WOS_API_KEY", "woskey")
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = WebOfScienceProvider()
        result = provider.search("maritime transport")
        hashes = [ev.provenance_hash for ev in result.provenance]
        assert len(hashes) == 2
        assert len(set(hashes)) == 2

    def test_search_merges_and_deduplicates_keyword_sources(self, monkeypatch):
        payload = {
            "hits": [
                {
                    "title": "Keyword Merge Paper",
                    "source": {"sourceTitle": "WoS Journal", "publishYear": 2024},
                    "identifiers": {"doi": "10.1234/kw"},
                    "links": {"record": "https://example.org/wos-kw"},
                    "keywords": {
                        "authorKeywords": ["shipping", "ports"],
                        "keywordsPlus": ["ports", "governance"],
                        "keyword": ["governance", "resilience"],
                    },
                }
            ]
        }

        def fake_urlopen(req, timeout=12):
            return _DummyResponse(payload)

        monkeypatch.setenv("WOS_API_KEY", "woskey")
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        provider = WebOfScienceProvider()
        result = provider.search("shipping")
        assert result.records[0].subject_terms == [
            "shipping",
            "ports",
            "governance",
            "resilience",
        ]

    # Minimal synthetic WoS Starter API hits payload.
    _WOS_PAYLOAD = {
        "hits": [
            {
                "uid": "WOS:000000000000001",
                "title": "Maritime Transport Resilience",
                "types": ["Article"],
                "names": {
                    "authors": [{"displayName": "Smith, J.", "wosStandard": "Smith, J"}]
                },
                "source": {"sourceTitle": "Maritime Policy", "publishYear": 2022},
                "identifiers": {"doi": "10.8888/wos-test"},
                "keywords": {
                    "authorKeywords": ["shipping", "resilience"],
                    "keywordsPlus": ["port logistics"],
                },
                "links": {
                    "record": "https://www.webofscience.com/wos/woscc/full-record/WOS:000000000000001"
                },
                "citations": [{"db": "WOS", "count": 12}],
            }
        ]
    }

    def test_search_with_key_parses_records(self, monkeypatch):
        """When key present, search must return a parsed LiteratureRecord."""
        monkeypatch.setenv("WOS_API_KEY", "woskey")

        def fake_urlopen(req, timeout=15):
            return _DummyResponse(self._WOS_PAYLOAD)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = WebOfScienceProvider()
        result = provider.search("maritime transport")
        assert not result.is_empty
        rec = result.records[0]
        assert rec.title == "Maritime Transport Resilience"
        assert "Smith" in rec.authors
        assert rec.year == "2022"
        assert rec.doi == "10.8888/wos-test"
        assert rec.journal == "Maritime Policy"
        assert rec.provider == "Web of Science (Clarivate)"
        assert "shipping" in rec.subject_terms
        assert "port logistics" in rec.subject_terms
        assert len(result.provenance) == 1

    def test_search_sets_stage1_compliance_flags(self, monkeypatch):
        """WoS records must never store abstract content (Stage 1 governance)."""
        monkeypatch.setenv("WOS_API_KEY", "woskey")

        def fake_urlopen(req, timeout=15):
            return _DummyResponse(self._WOS_PAYLOAD)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = WebOfScienceProvider()
        result = provider.search("maritime transport")
        rec = result.records[0]
        assert rec.abstract_available is False
        assert rec.abstract_stored is False

    def test_search_returns_error_on_network_failure(self, monkeypatch):
        """Network errors must surface as errors, not exceptions."""
        monkeypatch.setenv("WOS_API_KEY", "woskey")

        def fake_urlopen(req, timeout=15):
            raise OSError("network down")

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = WebOfScienceProvider()
        result = provider.search("maritime")
        assert result.is_empty
        assert result.errors
        assert "Web of Science search error" in result.errors[0]

    def test_verify_doi_with_key_parses_record(self, monkeypatch):
        """verify_doi must parse a WoS hit into a LiteratureRecord."""
        monkeypatch.setenv("WOS_API_KEY", "woskey")

        def fake_urlopen(req, timeout=15):
            return _DummyResponse(self._WOS_PAYLOAD)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = WebOfScienceProvider()
        result = provider.verify_doi("10.8888/wos-test")
        assert not result.is_empty
        assert result.records[0].doi == "10.8888/wos-test"

    def test_verify_doi_returns_error_on_network_failure(self, monkeypatch):
        """Network errors in verify_doi must surface as errors, not exceptions."""
        monkeypatch.setenv("WOS_API_KEY", "woskey")

        def fake_urlopen(req, timeout=15):
            raise OSError("timeout")

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = WebOfScienceProvider()
        result = provider.verify_doi("10.8888/x")
        assert result.is_empty
        assert result.errors
        assert "Web of Science DOI verification error" in result.errors[0]

    def test_wos_citation_count_parsed(self, monkeypatch):
        """Citation count from WoS citations[] must be parsed (transient only)."""
        monkeypatch.setenv("WOS_API_KEY", "woskey")

        def fake_urlopen(req, timeout=15):
            return _DummyResponse(self._WOS_PAYLOAD)

        import urllib.request

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        provider = WebOfScienceProvider()
        result = provider.search("maritime")
        assert result.records[0].citation_count == 12


# ---------------------------------------------------------------------------
# Tests for Microsoft Graph helper functions
# ---------------------------------------------------------------------------


class TestODataEscape:
    """_odata_escape must double single quotes for OData string literals."""

    def test_plain_query_unchanged(self):
        from src.scientific_sources.microsoft_graph import _odata_escape

        assert _odata_escape("blue economy") == "blue economy"

    def test_single_quote_doubled(self):
        from src.scientific_sources.microsoft_graph import _odata_escape

        assert _odata_escape("O'Brien") == "O''Brien"

    def test_multiple_single_quotes(self):
        from src.scientific_sources.microsoft_graph import _odata_escape

        assert _odata_escape("it's O'Brien's data") == "it''s O''Brien''s data"

    def test_empty_string(self):
        from src.scientific_sources.microsoft_graph import _odata_escape

        assert _odata_escape("") == ""

    def test_no_double_url_encoding(self):
        """_odata_escape must NOT percent-encode; URL-encoding is a separate step."""
        from src.scientific_sources.microsoft_graph import _odata_escape

        result = _odata_escape("blue & green")
        assert "%" not in result


class TestSearchUrl:
    """_search_url must produce valid OData-safe URLs."""

    def test_plain_query_contains_encoded_value(self):
        from src.scientific_sources.microsoft_graph import _search_url

        url = _search_url("site1", "drive1", "blue economy")
        # spaces become %20 or +
        assert "blue" in url
        assert "economy" in url

    def test_apostrophe_in_query_produces_doubled_quote(self):
        """Single quotes must be doubled (OData) before URL-encoding."""
        from src.scientific_sources.microsoft_graph import _search_url
        import urllib.parse

        url = _search_url("site1", "drive1", "O'Brien")
        # The OData-escaped form "O''Brien" should appear URL-encoded in the URL.
        assert urllib.parse.quote("O''Brien", safe="") in url

    def test_apostrophe_is_not_raw_in_url(self):
        """A bare unescaped single quote must not appear in the URL path."""
        from src.scientific_sources.microsoft_graph import _search_url

        url = _search_url("site1", "drive1", "O'Brien")
        # The raw (unescaped) OData literal "O'Brien" must not appear verbatim.
        assert "O'Brien" not in url

    def test_url_contains_site_and_drive(self):
        from src.scientific_sources.microsoft_graph import _search_url

        url = _search_url("mysite", "mydrive", "test")
        assert "mysite" in url
        assert "mydrive" in url


class TestMakeSourceId:
    """_make_source_id must produce a single-prefixed graph: identifier."""

    def test_uses_item_id_when_present(self):
        from src.scientific_sources.microsoft_graph import _make_source_id

        sid = _make_source_id({"id": "abc123", "name": "Document.pdf"})
        assert sid == "graph:abc123"

    def test_falls_back_to_name_when_no_id(self):
        from src.scientific_sources.microsoft_graph import _make_source_id

        sid = _make_source_id({"name": "Blue Economy Report"})
        assert sid == "graph:Blue Economy Report"
        assert not sid.startswith("graph:graph:")

    def test_no_double_prefix(self):
        """source_id must never start with 'graph:graph:'."""
        from src.scientific_sources.microsoft_graph import _make_source_id

        sid = _make_source_id({"name": "Report"})
        assert sid.count("graph:") == 1

    def test_name_truncated_to_40_chars(self):
        from src.scientific_sources.microsoft_graph import _make_source_id

        long_name = "A" * 80
        sid = _make_source_id({"name": long_name})
        # Discriminator is first 40 chars of name; plus 'graph:' prefix
        assert sid == f"graph:{'A' * 40}"

    def test_fallback_to_title_field_when_no_name_or_id(self):
        from src.scientific_sources.microsoft_graph import _make_source_id

        sid = _make_source_id({"title": "Maritime Security"})
        assert sid == "graph:Maritime Security"

    def test_unknown_when_no_fields(self):
        from src.scientific_sources.microsoft_graph import _make_source_id

        sid = _make_source_id({})
        assert sid == "graph:unknown"


class TestProbeMicrosoftGraph:
    """probe_microsoft_graph must classify all URLError subtypes as transient."""

    def test_connection_error_is_transient(self, monkeypatch):
        import urllib.error
        import urllib.request
        from src.scientific_sources.microsoft_graph import probe_microsoft_graph

        def fake_urlopen(req, timeout=5):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        assert probe_microsoft_graph("t", "c", "s") == "transient-network-error"

    def test_connection_reset_is_transient(self, monkeypatch):
        import urllib.error
        import urllib.request
        from src.scientific_sources.microsoft_graph import probe_microsoft_graph

        def fake_urlopen(req, timeout=5):
            raise urllib.error.URLError("connection reset by peer")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        assert probe_microsoft_graph("t", "c", "s") == "transient-network-error"

    def test_http_error_is_transient(self, monkeypatch):
        """HTTPError (4xx/5xx) must also be classified as transient."""
        import email.message
        import urllib.error
        import urllib.request
        from src.scientific_sources.microsoft_graph import probe_microsoft_graph

        def fake_urlopen(req, timeout=5):
            raise urllib.error.HTTPError(
                url="https://example.com",
                code=401,
                msg="Unauthorized",
                hdrs=email.message.Message(),
                fp=None,
            )

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        assert probe_microsoft_graph("t", "c", "s") == "transient-network-error"

    def test_generic_os_error_is_transient(self, monkeypatch):
        """Any other exception must not produce 'present-but-invalid'."""
        import urllib.request
        from src.scientific_sources.microsoft_graph import probe_microsoft_graph

        def fake_urlopen(req, timeout=5):
            raise OSError("ssl handshake failed")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        assert probe_microsoft_graph("t", "c", "s") == "transient-network-error"

    def test_successful_response_is_valid(self, monkeypatch):
        import urllib.request
        from src.scientific_sources.microsoft_graph import probe_microsoft_graph

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        monkeypatch.setattr(
            urllib.request, "urlopen", lambda req, timeout=5: _FakeResp()
        )
        assert probe_microsoft_graph("t", "c", "s") == "present-and-valid"
