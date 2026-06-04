"""Tests for cumulative update merge script HTML restoration behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.cumulative_update_merge_full_live_enriched_and_static_all_outputs_fragmented_analysis import (
    Candidate,
    _is_mergeable_repo_path,
    _merge_candidate_groups,
)


def test_is_mergeable_repo_path_includes_html_only_when_requested() -> None:
    path = "outputs/report_index.html"
    assert _is_mergeable_repo_path(path, include_html=False) is False
    assert _is_mergeable_repo_path(path, include_html=True) is True


def test_merge_candidate_groups_writes_largest_html_candidate(tmp_path: Path) -> None:
    grouped = {
        "outputs/report_index.html": [
            Candidate("ref:main", "outputs/report_index.html", b"<html>small</html>"),
            Candidate(
                "input-dir:/tmp/artifact",
                "outputs/report_index.html",
                b"<html><body>this candidate is larger and should win</body></html>",
            ),
        ]
    }

    with patch(
        "scripts.cumulative_update_merge_full_live_enriched_and_static_all_outputs_fragmented_analysis.REPO_ROOT",
        tmp_path,
    ):
        manifest = _merge_candidate_groups(grouped, dry_run=False)

    out = tmp_path / "outputs" / "report_index.html"
    assert out.exists()
    assert out.read_bytes() == grouped["outputs/report_index.html"][1].payload
    assert manifest["outputs/report_index.html"]["status"] == "written"
    assert manifest["outputs/report_index.html"]["mode"] == "passthrough"
    assert manifest["outputs/report_index.html"]["selected_source"] == "input-dir:/tmp/artifact"
