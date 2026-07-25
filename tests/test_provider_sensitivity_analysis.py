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
                    "providers_seen": "crossref|scopus",
                    "evidence_ids": "E1",
                },
                {
                    "competence_demand_id": "D-OCE-1",
                    "competence_label": "governance",
                    "sector": "coastal_tourism",
                    "axis_group": "OCEANIC",
                    "demand_strength_score": "0.45",
                    "providers_seen": "openalex",
                    "evidence_ids": "E2",
                },
                {
                    "competence_demand_id": "D-CROSSREF-ONLY",
                    "competence_label": "policy",
                    "sector": "ports",
                    "axis_group": "MARITIME",
                    "demand_strength_score": "0.75",
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
            {"evidence_id": "E1", "canonical_doi": "10.1/a", "providers_seen": "crossref|scopus", "sector": "ports"},
            {"evidence_id": "E2", "canonical_doi": "10.1/b", "providers_seen": "openalex", "sector": "coastal_tourism"},
            {"evidence_id": "E3", "canonical_doi": "10.1/c", "providers_seen": "crossref", "sector": "ports"},
        ],
    )
    _write_jsonl(
        signals,
        [
            {"signal_id": "S1", "evidence_id": "E1", "axis_group": "MARITIME"},
            {"signal_id": "S2", "evidence_id": "E2", "axis_group": "OCEANIC"},
            {"signal_id": "S3", "evidence_id": "E3", "axis_group": "MARITIME"},
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
    direct_excluded = result["subsets"]["direct_crossref_excluded"]
    assert direct_excluded["providers"] == ["openalex", "scopus"]
    assert direct_excluded["evidence_record_count"] == 2
    assert direct_excluded["unique_doi_count"] == 2
    assert direct_excluded["semantic_signal_count"] == 2
    assert direct_excluded["derived_demand_count"] == 2
    assert direct_excluded["h2"]["interpretation"] == "not_computable"
    assert (tmp_path / "provider_sensitivity_analysis.md").is_file()
