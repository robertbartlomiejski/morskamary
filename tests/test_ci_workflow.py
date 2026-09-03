from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

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
STATIC_MODE_PATTERN = re.compile(r"--analysis-input-mode\s+['\"]?static\b")


def _static_recovery_scope_errors(workflow: dict[str, Any]) -> tuple[int, list[str]]:
    job = workflow["jobs"]["run-analysis"]
    job_env = job.get("env", {})
    invocation_count = 0
    errors = []

    for step in job["steps"]:
        step_invocation_count = len(
            STATIC_MODE_PATTERN.findall(step.get("run", ""))
        )
        if step_invocation_count == 0:
            continue
        invocation_count += step_invocation_count
        effective_env = {**job_env, **step.get("env", {})}
        if effective_env.get("ALLOW_STATIC_RECOVERY_MODE") != "true":
            errors.append(step["name"])
            continue
        if not effective_env.get("STATIC_RECOVERY_REASON"):
            errors.append(step["name"])

    return invocation_count, errors


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
    static_invocation_count, scope_errors = _static_recovery_scope_errors(
        FULL_ANALYSIS_WORKFLOW
    )

    assert job_env["ALLOW_STATIC_RECOVERY_MODE"] == "true"
    assert (
        job_env["STATIC_RECOVERY_REASON"] == "Full Analysis CI reproducibility check"
    )
    assert static_invocation_count > 0
    assert scope_errors == []
    assert '--baseline-root "$STATIC_COMPARE_ROOT"' in FULL_ANALYSIS_WORKFLOW_TEXT


def test_static_recovery_env_from_an_earlier_step_does_not_cover_later_steps() -> None:
    workflow = {
        "jobs": {
            "run-analysis": {
                "steps": [
                    {
                        "name": "First static invocation",
                        "env": {
                            "ALLOW_STATIC_RECOVERY_MODE": "true",
                            "STATIC_RECOVERY_REASON": "Regression fixture",
                        },
                        "run": "python run_full_analysis.py --analysis-input-mode static",
                    },
                    {
                        "name": "Second static invocation",
                        "run": "python run_full_analysis.py --analysis-input-mode static",
                    },
                ]
            }
        }
    }

    invocation_count, scope_errors = _static_recovery_scope_errors(workflow)

    assert invocation_count == 2
    assert scope_errors == ["Second static invocation"]


def test_full_analysis_clean_tree_blocks_stale_outputs_before_determinism() -> None:
    job = FULL_ANALYSIS_WORKFLOW["jobs"]["run-analysis"]
    steps = job["steps"]
    step_names = [step.get("name") for step in steps]
    snapshot_index = step_names.index(
        "Snapshot committed outputs and detect their analysis mode"
    )
    regeneration_index = step_names.index(
        "Regenerate outputs in the committed analysis mode"
    )
    freshness_index = step_names.index("Check committed outputs are fresh")
    determinism_index = step_names.index(
        "Check static outputs are reproducible in isolation"
    )

    assert snapshot_index < regeneration_index < freshness_index < determinism_index
    snapshot_step = steps[snapshot_index]
    assert snapshot_step["id"] == "committed-outputs"
    assert 'static|live-enriched)' in snapshot_step["run"]
    snapshot_script = snapshot_step["run"]
    assert (
        snapshot_step["env"]["RETAINED_INPUT_ROOT"]
        == "${{ runner.temp }}/full-analysis-retained-inputs"
    )
    assert '"research_sources/live_records_triangulated.json"' in snapshot_script
    assert 'cp -R outputs/. "$COMMITTED_COMPARE_ROOT/"' not in snapshot_script
    for generated_path in (
        "competences_full_database.json",
        "credentials_database.json",
        "credentials_dynamic_database.json",
        "credentials_generation_rationale.json",
        "credentials_matrix.html",
        "cumulative_qmbd_records.json",
        "gap_priority_ranking.csv",
        "gaps_by_sector.html",
        "gaps_by_sector_axis.csv",
        "gaps_detailed.json",
        "gaps_summary.csv",
        "literature_integration.html",
        "report_index.html",
        "sector_dictionaries",
        "sector_pathways.json",
        "sector_qmbd_learning_pathways.json",
    ):
        assert f'"{generated_path}"' in snapshot_script

    regeneration_step = steps[regeneration_index]
    assert (
        '${{ steps.committed-outputs.outputs.analysis_mode }}'
        in regeneration_step["run"]
    )
    cleanup_index = snapshot_script.index("rm -rf outputs")
    restore_index = snapshot_script.index(
        'cp "$RETAINED_INPUT_ROOT/$retained_path" "outputs/$retained_path"'
    )
    assert cleanup_index < restore_index
    assert 'cp -R "$COMMITTED_COMPARE_ROOT/." outputs/' not in snapshot_script

    freshness_step = steps[freshness_index]
    assert '--baseline-root "$COMMITTED_COMPARE_ROOT"' in freshness_step["run"]
    assert (
        freshness_step["env"]["COMMITTED_COMPARE_ROOT"]
        == "${{ runner.temp }}/full-analysis-committed"
    )

    determinism_step = steps[determinism_index]
    determinism_script = determinism_step["run"]
    static_run = "python run_full_analysis.py --analysis-input-mode static"
    assert determinism_script.count(static_run) == 2
    assert (
        determinism_step["env"]["STATIC_INPUT_ROOT"]
        == "${{ runner.temp }}/full-analysis-static-input"
    )
    snapshot_input = 'cp -R outputs/. "$STATIC_INPUT_ROOT/"'
    restore_input = 'cp -R "$STATIC_INPUT_ROOT/." outputs/'
    first_run_index = determinism_script.index(static_run)
    baseline_index = determinism_script.index(
        'cp -R outputs/. "$STATIC_COMPARE_ROOT/"'
    )
    restore_index = determinism_script.index(restore_input)
    second_run_index = determinism_script.index(static_run, first_run_index + 1)
    assert determinism_script.index(snapshot_input) < first_run_index
    assert first_run_index < baseline_index < restore_index < second_run_index
    assert "rm -rf outputs" in determinism_script[baseline_index:restore_index]
    assert '--baseline-root "$STATIC_COMPARE_ROOT"' in determinism_script


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
        assert run_script.count(artifact) >= 2
    tracked_check_index = run_script.index("git ls-files --error-unmatch --")
    diff_check_index = run_script.index("git diff --exit-code --")
    assert tracked_check_index < diff_check_index
    assert '"${projection_paths[@]}"' in run_script
    assert "git diff --exit-code --" in run_script


def test_ci_changelog_guard_step_fetches_non_shallow_base_history() -> None:
    job = CI_WORKFLOW["jobs"]["governance-and-repro"]
    changelog_step = next(
        step
        for step in job["steps"]
        if step.get("name")
        == "Enforce CHANGELOG update on PRs that change tracked artifacts (lightweight rule)"
    )
    run_script = changelog_step["run"]

    assert "git fetch --no-tags --prune --unshallow origin || true" in run_script
    assert 'git fetch --no-tags --prune origin "$base_ref"' in run_script
    assert '--depth=1' not in run_script
