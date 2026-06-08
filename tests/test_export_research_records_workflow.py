from __future__ import annotations

from pathlib import Path


WORKFLOW_TEXT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "export-research-records.yml"
).read_text(encoding="utf-8")


def test_export_workflow_uses_ci_safe_provider_defaults() -> None:
    assert "default: 'crossref,scopus'" in WORKFLOW_TEXT


def test_export_workflow_preflight_scopes_to_requested_providers() -> None:
    assert "python scripts/check_research_api_health.py" in WORKFLOW_TEXT
    assert '--providers "${{ github.event.inputs.providers }}"' in WORKFLOW_TEXT
    assert "--require-valid" in WORKFLOW_TEXT
