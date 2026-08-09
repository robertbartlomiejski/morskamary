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
    committed = {"metadata": {"timestamp_utc": "old"}, "records": [{"id": 1}]}
    current = {"metadata": {"timestamp_utc": "new"}, "records": [{"id": 1}]}
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
