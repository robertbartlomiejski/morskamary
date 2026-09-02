from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.scientific_sources.performative_demand_analysis import (
    AXES,
    AXIS_CODES,
    REALMS,
    PerformativeDemandAnalysisError,
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


def test_axis_codes_are_explicit_in_analysis_tables() -> None:
    demands, evidence, signals = _frames()
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    for frame in (
        analysis.residuals,
        analysis.sector_axis_features,
        analysis.sector_axis_realms,
        analysis.axis_features,
    ):
        assert "axis_code" in frame.columns
        assert all(
            row.axis_code == AXIS_CODES[row.axis_group]
            for row in frame.itertuples(index=False)
        )
    assert "dominant_axis_code" in analysis.sector_profile.columns
    assert all(
        row.dominant_axis_code == AXIS_CODES[row.dominant_axis]
        for row in analysis.sector_profile.itertuples(index=False)
        if row.dominant_axis is not None
    )


def test_screening_surface_tracks_retained_semantic_scope() -> None:
    demands, evidence, signals = _frames()
    signals.loc[signals["evidence_id"].eq("E-1"), "semantic_scope"] = "abstract"
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    row = analysis.sector_axis_features.loc[
        analysis.sector_axis_features["sector"].eq("sector_a")
        & analysis.sector_axis_features["axis_group"].eq("MARINE")
    ].iloc[0]
    assert row["evidence_surface"] == "abstract|title"
    assert row["evidence_status"] == "screening_not_human_validated"


def test_builder_is_pandas_15_compatible_and_tourism_is_uncited_comparison() -> None:
    import inspect

    from scripts.build_performative_demand_cross_axis_analysis import (
        _tourism_case_table,
        _write_long_matrix,
    )

    assert "future_stack" not in inspect.getsource(_write_long_matrix)
    tourism = _tourism_case_table()
    assert tourism["citation_needed"].all()
    assert set(tourism["source_status"]) == {"comparison_data_not_repository_evidence"}
    assert all(
        row.axis_code == AXIS_CODES[row.axis_group]
        for row in tourism.itertuples(index=False)
    )


def test_rejected_signals_are_excluded_fail_closed() -> None:
    demands, evidence, signals = _frames()
    rejected = signals.iloc[[0]].copy()
    rejected["signal_type"] = "digital_skill"
    rejected["manual_review_status"] = "rejected"
    signals = pd.concat([signals, rejected], ignore_index=True)
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    row = analysis.sector_axis_features.loc[
        analysis.sector_axis_features["sector"].eq("sector_a")
        & analysis.sector_axis_features["axis_group"].eq("MARINE")
    ].iloc[0]
    assert row["technical_operational_capability_count"] == 1
    assert (
        analysis.summary["screening_feature_boundary"]["rejected_signal_rows_excluded"]
        == 1
    )


def test_non_screening_review_status_requires_validation_ledger() -> None:
    demands, evidence, signals = _frames()
    signals.loc[0, "manual_review_status"] = "manually_reviewed"
    with pytest.raises(PerformativeDemandAnalysisError, match="validation ledger"):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


def test_title_level_audit_uses_normalized_scopes() -> None:
    demands, evidence, signals = _frames()
    signals.loc[0, "semantic_scope"] = " Title "
    signals.loc[1, "semantic_scope"] = "TITLE"
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    assert analysis.summary["screening_feature_boundary"]["all_title_level"] is True


def test_zero_margin_dimensions_are_excluded_from_inference() -> None:
    demands, evidence, signals = _frames()
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    inference = analysis.summary["sector_axis_independence"]
    assert inference["active_rows_for_inference"] == 2
    assert inference["active_columns_for_inference"] == 2
    assert inference["degrees_of_freedom"] == 1
    assert inference["inferential_status"] == "computed_on_nonzero_margins"


def test_query_scopes_are_rejected_from_positive_screening() -> None:
    demands, evidence, signals = _frames()
    signals.loc[0, "semantic_scope"] = "source_query"
    with pytest.raises(PerformativeDemandAnalysisError, match="semantic_scope"):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


def test_fractional_weight_denominator_uses_screening_population() -> None:
    demands, evidence, signals = _frames()
    demands = pd.concat(
        [
            demands,
            pd.DataFrame(
                [
                    {
                        "competence_demand_id": "D-4",
                        "sector": "sector_a",
                        "axis_group": "MARINE",
                        "evidence_ids": "E-5",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    evidence = pd.concat([evidence, pd.DataFrame([{"evidence_id": "E-5"}])], ignore_index=True)
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    assert analysis.summary["linked_evidence"] == 5
    assert analysis.summary["realm_screening_audit"]["fractional_weight_expected"] == 4


def test_source_provenance_rejects_run_id_alias_mismatch(tmp_path: Path) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _source_provenance

    db = tmp_path / "db"
    db.mkdir()
    (db / "cumulative_database_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "current_run_id": "RUN-A",
                "built_at_utc": "2026-01-01T00:00:00+00:00",
                "workflow_context": {"github_workflow": "Full Live-Enriched Analysis"},
                "counts": {"evidence_records": 2},
            }
        ),
        encoding="utf-8",
    )
    (db / "layer4_manifest.json").write_text(
        json.dumps(
            {
                "current_run_id": "RUN-A",
                "classifier_version": "model-v1",
                "demand_strength_formula": "x",
                "built_at_utc": "2026-01-01T00:00:01+00:00",
            }
        ),
        encoding="utf-8",
    )
    (db / "layer_readiness_report.json").write_text(
        '{"generated_at_utc":"2026-01-01T00:00:02+00:00","layers":[{"usable_for_layer4":true}]}',
        encoding="utf-8",
    )
    for name in (
        "derived_competence_demands.csv",
        "evidence_records.csv",
        "competence_demand_signals.csv",
    ):
        (db / name).write_text("id\n1\n", encoding="utf-8")
    demands = pd.DataFrame({"evidence_ids": ["E-1"], "current_run_id": ["RUN-A"]})
    evidence = pd.DataFrame({"evidence_id": ["E-1"]})
    signals = pd.DataFrame({"run_id": ["RUN-B"], "classifier_version": ["model-v1"]})
    with pytest.raises(RuntimeError, match="run lineage aliases conflict"):
        _source_provenance(
            db, {"demands": demands, "evidence": evidence, "signals": signals}
        )


def test_source_provenance_maps_aliases_to_current_run_id(tmp_path: Path) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _source_provenance

    db = tmp_path / "db"
    db.mkdir()
    (db / "cumulative_database_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "current_run_id": "RUN-A",
                "built_at_utc": "2026-01-01T00:00:00+00:00",
                "workflow_context": {"github_workflow": "Full Live-Enriched Analysis"},
                "counts": {"evidence_records": 2},
            }
        ),
        encoding="utf-8",
    )
    (db / "layer4_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "RUN-A",
                "classifier_version": "model-v1",
                "demand_strength_formula": "x",
                "built_at_utc": "2026-01-01T00:00:01+00:00",
            }
        ),
        encoding="utf-8",
    )
    (db / "layer_readiness_report.json").write_text(
        '{"generated_at_utc":"2026-01-01T00:00:02+00:00","layers":[{"usable_for_layer4":true}]}',
        encoding="utf-8",
    )
    for name in (
        "derived_competence_demands.csv",
        "evidence_records.csv",
        "competence_demand_signals.csv",
    ):
        (db / name).write_text("id\n1\n", encoding="utf-8")
    demands = pd.DataFrame({"evidence_ids": ["E-1"], "current_run_id": ["RUN-A"]})
    evidence = pd.DataFrame({"evidence_id": ["E-1"]})
    signals = pd.DataFrame({"run_id": ["RUN-A"], "classifier_version": ["model-v1"]})
    provenance = _source_provenance(
        db, {"demands": demands, "evidence": evidence, "signals": signals}
    )
    assert provenance["run_classifier_identity"]["current_run_id"] == "RUN-A"
    assert provenance["cumulative_manifest_generated_at_utc"] == "2026-01-01T00:00:00+00:00"
