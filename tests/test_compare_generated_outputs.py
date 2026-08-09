from __future__ import annotations

import subprocess

import pytest

from scripts.compare_generated_outputs import (
    compare_csv_payloads,
    compare_json_payloads,
    normalize_payload,
)
from scripts import compare_generated_outputs as compare_module


def test_normalization_removes_only_declared_keys() -> None:
    payload = {"stable": {"count": 2}, "timestamp_utc": "new", "other": "kept"}
    assert normalize_payload(payload, {"timestamp_utc"}) == {
        "stable": {"count": 2},
        "other": "kept",
    }


def test_cumulative_metadata_drift_is_allowed_but_data_drift_is_not() -> None:
    committed = {
        "metadata": {"timestamp_utc": "old", "github_run_attempt": "1"},
        "records": [{"id": 1}],
    }
    current = {
        "metadata": {"timestamp_utc": "new", "github_run_attempt": "2"},
        "records": [{"id": 1}],
    }
    assert compare_json_payloads(
        current, committed, filename="cumulative_qmbd_records.json"
    )

    changed = {"metadata": {"timestamp_utc": "new"}, "records": [{"id": 2}]}
    assert not compare_json_payloads(
        changed, committed, filename="cumulative_qmbd_records.json"
    )


def test_supply_audit_metadata_drift_is_narrowly_allowed() -> None:
    committed = {"generated_supply_audit_only_count": 1, "credentials": ["a"]}
    current = {"generated_supply_audit_only_count": 2, "credentials": ["a"]}
    assert compare_json_payloads(
        current, committed, filename="credentials_dynamic_database.json"
    )


def test_rationale_audit_context_evidence_id_drift_is_not_allowed() -> None:
    committed = {
        "generated_credentials": [
            {
                "id": "credential-1",
                "generated_supply_audit_context": ["evidence-1"],
                "generated_supply_audit_only_count": 1,
            }
        ]
    }
    current = {
        "generated_credentials": [
            {
                "id": "credential-1",
                "generated_supply_audit_context": ["evidence-1"],
                "generated_supply_audit_only_count": 2,
            }
        ]
    }
    assert compare_json_payloads(
        current,
        committed,
        filename="credentials_generation_rationale.json",
    )

    current["generated_credentials"][0]["generated_supply_audit_context"] = [
        "evidence-2"
    ]
    assert not compare_json_payloads(
        current,
        committed,
        filename="credentials_generation_rationale.json",
    )


def test_gaps_summary_allows_only_declared_run_metadata_drift() -> None:
    committed = (
        "Sector,Missing_HYDRONIZATION,Generated_at,Run_id,Schema_version\n"
        "Desalination,15,old-time,old-run,2\n"
    )
    current = (
        "Sector,Missing_HYDRONIZATION,Generated_at,Run_id,Schema_version\n"
        "Desalination,15,new-time,new-run,2\n"
    )
    assert compare_csv_payloads(current, committed, filename="gaps_summary.csv")

    changed = current.replace("Desalination,15", "Desalination,16")
    assert not compare_csv_payloads(changed, committed, filename="gaps_summary.csv")


def test_gaps_summary_csv_metadata_drift_is_allowed() -> None:
    committed = (
        "Sector,Generated_at,Run_id,Missing\n"
        "Blue Biotech,2026-01-01T00:00:00+00:00,100,10\n"
    )
    current = (
        "Sector,Generated_at,Run_id,Missing\n"
        "Blue Biotech,2026-01-02T00:00:00+00:00,101,10\n"
    )
    assert compare_csv_payloads(current, committed, filename="gaps_summary.csv")


def test_gaps_summary_csv_substantive_drift_is_not_allowed() -> None:
    committed = (
        "Sector,Generated_at,Run_id,Missing\n"
        "Blue Biotech,2026-01-01T00:00:00+00:00,100,10\n"
    )
    current = (
        "Sector,Generated_at,Run_id,Missing\n"
        "Blue Biotech,2026-01-02T00:00:00+00:00,101,11\n"
    )
    assert not compare_csv_payloads(current, committed, filename="gaps_summary.csv")


@pytest.mark.parametrize("metadata_value", [None, [], "static", 1])
def test_cumulative_metadata_non_dict_raises_value_error(metadata_value) -> None:
    committed = {"metadata": {}, "records": [{"id": 1}]}
    current = {"metadata": metadata_value, "records": [{"id": 1}]}
    with pytest.raises(ValueError, match="metadata must be an object"):
        compare_json_payloads(
            current, committed, filename="cumulative_qmbd_records.json"
        )


def test_gaps_summary_csv_malformed_row_raises_value_error() -> None:
    committed = (
        "Sector,Generated_at,Run_id,Missing\n"
        "Blue Biotech,2026-01-01T00:00:00+00:00,100,10\n"
    )
    current = (
        "Sector,Generated_at,Run_id,Missing\n"
        "Blue Biotech,2026-01-01T00:00:00+00:00,100,10,extra\n"
    )
    with pytest.raises(ValueError, match="malformed CSV row"):
        compare_csv_payloads(current, committed, filename="gaps_summary.csv")


def test_changed_output_paths_include_untracked_files(monkeypatch) -> None:
    tracked = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="outputs\\tracked.json\n",
        stderr="",
    )
    untracked = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="outputs\\new.json\n",
        stderr="",
    )
    calls = iter([tracked, untracked])
    monkeypatch.setattr(compare_module.subprocess, "run", lambda *args, **kwargs: next(calls))

    changed = compare_module._changed_output_paths(compare_module.Path("outputs"))

    assert compare_module.Path("outputs\\tracked.json") in changed
    assert compare_module.Path("outputs\\new.json") in changed


def test_main_consumes_sys_argv_when_argv_none(monkeypatch, capsys) -> None:
    root = compare_module.Path("custom-outputs")
    monkeypatch.setattr(compare_module, "compare_outputs", lambda value: [str(value)])
    monkeypatch.setattr(compare_module.sys, "argv", ["compare_generated_outputs.py", "--root", str(root)])

    exit_code = compare_module.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert str(root) in captured.err


def test_compare_output_trees_allows_declared_json_metadata_drift(tmp_path) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    baseline_root.mkdir()
    current_root.mkdir()
    baseline = baseline_root / "cumulative_qmbd_records.json"
    current = current_root / "cumulative_qmbd_records.json"
    baseline.write_text(
        '{"metadata":{"timestamp_utc":"old"},"records":[{"id":1}]}\n',
        encoding="utf-8",
    )
    current.write_text(
        '{"metadata":{"timestamp_utc":"new"},"records":[{"id":1}]}\n',
        encoding="utf-8",
    )

    assert compare_module.compare_output_trees(current_root, baseline_root) == []


def test_compare_output_trees_requires_matching_file_sets(tmp_path) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    baseline_root.mkdir()
    current_root.mkdir()
    (baseline_root / "report_index.html").write_text("old\n", encoding="utf-8")

    errors = compare_module.compare_output_trees(current_root, baseline_root)

    assert errors == ["missing generated files: report_index.html"]


def test_two_fresh_trees_can_agree_while_committed_tree_is_stale(tmp_path) -> None:
    committed_root = tmp_path / "committed"
    first_generated_root = tmp_path / "generated-first"
    second_generated_root = tmp_path / "generated-second"
    for root in (committed_root, first_generated_root, second_generated_root):
        root.mkdir()

    stale = '{"metadata":{"analysis_input_mode":"static"},"records":[{"id":1}]}\n'
    fresh = '{"metadata":{"analysis_input_mode":"static"},"records":[{"id":2}]}\n'
    filename = "cumulative_qmbd_records.json"
    (committed_root / filename).write_text(stale, encoding="utf-8")
    (first_generated_root / filename).write_text(fresh, encoding="utf-8")
    (second_generated_root / filename).write_text(fresh, encoding="utf-8")

    assert (
        compare_module.compare_output_trees(
            second_generated_root, first_generated_root
        )
        == []
    )
    assert compare_module.compare_output_trees(
        first_generated_root, committed_root
    ) == [f"{filename}: substantive JSON drift"]


def test_output_tree_comparison_rejects_analysis_mode_mismatch(tmp_path) -> None:
    static_root = tmp_path / "static"
    live_root = tmp_path / "live"
    static_root.mkdir()
    live_root.mkdir()
    filename = "cumulative_qmbd_records.json"
    (static_root / filename).write_text(
        '{"metadata":{"analysis_input_mode":"static"},"records":[]}\n',
        encoding="utf-8",
    )
    (live_root / filename).write_text(
        '{"metadata":{"analysis_input_mode":"live-enriched"},"records":[]}\n',
        encoding="utf-8",
    )

    assert compare_module.compare_output_trees(static_root, live_root) == [
        f"{filename}: substantive JSON drift"
    ]
