"""Tests for scripts/compute_provider_sensitivity_analysis.py."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import scripts.compute_provider_sensitivity_analysis as sensitivity


def _write_records(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def _write_query_log(path: Path, providers: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "query_id",
        "sector_slug",
        "query_family",
        "query_text",
        "provider",
        "provider_canonical",
        "execution_status",
        "returned_record_count",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, (provider, canonical) in enumerate(providers, start=1):
            writer.writerow(
                {
                    "query_id": f"Q{index}",
                    "sector_slug": "test-sector",
                    "query_family": "hypothesis_verification",
                    "query_text": "test query",
                    "provider": provider,
                    "provider_canonical": canonical,
                    "execution_status": "completed",
                    "returned_record_count": "1",
                }
            )


def test_leave_one_out_excludes_provider_records(tmp_path: Path) -> None:
    input_dir = tmp_path / "research_sources"
    _write_records(
        input_dir / "live_records.json",
        [
            {
                "title": "Port logistics training",
                "provider": "Crossref",
                "subject_terms": ["shipping"],
            },
            {
                "title": "Policy cooperation for oceans",
                "provider": "Scopus",
                "subject_terms": ["justice"],
            },
            {
                "title": "Ecosystem stewardship methods",
                "provider": "OpenAlex",
                "subject_terms": ["biodiversity"],
            },
        ],
    )
    _write_query_log(
        input_dir / "query_execution_log.csv",
        [("Crossref", "crossref"), ("Scopus", "scopus"), ("OpenAlex", "openalex")],
    )

    report = sensitivity.analyze_provider_sensitivity(input_dir=input_dir)

    assert report["full_sample"]["total_records"] == 3
    assert report["leave_one_out"]["crossref"]["excluded_records"] == 1
    assert report["leave_one_out"]["crossref"]["remaining_records"] == 2
    assert report["leave_one_out"]["crossref"]["axis_fragment_counts"] == {
        "MARINE": 2,
        "MARITIME": 0,
        "OCEANIC": 2,
        "HYDRONIZATION": 0,
    }


def test_direction_change_detection_marks_sensitive_provider(tmp_path: Path) -> None:
    input_dir = tmp_path / "research_sources"
    _write_records(
        input_dir / "live_records_triangulated.json",
        [
            {
                "title": "Port logistics workforce skills",
                "provider": "Crossref",
                "subject_terms": ["shipping infrastructure"],
            },
            {
                "title": "Ocean governance policy",
                "provider": "Scopus",
                "subject_terms": [],
            },
            {
                "title": "Policy cooperation for ocean justice",
                "provider": "OpenAlex",
                "subject_terms": [],
            },
        ],
    )
    _write_query_log(
        input_dir / "query_execution_log.csv",
        [("Crossref", "crossref"), ("Scopus", "scopus"), ("OpenAlex", "openalex")],
    )

    report = sensitivity.analyze_provider_sensitivity(input_dir=input_dir)

    assert report["full_sample"]["h1_maritime_oceanic_ratio"] == 1.0
    assert report["leave_one_out"]["crossref"]["h1_maritime_oceanic_ratio"] == 0.0
    assert report["leave_one_out"]["crossref"]["h1_direction_changed"] is True
    assert report["sensitivity_verdict"] == "sensitive_to_crossref"


def test_empty_subset_handling_marks_not_computable(tmp_path: Path) -> None:
    input_dir = tmp_path / "research_sources"
    _write_records(
        input_dir / "live_records.json",
        [
            {
                "title": "Port logistics workforce skills",
                "provider": "Crossref",
                "subject_terms": ["shipping infrastructure"],
            }
        ],
    )
    _write_query_log(
        input_dir / "query_execution_log.csv",
        [("Crossref", "crossref"), ("Scopus", "scopus")],
    )

    report = sensitivity.analyze_provider_sensitivity(input_dir=input_dir)

    crossref_subset = report["leave_one_out"]["crossref"]
    scopus_subset = report["leave_one_out"]["scopus"]

    assert crossref_subset["remaining_records"] == 0
    assert crossref_subset["axis_fragment_counts"] == {
        "MARINE": 0,
        "MARITIME": 0,
        "OCEANIC": 0,
        "HYDRONIZATION": 0,
    }
    assert crossref_subset["h1_maritime_oceanic_ratio"] is None
    assert crossref_subset["h3_marine_oceanic_balance"] is None
    assert crossref_subset["h1_direction_changed"] is True
    assert scopus_subset["excluded_records"] == 0


def test_main_writes_report_to_requested_output_dir(tmp_path: Path) -> None:
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    _write_records(
        input_dir / "live_records.json",
        [
            {
                "title": "Ecosystem biodiversity monitoring",
                "provider": "Crossref",
                "subject_terms": ["habitat"],
            }
        ],
    )
    _write_query_log(
        input_dir / "query_execution_log.csv",
        [("Crossref", "crossref")],
    )

    with patch.object(
        sensitivity,
        "_utc_now_iso",
        return_value="2026-07-25T12:00:00+00:00",
    ), patch(
        "sys.argv",
        [
            "compute_provider_sensitivity_analysis.py",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
        ],
    ):
        exit_code = sensitivity.main()

    report_path = output_dir / "provider_sensitivity_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["timestamp_utc"] == "2026-07-25T12:00:00+00:00"
    assert payload["leave_one_out"]["crossref"]["excluded_records"] == 1
