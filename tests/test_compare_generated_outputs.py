from __future__ import annotations

import subprocess

from scripts.compare_generated_outputs import compare_json_payloads, normalize_payload
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
