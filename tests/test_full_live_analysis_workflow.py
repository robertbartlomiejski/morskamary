"""Contract tests for the protected full-live workflow."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(".github/workflows/full-live-analysis.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _run_block_text() -> str:
    blocks: list[str] = []
    in_run = False
    run_indent = 0
    for line in _text().splitlines():
        if re.match(r"\s+run:\s*[|>][+-]?\s*$", line):
            in_run = True
            run_indent = len(line) - len(line.lstrip())
            continue
        if in_run:
            indent = len(line) - len(line.lstrip())
            if line.strip() and indent <= run_indent:
                in_run = False
            else:
                blocks.append(line)
    return "\n".join(blocks)


def test_full_live_is_manual_and_defaults_to_no_provider_calls() -> None:
    text = _text()
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "default: hardening_dry_run" in text
    assert "if: inputs.execution_mode == 'hardening_dry_run'" in text
    assert "if: inputs.execution_mode != 'hardening_dry_run'" in text


def test_live_calls_require_exact_authorization_and_protected_environment() -> None:
    text = _text()
    assert "environment: live-research" in text
    assert "AUTHORIZE_LIVE_PROVIDER_CALLS" in text
    assert "Live provider calls are frozen" in text
    assert "ALLOW_PUBLICATION_RELEASES" in text
    assert "publication_candidate" in text


def test_workflow_uses_explicit_page_contract_and_budget() -> None:
    text = _text()
    assert "logical_pages:" in text
    assert "rows_per_page:" in text
    assert "MAX_RESULTS_PER_QUERY" in text
    assert "api_budget_plan.json" in text
    plan = Path("scripts/prepare_live_acquisition_plan.py").read_text(encoding="utf-8")
    assert '"abort_on_budget_exceeded": True' in plan


def test_acquisition_plan_is_validated_before_provider_calls() -> None:
    text = _text()
    projection = text.index("Project and validate authoritative live query protocol")
    plan = text.index("Validate and materialize acquisition plan")
    health = text.index("Provider health preflight")
    acquisition = text.index("Export live research records")
    assert projection < plan < health < acquisition
    assert "scripts/prepare_live_acquisition_plan.py" in text


def test_failed_pre_acquisition_run_cannot_upload_stale_evidence() -> None:
    text = _text()
    clear = text.index("Clear stale committed run directories for current run ID")
    plan = text.index("Validate and materialize acquisition plan")
    assert clear < plan
    assert "rm -f outputs/research_sources/query_execution_log.csv" in text
    assert "rm -f outputs/cumulative_database/novelty_gate_report.json" in text
    for upload in (
        "Upload curated release",
        "Upload short-retention debug files",
        "Upload current-run audit",
    ):
        block = text[text.index(f"- name: {upload}") :]
        assert "if: success()" in block.split("uses:", 1)[0]


def test_h2_map_is_built_then_consumed_only_when_validated() -> None:
    text = _text()
    map_pos = text.index("Build and conditionally consume validated H2 supply map")
    map_arg_pos = text.index("--validated-supply-map", map_pos)
    sensitivity_pos = text.index("Build fail-closed provider sensitivity diagnostics")
    assert map_pos < map_arg_pos < sensitivity_pos
    assert 'if [ "$HAS_SUPPLY" = "true" ]' in text


def test_current_run_is_archived_before_cross_run_stability() -> None:
    text = _text()
    archive_pos = text.index("Archive immutable current-run outputs")
    validate_pos = text.index("validate_run_archive_integrity.py", archive_pos)
    stability_pos = text.index("Build cross-run stability outside immutable archives")
    report_path_pos = text.index(
        "outputs/cross_run_reports/run_stability_report.json",
        stability_pos,
    )
    assert archive_pos < validate_pos < stability_pos < report_path_pos


def test_cross_run_report_is_not_archived_as_current_run_payload() -> None:
    text = _text()
    archive_block = text[
        text.index("Archive immutable current-run outputs") : text.index(
            "Build cross-run stability outside immutable archives"
        )
    ]
    assert "run_stability_report.json" not in archive_block


def test_artifacts_are_tiered_and_do_not_repeat_outputs_root() -> None:
    text = _text()
    assert "name: morskamary-release-" in text
    assert "name: morskamary-run-audit-" in text
    assert "name: morskamary-debug-" in text
    assert "\n            outputs/\n" not in text
    assert "outputs/run_archive/\n" not in text
    assert "retention-days: 7" in text


def test_github_context_is_passed_through_env_before_shell_use() -> None:
    text = _text()
    run_text = _run_block_text()
    assert "GH_CONTEXT_RUN_ID: ${{ github.run_id }}" in text
    assert "GH_CONTEXT_RUN_ATTEMPT: ${{ github.run_attempt }}" in text
    assert "GH_CONTEXT_SHA: ${{ github.sha }}" in text
    assert "${{ github." not in run_text


def test_uploaded_artifacts_exclude_raw_api_payloads() -> None:
    text = _text()
    assert "!outputs/release_packages/**/raw_api_payloads/**" in text
    assert "!outputs/run_archive/**/raw_api_payloads/**" in text
    assert "!outputs/live_runs/**/raw_api_payloads/**" in text
    assert "!outputs/research_sources/raw_api_payloads/**" in text
    assert "!outputs/cumulative_database/**/raw_api_payloads/**" in text


def test_automatic_output_publication_is_removed() -> None:
    text = _text()
    assert "commit-outputs:" not in text
    assert "gh pr create" not in text
    assert "LIVE_OUTPUTS_AUTOCOMMIT" not in text
    assert '"automatic_publication_performed": False' in text


def test_exploratory_provider_relaxation_does_not_apply_to_replication() -> None:
    text = _text()
    gate_block = text[
        text.index("Evaluate live novelty gates") : text.index(
            "Archive immutable current-run outputs"
        )
    ]
    assert 'if [ "$EXECUTION_MODE" = "exploratory_live" ]' in gate_block
    assert "--allow-minimum-provider-contribution" in gate_block


def test_stability_thresholds_are_explicit_in_workflow() -> None:
    """Workflow must pass saturation thresholds explicitly so default drift cannot
    silently change the published method."""
    text = _text()
    stability_block = text[
        text.index("Build cross-run stability outside immutable archives") : text.index(
            "Build reports and curated release package"
        )
    ]
    assert "--jaccard-threshold 0.90" in stability_block
    assert "--new-doi-threshold 0.05" in stability_block
    assert "--axis-stability-threshold 0.95" in stability_block


def test_budget_ceiling_enforcement_step_exists_after_acquisition() -> None:
    """The workflow must enforce the logical-request ceiling immediately after
    acquisition and before source validation or downstream analysis."""
    text = _text()

    export_pos = text.index("Export live research records")
    budget_pos = text.index("Enforce post-acquisition logical-request budget ceiling")
    validate_pos = text.index("Validate live research source outputs")

    assert export_pos < budget_pos < validate_pos, (
        "budget ceiling enforcement must occur after acquisition and before validation"
    )


def test_budget_step_invokes_check_budget_ceiling_script() -> None:
    """The budget enforcement step must invoke scripts/check_budget_ceiling.py
    (the deterministic offline-testable validator) rather than inline Python."""
    text = _text()
    budget_block = text[
        text.index("Enforce post-acquisition logical-request budget ceiling") : text.index(
            "Validate live research source outputs"
        )
    ]
    assert "scripts/check_budget_ceiling.py" in budget_block, (
        "budget step must call python scripts/check_budget_ceiling.py"
    )


def test_check_budget_ceiling_script_contains_fail_closed_contracts() -> None:
    """The deterministic budget ceiling validator must enforce all required contracts:
    api_budget_plan.json, query_execution_log.csv, maximum_total_logical_requests,
    logical_pages_attempted, and sys.exit on any violation."""
    script = Path("scripts/check_budget_ceiling.py").read_text(encoding="utf-8")
    assert "api_budget_plan.json" in script
    assert "query_execution_log.csv" in script
    assert "maximum_total_logical_requests" in script
    assert "logical_pages_attempted" in script
    assert "sys.exit" in script


def test_check_budget_ceiling_script_rejects_bool_ceiling() -> None:
    """The validator must reject boolean maximum_total_logical_requests."""
    script = Path("scripts/check_budget_ceiling.py").read_text(encoding="utf-8")
    assert "bool" in script, (
        "validator must explicitly check for and reject boolean ceiling values"
    )


def test_check_budget_ceiling_script_requires_header_column() -> None:
    """The validator must explicitly verify logical_pages_attempted is in CSV fieldnames."""
    script = Path("scripts/check_budget_ceiling.py").read_text(encoding="utf-8")
    assert "fieldnames" in script, (
        "validator must check CSV fieldnames to ensure the required column is present"
    )


def test_no_github_expression_in_shell_run_blocks() -> None:
    """No ${{ github.* }} expression must appear in any run: shell body."""
    run_text = _run_block_text()
    assert "${{ github." not in run_text, (
        "github.* values must be passed through env:, not interpolated in shell"
    )
