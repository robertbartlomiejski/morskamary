"""Tests for offline provider-sensitivity diagnostics."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import build_provider_sensitivity_analysis as sensitivity


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _write_demands(path: Path) -> None:
    fieldnames = [
        "competence_demand_id",
        "competence_label",
        "sector",
        "axis_group",
        "demand_strength_score",
        "query_families_seen",
        "semantic_confidence_mean",
        "latest_seen_at_utc",
        "providers_seen",
        "evidence_ids",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "competence_demand_id": "D-MAR-1",
                    "competence_label": "safety",
                    "sector": "ports",
                    "axis_group": "MARITIME",
                    "demand_strength_score": "0.80",
                    "query_families_seen": "competence_demand|hypothesis_verification",
                    "semantic_confidence_mean": "0.90",
                    "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
                    "providers_seen": "crossref|scopus",
                    "evidence_ids": "E1|E4",
                },
                {
                    "competence_demand_id": "D-OCE-1",
                    "competence_label": "governance",
                    "sector": "coastal_tourism",
                    "axis_group": "OCEANIC",
                    "demand_strength_score": "0.45",
                    "query_families_seen": "competence_demand",
                    "semantic_confidence_mean": "0.70",
                    "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
                    "providers_seen": "openalex",
                    "evidence_ids": "E2",
                },
                {
                    "competence_demand_id": "D-CROSSREF-ONLY",
                    "competence_label": "policy",
                    "sector": "ports",
                    "axis_group": "MARITIME",
                    "demand_strength_score": "0.75",
                    "query_families_seen": "competence_demand",
                    "semantic_confidence_mean": "0.80",
                    "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
                    "providers_seen": "crossref",
                    "evidence_ids": "E3",
                },
            ]
        )


def test_provider_sensitivity_uses_archived_rows_without_provider_clients(
    tmp_path: Path,
) -> None:
    script_text = Path(sensitivity.__file__).read_text(encoding="utf-8")
    assert "SourceRegistry" not in script_text
    assert "CrossrefProvider" not in script_text
    evidence = tmp_path / "evidence_records.jsonl"
    signals = tmp_path / "competence_demand_signals.jsonl"
    demands = tmp_path / "derived_competence_demands.csv"
    fragments = tmp_path / "hypothesis_semantic_fragments.jsonl"
    _write_jsonl(
        evidence,
        [
            {
                "evidence_id": "E1",
                "canonical_doi": "10.1/a",
                "providers_seen": "crossref|scopus",
                "sector": "ports",
                "first_seen_at_utc": "2026-07-20T00:00:00+00:00",
                "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
            },
            {
                "evidence_id": "E2",
                "canonical_doi": "10.1/b",
                "providers_seen": "openalex",
                "sector": "coastal_tourism",
                "first_seen_at_utc": "2026-07-20T00:00:00+00:00",
                "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
            },
            {
                "evidence_id": "E3",
                "canonical_doi": "10.1/c",
                "providers_seen": "crossref",
                "sector": "ports",
                "first_seen_at_utc": "2026-07-20T00:00:00+00:00",
                "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
            },
            {
                "evidence_id": "E4",
                "canonical_doi": "10.1/d",
                "providers_seen": "crossref",
                "sector": "ports",
                "first_seen_at_utc": "2026-07-20T00:00:00+00:00",
                "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
            },
        ],
    )
    _write_jsonl(
        signals,
        [
            {
                "signal_id": "S1",
                "evidence_id": "E1",
                "axis_group": "MARITIME",
                "competence_label": "safety",
                "sector": "ports",
                "query_family": "competence_demand",
                "confidence_score": 0.95,
            },
            {
                "signal_id": "S2",
                "evidence_id": "E2",
                "axis_group": "OCEANIC",
                "competence_label": "governance",
                "sector": "coastal_tourism",
                "query_family": "competence_demand",
                "confidence_score": 0.75,
            },
            {
                "signal_id": "S3",
                "evidence_id": "E3",
                "axis_group": "MARITIME",
                "competence_label": "policy",
                "sector": "ports",
                "query_family": "competence_demand",
                "confidence_score": 0.80,
            },
            {
                "signal_id": "S4",
                "evidence_id": "E4",
                "axis_group": "MARITIME",
                "competence_label": "safety",
                "sector": "ports",
                "query_family": "hypothesis_verification",
                "confidence_score": 0.60,
            },
        ],
    )
    _write_demands(demands)
    _write_jsonl(
        fragments,
        [
            {"evidence_id": "E1", "hypothesis_id": "H3", "axis_group": "MARINE"},
            {"evidence_id": "E2", "hypothesis_id": "H3", "axis_group": "OCEANIC"},
        ],
    )

    result = sensitivity.build_provider_sensitivity_analysis(
        evidence_path=evidence,
        signals_path=signals,
        derived_demands_path=demands,
        hypothesis_fragments_path=fragments,
        validated_supply_map_path=None,
        output_json_path=tmp_path / "provider_sensitivity_analysis.json",
        output_markdown_path=tmp_path / "provider_sensitivity_analysis.md",
    )

    assert result["api_calls_performed"] == 0
    assert "not Crossref-independent" in result["sensitivity_note"]
    assert {"direct_crossref_excluded", "scopus_excluded", "openalex_excluded"} <= set(
        result["subsets"]
    )
    direct_excluded = result["subsets"]["direct_crossref_excluded"]
    assert direct_excluded["providers"] == ["openalex", "scopus"]
    assert direct_excluded["evidence_record_count"] == 2
    assert direct_excluded["unique_doi_count"] == 2
    assert direct_excluded["semantic_signal_count"] == 2
    assert direct_excluded["derived_demand_count"] == 2
    assert direct_excluded["h2"]["interpretation"] == "not_computable"
    all_canonical = result["subsets"]["all_canonical"]
    retained_safety = next(
        row
        for row in direct_excluded["top_demands"]
        if row["competence_demand_id"] == "D-MAR-1"
    )
    baseline_safety = next(
        row
        for row in all_canonical["top_demands"]
        if row["competence_demand_id"] == "D-MAR-1"
    )
    assert retained_safety["provider_count"] == 1
    assert retained_safety["unique_doi_count"] == 1
    assert retained_safety["demand_strength_score"] < baseline_safety["demand_strength_score"]
    assert all(
        row["competence_demand_id"] != "D-CROSSREF-ONLY"
        for row in direct_excluded["top_demands"]
    )
    assert (tmp_path / "provider_sensitivity_analysis.md").is_file()
