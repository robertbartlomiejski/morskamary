"""Regression tests for fail-closed provider-sensitivity diagnostics."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts import build_provider_sensitivity_analysis as sensitivity


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_demands(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "competence_demand_id",
                "competence_label",
                "sector",
                "axis_group",
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "competence_demand_id": "D-MAR-1",
                    "competence_label": "safety",
                    "sector": "ports",
                    "axis_group": "MARITIME",
                },
                {
                    "competence_demand_id": "D-OCE-1",
                    "competence_label": "governance",
                    "sector": "coastal_tourism",
                    "axis_group": "OCEANIC",
                },
                {
                    "competence_demand_id": "D-HYD-1",
                    "competence_label": "hydrosocial governance",
                    "sector": "desalination",
                    "axis_group": "HYDRONIZATION",
                },
                {
                    "competence_demand_id": "D-CROSSREF-ONLY",
                    "competence_label": "policy",
                    "sector": "ports",
                    "axis_group": "MARITIME",
                },
            ],
        )


def _write_manifest(tmp_path: Path) -> None:
    """Write a mock layer4_manifest.json required by the fail-closed timestamp loader."""
    manifest = tmp_path / "layer4_manifest.json"
    manifest.write_text(
        json.dumps({"analysis_timestamp_utc": "2026-07-20T12:00:00+00:00"}),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path, *, include_wos: bool = False) -> dict[str, Path]:
    evidence = tmp_path / "evidence_records.jsonl"
    signals = tmp_path / "competence_demand_signals.jsonl"
    demands = tmp_path / "derived_competence_demands.csv"
    fragments = tmp_path / "hypothesis_semantic_fragments.jsonl"
    _write_manifest(tmp_path)

    evidence_rows = [
        {
            "evidence_id": "E1",
            "canonical_doi": "10.1/a",
            "providers_seen": "crossref|scopus",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
        {
            "evidence_id": "E2",
            "canonical_doi": "10.1/b",
            "providers_seen": "openalex",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
        {
            "evidence_id": "E3",
            "canonical_doi": "10.1/c",
            "providers_seen": "crossref",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
        {
            "evidence_id": "E4",
            "canonical_doi": "10.1/d",
            "providers_seen": "crossref",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
        {
            "evidence_id": "E5",
            "canonical_doi": "10.1/e",
            "providers_seen": "openalex",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
    ]
    if include_wos:
        evidence_rows.append(
            {
                "evidence_id": "E6",
                "canonical_doi": "10.1/f",
                "providers_seen": "wos",
                "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
            }
        )
    _write_jsonl(evidence, evidence_rows)

    signal_rows = [
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
        {
            "signal_id": "S5",
            "evidence_id": "E5",
            "axis_group": "HYDRONIZATION",
            "competence_label": "hydrosocial governance",
            "sector": "desalination",
            "query_family": "competence_demand",
            "confidence_score": 0.85,
        },
    ]
    if include_wos:
        signal_rows.append(
            {
                "signal_id": "S6",
                "evidence_id": "E6",
                "axis_group": "OCEANIC",
                "competence_label": "governance",
                "sector": "coastal_tourism",
                "query_family": "hypothesis_verification",
                "confidence_score": 0.70,
            }
        )
    _write_jsonl(signals, signal_rows)
    _write_demands(demands)
    _write_jsonl(
        fragments,
        [
            {
                "evidence_id": "E1",
                "signal_id": "BRIDGE",
                "hypothesis_id": "H3",
                "axis_group": "MARINE",
            },
            {
                "evidence_id": "E2",
                "signal_id": "BRIDGE",
                "hypothesis_id": "H3",
                "axis_group": "OCEANIC",
            },
            {
                "evidence_id": "E2",
                "signal_id": "NOT-H3",
                "hypothesis_id": "H1",
                "axis_group": "OCEANIC",
            },
        ],
    )
    return {
        "evidence": evidence,
        "signals": signals,
        "demands": demands,
        "fragments": fragments,
    }


def _build(tmp_path: Path, paths: dict[str, Path], supply: Path | None = None) -> dict:
    return sensitivity.build_provider_sensitivity_analysis(
        evidence_path=paths["evidence"],
        signals_path=paths["signals"],
        derived_demands_path=paths["demands"],
        hypothesis_fragments_path=paths["fragments"],
        validated_supply_map_path=supply,
        output_json_path=tmp_path / "provider_sensitivity_analysis.json",
        output_markdown_path=tmp_path / "provider_sensitivity_analysis.md",
    )


def test_recomputes_each_provider_subset_and_emits_complete_contract(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    result = _build(tmp_path, paths)

    assert result["api_calls_performed"] == 0
    assert {
        "all_canonical",
        "direct_crossref_excluded",
        "scopus_excluded",
        "openalex_excluded",
        "crossref_only",
        "scopus_only",
        "openalex_only",
    } <= set(result["subsets"])

    direct = result["subsets"]["direct_crossref_excluded"]
    baseline = result["subsets"]["all_canonical"]
    retained = next(
        row for row in direct["top_demands"]
        if row["competence_demand_id"] == "D-MAR-1"
    )
    original = next(
        row for row in baseline["top_demands"]
        if row["competence_demand_id"] == "D-MAR-1"
    )
    assert retained["provider_count"] == 1
    assert retained["unique_doi_count"] == 1
    assert retained["axis_code"] == "T"
    assert retained["demand_strength_score"] < original["demand_strength_score"]
    assert all(
        row["competence_demand_id"] != "D-CROSSREF-ONLY"
        for row in direct["top_demands"]
    )

    for hypothesis_id in ("h1", "h2", "h3"):
        assert direct[hypothesis_id]["hypothesis_id"] == hypothesis_id.upper()
        assert "hypothesis_label" in direct[hypothesis_id]
        assert "interpretation" in direct[hypothesis_id]

    assert baseline["h3"]["matched_fragment_count"] == 2
    assert baseline["h3"]["oceanic_fragment_count"] == 1
    assert baseline["h3"]["semantic_bridge_count"] == 1
    assert (tmp_path / "provider_sensitivity_analysis.md").is_file()


def test_subsets_follow_actual_contributing_providers_including_wos(
    tmp_path: Path,
) -> None:
    result = _build(tmp_path, _fixture(tmp_path, include_wos=True))
    assert "wos_only" in result["subsets"]
    assert "wos_excluded" in result["subsets"]
    assert "wos" in result["subsets"]["all_canonical"]["providers"]


def test_missing_required_input_fails_closed(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["signals"].unlink()
    with pytest.raises(ValueError, match="required signals file does not exist"):
        _build(tmp_path, paths)


def test_explicit_unvalidated_supply_map_is_rejected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    supply = tmp_path / "supply.json"
    supply.write_text(
        json.dumps(
            {
                "validation_status": "candidate",
                "has_validated_supply": True,
                "validated_supply_by_demand_id": {
                    "D-HYD-1": {
                        "eqf_levels": [6],
                        "validation_evidence_ids": ["REG-1"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be validated"):
        _build(tmp_path, paths, supply)


def test_validated_supply_changes_h2_only_with_evidence(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    supply = tmp_path / "supply.json"
    supply.write_text(
        json.dumps(
            {
                "validation_status": "validated",
                "has_validated_supply": True,
                "validated_supply_by_demand_id": {
                    "D-HYD-1": {
                        "validation_status": "validated",
                        "eqf_levels": [6],
                        "validation_evidence_ids": ["REG-1"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    result = _build(tmp_path, paths, supply)
    h2 = result["subsets"]["all_canonical"]["h2"]
    assert h2["validated_supply_map_provided"] is True
    assert h2["validated_covered_demand_count"] == 1
    assert h2["validated_missing_demand_count"] == 0
    assert h2["interpretation"] == "not_supported"
