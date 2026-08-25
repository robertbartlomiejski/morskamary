from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.scientific_sources.performative_demand_analysis import (
    AXES,
    REALMS,
    build_performative_demand_analysis,
    build_unique_evidence_map,
)


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    demands = pd.DataFrame(
        [
            {
                "competence_demand_id": "D-1",
                "sector": "sector_a",
                "axis_group": "MARINE",
                "evidence_ids": "E-1|E-2",
            },
            {
                "competence_demand_id": "D-2",
                "sector": "sector_a",
                "axis_group": "MARINE",
                "evidence_ids": "E-1",
            },
            {
                "competence_demand_id": "D-3",
                "sector": "sector_b",
                "axis_group": "OCEANIC",
                "evidence_ids": "E-3|E-4",
            },
        ]
    )
    evidence = pd.DataFrame({"evidence_id": ["E-1", "E-2", "E-3", "E-4"]})
    signals = pd.DataFrame(
        [
            {
                "evidence_id": evidence_id,
                "sector": sector,
                "axis_group": axis,
                "signal_type": signal_type,
                "semantic_scope": "title",
                "manual_review_status": "review_required",
            }
            for evidence_id, sector, axis, signal_type in [
                ("E-1", "sector_a", "MARINE", "workforce_skill"),
                ("E-2", "sector_a", "MARINE", "technical_skill"),
                ("E-3", "sector_b", "OCEANIC", "governance_skill"),
                ("E-4", "sector_b", "OCEANIC", "social_science_skill"),
            ]
        ]
    )
    return demands, evidence, signals


def test_unique_evidence_is_not_inflated_by_duplicate_demand_links() -> None:
    demands, _, _ = _frames()
    result = build_unique_evidence_map(demands)
    assert len(result) == 4
    assert result["evidence_id"].nunique() == 4


def test_analysis_keeps_complete_zero_cells_and_fractional_audit() -> None:
    demands, evidence, signals = _frames()
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=99,
        seed=42,
    )
    assert analysis.observed.shape == (2, len(AXES))
    assert int((analysis.observed.to_numpy() == 0).sum()) == 6
    assert len(analysis.sector_axis_realms) == 2 * len(AXES) * len(REALMS)
    audit = analysis.summary["realm_screening_audit"]
    assert audit["fractional_candidate_weight"] == 4
    assert audit["fractional_weight_expected"] == 4


def test_repository_outputs_reproduce_current_evidence_counts() -> None:
    root = Path(__file__).resolve().parents[1]
    database = root / "outputs" / "cumulative_database"
    demands = pd.read_csv(database / "derived_competence_demands.csv")
    evidence = pd.read_csv(database / "evidence_records.csv")
    signals = pd.read_csv(database / "competence_demand_signals.csv")
    sector_labels = {
        "blue_biotech": "Blue Biotech",
        "coastal_tourism": "Coastal Tourism",
        "desalination": "Desalination",
        "infra_robotics": "Infra & Robotics",
        "living_res": "Living Res.",
        "non_living_res": "Non-living Res.",
        "renewable_energy": "Renewable Energy",
        "maritime_defence": "Maritime Defence",
        "maritime_transport": "Maritime Transport",
        "port_activities": "Port Activities",
        "r_i": "R&I",
        "ship_repair": "Ship Repair",
    }
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        sector_labels,
        permutations=99,
        seed=42,
    )
    assert int(analysis.observed.to_numpy().sum()) == 978
    assert analysis.observed.sum(axis=0).to_dict() == {
        "MARINE": 197,
        "MARITIME": 402,
        "OCEANIC": 295,
        "HYDRONIZATION": 84,
    }
    assert len(analysis.sector_axis_realms) == 192
