from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW_TEXT = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
).read_text(encoding="utf-8")
BLANK_WORKFLOW_TEXT = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "blank.yml"
).read_text(encoding="utf-8")
FULL_ANALYSIS_WORKFLOW_TEXT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "full-analysis.yml"
).read_text(encoding="utf-8")
FULL_ANALYSIS_WORKFLOW = yaml.safe_load(FULL_ANALYSIS_WORKFLOW_TEXT)
CI_WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)


def test_quick_mode_gate_validates_run_archive_integrity() -> None:
    assert "Validate archived run integrity (if archive exists)" in WORKFLOW_TEXT
    assert (
        "python scripts/validate_run_archive_integrity.py --archive-root outputs/run_archive"
        in WORKFLOW_TEXT
    )


def test_blank_workflow_installs_and_runs_flake8_via_python_module() -> None:
    assert "name: Install flake8" in BLANK_WORKFLOW_TEXT
    assert "python -m pip install flake8" in BLANK_WORKFLOW_TEXT
    assert "python -m flake8 src/ tests/" in BLANK_WORKFLOW_TEXT


def test_ci_static_quality_job_runs_module_based_flake8_and_mypy() -> None:
    assert "static-quality:" in WORKFLOW_TEXT
    assert 'python-version: "3.10"' in WORKFLOW_TEXT
    assert "python -m flake8 src scripts tests run_full_analysis.py main.py" in WORKFLOW_TEXT
    assert 'python -m flake8 $(git ls-files "*.py")' not in WORKFLOW_TEXT
    assert "python -m mypy src scripts run_full_analysis.py main.py" in WORKFLOW_TEXT


def test_full_analysis_workflow_uses_explicit_static_recovery_mode() -> None:
    job = FULL_ANALYSIS_WORKFLOW["jobs"]["run-analysis"]
    job_env = job["env"]
    static_steps = [
        step
        for step in job["steps"]
        if "python run_full_analysis.py --analysis-input-mode static" in step.get("run", "")
    ]

    assert static_steps
    assert job_env["ALLOW_STATIC_RECOVERY_MODE"] == "true"
    assert (
        job_env["STATIC_RECOVERY_REASON"] == "Full Analysis CI reproducibility check"
    )
    for step in static_steps:
        step_env = step.get("env", {})
        effective_env = {**job_env, **step_env}
        assert effective_env["ALLOW_STATIC_RECOVERY_MODE"] == "true"
        assert (
            effective_env["STATIC_RECOVERY_REASON"]
            == "Full Analysis CI reproducibility check"
        )

    assert '--baseline-root "$STATIC_COMPARE_ROOT"' in FULL_ANALYSIS_WORKFLOW_TEXT


def test_ci_workflow_revalidates_tracked_protocol_projection_outputs() -> None:
    job = CI_WORKFLOW["jobs"]["governance-and-repro"]
    projection_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Verify authoritative protocol projection is committed and in sync"
    )
    run_script = projection_step["run"]

    assert (
        "python scripts/export_live_query_protocol_projection.py" in run_script
    )
    for artifact in (
        "outputs/research_sources/research_queries_from_protocol.yml",
        "outputs/research_sources/research_queries_from_protocol_summary.json",
        "outputs/research_sources/query_protocol_constraints.json",
    ):
        assert artifact in run_script
    assert "git diff --exit-code --" in run_script
