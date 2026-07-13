from __future__ import annotations

from pathlib import Path

import yaml


_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "codeql.yml"
WORKFLOW_TEXT = _WORKFLOW_PATH.read_text(encoding="utf-8")
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)


def test_codeql_workflow_is_repo_managed_for_python_and_actions() -> None:
    assert "name: CodeQL" in WORKFLOW_TEXT
    assert "pull_request:" in WORKFLOW_TEXT
    assert 'branches: ["main"]' in WORKFLOW_TEXT
    assert "workflow_dispatch:" in WORKFLOW_TEXT


def test_codeql_workflow_matrix_pairs_are_exact() -> None:
    """Assert that each declared matrix entry has the expected language/build-mode pair."""
    matrix_includes = WORKFLOW["jobs"]["analyze"]["strategy"]["matrix"]["include"]
    pairs = {entry["language"]: entry["build-mode"] for entry in matrix_includes}
    assert pairs.get("actions") == "none", f"expected actions -> none, got {pairs.get('actions')!r}"
    assert pairs.get("python") == "none", f"expected python -> none, got {pairs.get('python')!r}"


def test_codeql_workflow_uses_minimal_actions_and_no_autobuild() -> None:
    assert "actions/checkout@v6" in WORKFLOW_TEXT
    assert "github/codeql-action/init@v4" in WORKFLOW_TEXT
    assert "github/codeql-action/analyze@v4" in WORKFLOW_TEXT
    assert "autobuild" not in WORKFLOW_TEXT
