from __future__ import annotations

import os
import subprocess
import textwrap
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
    # The publication job requires exactly one `contents: write` and exactly
    # one `pull-requests: write` because it creates a bot branch and opens a
    # PR against main instead of pushing to main directly.
    assert WORKFLOW_TEXT.count("contents: write") == 1
    assert WORKFLOW_TEXT.count("pull-requests: write") == 1
    assert "commit-outputs:" in WORKFLOW_TEXT
    commit_index = WORKFLOW_TEXT.index("commit-outputs:")
    commit_block = WORKFLOW_TEXT[commit_index:]
    assert "contents: write" in commit_block
    assert "pull-requests: write" in commit_block


def test_all_checkouts_disable_persist_credentials() -> None:
    """Regression test for Fix 9: every actions/checkout in the live-analysis
    workflow must set persist-credentials: false so no reusable Git credential
    is left on a runner that also handles proprietary provider secrets."""
    checkout_count = WORKFLOW_TEXT.count("uses: actions/checkout@")
    # Both the live-analysis and commit-outputs jobs check out the repo.
    assert checkout_count >= 2
    assert WORKFLOW_TEXT.count("persist-credentials: false") == checkout_count


def test_commit_outputs_job_uses_bot_branch_and_pull_request_not_direct_push() -> None:
    """Regression test for Fix 10: the publication path must never push
    generated outputs directly to `main`.  It must create a uniquely named
    bot branch and open a pull request against main."""
    commit_index = WORKFLOW_TEXT.index("commit-outputs:")
    commit_block = WORKFLOW_TEXT[commit_index:]
    # Uniquely named bot branch per run/attempt.
    assert "bot/live-research/" in commit_block
    assert "${RUN_ID}" in commit_block and "${RUN_ATTEMPT}" in commit_block
    # Opens a PR against main via `gh pr create` (no third-party action).
    assert "gh pr create" in commit_block
    assert "--base main" in commit_block
    # No direct `git push` to `main` (only pushes the bot branch).
    assert "HEAD:refs/heads/${BOT_BRANCH}" in commit_block
    assert "git push origin main" not in commit_block
    assert "git push origin HEAD:main" not in commit_block
    # Explicit failure to open PR is required, not silent success.
    assert "Failed to open pull request" in commit_block


def test_commit_outputs_job_runs_under_live_research_environment() -> None:
    """Regression test for Fix 10: the publication job must be gated behind
    the same reviewer-approved environment as the live-analysis job."""
    commit_index = WORKFLOW_TEXT.index("commit-outputs:")
    commit_block = WORKFLOW_TEXT[commit_index:]
    assert "environment: live-research" in commit_block


def test_commit_outputs_job_preserves_double_publication_gate() -> None:
    """Regression test for Fix 10: publication remains disabled-by-default via
    the existing double (workflow_dispatch) / triple (schedule) gate."""
    commit_index = WORKFLOW_TEXT.index("commit-outputs:")
    commit_block = WORKFLOW_TEXT[commit_index:]
    assert "vars.ALLOW_BOT_COMMITS == 'true'" in commit_block
    assert "github.event.inputs.commit_outputs == 'true'" in commit_block
    assert "vars.LIVE_OUTPUTS_AUTOCOMMIT == 'true'" in commit_block


def test_commit_job_downloads_artifact_before_committing() -> None:
    assert "actions/download-artifact@v4" in WORKFLOW_TEXT
    assert "name: live-enriched-analysis-outputs" in WORKFLOW_TEXT


def test_workflow_archives_full_run_outputs_into_run_archive() -> None:
    assert "python scripts/archive_run_outputs.py" in WORKFLOW_TEXT
    assert "--archive-root outputs/run_archive" in WORKFLOW_TEXT
    assert '--run-id "${{ github.run_id }}-${{ github.run_attempt }}"' in WORKFLOW_TEXT
    assert "python scripts/validate_run_archive_integrity.py" in WORKFLOW_TEXT
    assert "--require-present" in WORKFLOW_TEXT
    assert "validation_state.json" in WORKFLOW_TEXT
    assert "outputs/run_archive/" in WORKFLOW_TEXT


def test_workflow_builds_layer1_live_run_audit_bundle() -> None:
    assert "python scripts/build_live_run_audit.py" in WORKFLOW_TEXT
    assert "--research-sources-dir outputs/research_sources" in WORKFLOW_TEXT
    assert "--output-root outputs/live_runs" in WORKFLOW_TEXT
    assert "--protocol-path config/live_query_protocol.yml" in WORKFLOW_TEXT


def test_workflow_projects_protocol_before_exporting_live_records() -> None:
    assert "python scripts/export_live_query_protocol_projection.py" in WORKFLOW_TEXT
    assert "--output-path outputs/research_sources/research_queries_from_protocol.yml" in (
        WORKFLOW_TEXT
    )
    projection_index = WORKFLOW_TEXT.index(
        "python scripts/export_live_query_protocol_projection.py"
    )
    export_index = WORKFLOW_TEXT.index("python scripts/export_live_research_records.py")
    assert projection_index < export_index
    export_block = WORKFLOW_TEXT[export_index : export_index + 300]
    assert "--query-file outputs/research_sources/research_queries_from_protocol.yml" in (
        export_block
    )


def test_layer1_run_id_matches_archive_run_id_convention() -> None:
    build_index = WORKFLOW_TEXT.index("python scripts/build_live_run_audit.py")
    build_step = WORKFLOW_TEXT[build_index : build_index + 500]
    assert (
        '--run-id "${{ github.run_id }}-${{ github.run_attempt }}"'
        in build_step
    )


def test_workflow_uploads_live_runs_directory_as_artifact() -> None:
    upload_index = WORKFLOW_TEXT.index("name: live-enriched-analysis-outputs")
    upload_block = WORKFLOW_TEXT[upload_index : upload_index + 500]
    assert "outputs/live_runs/" in upload_block


def test_commit_outputs_job_stages_live_runs_directory() -> None:
    commit_index = WORKFLOW_TEXT.index("commit-outputs:")
    commit_block = WORKFLOW_TEXT[commit_index:]
    assert "git add" in commit_block
    assert "outputs/live_runs/" in commit_block


def test_workflow_builds_layer23_cumulative_scientific_database() -> None:
    assert "python scripts/build_cumulative_scientific_database.py" in WORKFLOW_TEXT
    assert "--current-run outputs" in WORKFLOW_TEXT
    assert "--archive-root outputs/run_archive" in WORKFLOW_TEXT
    assert "--live-runs-root outputs/live_runs" in WORKFLOW_TEXT
    assert "--query-protocol config/live_query_protocol.yml" in WORKFLOW_TEXT
    assert "--output-dir outputs/cumulative_database" in WORKFLOW_TEXT
    build_index = WORKFLOW_TEXT.index(
        "python scripts/build_cumulative_scientific_database.py"
    )
    build_block = WORKFLOW_TEXT[build_index : build_index + 600]
    assert (
        '--current-run-id "${{ github.run_id }}-${{ github.run_attempt }}"'
        in build_block
    )


def test_layer23_step_runs_after_archive_integrity_validation() -> None:
    integrity_index = WORKFLOW_TEXT.index(
        "python scripts/validate_run_archive_integrity.py"
    )
    layer23_index = WORKFLOW_TEXT.index(
        "python scripts/build_cumulative_scientific_database.py"
    )
    assert integrity_index < layer23_index, (
        "Layer 2-3 build must run after archived-run integrity validation."
    )


def test_workflow_uploads_cumulative_database_directory_as_artifact() -> None:
    upload_index = WORKFLOW_TEXT.index("name: live-enriched-analysis-outputs")
    upload_block = WORKFLOW_TEXT[upload_index : upload_index + 500]
    assert "outputs/cumulative_database/" in upload_block


def test_workflow_evaluates_novelty_gates_in_strict_mode() -> None:
    step_index = WORKFLOW_TEXT.index("python scripts/compute_live_novelty_metrics.py")
    step_block = WORKFLOW_TEXT[step_index : step_index + 400]
    assert "--strict" in step_block


def test_commit_outputs_job_stages_cumulative_database_directory() -> None:
    commit_index = WORKFLOW_TEXT.index("commit-outputs:")
    commit_block = WORKFLOW_TEXT[commit_index:]
    assert "outputs/cumulative_database/" in commit_block


def test_commit_outputs_job_avoids_broad_outputs_staging_and_unstages_raw_payloads() -> None:
    commit_index = WORKFLOW_TEXT.index("commit-outputs:")
    commit_block = WORKFLOW_TEXT[commit_index:]
    assert "git add \\\n            outputs/ \\" not in commit_block
    assert "outputs/research_sources/" in commit_block
    assert "git reset --quiet -- ':(glob)outputs/**/raw_api_payloads/**'" in commit_block


def test_release_package_step_passes_stats_dir_and_raw_acquisition_index() -> None:
    package_index = WORKFLOW_TEXT.index(
        "python scripts/build_live_cumulative_release_package.py"
    )
    package_block = WORKFLOW_TEXT[package_index : package_index + 700]
    assert "--stats-dir outputs/layer4_statistics" in package_block
    assert (
        '--raw-acquisition-index "outputs/live_runs/${{ github.run_id }}-${{ github.run_attempt }}/raw/raw_acquisition_index.csv"'
        in package_block
    )
    assert '--current-run-id "${{ github.run_id }}-${{ github.run_attempt }}"' in package_block
    layer1_index = WORKFLOW_TEXT.index("python scripts/build_live_run_audit.py")
    assert layer1_index < package_index


def test_statistical_report_step_is_current_run_scoped() -> None:
    report_index = WORKFLOW_TEXT.index("python scripts/build_statistical_research_report.py")
    report_block = WORKFLOW_TEXT[report_index : report_index + 400]
    assert '--current-run-id "${{ github.run_id }}-${{ github.run_attempt }}"' in report_block


def test_workflow_captures_single_analysis_timestamp_before_layer45() -> None:
    """Recency-sensitive Layer 4-5 outputs must be deterministic within a run.
    The workflow must capture one workflow-level UTC timestamp into
    ANALYSIS_TIMESTAMP_UTC before invoking the Layer 4-5 build, so no
    downstream published-recency calculation calls wall-clock ``datetime.now()``
    independently."""
    assert "ANALYSIS_TIMESTAMP_UTC=" in WORKFLOW_TEXT
    capture_index = WORKFLOW_TEXT.index("ANALYSIS_TIMESTAMP_UTC=")
    layer45_index = WORKFLOW_TEXT.index(
        "python scripts/build_layer4_5_scientific_analysis.py"
    )
    assert capture_index < layer45_index, (
        "ANALYSIS_TIMESTAMP_UTC must be captured before the Layer 4-5 build step."
    )
    # The capture step must derive the timestamp exactly once via `date -u`
    # so all downstream consumers share the identical value.
    assert 'ANALYSIS_TS="$(date -u' in WORKFLOW_TEXT


def test_layer45_step_passes_fixed_analysis_timestamp_utc() -> None:
    """The Layer 4-5 build step must pass ``--analysis-timestamp-utc`` bound to
    the single workflow-level ``ANALYSIS_TIMESTAMP_UTC`` env var captured
    earlier in the same job."""
    layer45_index = WORKFLOW_TEXT.index(
        "python scripts/build_layer4_5_scientific_analysis.py"
    )
    layer45_block = WORKFLOW_TEXT[layer45_index : layer45_index + 600]
    assert "--analysis-timestamp-utc" in layer45_block
    assert '"$ANALYSIS_TIMESTAMP_UTC"' in layer45_block


def test_export_step_passes_generated_constraints_path() -> None:
    """The export step must explicitly pass ``--query-constraints-file`` so that
    authoritative constraints from the protocol projection are enforced rather
    than falling back silently to ad-hoc defaults."""
    export_index = WORKFLOW_TEXT.index(
        "python scripts/export_live_research_records.py"
    )
    export_block = WORKFLOW_TEXT[export_index : export_index + 600]
    assert "--query-constraints-file" in export_block
    assert "query_protocol_constraints.json" in export_block


def test_workflow_dispatch_declares_allow_minimum_provider_contribution_input() -> None:
    """The controlled-acquisition input must be declared as a workflow_dispatch
    choice input, defaulting to 'true', so Gate A/E coherence behavior in
    scripts/compute_live_novelty_metrics.py can be toggled per run."""
    assert "allow_minimum_provider_contribution:" in WORKFLOW_TEXT
    input_index = WORKFLOW_TEXT.index("allow_minimum_provider_contribution:")
    input_block = WORKFLOW_TEXT[input_index : input_index + 320]
    assert 'required: false' in input_block
    assert 'default: "true"' in input_block
    assert "type: choice" in input_block
    assert 'options: ["true", "false"]' in input_block
    # This input must be declared before the publication (commit_outputs) input.
    commit_index = WORKFLOW_TEXT.index("commit_outputs:")
    assert input_index < commit_index


def test_allow_minimum_provider_contribution_env_var_defaults_true() -> None:
    """The job-level env var must be wired from the dispatch input with a
    'true' fallback, matching the input's own default so scheduled (non
    workflow_dispatch) runs still get controlled-acquisition behavior."""
    assert (
        "ALLOW_MINIMUM_PROVIDER_CONTRIBUTION: "
        "${{ github.event.inputs.allow_minimum_provider_contribution || 'true' }}"
        in WORKFLOW_TEXT
    )


def test_novelty_gate_step_conditionally_builds_allow_minimum_provider_contribution_flag() -> None:
    """The 'Evaluate live novelty gates (A-E)' step must build a GATE_ARGS
    array and only append --allow-minimum-provider-contribution when the env
    var is exactly 'true', then pass GATE_ARGS alongside --strict."""
    step_index = WORKFLOW_TEXT.index("Evaluate live novelty gates (A-E)")
    step_block = WORKFLOW_TEXT[step_index : step_index + 800]

    assert "GATE_ARGS=()" in step_block
    assert 'if [ "$ALLOW_MINIMUM_PROVIDER_CONTRIBUTION" = "true" ]; then' in step_block
    assert "GATE_ARGS+=(--allow-minimum-provider-contribution)" in step_block
    assert "python scripts/compute_live_novelty_metrics.py" in step_block
    assert "--strict" in step_block
    assert '"${GATE_ARGS[@]}"' in step_block

    # GATE_ARGS must be computed before the python invocation, and the
    # conditional flag must be appended after --strict so strict enforcement
    # is never silently disabled by the optional gate args.
    build_index = step_block.index("GATE_ARGS=()")
    strict_index = step_block.index("--strict")
    invocation_index = step_block.index("python scripts/compute_live_novelty_metrics.py")
    gate_args_usage_index = step_block.index('"${GATE_ARGS[@]}"')
    assert build_index < invocation_index < strict_index < gate_args_usage_index


def test_novelty_gate_step_runs_after_layer45_build() -> None:
    """Novelty gate evaluation consumes run_novelty_metrics.json, which is
    only produced once the Layer 4-5 competence/gap model has been built."""
    layer45_index = WORKFLOW_TEXT.index(
        "python scripts/build_layer4_5_scientific_analysis.py"
    )
    gate_index = WORKFLOW_TEXT.index("python scripts/compute_live_novelty_metrics.py")
    assert layer45_index < gate_index


def _extract_gate_args_bash_snippet() -> str:
    """Extract and dedent the GATE_ARGS-building bash snippet (up to and
    including the closing 'fi') from the 'Evaluate live novelty gates (A-E)'
    step, without the Python invocation that follows it."""
    step_index = WORKFLOW_TEXT.index("Evaluate live novelty gates (A-E)")
    fi_index = WORKFLOW_TEXT.index("fi\n", step_index)
    python_index = WORKFLOW_TEXT.index(
        "python scripts/compute_live_novelty_metrics.py", step_index
    )
    assert fi_index < python_index, (
        "Expected the GATE_ARGS conditional to close before the python "
        "invocation in the workflow step."
    )
    snippet = WORKFLOW_TEXT[step_index : fi_index + len("fi\n")]
    run_marker = "run: |\n"
    assert run_marker in snippet
    body = snippet.split(run_marker, 1)[1]
    return textwrap.dedent(body)


def _run_gate_args_snippet(allow_value: str) -> str:
    """Execute the real GATE_ARGS bash snippet from the workflow with
    ALLOW_MINIMUM_PROVIDER_CONTRIBUTION set to ``allow_value``, and return the
    resulting GATE_ARGS array contents (one element per line)."""
    body = _extract_gate_args_bash_snippet()
    script = body + '\nprintf "%s\\n" "${GATE_ARGS[@]}"\n'
    env = dict(os.environ)
    env["ALLOW_MINIMUM_PROVIDER_CONTRIBUTION"] = allow_value
    result = subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_gate_args_bash_logic_adds_flag_when_allowed() -> None:
    """Regression test: executing the actual bash conditional extracted from
    the workflow with the env var set to 'true' must produce a GATE_ARGS
    array containing exactly --allow-minimum-provider-contribution."""
    stdout = _run_gate_args_snippet("true")
    assert stdout.strip() == "--allow-minimum-provider-contribution"


def test_gate_args_bash_logic_omits_flag_when_disallowed() -> None:
    """Negative/boundary case: when the env var is 'false' the GATE_ARGS array
    must remain empty, so no --allow-minimum-provider-contribution flag is
    ever passed to scripts/compute_live_novelty_metrics.py."""
    stdout = _run_gate_args_snippet("false")
    assert stdout.strip() == ""


def test_gate_args_bash_logic_omits_flag_for_unrecognized_value() -> None:
    """Boundary case: any value other than the literal string 'true' (e.g. an
    empty string, or an unexpected value) must not enable the controlled
    acquisition flag, since the bash comparison is a strict string equality
    check rather than a truthy/falsy coercion."""
    for value in ("", "TRUE", "1", "yes"):
        stdout = _run_gate_args_snippet(value)
        assert stdout.strip() == "", f"unexpected flag for value={value!r}"
