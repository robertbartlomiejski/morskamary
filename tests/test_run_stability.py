from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_run_stability_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_run_stability_report", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _doi_series(count: int) -> list[str]:
    return [f"10.1000/{index:04d}" for index in range(1, count + 1)]


def _seed_archive(
    root: Path,
    runs: list[dict[str, Any]],
    *,
    protocol_version: str = "1.0.0",
    provider_set: str = "crossref,scopus",
) -> Path:
    archive_root = root / "outputs" / "run_archive"
    index_dir = archive_root / "_index"
    index_dir.mkdir(parents=True, exist_ok=True)

    jsonl_lines: list[str] = []
    csv_rows: list[dict[str, str]] = []
    for run in runs:
        run_id = str(run["run_id"])
        timestamp = str(run["timestamp_utc"])
        run_path = f"runs/{run_id}"
        run_dir = archive_root / run_path

        manifest_payload: dict[str, Any] = {
            "run_id": run_id,
            "timestamp_utc": timestamp,
            "analysis_timestamp_utc": timestamp,
            "provider_set": str(run.get("provider_set", provider_set)),
            "workflow": {"inputs": {"providers": str(run.get("provider_set", provider_set))}},
        }
        if run.get("is_static_recovery_mode"):
            manifest_payload["is_static_recovery_mode"] = True
        _write_json(run_dir / "manifest.json", manifest_payload)

        query_ids = run.get("query_ids", ["q1"])
        _write_json(
            run_dir / "research_sources" / "query_protocol_constraints.json",
            {
                "protocol_version": str(run.get("protocol_version", protocol_version)),
                "queries": [
                    {
                        "query_id": query_id,
                        "time_window": {"from_year": 2020, "to_year": 2026},
                        "sampling_strategy": {
                            "mode": "pages",
                            "pages": 2,
                            "rows_per_page": 50,
                            "dedupe_key": "doi",
                        },
                    }
                    for query_id in query_ids
                ],
            },
        )
        dois = run.get("dois", [])
        if not isinstance(dois, list):
            dois = []
        _write_json(
            run_dir / "research_sources" / "live_records.json",
            [{"doi": str(doi), "title": f"Title {doi}"} for doi in dois],
        )
        axis_distribution = run.get("axis_distribution")
        if not isinstance(axis_distribution, dict):
            axis_distribution = {
                "MARINE": 10,
                "MARITIME": 5,
                "OCEANIC": 3,
                "HYDRONIZATION": 2,
            }
        qmbd_records: list[dict[str, object]] = []
        for axis_name, count in axis_distribution.items():
            for idx in range(int(count)):
                qmbd_records.append(
                    {
                        "doi": f"{run_id}-{axis_name}-{idx}",
                        "title": f"{axis_name} evidence {idx}",
                        "axis_name": axis_name,
                    }
                )
        _write_json(run_dir / "analysis_outputs" / "cumulative_qmbd_records.json", qmbd_records)

        jsonl_lines.append(
            json.dumps(
                {
                    "run_id": run_id,
                    "archived_at": timestamp,
                    "run_path": run_path,
                }
            )
        )
        csv_rows.append(
            {
                "timestamp_utc": timestamp,
                "run_id": run_id,
                "run_path": run_path,
            }
        )

    _write_text(index_dir / "runs_index.jsonl", "\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""))
    csv_path = archive_root / "cumulative_runs_index.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", "run_id", "run_path"])
        writer.writeheader()
        writer.writerows(csv_rows)
    return archive_root


def test_compute_jaccard_similarity() -> None:
    module = _load_module()
    left = {"10.1000/a", "10.1000/b", "10.1000/c"}
    right = {"10.1000/b", "10.1000/c", "10.1000/d"}
    assert module.compute_jaccard_similarity(left, right) == 0.5
    assert module.compute_jaccard_similarity(set(), set()) == 1.0


def test_build_comparability_fingerprint_matches_only_for_same_payload() -> None:
    module = _load_module()
    fingerprint_a, payload_a = module.build_comparability_fingerprint(
        providers_used=["crossref", "scopus"],
        query_protocol_version="1.0.0",
        time_windows=['{"from_year":2020,"to_year":2026}'],
        sampling_strategies=['{"dedupe_key":"doi","mode":"pages","pages":2,"rows_per_page":50}'],
    )
    fingerprint_b, payload_b = module.build_comparability_fingerprint(
        providers_used=["scopus", "crossref"],
        query_protocol_version="1.0.0",
        time_windows=['{"from_year":2020,"to_year":2026}'],
        sampling_strategies=['{"dedupe_key":"doi","mode":"pages","pages":2,"rows_per_page":50}'],
    )
    fingerprint_c, _ = module.build_comparability_fingerprint(
        providers_used=["crossref"],
        query_protocol_version="1.0.0",
        time_windows=['{"from_year":2020,"to_year":2026}'],
        sampling_strategies=['{"dedupe_key":"doi","mode":"pages","pages":2,"rows_per_page":50}'],
    )
    assert payload_a == payload_b
    assert fingerprint_a == fingerprint_b
    assert fingerprint_a != fingerprint_c


def test_compute_axis_stability_score_uses_max_ratio_gap() -> None:
    module = _load_module()
    axis_a = {"MARINE": 10, "MARITIME": 0, "OCEANIC": 0, "HYDRONIZATION": 0}
    axis_b = {"MARINE": 9, "MARITIME": 1, "OCEANIC": 0, "HYDRONIZATION": 0}
    assert module.compute_axis_stability_score(axis_a, axis_b) == 0.9


def test_report_is_not_assessable_with_zero_or_one_run(tmp_path: Path) -> None:
    module = _load_module()

    empty_archive = _seed_archive(tmp_path / "empty", [])
    empty_output = tmp_path / "empty" / "outputs" / "run_stability_report.json"
    assert module.main(["--archive-root", str(empty_archive), "--output-path", str(empty_output)]) == 0
    empty_report = json.loads(empty_output.read_text(encoding="utf-8"))
    assert empty_report["runs_analyzed"] == 0
    assert empty_report["saturation_assessment"]["status"] == "not_assessable"

    single_archive = _seed_archive(
        tmp_path / "single",
        [{"run_id": "run-1", "timestamp_utc": "2026-07-01T00:00:00+00:00", "dois": _doi_series(20)}],
    )
    single_output = tmp_path / "single" / "outputs" / "run_stability_report.json"
    assert module.main(["--archive-root", str(single_archive), "--output-path", str(single_output)]) == 0
    single_report = json.loads(single_output.read_text(encoding="utf-8"))
    assert single_report["runs_analyzed"] == 1
    assert single_report["saturation_assessment"]["status"] == "not_assessable"


def test_two_runs_can_be_comparable_but_not_yet_saturated(tmp_path: Path) -> None:
    module = _load_module()
    archive_root = _seed_archive(
        tmp_path,
        [
            {"run_id": "run-1", "timestamp_utc": "2026-07-01T00:00:00+00:00", "dois": _doi_series(20)},
            {"run_id": "run-2", "timestamp_utc": "2026-07-02T00:00:00+00:00", "dois": _doi_series(21)},
        ],
    )
    output_path = tmp_path / "outputs" / "run_stability_report.json"
    assert module.main(["--archive-root", str(archive_root), "--output-path", str(output_path)]) == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["runs_analyzed"] == 2
    assert report["saturation_assessment"]["status"] == "not_saturated"
    assert report["run_pairs"][0]["comparability_fingerprint_match"] is True
    assert report["run_pairs"][0]["stable_transition"] is True
    assert report["run_pairs"][0]["new_unique_dois"] == 1


def test_three_runs_trigger_provisional_saturation(tmp_path: Path) -> None:
    module = _load_module()
    archive_root = _seed_archive(
        tmp_path,
        [
            {"run_id": "run-1", "timestamp_utc": "2026-07-01T00:00:00+00:00", "dois": _doi_series(20)},
            {"run_id": "run-2", "timestamp_utc": "2026-07-02T00:00:00+00:00", "dois": _doi_series(21)},
            {"run_id": "run-3", "timestamp_utc": "2026-07-03T00:00:00+00:00", "dois": _doi_series(22)},
        ],
    )
    output_path = tmp_path / "outputs" / "run_stability_report.json"
    assert module.main(["--archive-root", str(archive_root), "--output-path", str(output_path)]) == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["saturation_assessment"]["status"] == "provisional_saturation"
    assert report["saturation_assessment"]["consecutive_stable_transitions"] == 2


def test_four_runs_trigger_saturated_status(tmp_path: Path) -> None:
    module = _load_module()
    archive_root = _seed_archive(
        tmp_path,
        [
            {"run_id": "run-1", "timestamp_utc": "2026-07-01T00:00:00+00:00", "dois": _doi_series(20)},
            {"run_id": "run-2", "timestamp_utc": "2026-07-02T00:00:00+00:00", "dois": _doi_series(21)},
            {"run_id": "run-3", "timestamp_utc": "2026-07-03T00:00:00+00:00", "dois": _doi_series(22)},
            {"run_id": "run-4", "timestamp_utc": "2026-07-04T00:00:00+00:00", "dois": _doi_series(23)},
        ],
    )
    output_path = tmp_path / "outputs" / "run_stability_report.json"
    assert module.main(["--archive-root", str(archive_root), "--output-path", str(output_path)]) == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["saturation_assessment"]["status"] == "saturated"
    assert report["saturation_assessment"]["consecutive_stable_transitions"] == 3


def test_fingerprint_mismatch_makes_report_not_assessable(tmp_path: Path) -> None:
    module = _load_module()
    archive_root = _seed_archive(
        tmp_path,
        [
            {
                "run_id": "run-1",
                "timestamp_utc": "2026-07-01T00:00:00+00:00",
                "dois": _doi_series(20),
                "provider_set": "crossref,scopus",
            },
            {
                "run_id": "run-2",
                "timestamp_utc": "2026-07-02T00:00:00+00:00",
                "dois": _doi_series(21),
                "provider_set": "crossref",
            },
        ],
    )
    output_path = tmp_path / "outputs" / "run_stability_report.json"
    assert module.main(["--archive-root", str(archive_root), "--output-path", str(output_path)]) == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["run_pairs"][0]["comparability_fingerprint_match"] is False
    assert report["saturation_assessment"]["status"] == "not_assessable"


def test_different_query_id_universe_makes_fingerprint_mismatch(tmp_path: Path) -> None:
    """Two runs with identical providers/time windows but a different set of
    executed query_ids must not be treated as comparable."""
    module = _load_module()
    archive_root = _seed_archive(
        tmp_path,
        [
            {
                "run_id": "run-1",
                "timestamp_utc": "2026-07-01T00:00:00+00:00",
                "dois": _doi_series(20),
                "query_ids": ["q1", "q2"],
            },
            {
                "run_id": "run-2",
                "timestamp_utc": "2026-07-02T00:00:00+00:00",
                "dois": _doi_series(21),
                "query_ids": ["q1", "q3"],
            },
        ],
    )
    output_path = tmp_path / "outputs" / "run_stability_report.json"
    assert module.main(["--archive-root", str(archive_root), "--output-path", str(output_path)]) == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["run_pairs"][0]["comparability_fingerprint_match"] is False
    assert report["saturation_assessment"]["status"] == "not_assessable"


def test_same_query_id_universe_across_runs_is_comparable(tmp_path: Path) -> None:
    """Sanity counterpart: identical query_id sets must still match fingerprints."""
    module = _load_module()
    archive_root = _seed_archive(
        tmp_path,
        [
            {
                "run_id": "run-1",
                "timestamp_utc": "2026-07-01T00:00:00+00:00",
                "dois": _doi_series(20),
                "query_ids": ["q1", "q2"],
            },
            {
                "run_id": "run-2",
                "timestamp_utc": "2026-07-02T00:00:00+00:00",
                "dois": _doi_series(21),
                "query_ids": ["q1", "q2"],
            },
        ],
    )
    output_path = tmp_path / "outputs" / "run_stability_report.json"
    assert module.main(["--archive-root", str(archive_root), "--output-path", str(output_path)]) == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["run_pairs"][0]["comparability_fingerprint_match"] is True


def test_static_recovery_run_excluded_from_full_pipeline(tmp_path: Path) -> None:
    """A static-recovery archived run must be dropped from analysis entirely,
    both from the runs_analyzed count and from any run-pair comparison."""
    module = _load_module()
    archive_root = _seed_archive(
        tmp_path,
        [
            {"run_id": "run-1", "timestamp_utc": "2026-07-01T00:00:00+00:00", "dois": _doi_series(20)},
            {
                "run_id": "run-2-static",
                "timestamp_utc": "2026-07-02T00:00:00+00:00",
                "dois": _doi_series(5),
                "is_static_recovery_mode": True,
            },
            {"run_id": "run-3", "timestamp_utc": "2026-07-03T00:00:00+00:00", "dois": _doi_series(21)},
        ],
    )
    output_path = tmp_path / "outputs" / "run_stability_report.json"
    assert module.main(["--archive-root", str(archive_root), "--output-path", str(output_path)]) == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["runs_analyzed"] == 2
    run_ids_seen = {pair["run_a"] for pair in report["run_pairs"]} | {
        pair["run_b"] for pair in report["run_pairs"]
    }
    assert "run-2-static" not in run_ids_seen
    assert run_ids_seen == {"run-1", "run-3"}
