"""Tests for scripts.cumulative_fragment_analysis cumulative provenance workflow."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.cumulative_fragment_analysis import (
    compute_fragment_id,
    load_state,
    update_state,
    FragmentInput,
    write_state,
)


def test_compute_fragment_id_is_stable_and_case_insensitive() -> None:
    fragment_id_1 = compute_fragment_id("10.1234/ABC", "A sentence about ports.  ")
    fragment_id_2 = compute_fragment_id("10.1234/ABC", "a sentence about ports.")
    assert fragment_id_1 == fragment_id_2


def test_update_state_skips_duplicates_across_runs(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"

    state = load_state(state_path)
    stats_first = update_state(
        state,
        [FragmentInput(doi="10.1/doi", text="Port logistics need training.")],
        input_path=tmp_path / "input.json",
    )
    assert stats_first["added"] == 1
    assert stats_first["skipped"] == 0

    stats_second = update_state(
        state,
        [
            FragmentInput(doi="10.1/doi", text="Port logistics need training."),
            FragmentInput(doi="10.1/doi", text="Port logistics need training.  "),
        ],
        input_path=tmp_path / "input.json",
    )
    assert stats_second["added"] == 0
    assert stats_second["skipped"] == 2

    assert len(state["fragments"]) == 1

    write_state(state, state_path)
    reloaded = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(reloaded["fragments"]) == 1
