from __future__ import annotations

import json
import hashlib
import math
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
                "axis_code": "M",
                "evidence_ids": "E-1|E-2",
            },
            {
                "competence_demand_id": "D-2",
                "sector": "sector_a",
                "axis_group": "MARINE",
                "axis_code": "M",
                "evidence_ids": "E-1",
            },
            {
                "competence_demand_id": "D-3",
                "sector": "sector_b",
                "axis_group": "OCEANIC",
                "axis_code": "O",
                "evidence_ids": "E-3|E-4",
            },
        ]
    )
    evidence = pd.DataFrame({"evidence_id": ["E-1", "E-2", "E-3", "E-4"]})
    signals = pd.DataFrame(
        [
            {
                "signal_id": f"S-{index}",
                "evidence_id": evidence_id,
                "sector": sector,
                "axis_group": axis,
                "axis_code": AXIS_CODES[axis],
                "signal_type": signal_type,
                "semantic_scope": "title",
                "manual_review_status": "review_required",
            }
            for index, (evidence_id, sector, axis, signal_type) in enumerate([
                ("E-1", "sector_a", "MARINE", "workforce_skill"),
                ("E-2", "sector_a", "MARINE", "technical_skill"),
                ("E-3", "sector_b", "OCEANIC", "governance_skill"),
                ("E-4", "sector_b", "OCEANIC", "social_science_skill"),
            ])
        ]
    )
    return demands, evidence, signals


def test_unique_evidence_is_not_inflated_by_duplicate_demand_links() -> None:
    demands, _, _ = _frames()
    result = build_unique_evidence_map(demands)
    assert len(result) == 4
    assert result["evidence_id"].nunique() == 4


def test_duplicate_evidence_member_within_one_demand_is_rejected_before_audit() -> None:
    demands, _, _ = _frames()
    demands.loc[0, "evidence_ids"] = "E-1| E-1"

    with pytest.raises(
        PerformativeDemandAnalysisError,
        match="must not repeat canonical evidence IDs",
    ):
        build_unique_evidence_map(demands)


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


def test_build_unique_evidence_map_rejects_mismatched_axis_group_axis_code() -> None:
    demands, _, _ = _frames()
    demands.loc[0, "axis_code"] = "T"
    with pytest.raises(PerformativeDemandAnalysisError, match="axis_group/axis_code"):
        build_unique_evidence_map(demands)


@pytest.mark.parametrize("invalid_evidence_ids", [None, "", " |  | "])
def test_derived_demands_with_empty_evidence_links_are_rejected(
    invalid_evidence_ids: object,
) -> None:
    demands, evidence, signals = _frames()
    demands.loc[0, "evidence_ids"] = invalid_evidence_ids

    with pytest.raises(
        PerformativeDemandAnalysisError,
        match="must each contain at least one canonical evidence ID",
    ):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


@pytest.mark.parametrize("invalid_demand_id", [None, "", "   "])
def test_layer4_blank_demand_id_fails_before_evidence_explosion(
    invalid_demand_id: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demands, _, _ = _frames()
    demands.loc[0, "competence_demand_id"] = invalid_demand_id
    monkeypatch.setattr(
        "src.scientific_sources.performative_demand_analysis.split_pipe",
        lambda _value: pytest.fail("evidence links were exploded before identity validation"),
    )

    with pytest.raises(PerformativeDemandAnalysisError, match="blank competence_demand_id"):
        build_unique_evidence_map(demands)


def test_duplicate_layer4_demand_id_fails_before_linkage_or_demand_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demands, evidence, signals = _frames()
    demands = pd.concat([demands, demands.iloc[[0]]], ignore_index=True)
    monkeypatch.setattr(
        "src.scientific_sources.performative_demand_analysis._linkage_dependence_audit",
        lambda _demands: pytest.fail("linkage totals ran before identity validation"),
    )

    with pytest.raises(PerformativeDemandAnalysisError, match="duplicate competence_demand_id"):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


@pytest.mark.parametrize("invalid_evidence_id", [None, "   "])
def test_layer3_signals_with_null_or_blank_evidence_ids_are_rejected_before_join(
    invalid_evidence_id: object,
) -> None:
    demands, evidence, signals = _frames()
    signals.loc[0, "evidence_id"] = invalid_evidence_id

    with pytest.raises(
        PerformativeDemandAnalysisError,
        match="signals contain .* evidence_id",
    ):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


@pytest.mark.parametrize(
    ("column", "value", "error_match"),
    [
        ("axis_code", None, "null or blank axis_group/axis_code"),
        ("axis_code", "", "null or blank axis_group/axis_code"),
        ("axis_group", "UNKNOWN", "non-canonical axis_group"),
        ("axis_code", "X", "non-canonical axis_code"),
        ("axis_code", "T", "axis_group/axis_code mismatches"),
    ],
)
def test_layer3_signal_axis_lineage_is_fail_closed_before_join(
    column: str,
    value: object,
    error_match: str,
) -> None:
    demands, evidence, signals = _frames()
    signals.loc[0, column] = value

    with pytest.raises(PerformativeDemandAnalysisError, match=error_match):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


@pytest.mark.parametrize("invalid_signal_id", [None, "", "   "])
def test_layer3_blank_signal_ids_are_rejected_before_join(
    invalid_signal_id: object,
) -> None:
    demands, evidence, signals = _frames()
    signals.loc[0, "signal_id"] = invalid_signal_id

    with pytest.raises(PerformativeDemandAnalysisError, match="blank signal_id"):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


def test_duplicate_identical_layer3_signal_id_is_rejected_before_join() -> None:
    demands, evidence, signals = _frames()
    signals = pd.concat([signals, signals.iloc[[0]]], ignore_index=True)

    with pytest.raises(PerformativeDemandAnalysisError, match="duplicate signal_id"):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


def test_duplicate_divergent_layer3_signal_id_is_rejected_before_join() -> None:
    demands, evidence, signals = _frames()
    divergent = signals.iloc[[0]].copy()
    divergent["signal_type"] = "governance_skill"
    divergent["semantic_scope"] = "abstract"
    signals = pd.concat([signals, divergent], ignore_index=True)

    with pytest.raises(PerformativeDemandAnalysisError, match="duplicate signal_id"):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


def test_layer3_signal_evidence_ids_are_normalized_before_linked_demand_join() -> None:
    demands, evidence, signals = _frames()
    signals.loc[0, "evidence_id"] = " E-1 "

    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )

    assert analysis.summary["linked_evidence_with_signals"] == 4


def test_layer3_signals_with_orphaned_evidence_ids_are_rejected_before_join() -> None:
    demands, evidence, signals = _frames()
    signals.loc[0, "evidence_id"] = "E-orphan"

    with pytest.raises(
        PerformativeDemandAnalysisError,
        match="absent from evidence_records",
    ):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
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
    assert row["analysis_scope"] == "deterministic_screening_only_not_validated"


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
    assert set(tourism["provenance_class"]) == {
        "external_comparison_only_not_repository_evidence"
    }
    assert all(
        row.axis_code == AXIS_CODES[row.axis_group]
        for row in tourism.itertuples(index=False)
    )


def test_performative_package_writers_use_lf_line_endings(tmp_path: Path) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import (
        _write_csv,
        _write_json,
    )

    csv_path = tmp_path / "table.csv"
    json_path = tmp_path / "payload.json"
    _write_csv(pd.DataFrame([{"column": "value"}]), csv_path)
    _write_json(json_path, {"value": "payload"})

    assert b"\r\n" not in csv_path.read_bytes()
    assert b"\r\n" not in json_path.read_bytes()
    assert csv_path.read_bytes().endswith(b"\n")
    assert json_path.read_bytes().endswith(b"\n")


def test_performative_csv_writer_canonicalizes_one_ulp_float_variants(
    tmp_path: Path,
) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _write_csv

    linux_value = 2.3062040545529316e-05
    windows_value = math.nextafter(linux_value, 0.0)
    assert linux_value != windows_value

    linux_path = tmp_path / "linux.csv"
    windows_path = tmp_path / "windows.csv"
    _write_csv(pd.DataFrame([{"value": linux_value}]), linux_path)
    _write_csv(pd.DataFrame([{"value": windows_value}]), windows_path)

    assert linux_path.read_bytes() == windows_path.read_bytes()


def test_rejected_signals_are_excluded_fail_closed() -> None:
    demands, evidence, signals = _frames()
    rejected = signals.iloc[[0]].copy()
    rejected["signal_id"] = "S-rejected"
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


def test_all_rejected_signals_preserve_linked_structure_as_zero_screening() -> None:
    demands, evidence, signals = _frames()
    signals["manual_review_status"] = "rejected"

    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )

    assert int(analysis.observed.to_numpy().sum()) == 4
    assert analysis.summary["linked_evidence"] == 4
    assert analysis.summary["linked_signal_rows"] == 0
    boundary = analysis.summary["screening_feature_boundary"]
    assert boundary["rejected_signal_rows_excluded"] == 4
    assert boundary["accepted_candidate_signal_rows"] == 0
    assert boundary["screening_outcome"] == "zero_accepted_candidate_screening_evidence"
    assert int(analysis.sector_axis_realms["candidate_evidence_count"].sum()) == 0
    assert float(analysis.sector_axis_realms["fractional_candidate_weight"].sum()) == 0
    assert analysis.summary["realm_screening_audit"]["fractional_weight_expected"] == 0
    assert "linked_evidence_zero_accepted_candidate_screening" in set(
        analysis.sector_axis_features["evidence_status"]
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
    assert "not an iid sample" in inference["unit_independence_note"]
    assert (
        inference["inferential_table_use"]
        == "descriptive_corpus_structure_diagnostic_only_not_population_inference"
    )
    assert "non-random corpus structure" in inference["permutation_interpretation"]
    dependence = inference["linkage_dependence_audit"]
    assert dependence["total_demand_link_rows"] == 5
    assert dependence["unique_linked_evidence_ids"] == 4
    assert dependence["duplicated_linked_evidence_ids"] == 1
    assert dependence["max_demand_links_per_evidence_id"] == 2
    assert dependence["independence_risk_flag"] is True


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


def test_unmapped_signal_types_are_rejected_fail_closed() -> None:
    demands, evidence, signals = _frames()
    signals.loc[0, "signal_type"] = "new_signal_type_not_in_mapping"
    with pytest.raises(PerformativeDemandAnalysisError, match="unsupported signal_type"):
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
                        "axis_code": "M",
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
    assert (
        "deterministic signal-type to realm crosswalk"
        in analysis.summary["realm_screening_audit"]["mapping_basis"]
    )
    assert (
        analysis.summary["screening_feature_boundary"]["title_only_interpretation"]
        == "title_only_screening_condition"
    )
    sector_a_profile = analysis.sector_profile.loc[
        analysis.sector_profile["sector"].eq("sector_a")
    ].iloc[0]
    assert sector_a_profile["linked_evidence_count"] == 3
    assert sector_a_profile["screening_eligible_linked_evidence_count"] == 2


def test_screening_boundary_reports_non_title_scope_mix() -> None:
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
    boundary = analysis.summary["screening_feature_boundary"]
    assert boundary["all_title_level"] is False
    assert boundary["observed_semantic_scopes"] == ["abstract", "title"]
    assert (
        boundary["title_only_interpretation"]
        == "mixed_semantic_surfaces_screening_condition"
    )


def test_realm_overlap_audit_flags_multi_realm_candidates() -> None:
    demands, evidence, signals = _frames()
    overlap_row = {
        "signal_id": "S-overlap",
        "evidence_id": "E-1",
        "sector": "sector_a",
        "axis_group": "MARINE",
        "axis_code": "M",
        "signal_type": "governance_skill",
        "semantic_scope": "title",
        "manual_review_status": "review_required",
    }
    signals = pd.concat([signals, pd.DataFrame([overlap_row])], ignore_index=True)
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    overlap = analysis.summary["realm_screening_audit"]["overlap_audit"]
    assert overlap["multi_realm_evidence_count"] >= 1
    assert overlap["multi_realm_evidence_share"] > 0
    assert overlap["max_candidate_realms_per_evidence"] >= 2


def test_realm_rows_and_profile_repeat_screening_only_scope() -> None:
    demands, evidence, signals = _frames()
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    candidate_rows = analysis.sector_axis_realms.loc[
        analysis.sector_axis_realms["candidate_evidence_count"].gt(0)
    ]
    assert not candidate_rows.empty
    assert set(candidate_rows["analysis_scope"]) == {
        "deterministic_screening_only_not_validated"
    }
    assert set(candidate_rows["screening_validation_state"]) == {
        "screening_only_not_validated"
    }
    assert set(candidate_rows["zero_interpretation"]) == {
        "candidate_for_exact_text_review_not_validated"
    }
    assert set(analysis.sector_profile["analysis_scope"]) == {
        "deterministic_screening_profile_not_validated"
    }
    assert set(analysis.sector_profile["screening_validation_state"]) == {
        "screening_only_not_validated"
    }


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
    demands = pd.DataFrame(
        {
            "competence_demand_id": ["D-1"],
            "sector": ["sector_a"],
            "axis_group": ["MARINE"],
            "axis_code": ["M"],
            "evidence_ids": ["E-1"],
            "current_run_id": ["RUN-A"],
        }
    )
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
    demands = pd.DataFrame(
        {
            "competence_demand_id": ["D-1"],
            "sector": ["sector_a"],
            "axis_group": ["MARINE"],
            "axis_code": ["M"],
            "evidence_ids": ["E-1"],
            "current_run_id": ["RUN-A"],
        }
    )
    evidence = pd.DataFrame({"evidence_id": ["E-1"]})
    signals = pd.DataFrame({"run_id": ["RUN-A"], "classifier_version": ["model-v1"]})
    provenance = _source_provenance(
        db, {"demands": demands, "evidence": evidence, "signals": signals}
    )
    assert provenance["run_classifier_identity"]["current_run_id"] == "RUN-A"
    assert provenance["cumulative_manifest_generated_at_utc"] == "2026-01-01T00:00:00+00:00"
    assert provenance["evidence_map_exact_rows"] == 1
    assert provenance["joined_evidence_id_count"] == 1
    assert provenance["lineage_validation_mode"] == "fail_closed"
    assert (
        provenance["run_classifier_identity"]["status"]
        == "verified_complete_run_classifier_identity"
    )


def _lineage_frames(
    *, run_id: str | None, classifier_version: str | None
) -> dict[str, pd.DataFrame]:
    demand_data: dict[str, list[str]] = {
        "competence_demand_id": ["D-1"],
        "sector": ["sector_a"],
        "axis_group": ["MARINE"],
        "axis_code": ["M"],
        "evidence_ids": ["E-1"],
    }
    signal_data: dict[str, list[str]] = {}
    if run_id is not None:
        demand_data["current_run_id"] = [run_id]
        signal_data["run_id"] = [run_id]
    if classifier_version is not None:
        signal_data["classifier_version"] = [classifier_version]
    return {
        "demands": pd.DataFrame(demand_data),
        "evidence": pd.DataFrame({"evidence_id": ["E-1"]}),
        "signals": pd.DataFrame(signal_data, index=[0]),
    }


def _set_database_lineage(
    database: Path,
    *,
    run_id: str | None,
    classifier_version: str | None,
) -> None:
    manifest_path = database / "cumulative_database_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("current_run_id", None)
    manifest.pop("run_id", None)
    manifest.pop("classifier_version", None)
    if run_id is not None:
        manifest["current_run_id"] = run_id
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    layer4_path = database / "layer4_manifest.json"
    layer4 = json.loads(layer4_path.read_text(encoding="utf-8"))
    layer4.pop("current_run_id", None)
    layer4.pop("run_id", None)
    layer4.pop("classifier_version", None)
    if run_id is not None:
        layer4["run_id"] = run_id
    if classifier_version is not None:
        layer4["classifier_version"] = classifier_version
    layer4_path.write_text(json.dumps(layer4), encoding="utf-8")


@pytest.mark.parametrize(
    ("run_id", "classifier_version", "error_match"),
    [
        ("RUN-A", None, "missing classifier_version"),
        (None, "model-v1", "missing a canonical run_id"),
        (None, None, "exactly one nonblank run identity"),
    ],
)
def test_source_provenance_requires_complete_run_and_classifier_identity(
    tmp_path: Path,
    run_id: str | None,
    classifier_version: str | None,
    error_match: str,
) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _source_provenance

    database = _readiness_db(
        tmp_path,
        '{"generated_at_utc":"2026-01-01T00:00:02+00:00","layers":[{"usable_for_layer4":true}]}',
    )
    _set_database_lineage(
        database, run_id=run_id, classifier_version=classifier_version
    )

    with pytest.raises(RuntimeError, match=error_match):
        _source_provenance(
            database,
            _lineage_frames(
                run_id=run_id, classifier_version=classifier_version
            ),
        )


def test_source_provenance_rejects_conflicting_classifier_versions(
    tmp_path: Path,
) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _source_provenance

    database = _readiness_db(
        tmp_path,
        '{"generated_at_utc":"2026-01-01T00:00:02+00:00","layers":[{"usable_for_layer4":true}]}',
    )

    with pytest.raises(RuntimeError, match="classifier_version conflicts"):
        _source_provenance(
            database,
            _lineage_frames(run_id="RUN-A", classifier_version="model-v2"),
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [("run_id", ""), ("classifier_version", None)],
)
def test_source_provenance_rejects_incomplete_lineage_on_any_signal_row(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _source_provenance

    database = _readiness_db(
        tmp_path,
        '{"generated_at_utc":"2026-01-01T00:00:02+00:00","layers":[{"usable_for_layer4":true}]}',
    )
    frames = _lineage_frames(run_id="RUN-A", classifier_version="model-v1")
    frames["signals"] = pd.concat(
        [frames["signals"], frames["signals"].copy()], ignore_index=True
    )
    frames["signals"].loc[1, column] = value

    with pytest.raises(RuntimeError, match="row-level incomplete run_id/classifier_version"):
        _source_provenance(database, frames)


def test_axis_features_do_not_report_wilson_confidence_intervals() -> None:
    demands, evidence, signals = _frames()
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    assert "wilson_95_lower" not in analysis.axis_features.columns
    assert "wilson_95_upper" not in analysis.axis_features.columns


def test_performative_builder_rejects_unused_protocol_option() -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _parse_args

    with pytest.raises(SystemExit):
        _parse_args(["--protocol", "unverified-protocol.yml"])


def test_residual_cells_use_observed_linked_evidence_label() -> None:
    demands, evidence, signals = _frames()
    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        {"sector_a": "Sector A", "sector_b": "Sector B"},
        permutations=9,
        seed=42,
    )
    assert "observed_screening_evidence" not in set(analysis.residuals["cell_status"])
    assert "observed_linked_evidence" in set(analysis.residuals["cell_status"])


def test_validate_evidence_identities_rejects_blank_or_null_ids() -> None:
    from src.scientific_sources.performative_demand_analysis import (
        validate_evidence_identities,
    )

    evidence = pd.DataFrame({"evidence_id": ["E-1", "", None]})
    with pytest.raises(PerformativeDemandAnalysisError, match="null and 1 blank"):
        validate_evidence_identities(evidence)


def test_validate_evidence_identities_rejects_duplicates() -> None:
    from src.scientific_sources.performative_demand_analysis import (
        validate_evidence_identities,
    )

    evidence = pd.DataFrame({"evidence_id": ["E-1", "E-1", "E-2"]})
    with pytest.raises(PerformativeDemandAnalysisError, match="duplicate evidence_id"):
        validate_evidence_identities(evidence)


def test_build_performative_demand_analysis_fails_closed_on_duplicate_evidence_id() -> None:
    demands, evidence, signals = _frames()
    evidence = pd.concat([evidence, pd.DataFrame([{"evidence_id": "E-1"}])], ignore_index=True)
    with pytest.raises(PerformativeDemandAnalysisError, match="duplicate evidence_id"):
        build_performative_demand_analysis(
            demands,
            evidence,
            signals,
            {"sector_a": "Sector A", "sector_b": "Sector B"},
            permutations=9,
            seed=42,
        )


def test_sparse_cell_diagnostics_are_scoped_to_active_margins() -> None:
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
    assert (
        inference["sparse_cell_diagnostic_scope"]
        == "active_inferential_margins_only_not_full_display_matrix"
    )
    # Full display matrix is 2 sectors x 4 axes = 8 cells, but only the
    # 2x2 active (nonzero-margin) submatrix should be used for diagnostics.
    assert inference["expected_cells_below_5"] <= 4
    assert inference["expected_cells_below_1"] <= 4


def _readiness_db(tmp_path: Path, readiness_payload: str) -> Path:
    db = tmp_path / "db"
    db.mkdir()
    (db / "cumulative_database_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "current_run_id": "RUN-A",
                "built_at_utc": "2026-01-01T00:00:00+00:00",
                "workflow_context": {"github_workflow": "Full Live-Enriched Analysis"},
                "counts": {"evidence_records": 1},
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
    (db / "layer_readiness_report.json").write_text(readiness_payload, encoding="utf-8")
    for name in (
        "derived_competence_demands.csv",
        "evidence_records.csv",
        "competence_demand_signals.csv",
    ):
        (db / name).write_text("id\n1\n", encoding="utf-8")
    return db


def test_source_provenance_fails_closed_on_empty_layer_readiness(tmp_path: Path) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _source_provenance

    db = _readiness_db(
        tmp_path, '{"generated_at_utc":"2026-01-01T00:00:02+00:00","layers":[]}'
    )
    demands = pd.DataFrame(
        {
            "competence_demand_id": ["D-1"],
            "sector": ["sector_a"],
            "axis_group": ["MARINE"],
            "axis_code": ["M"],
            "evidence_ids": ["E-1"],
            "current_run_id": ["RUN-A"],
        }
    )
    evidence = pd.DataFrame({"evidence_id": ["E-1"]})
    signals = pd.DataFrame({"run_id": ["RUN-A"], "classifier_version": ["model-v1"]})
    with pytest.raises(RuntimeError, match="no usable layer entries"):
        _source_provenance(
            db, {"demands": demands, "evidence": evidence, "signals": signals}
        )


def test_source_provenance_fails_closed_on_unusable_layer(tmp_path: Path) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _source_provenance

    db = _readiness_db(
        tmp_path,
        json.dumps(
            {
                "generated_at_utc": "2026-01-01T00:00:02+00:00",
                "layers": [
                    {"name": "layer2", "usable_for_layer4": True},
                    {"name": "layer3", "usable_for_layer4": False},
                ],
            }
        ),
    )
    demands = pd.DataFrame(
        {
            "competence_demand_id": ["D-1"],
            "sector": ["sector_a"],
            "axis_group": ["MARINE"],
            "axis_code": ["M"],
            "evidence_ids": ["E-1"],
            "current_run_id": ["RUN-A"],
        }
    )
    evidence = pd.DataFrame({"evidence_id": ["E-1"]})
    signals = pd.DataFrame({"run_id": ["RUN-A"], "classifier_version": ["model-v1"]})
    with pytest.raises(RuntimeError, match="not usable for Layer 4"):
        _source_provenance(
            db, {"demands": demands, "evidence": evidence, "signals": signals}
        )


def test_source_provenance_evidence_map_excludes_unlinked_evidence_ids(
    tmp_path: Path,
) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _source_provenance

    db = _readiness_db(
        tmp_path, '{"generated_at_utc":"2026-01-01T00:00:02+00:00","layers":[{"usable_for_layer4":true}]}'
    )
    demands = pd.DataFrame(
        {
            "competence_demand_id": ["D-1"],
            "sector": ["sector_a"],
            "axis_group": ["MARINE"],
            "axis_code": ["M"],
            "evidence_ids": ["E-1"],
            "current_run_id": ["RUN-A"],
        }
    )
    # E-2 is a valid evidence record that is never linked to any demand.
    evidence = pd.DataFrame({"evidence_id": ["E-1", "E-2"]})
    signals = pd.DataFrame({"run_id": ["RUN-A"], "classifier_version": ["model-v1"]})
    provenance = _source_provenance(
        db, {"demands": demands, "evidence": evidence, "signals": signals}
    )
    assert provenance["evidence_map_exact_rows"] == 1
    assert provenance["joined_evidence_id_count"] == 1


def test_staged_output_dir_removes_stale_files_on_promotion(tmp_path: Path) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _staged_output_dir

    output = tmp_path / "out"
    output.mkdir()
    stale = output / "stale_artifact.csv"
    stale.write_text("old", encoding="utf-8")
    with _staged_output_dir(output) as staging:
        (staging / "new_artifact.csv").write_text("new", encoding="utf-8")
    assert not (output / "stale_artifact.csv").exists()
    assert (output / "new_artifact.csv").read_text(encoding="utf-8") == "new"


def test_staged_output_dir_preserves_original_on_failure(tmp_path: Path) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _staged_output_dir

    output = tmp_path / "out"
    output.mkdir()
    original = output / "original.csv"
    original.write_text("original", encoding="utf-8")
    with pytest.raises(RuntimeError):
        with _staged_output_dir(output) as staging:
            (staging / "partial.csv").write_text("partial", encoding="utf-8")
            raise RuntimeError("boom")
    assert (output / "original.csv").read_text(encoding="utf-8") == "original"
    assert not (output / "partial.csv").exists()


def test_verify_retained_inputs_fails_on_checksum_mismatch(tmp_path: Path) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _verify_retained_inputs

    db = tmp_path / "db"
    db.mkdir()
    files = {
        "derived_competence_demands.csv": "a\n1\n",
        "evidence_records.csv": "evidence_id\nE-1\n",
        "competence_demand_signals.csv": "evidence_id\nE-1\n",
        "cumulative_database_manifest.json": (
            '{"protocol_binding":{"protocol_path":"config/live_query_protocol.yml",'
            '"protocol_version":"1.2.0","protocol_sha256":"x"}}\n'
        ),
        "layer4_manifest.json": "{}\n",
        "layer_readiness_report.json": '{"layers":[{"usable_for_layer4":true}]}\n',
    }
    for rel, content in files.items():
        (db / rel).write_text(content, encoding="utf-8")
    lines = []
    for rel in files:
        digest = hashlib.sha256((db / rel).read_bytes()).hexdigest()
        if rel == "evidence_records.csv":
            digest = "0" * 64
        lines.append(f"{digest}  {rel}")
    (db / "_checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _verify_retained_inputs(db)


def test_verified_protocol_identity_rejects_unverifiable_source_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import (
        _verified_protocol_identity,
    )

    db = tmp_path / "db"
    db.mkdir()
    protocol_rel = "retained_protocol/live_query_protocol.yml"
    protocol_bytes = b"protocol_version: 1.2.0\nsectors: {}\nhypotheses: {}\n"
    (db / "retained_protocol").mkdir()
    (db / protocol_rel).write_bytes(protocol_bytes)
    manifest = {
        "workflow_context": {"github_sha": "4eb044988659e51219a2ad62137091f0cb0f97c4"},
        "protocol_binding": {
            "protocol_path": "config/live_query_protocol.yml",
            "retained_protocol_artifact": protocol_rel,
            "source_commit": "4eb044988659e51219a2ad62137091f0cb0f97c4",
            "source_path": "config/live_query_protocol.yml",
            "source_blob_sha1": "0bb256b0139af99d494e39b95ee20261005c40d5",
            "protocol_version": "1.2.0",
            "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        }
    }
    monkeypatch.setattr(
        "scripts.build_performative_demand_cross_axis_analysis._git_show_bytes",
        lambda commit, path: b"different protocol bytes\n",
    )
    monkeypatch.setattr(
        "scripts.build_performative_demand_cross_axis_analysis._git_blob_id",
        lambda commit, path: "0bb256b0139af99d494e39b95ee20261005c40d5",
    )
    with pytest.raises(RuntimeError, match="do not match recorded source commit/path"):
        _verified_protocol_identity(manifest=manifest, database=db)


def test_governance_schema_requires_residual_measure_columns(tmp_path: Path) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import (
        _write_governance_artifacts,
    )

    out = tmp_path / "out"
    out.mkdir()
    _write_governance_artifacts(
        out,
        {"hypotheses": {}, "protocol_version": "1.2.0"},
        {"protocol_identity": {"verification_status": "verified_against_retained_snapshot"}},
    )
    schema = json.loads((out / "package_schema.json").read_text(encoding="utf-8"))
    residual_fields = schema["artifacts"]["sector_axis_residuals.csv"]
    assert residual_fields == [
        "sector",
        "sector_label",
        "axis_group",
        "axis_code",
        "observed_evidence_count",
        "expected_evidence_count",
        "adjusted_standardized_residual",
        "raw_cell_p",
        "holm_p",
        "bh_p",
        "holm_significant_0_05",
        "bh_significant_0_05",
        "cell_status",
    ]

    realm_fields = set(schema["artifacts"]["sector_axis_realm_screening.csv"])
    assert {
        "sector",
        "sector_label",
        "axis_group",
        "axis_code",
        "evidence_surface",
        "realm",
        "candidate_evidence_count",
        "fractional_candidate_weight",
        "screening_validation_state",
    } <= realm_fields

    sector_feature_fields = set(schema["artifacts"]["sector_axis_screening_features.csv"])
    assert {
        "sector",
        "sector_label",
        "axis_group",
        "axis_code",
        "evidence_surface",
        "unique_evidence_count",
        "derived_demand_count",
        "distinct_signal_type_count",
        "mean_signal_type_richness",
        "median_signal_type_richness",
        "validated_demand_count",
        "validated_translation_count",
        "validated_supply_count",
        "supply_gap_status",
        "screening_validation_state",
        "evidence_status",
        "analysis_scope",
        "demand_articulation_count",
        "demand_articulation_share",
        "learning_credential_translation_count",
        "learning_credential_translation_share",
        "technical_operational_capability_count",
        "technical_operational_capability_share",
        "institutional_governance_count",
        "institutional_governance_share",
        "reflexive_cultural_capability_count",
        "reflexive_cultural_capability_share",
    } <= sector_feature_fields

    axis_share_fields = set(schema["artifacts"]["axis_screening_feature_shares.csv"])
    assert {
        "axis_group",
        "axis_code",
        "evidence_surface",
        "feature",
        "evidence_with_feature",
        "axis_evidence_total",
        "feature_share",
        "status",
    } <= axis_share_fields


def test_ensure_commit_available_fetches_missing_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.build_performative_demand_cross_axis_analysis import _ensure_commit_available

    calls: list[list[str]] = []
    state = {"cat_file_checks": 0}

    def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        import subprocess

        cmd = list(args[0])
        calls.append(cmd)
        if "cat-file" in cmd:
            state["cat_file_checks"] += 1
            if state["cat_file_checks"] == 1:
                return subprocess.CompletedProcess(cmd, 1, b"", b"missing")
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        if "fetch" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr("scripts.build_performative_demand_cross_axis_analysis.subprocess.run", _fake_run)
    _ensure_commit_available("4eb044988659e51219a2ad62137091f0cb0f97c4")
    assert any("fetch" in cmd for cmd in calls)
