"""Tests for auxiliary research environment and capability scripts."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from src.scientific_sources.models import SourceCapability


SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _cap(
    *,
    name: str,
    provider: str,
    configured: bool,
    requires_secret: bool,
    live_test_allowed: bool = False,
) -> SourceCapability:
    """Build a SourceCapability fixture object."""
    return SourceCapability(
        name=name,
        provider=provider,
        requires_secret=requires_secret,
        configured=configured,
        live_test_allowed=live_test_allowed,
        allowed_metadata_fields=["title"],
        licence_note="test",
    )


class TestAuditResearchApiConfig:
    """Coverage for scripts/audit_research_api_config.py."""

    def test_main_prints_status_hints_and_counts(self, monkeypatch, capsys):
        import audit_research_api_config as script

        capabilities = [
            _cap(
                name="crossref",
                provider="Crossref",
                configured=True,
                requires_secret=False,
                live_test_allowed=True,
            ),
            _cap(
                name="scopus",
                provider="Elsevier Scopus",
                configured=False,
                requires_secret=True,
            ),
        ]

        class FakeRegistry:
            def list_capabilities(self):
                return capabilities

        monkeypatch.setattr(script, "SourceRegistry", FakeRegistry)
        monkeypatch.setenv("LIVE_RESEARCH_API_TESTS", "true")

        assert script.main() == 0
        out = capsys.readouterr().out
        assert "Crossref" in out and "✓ CONFIGURED" in out
        assert "Elsevier Scopus" in out and "✗ not configured" in out
        assert "ELSEVIER_API_KEY or SCOPUS_API_KEY" in out
        assert "Configured: 1/2 providers" in out
        assert "Live API tests: enabled (LIVE_RESEARCH_API_TESTS=true)" in out

    def test_main_falls_back_to_generic_env_hint(self, monkeypatch, capsys):
        import audit_research_api_config as script

        class FakeRegistry:
            def list_capabilities(self):
                return [
                    _cap(
                        name="unknown_provider",
                        provider="Unknown Provider",
                        configured=False,
                        requires_secret=True,
                    )
                ]

        monkeypatch.setattr(script, "SourceRegistry", FakeRegistry)
        monkeypatch.delenv("LIVE_RESEARCH_API_TESTS", raising=False)

        assert script.main() == 0
        out = capsys.readouterr().out
        assert "provider-specific credential" in out
        assert "Live API tests: disabled (LIVE_RESEARCH_API_TESTS=false)" in out


class TestExportResearchSourceCapabilities:
    """Coverage for scripts/export_research_source_capabilities.py."""

    def test_main_writes_json_and_summary(self, tmp_path, monkeypatch, capsys):
        import export_research_source_capabilities as script

        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        monkeypatch.setattr(
            script,
            "__file__",
            str(scripts_dir / "export_research_source_capabilities.py"),
        )

        capabilities = {
            "crossref": {"configured": True},
            "scopus": {"configured": False},
        }

        class FakeRegistry:
            def capabilities_dict(self):
                return capabilities

        monkeypatch.setattr(script, "SourceRegistry", FakeRegistry)

        assert script.main() == 0
        out = capsys.readouterr().out
        assert "1/2 providers configured" in out

        output_path = tmp_path / "outputs" / "research_source_capabilities.json"
        assert output_path.exists()

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["providers"] == capabilities
        assert payload["generated_at"]
        assert "Provider capability snapshot." in payload["note"]


class TestCheckResearchEnv:
    """Coverage for scripts/check_research_env.py."""

    def test_check_package_installed_true(self, monkeypatch, capsys):
        import check_research_env as script

        monkeypatch.setattr(script.importlib, "import_module", lambda _: object())
        assert script.check_package_installed("numpy") is True
        assert "Package numpy" in capsys.readouterr().out

    def test_check_package_installed_false(self, monkeypatch, capsys):
        import check_research_env as script

        def _raise_import_error(_):
            raise ImportError("missing")

        monkeypatch.setattr(script.importlib, "import_module", _raise_import_error)
        assert script.check_package_installed("numpy") is False
        assert "MISSING" in capsys.readouterr().out

    def test_check_env_var_set_and_not_set(self, monkeypatch, capsys):
        import check_research_env as script

        monkeypatch.setenv("TEST_VAR", "value")
        assert script.check_env_var("TEST_VAR", "Test Var") is True
        assert "SET" in capsys.readouterr().out

        monkeypatch.delenv("TEST_VAR", raising=False)
        assert script.check_env_var("TEST_VAR", "Test Var") is False
        assert "not set" in capsys.readouterr().out

    def test_main_success_path(self, monkeypatch, capsys):
        import check_research_env as script
        import src.scientific_sources.source_registry as registry_module

        class FakeRegistry:
            def list_capabilities(self):
                return [
                    _cap(
                        name="crossref",
                        provider="Crossref",
                        configured=True,
                        requires_secret=False,
                    )
                ]

        monkeypatch.setattr(script, "check_python_version", lambda: True)
        monkeypatch.setattr(script, "check_package_installed", lambda _pkg: True)
        monkeypatch.setattr(script, "check_env_var", lambda _env, _label: True)
        monkeypatch.setenv("LIVE_RESEARCH_API_TESTS", "true")
        monkeypatch.setattr(registry_module, "SourceRegistry", FakeRegistry)

        assert script.main() == 0
        out = capsys.readouterr().out
        assert "Live API calls ENABLED" in out
        assert "Environment check complete. Core dependencies OK." in out

    def test_main_returns_failure_on_registry_error(self, monkeypatch, capsys):
        import check_research_env as script
        import src.scientific_sources.source_registry as registry_module

        class BrokenRegistry:
            def __init__(self):
                raise RuntimeError("registry unavailable")

        monkeypatch.setattr(script, "check_python_version", lambda: False)
        monkeypatch.setattr(script, "check_package_installed", lambda _pkg: True)
        monkeypatch.setattr(script, "check_env_var", lambda _env, _label: True)
        monkeypatch.setenv("LIVE_RESEARCH_API_TESTS", "false")
        monkeypatch.setattr(registry_module, "SourceRegistry", BrokenRegistry)

        assert script.main() == 1
        out = capsys.readouterr().out
        assert "Live API calls disabled" in out
        assert "ERROR loading registry: registry unavailable" in out
        assert "Environment check found issues." in out


def test_script_main_blocks_are_present():
    """Ensure script modules expose callable main functions for CLI execution."""
    audit = importlib.import_module("audit_research_api_config")
    export = importlib.import_module("export_research_source_capabilities")
    env = importlib.import_module("check_research_env")

    assert callable(audit.main)
    assert callable(export.main)
    assert callable(env.main)


class TestValidateResearchSourceOutputs:
    """Coverage for scripts/validate_research_source_outputs.py."""

    def test_main_warns_when_outputs_dir_missing(self, tmp_path, monkeypatch, capsys):
        import validate_research_source_outputs as script

        missing_dir = tmp_path / "missing-outputs"
        monkeypatch.setattr(script, "OUTPUTS_DIR", str(missing_dir))

        assert script.main() == 0
        out = capsys.readouterr().out
        assert "outputs/ directory not found" in out
        assert "Warnings: 1" in out
        assert "Errors:   0" in out

    def test_validate_capabilities_json_happy_path(self, tmp_path, monkeypatch, capsys):
        import validate_research_source_outputs as script

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        capabilities_path = outputs_dir / "research_source_capabilities.json"
        capabilities_path.write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00+00:00",
                    "providers": {"crossref": {"configured": True}, "scopus": {}},
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "OUTPUTS_DIR", str(outputs_dir))
        script.ERRORS.clear()
        script.WARNINGS.clear()

        script.validate_capabilities_json()
        out = capsys.readouterr().out
        assert "OK: research_source_capabilities.json (2 providers)" in out
        assert script.ERRORS == []
        assert script.WARNINGS == []

    def test_validate_capabilities_json_reports_invalid_json(
        self, tmp_path, monkeypatch, capsys
    ):
        import validate_research_source_outputs as script

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        capabilities_path = outputs_dir / "research_source_capabilities.json"
        capabilities_path.write_text("{ invalid json", encoding="utf-8")

        monkeypatch.setattr(script, "OUTPUTS_DIR", str(outputs_dir))
        script.ERRORS.clear()
        script.WARNINGS.clear()

        script.validate_capabilities_json()
        out = capsys.readouterr().out
        assert "not valid JSON" in out
        assert len(script.ERRORS) == 1

    def test_main_fails_when_crossref_missing(self, tmp_path, monkeypatch, capsys):
        import validate_research_source_outputs as script

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        (outputs_dir / "research_source_capabilities.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00+00:00",
                    "providers": {"scopus": {"configured": True}},
                }
            ),
            encoding="utf-8",
        )
        (outputs_dir / "research_api_smoke_report.json").write_text(
            json.dumps({"ok": True}),
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "OUTPUTS_DIR", str(outputs_dir))
        assert script.main() == 1
        out = capsys.readouterr().out
        assert "crossref provider missing from capabilities export" in out
        assert "Validation FAILED." in out

    def test_validate_live_research_sources_required_happy_path(
        self, tmp_path, monkeypatch, capsys
    ):
        import validate_research_source_outputs as script

        outputs_dir = tmp_path / "outputs"
        research_dir = outputs_dir / "research_sources"
        research_dir.mkdir(parents=True)

        (outputs_dir / "research_source_capabilities.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00+00:00",
                    "providers": {"crossref": {"configured": True}},
                }
            ),
            encoding="utf-8",
        )
        (outputs_dir / "research_api_health.json").write_text(
            json.dumps(
                {
                    "statuses": [
                        {
                            "provider": "crossref",
                            "status": "ok",
                            "detail": "request succeeded",
                            "http_status": 200,
                        }
                    ],
                    "summary": {"ok": 1},
                }
            ),
            encoding="utf-8",
        )

        live_record = {
            "title": "Live record",
            "source_id": "crossref:10.1234/test",
            "provider": "Crossref",
        }
        for name in [
            "live_records.json",
            "live_records_triangulated.json",
            "crossref_records.json",
        ]:
            (research_dir / name).write_text(json.dumps([live_record]), encoding="utf-8")

        (research_dir / "live_provenance.json").write_text(
            json.dumps([{"provider": "crossref", "source_id": "crossref:10.1234/test"}]),
            encoding="utf-8",
        )
        (research_dir / "low_confidence_live_records.json").write_text(
            json.dumps([]),
            encoding="utf-8",
        )
        (research_dir / "live_records.csv").write_text(
            "title,source_id,provider\nLive record,crossref:10.1234/test,Crossref\n",
            encoding="utf-8",
        )
        (research_dir / "live_source_coverage.csv").write_text(
            "sector,provider,query,record_count\nBlue Biotech,crossref,test,1\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "OUTPUTS_DIR", str(outputs_dir))

        assert script.main(["--require-health", "--require-live"]) == 0
        out = capsys.readouterr().out
        assert "OK: live_records.json (1 JSON records/items)" in out
        assert "OK: live_source_coverage.csv (1 CSV rows)" in out

    def test_validate_live_research_sources_required_fails_when_missing(
        self, tmp_path, monkeypatch, capsys
    ):
        import validate_research_source_outputs as script

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        (outputs_dir / "research_source_capabilities.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-01-01T00:00:00+00:00",
                    "providers": {"crossref": {"configured": True}},
                }
            ),
            encoding="utf-8",
        )
        (outputs_dir / "research_api_health.json").write_text(
            json.dumps(
                {
                    "statuses": [
                        {
                            "provider": "crossref",
                            "status": "ok",
                            "detail": "request succeeded",
                            "http_status": 200,
                        }
                    ],
                    "summary": {"ok": 1},
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(script, "OUTPUTS_DIR", str(outputs_dir))

        assert script.main(["--require-health", "--require-live"]) == 1
        out = capsys.readouterr().out
        assert "outputs/research_sources directory not found" in out
        assert "Validation FAILED." in out
