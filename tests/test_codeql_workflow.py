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
    """Assert that the matrix contains exactly the expected language/build-mode pairs."""
    matrix_includes = WORKFLOW["jobs"]["analyze"]["strategy"]["matrix"]["include"]
    pairs = {(entry["language"], entry["build-mode"]) for entry in matrix_includes}
    expected = {("actions", "none"), ("python", "none")}
    assert len(matrix_includes) == len(expected), (
        f"expected exactly {len(expected)} matrix entries, got {len(matrix_includes)}"
    )
    assert pairs == expected, f"expected exact matrix pairs {expected}, got {pairs}"


def test_codeql_checkout_does_not_persist_credentials() -> None:
    """Assert that the checkout step sets persist-credentials: false."""
    steps = WORKFLOW["jobs"]["analyze"]["steps"]
    checkout_steps = [s for s in steps if "actions/checkout" in (s.get("uses") or "")]
    assert checkout_steps, "No actions/checkout step found"
    for step in checkout_steps:
        with_block = step.get("with") or {}
        assert with_block.get("persist-credentials") is False, (
            f"Expected persist-credentials: false on checkout step, got: {with_block!r}"
        )


def test_codeql_workflow_uses_minimal_actions_and_no_autobuild() -> None:
    assert "actions/checkout@v6" in WORKFLOW_TEXT
    assert "github/codeql-action/init@v4" in WORKFLOW_TEXT
    assert "github/codeql-action/analyze@v4" in WORKFLOW_TEXT
    assert "autobuild" not in WORKFLOW_TEXT
