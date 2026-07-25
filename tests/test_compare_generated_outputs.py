from __future__ import annotations

from scripts.compare_generated_outputs import compare_json_payloads, normalize_payload


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
