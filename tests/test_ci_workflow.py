from __future__ import annotations

from pathlib import Path


WORKFLOW_TEXT = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
).read_text(encoding="utf-8")


def test_quick_mode_gate_validates_run_archive_integrity() -> None:
    assert "Validate archived run integrity (if archive exists)" in WORKFLOW_TEXT
    assert (
        "python scripts/validate_run_archive_integrity.py --archive-root outputs/run_archive"
        in WORKFLOW_TEXT
    )
