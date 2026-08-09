"""Regression test for scripts/run_research_api_full.sh default MODE handling.

Normal analysis must be live-enriched; static mode is recovery-only (see
.github/copilot-instructions.md). A no-argument invocation of the script must
not silently select the static-recovery path, so this test asserts that the
default MODE value is "full-live" and that the full-static branch remains
gated behind ALLOW_STATIC_RECOVERY_MODE with an explicit reason.
"""

from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).parent.parent / "scripts" / "run_research_api_full.sh"
)


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_default_mode_is_not_full_static() -> None:
    """A bare no-argument invocation must not select static recovery mode."""
    text = _script_text()
    assert 'MODE="full-static"' not in text, (
        "Default MODE must not be full-static; static mode is recovery-only "
        "and must require an explicit --mode full-static/--mode selection."
    )
    assert 'MODE="full-live"' in text, (
        "Default MODE should be full-live so a no-argument invocation "
        "follows the live-enriched analysis path."
    )


def test_static_branch_still_requires_explicit_recovery_gate() -> None:
    """The full-static analysis branch must keep requiring the recovery gate."""
    text = _script_text()
    assert "ALLOW_STATIC_RECOVERY_MODE=true" in text
    assert "STATIC_RECOVERY_REASON" in text
