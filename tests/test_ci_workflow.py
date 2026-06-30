from __future__ import annotations

from pathlib import Path

WORKFLOW_TEXT = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
).read_text(encoding="utf-8")
BLANK_WORKFLOW_TEXT = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "blank.yml"
).read_text(encoding="utf-8")


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
    assert "python -m flake8 ." in WORKFLOW_TEXT
    assert 'python -m flake8 $(git ls-files "*.py")' not in WORKFLOW_TEXT
    assert "python -m mypy src scripts run_full_analysis.py main.py" in WORKFLOW_TEXT
