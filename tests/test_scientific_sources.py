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
import os

import pytest

from src.scientific_sources.models import (
    LiteratureRecord,
    ProviderResult,
    SourceCapability,
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
    defaults = dict(
        title="Blue Economy Governance",
        authors="Ada Lovelace",
        year="2024",
        doi="10.1234/blue",
        source_id="crossref:10.1234/blue",
        provider="Crossref",
        journal="Ocean Studies",
        url="https://example.org/paper",
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
        assert isinstance(d["abstract_available"], bool)

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
