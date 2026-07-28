"""Contract tests for the protected full-live workflow."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/full-live-analysis.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


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
    assert '"abort_on_budget_exceeded": True' in text


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
        text.index("Archive immutable current-run outputs"):
        text.index("Build cross-run stability outside immutable archives")
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


def test_automatic_output_publication_is_removed() -> None:
    text = _text()
    assert "commit-outputs:" not in text
    assert "gh pr create" not in text
    assert "LIVE_OUTPUTS_AUTOCOMMIT" not in text
    assert '"automatic_publication_performed": False' in text


def test_exploratory_provider_relaxation_does_not_apply_to_replication() -> None:
    text = _text()
    gate_block = text[
        text.index("Evaluate live novelty gates"):
        text.index("Archive immutable current-run outputs")
    ]
    assert 'if [ "$EXECUTION_MODE" = "exploratory_live" ]' in gate_block
    assert "--allow-minimum-provider-contribution" in gate_block
