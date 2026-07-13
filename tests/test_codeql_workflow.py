from __future__ import annotations

from pathlib import Path


WORKFLOW_TEXT = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "codeql.yml"
).read_text(encoding="utf-8")


def test_codeql_workflow_is_repo_managed_for_python_and_actions() -> None:
    assert "name: CodeQL" in WORKFLOW_TEXT
    assert "pull_request:" in WORKFLOW_TEXT
    assert 'branches: ["main"]' in WORKFLOW_TEXT
    assert "workflow_dispatch:" in WORKFLOW_TEXT
    assert "- language: actions" in WORKFLOW_TEXT
    assert "- language: python" in WORKFLOW_TEXT


def test_codeql_workflow_uses_build_mode_none_and_minimal_actions() -> None:
    assert "build-mode: none" in WORKFLOW_TEXT
    assert "actions/checkout@v6" in WORKFLOW_TEXT
    assert "github/codeql-action/init@v4" in WORKFLOW_TEXT
    assert "github/codeql-action/analyze@v4" in WORKFLOW_TEXT
    assert "autobuild" not in WORKFLOW_TEXT
