"""Tests for PR-3B dynamic credential generation from gap-model evidence."""

from __future__ import annotations

from pathlib import Path

from run_full_analysis import (
    _build_dynamic_credentials_from_gap_model,
    _convert_dynamic_to_legacy_credentials,
    export_credentials_dynamic_json,
    export_credentials_generation_rationale_json,
    export_credentials_json,
    export_sector_qmbd_learning_pathways_json,
)
from src.gap_model import GapCluster, GapEvidence, GapModelResult


def _ev(
    *,
    competence_id: str,
    sector: str,
    axis: str,
    name: str,
    overlap_status: str = "demand_only",
    matched_supply_id: str | None = None,
    matched_supply_origin: str | None = None,
    match_method: str | None = None,
    match_score: float | None = None,
    origin: str = "static_literature",
) -> GapEvidence:
    return GapEvidence(
        competence_id=competence_id,
        name=name,
        description=name,
        sector=sector,
        qmbd_axis=axis,
        origin=origin,
        source_file="data/derived/mock.csv",
        source_row=2,
        provider="crossref",
        doi="",
        title=name,
        year="2025",
        confidence_score=0.8,
        overlap_status=overlap_status,
        supporting_providers=["scopus"],
        matched_supply_id=matched_supply_id,
        matched_supply_origin=matched_supply_origin,
        match_method=match_method,
        match_score=match_score,
    )


def _cluster(
    sector: str,
    axis: str,
    priority: float,
    missing: list[GapEvidence],
    demand: list[GapEvidence],
    supply: list[GapEvidence],
    coverage_method: str = "uncovered",
) -> GapCluster:
    return GapCluster(
        sector=sector,
        qmbd_axis=axis,
        demand_items=demand,
        supply_items=supply,
        missing_items=missing,
        priority_score=priority,
        coverage_method=coverage_method,
    )


def _sample_gap_result() -> GapModelResult:
    bb_marine_missing = _ev(
        competence_id="bb_marine_1",
        sector="Blue Biotech",
        axis="MARINE",
        name="identify marine terminology and literacy",
    )
    bb_maritime_missing = _ev(
        competence_id="bb_maritime_1",
        sector="Blue Biotech",
        axis="MARITIME",
        name="implement operational compliance procedure",
    )
    bb_oceanic_missing = _ev(
        competence_id="bb_oceanic_1",
        sector="Blue Biotech",
        axis="OCEANIC",
        name="lead strategic governance research transformation",
    )
    mt_missing = _ev(
        competence_id="mt_oceanic_1",
        sector="Maritime Transport",
        axis="OCEANIC",
        name="analyze and design independent project evaluation",
    )
    covered_demand = _ev(
        competence_id="bb_covered_demand",
        sector="Blue Biotech",
        axis="MARITIME",
        name="implement covered demand",
        overlap_status="covered",
        matched_supply_id="bb_supply_1",
        matched_supply_origin="static_baseline",
        match_method="exact_id",
        match_score=1.0,
    )
    bb_supply = _ev(
        competence_id="bb_supply_1",
        sector="Blue Biotech",
        axis="MARITIME",
        name="baseline supply item",
        overlap_status="covered",
        origin="static_baseline",
    )
    generated_supply = _ev(
        competence_id="bb_generated_legacy",
        sector="Blue Biotech",
        axis="MARITIME",
        name="generated prior-run credential",
        overlap_status="supply_only",
        origin="generated_credential_previous_run",
    )

    clusters = [
        _cluster(
            "Blue Biotech",
            "MARINE",
            0.31,
            [bb_marine_missing],
            [bb_marine_missing],
            [],
            coverage_method="uncovered",
        ),
        _cluster(
            "Blue Biotech",
            "MARITIME",
            0.56,
            [bb_maritime_missing],
            [bb_maritime_missing, covered_demand],
            [bb_supply],
            coverage_method="mixed",
        ),
        _cluster(
            "Blue Biotech",
            "OCEANIC",
            0.89,
            [bb_oceanic_missing],
            [bb_oceanic_missing],
            [],
            coverage_method="uncovered",
        ),
        _cluster(
            "Maritime Transport",
            "OCEANIC",
            0.78,
            [mt_missing],
            [mt_missing],
            [],
            coverage_method="uncovered",
        ),
        _cluster(
            "Desalination", "MARINE", 0.0, [], [], [], coverage_method="no_demand"
        ),
    ]
    missing_clusters = [cluster for cluster in clusters if cluster.missing_items]
    return GapModelResult(
        demand_evidence={
            "Blue Biotech": [
                bb_marine_missing,
                bb_maritime_missing,
                bb_oceanic_missing,
            ],
            "Maritime Transport": [mt_missing],
        },
        supply_evidence={"Blue Biotech": [bb_supply]},
        generated_supply_evidence={"Blue Biotech": [generated_supply]},
        all_clusters=clusters,
        missing_clusters=missing_clusters,
    )


def test_dynamic_credentials_are_gap_cluster_derived_not_template_derived() -> None:
    dynamic, _, _ = _build_dynamic_credentials_from_gap_model(_sample_gap_result())
    sectors_with_credentials = {credential["sector"] for credential in dynamic}
    assert sectors_with_credentials == {"Blue Biotech", "Maritime Transport"}
    assert "Desalination" not in sectors_with_credentials


def test_no_credential_without_missing_evidence_cluster_and_review_required() -> None:
    _, rationale, _ = _build_dynamic_credentials_from_gap_model(_sample_gap_result())
    desalination_reviews = [
        item
        for item in rationale["review_required"]
        if item["sector"] == "Desalination"
    ]
    assert desalination_reviews
    assert any(
        "No evidence-backed missing clusters" in item["reason"]
        for item in desalination_reviews
    )


def test_generated_credentials_cite_missing_clusters_and_provenance() -> None:
    dynamic, rationale, _ = _build_dynamic_credentials_from_gap_model(
        _sample_gap_result()
    )
    assert all(credential["evidence_clusters"] for credential in dynamic)
    assert all(
        "missing_cluster" in credential["evidence_clusters"][0]
        for credential in dynamic
    )
    assert rationale["generated_credentials"]
    assert "used_evidence_items" in rationale["generated_credentials"][0]


def test_generated_supply_evidence_is_audit_only_not_verified_supply() -> None:
    dynamic, _, _ = _build_dynamic_credentials_from_gap_model(_sample_gap_result())
    blue_biotech = [item for item in dynamic if item["sector"] == "Blue Biotech"]
    assert blue_biotech
    assert all(
        credential["supply_gap_basis"]["generated_supply_audit_only_count"] == 1
        for credential in blue_biotech
    )
    assert all(
        credential["supply_gap_basis"]["missing_count"] >= 1
        for credential in blue_biotech
    )


def test_eqf_assignment_rules_are_explicit_and_level_specific() -> None:
    dynamic, _, _ = _build_dynamic_credentials_from_gap_model(_sample_gap_result())
    levels = {(credential["sector"], credential["eqf_level"]) for credential in dynamic}
    assert ("Blue Biotech", 4) in levels
    assert ("Blue Biotech", 5) in levels
    assert ("Blue Biotech", 7) in levels
    assert ("Maritime Transport", 6) in levels


def test_stackability_links_only_generated_credentials() -> None:
    dynamic, _, pathways = _build_dynamic_credentials_from_gap_model(
        _sample_gap_result()
    )
    generated_ids = {credential["id"] for credential in dynamic}
    for credential in dynamic:
        for prerequisite in credential["prerequisites"]:
            assert prerequisite in generated_ids
    for node in pathways["sector_qmbd_pathways"]:
        for link in node["stackability_links"]:
            assert link["from"] in generated_ids
            assert link["to"] in generated_ids


def test_backward_compatible_credentials_database_and_new_outputs(
    tmp_path: Path,
) -> None:
    dynamic, rationale, pathways = _build_dynamic_credentials_from_gap_model(
        _sample_gap_result()
    )
    legacy = _convert_dynamic_to_legacy_credentials(dynamic)

    legacy_path = tmp_path / "credentials_database.json"
    dynamic_path = tmp_path / "credentials_dynamic_database.json"
    rationale_path = tmp_path / "credentials_generation_rationale.json"
    pathways_path = tmp_path / "sector_qmbd_learning_pathways.json"

    export_credentials_json(legacy, legacy_path)
    export_credentials_dynamic_json(dynamic, dynamic_path)
    export_credentials_generation_rationale_json(rationale, rationale_path)
    export_sector_qmbd_learning_pathways_json(pathways, pathways_path)

    assert legacy_path.exists()
    assert dynamic_path.exists()
    assert rationale_path.exists()
    assert pathways_path.exists()

    legacy_payload = legacy_path.read_text(encoding="utf-8")
    assert '"credentials"' in legacy_payload
    dynamic_payload = dynamic_path.read_text(encoding="utf-8")
    assert '"evidence_clusters"' in dynamic_payload
    rationale_payload = rationale_path.read_text(encoding="utf-8")
    assert '"trigger_clusters"' in rationale_payload
    pathways_payload = pathways_path.read_text(encoding="utf-8")
    assert '"sector_qmbd_pathways"' in pathways_payload
