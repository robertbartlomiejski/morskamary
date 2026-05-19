"""Tests for scripts.cumulative_fragment_analysis cumulative provenance workflow."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.cumulative_fragment_analysis import (
    compute_frequencies,
    compute_fragment_id,
    emergent_discovery,
    load_fragments,
    load_state,
    main,
    normalize_fragment_record,
    parse_args,
    qmbd_label_from_text,
    update_state,
    FragmentInput,
    write_fragments_csv,
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


def test_normalize_fragment_record_supports_alternate_keys() -> None:
    normalized = normalize_fragment_record(
        {"DOI": "10.2/test", "original_fragment": "  Coastal literacy gap  "}
    )
    assert normalized == FragmentInput(doi="10.2/test", text="Coastal literacy gap")


def test_normalize_fragment_record_returns_none_for_blank_text() -> None:
    assert normalize_fragment_record({"doi": "10.2/test", "text": "   "}) is None


def test_load_fragments_supports_json_jsonl_csv(tmp_path: Path) -> None:
    json_path = tmp_path / "input.json"
    json_path.write_text(
        json.dumps([{"doi": "10.1/a", "text": "Port training needed"}]),
        encoding="utf-8",
    )
    jsonl_path = tmp_path / "input.jsonl"
    jsonl_path.write_text(
        '{"doi":"10.1/b","sentence":"Ocean policy challenge"}\n',
        encoding="utf-8",
    )
    csv_path = tmp_path / "input.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source_doi", "fragment"])
        writer.writeheader()
        writer.writerow({"source_doi": "10.1/c", "fragment": "Hydrosocial river lens"})

    assert load_fragments(json_path) == [
        FragmentInput(doi="10.1/a", text="Port training needed")
    ]
    assert load_fragments(jsonl_path) == [
        FragmentInput(doi="10.1/b", text="Ocean policy challenge")
    ]
    assert load_fragments(csv_path) == [
        FragmentInput(doi="10.1/c", text="Hydrosocial river lens")
    ]


def test_load_fragments_validation_errors(tmp_path: Path) -> None:
    bad_json = tmp_path / "bad.json"
    bad_json.write_text(
        json.dumps({"doi": "10.1/x", "text": "not list"}), encoding="utf-8"
    )
    unsupported = tmp_path / "input.txt"
    unsupported.write_text("x", encoding="utf-8")

    try:
        load_fragments(bad_json)
        assert False, "Expected ValueError for non-list JSON payload"
    except ValueError as exc:
        assert "JSON input must be a list" in str(exc)

    try:
        load_fragments(unsupported)
        assert False, "Expected ValueError for unsupported extension"
    except ValueError as exc:
        assert "Unsupported input format" in str(exc)


def test_load_state_tolerates_corrupt_or_invalid_shapes(tmp_path: Path) -> None:
    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("{not-json", encoding="utf-8")
    corrupt_state = load_state(corrupt_path)
    assert corrupt_state["fragments"] == {}
    assert corrupt_state["runs"] == []

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(
        json.dumps({"schema_version": "5", "fragments": [], "runs": {}}),
        encoding="utf-8",
    )
    invalid_state = load_state(invalid_path)
    assert invalid_state["schema_version"] == 5
    assert invalid_state["fragments"] == {}
    assert invalid_state["runs"] == []


def test_qmbd_label_and_emergent_discovery_keywords() -> None:
    assert qmbd_label_from_text("Hydrosocial estuary transitions") == "HYDRONIZATION"
    assert qmbd_label_from_text("   ") == "UNCLASSIFIED"
    assert qmbd_label_from_text("Port logistics and infrastructure") == "MARITIME"

    result = emergent_discovery(
        "Market investment in AI infrastructure needs training and policy support"
    )
    assert result["emerged_domains"] == ["ECONOMY", "TECHNOLOGY", "POLITICS"]
    assert "training" in result["skill_terms"]
    assert "need" in result["gap_terms"]


def test_compute_frequencies_and_write_fragments_csv(tmp_path: Path) -> None:
    state = {
        "fragments": {
            "frag-1": {
                "doi": "10.1/a",
                "text": "A",
                "added_at": "2026-01-01T00:00:00+00:00",
                "variant_1": {
                    "tmbd_axis": "MARITIME",
                    "tmbd_code": "T",
                    "qmbd_label": "MARITIME",
                },
                "variant_2": {
                    "emerged_domains": ["TECHNOLOGY"],
                    "skill_terms": [],
                    "gap_terms": [],
                },
            },
            "frag-2": {
                "doi": "10.1/b",
                "text": "B",
                "added_at": "2026-01-01T00:00:00+00:00",
                "variant_1": {
                    "tmbd_axis": "MARITIME",
                    "tmbd_code": "T",
                    "qmbd_label": "HYDRONIZATION",
                },
                "variant_2": {"emerged_domains": ["TECHNOLOGY", "ECONOMY"]},
            },
            "bad": "skip-me",
        }
    }
    freqs = compute_frequencies(state)
    assert freqs["variant_1_tmbd"]["MARITIME"] == 2
    assert freqs["variant_1_qmbd"]["HYDRONIZATION"] == 1
    assert freqs["variant_2_domains"]["TECHNOLOGY"] == 2

    csv_path = tmp_path / "out.csv"
    write_fragments_csv(state, csv_path)
    rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 2
    assert rows[0]["doi"] == "10.1/a"
    assert rows[1]["emerged_domains"] == "TECHNOLOGY,ECONOMY"


def test_parse_args_and_main_end_to_end(tmp_path: Path) -> None:
    args = parse_args(["--input", "in.json"])
    assert args.input == Path("in.json")
    assert args.state_path.name == "cumulative_semantic_analysis.json"

    input_path = tmp_path / "fragments.json"
    input_path.write_text(
        json.dumps(
            [
                {"doi": "10.9/x", "text": "Hydrosocial river training gap"},
                {"doi": "", "text": "Port infrastructure governance"},
            ]
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    csv_path = tmp_path / "state.csv"

    exit_code = main(
        [
            "--input",
            str(input_path),
            "--state-path",
            str(state_path),
            "--csv-path",
            str(csv_path),
        ]
    )
    assert exit_code == 0
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["frequencies"]["variant_1_qmbd"]
    assert csv_path.exists()
