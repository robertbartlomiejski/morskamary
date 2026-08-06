"""Tests for scripts.smoke_scientific_bridge."""

from __future__ import annotations

import types

import scripts.smoke_scientific_bridge as smoke
from src.scientific_sources.models import ProviderResult, SourceCapability


class _BridgeOk:
    def handle_request(self, payload):
        assert payload["method"] == "tools/list"
        return {
            "tools": [
                {"name": "fetch_scientific_proofs"},
                {"name": "verify_citation"},
                {"name": "list_research_source_capabilities"},
                {"name": "search_open_metadata"},
                {"name": "verify_doi"},
            ]
        }

    def handle_fetch_scientific_proofs(self, _payload):
        return {"content": [{"text": "topic is required"}]}


class _BridgeBad:
    def handle_request(self, _payload):
        return {"tools": [{"name": "fetch_scientific_proofs"}]}

    def handle_fetch_scientific_proofs(self, _payload):
        return {"content": [{"text": "unexpected"}]}


class _OfflineRegistry:
    def __init__(self, with_errors: bool = False):
        self.with_errors = with_errors

    def capabilities_dict(self):
        return {
            "crossref": {"configured": True},
            "scopus": {"configured": False},
            "wos": {"configured": False},
            "scival": {"configured": False},
            "google_drive": {"configured": False},
            "microsoft_graph": {"configured": False},
        }

    def search(self, _query, max_results=1, providers=None):
        _ = max_results
        _ = providers
        if self.with_errors:
            return [ProviderResult(errors=["boom"])]
        return [ProviderResult(warnings=["not configured"])]


class _LiveRegistry:
    def list_capabilities(self):
        return [
            SourceCapability(
                name="scopus",
                provider="Scopus",
                requires_secret=True,
                configured=False,
                live_test_allowed=False,
                allowed_metadata_fields=[],
                licence_note="n/a",
            ),
            SourceCapability(
                name="wos",
                provider="WoS",
                requires_secret=True,
                configured=True,
                live_test_allowed=True,
                allowed_metadata_fields=[],
                licence_note="n/a",
            ),
        ]

    def search(self, _query, max_results=2, providers=None):
        _ = max_results
        if providers == ["wos"]:
            return [ProviderResult(errors=["rate limited"])]
        return [ProviderResult()]

    @staticmethod
    def flat_records(_results):
        return []


def test_run_offline_checks_happy_path(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "SourceRegistry", lambda: _OfflineRegistry())
    monkeypatch.setitem(
        __import__("sys").modules,
        "scientific_bridge",
        types.SimpleNamespace(ScientificBridge=_BridgeOk),
    )

    failures = smoke.run_offline_checks()
    assert failures == []


def test_run_offline_checks_collects_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke, "SourceRegistry", lambda: _OfflineRegistry(with_errors=True)
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "scientific_bridge",
        types.SimpleNamespace(ScientificBridge=_BridgeBad),
    )

    failures = smoke.run_offline_checks()
    assert "scopus error" in failures
    assert "missing tools" in failures
    assert "missing topic error" in failures


def test_run_live_checks_handles_skip_and_failure(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "SourceRegistry", _LiveRegistry)
    failures = smoke.run_live_checks()
    assert failures == ["live wos"]


def test_main_offline_and_live_modes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(smoke, "run_offline_checks", lambda: [])
    monkeypatch.setattr(smoke, "run_live_checks", lambda: [])
    offline_report_path = tmp_path / "offline_research_api_smoke_report.json"
    monkeypatch.setattr(
        smoke.sys,
        "argv",
        [
            "smoke_scientific_bridge.py",
            "--offline",
            "--output",
            str(offline_report_path),
        ],
    )
    assert smoke.main() == 0
    assert offline_report_path.is_file()

    monkeypatch.setattr(smoke, "run_offline_checks", lambda: ["offline-fail"])
    monkeypatch.setattr(smoke, "run_live_checks", lambda: ["live-fail"])
    live_report_path = tmp_path / "live_research_api_smoke_report.json"
    monkeypatch.setattr(
        smoke.sys,
        "argv",
        [
            "smoke_scientific_bridge.py",
            "--live-if-secrets-present",
            "--output",
            str(live_report_path),
        ],
    )
    assert smoke.main() == 1
    assert live_report_path.is_file()
