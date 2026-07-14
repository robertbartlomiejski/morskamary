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
    git_add_index = commit_block.index("git add")
    git_add_line = commit_block[git_add_index : git_add_index + 200]
    assert "outputs/live_runs/" in git_add_line


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
    git_add_index = commit_block.index("git add")
    git_add_line = commit_block[git_add_index : git_add_index + 200]
    assert "outputs/cumulative_database/" in git_add_line


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
    layer1_index = WORKFLOW_TEXT.index("python scripts/build_live_run_audit.py")
    assert layer1_index < package_index


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
