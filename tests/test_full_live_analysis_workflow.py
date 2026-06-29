from __future__ import annotations

from pathlib import Path


WORKFLOW_TEXT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "full-live-analysis.yml"
).read_text(encoding="utf-8")


def test_workflow_dispatch_declares_commit_outputs_input() -> None:
    assert "workflow_dispatch:" in WORKFLOW_TEXT
    assert "commit_outputs:" in WORKFLOW_TEXT


def test_schedule_commit_gate_uses_explicit_repo_variable_not_dispatch_input() -> None:
    assert "github.event_name == 'schedule'" in WORKFLOW_TEXT
    assert "vars.LIVE_OUTPUTS_AUTOCOMMIT == 'true'" in WORKFLOW_TEXT

    schedule_line_index = WORKFLOW_TEXT.index("(github.event_name == 'schedule'")
    trailing = WORKFLOW_TEXT[schedule_line_index : schedule_line_index + 220]
    assert "github.event.inputs.commit_outputs" not in trailing


def test_permissions_are_least_privilege_for_analysis_and_commit_jobs() -> None:
    assert "permissions:\n  contents: read" in WORKFLOW_TEXT
    assert WORKFLOW_TEXT.count("contents: write") == 1
    assert "commit-outputs:" in WORKFLOW_TEXT
    assert "permissions:\n      contents: write" in WORKFLOW_TEXT


def test_commit_job_downloads_artifact_before_committing() -> None:
    assert "actions/download-artifact@v4" in WORKFLOW_TEXT
    assert "name: live-enriched-analysis-outputs" in WORKFLOW_TEXT


def test_workflow_archives_full_run_outputs_into_run_archive() -> None:
    assert "python scripts/archive_run_outputs.py" in WORKFLOW_TEXT
    assert "--archive-root outputs/run_archive" in WORKFLOW_TEXT
    assert '--run-id "${{ github.run_id }}-${{ github.run_attempt }}"' in WORKFLOW_TEXT
    assert "validation_state.json" in WORKFLOW_TEXT
    assert "outputs/run_archive/" in WORKFLOW_TEXT
