"""Tests for the H2 validated credential-supply registry builder."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.build_validated_credential_supply_map import (
    REGISTRY_FIELDS,
    build_validated_supply_map,
    main,
)
from src.scientific_sources.derived_competence_analysis import (
    DerivedCompetenceDemand,
    build_layer5,
)


def _write_demands(path: Path, demand_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["competence_demand_id", "sector"])
        writer.writeheader()
        for demand_id in demand_ids:
            writer.writerow({"competence_demand_id": demand_id, "sector": "desalination"})


def _registry_row(**overrides: str) -> dict[str, str]:
    row = {
        "credential_supply_id": "SUP-001",
        "programme_title": "Validated Hydronization Programme",
        "awarding_institution": "Blue University",
        "country": "PL",
        "programme_url": "https://example.edu/programme",
        "source_type": "programme_catalogue",
        "source_access_date": "2026-07-25",
        "eqf_level": "6",
        "qualification_framework": "EQF",
        "competence_demand_id": "cd:hydro:1",
        "mapping_basis": "manual curriculum outcome match",
        "mapping_evidence": "learning outcome 1 explicitly covers hydronization planning",
        "mapping_confidence": "high",
        "validation_status": "validated",
        "validated_by": "reviewer-a",
        "validation_date": "2026-07-25",
        "validation_evidence_ids": "E-1|E-2",
        "notes": "",
    }
    row.update(overrides)
    return row


def _write_registry(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REGISTRY_FIELDS))
        writer.writeheader()
        writer.writerows(rows)


def _build(
    tmp_path: Path,
    rows: list[dict[str, str]],
    demand_ids: list[str] | None = None,
):
    demand_ids = demand_ids or ["cd:hydro:1", "cd:hydro:2"]
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    output_path = tmp_path / "validated_credential_supply_map.json"
    audit_path = tmp_path / "validated_credential_supply_audit.json"
    _write_demands(demands_path, demand_ids)
    _write_registry(registry_path, rows)
    result = build_validated_supply_map(
        registry_path=registry_path,
        derived_demands_path=demands_path,
        output_path=output_path,
        audit_output_path=audit_path,
        built_at_utc="2026-07-25T00:00:00+00:00",
    )
    return result, output_path, audit_path


def test_builder_emits_only_validated_mappings_and_audits_candidates(
    tmp_path: Path,
) -> None:
    result, output_path, audit_path = _build(
        tmp_path,
        [
            _registry_row(),
            _registry_row(
                credential_supply_id="SUP-002",
                competence_demand_id="cd:hydro:2",
                validation_status="candidate",
                eqf_level="7",
            ),
        ],
    )

    written = json.loads(output_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert result == written
    assert written["validation_status"] == "validated"
    assert set(written["validated_supply_by_demand_id"]) == {"cd:hydro:1"}
    entry = written["validated_supply_by_demand_id"]["cd:hydro:1"]
    assert entry["validation_status"] == "validated"
    assert entry["eqf_levels"] == [6]
    assert entry["credential_supply_ids"] == ["SUP-001"]
    assert entry["validation_evidence_ids"] == ["E-1", "E-2"]
    assert audit["validated_mapping_rows"] == 1
    assert audit["excluded_row_count"] == 1
    assert audit["excluded_rows"][0]["reason"] == "not_explicitly_validated"


def test_candidate_only_registry_fails_closed_without_output(tmp_path: Path) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    output_path = tmp_path / "validated_credential_supply_map.json"
    audit_path = tmp_path / "audit.json"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row(validation_status="candidate")])

    with pytest.raises(ValueError, match="no explicitly validated mappings"):
        build_validated_supply_map(
            registry_path=registry_path,
            derived_demands_path=demands_path,
            output_path=output_path,
            audit_output_path=audit_path,
        )

    assert not output_path.exists()


def test_unknown_demand_id_fails(tmp_path: Path) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(
        registry_path,
        [_registry_row(competence_demand_id="cd:unknown", validation_status="validated")],
    )

    with pytest.raises(ValueError, match="unknown competence_demand_id"):
        build_validated_supply_map(
            registry_path=registry_path,
            derived_demands_path=demands_path,
            output_path=tmp_path / "map.json",
            audit_output_path=tmp_path / "audit.json",
        )


def test_validated_mapping_requires_source_and_validation_provenance(
    tmp_path: Path,
) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row(programme_url="")])

    with pytest.raises(ValueError, match="missing required field"):
        build_validated_supply_map(
            registry_path=registry_path,
            derived_demands_path=demands_path,
            output_path=tmp_path / "map.json",
            audit_output_path=tmp_path / "audit.json",
        )


def test_validated_mapping_requires_validation_evidence_ids(tmp_path: Path) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row(validation_evidence_ids="")])

    with pytest.raises(ValueError, match="validation_evidence_ids"):
        build_validated_supply_map(
            registry_path=registry_path,
            derived_demands_path=demands_path,
            output_path=tmp_path / "map.json",
            audit_output_path=tmp_path / "audit.json",
        )


def _hydro_demand(demand_id: str) -> DerivedCompetenceDemand:
    return DerivedCompetenceDemand(
        competence_demand_id=demand_id,
        competence_label="hydronization governance",
        competence_definition="validated hydronization competence",
        sector="desalination",
        axis_group="HYDRONIZATION",
        axis_code="H",
        eqf_relevance="5|6|7",
        demand_strength_score=0.8,
        evidence_record_count=1,
        unique_doi_count=1,
        record_occurrence_count=1,
        provider_count=1,
        providers_seen="openalex",
        provider_diversity_score=1.0,
        query_count=1,
        query_families_seen="validation_eqf_translation",
        query_diversity_score=1.0,
        temporal_recency_score=1.0,
        cross_sector_recurrence_score=0.1,
        semantic_confidence_mean=0.9,
        first_seen_run_id="RUN-1",
        latest_seen_run_id="RUN-1",
        first_seen_at_utc="2026-07-25T00:00:00+00:00",
        latest_seen_at_utc="2026-07-25T00:00:00+00:00",
        status="high_demand",
        manual_review_status="validated",
        validity_warning="",
        evidence_ids="E-1",
        signal_types="competence_demand",
    )


def test_only_validated_eqf_6_7_supply_affects_h2(tmp_path: Path) -> None:
    demand = _hydro_demand("cd:hydro:1")

    eqf5 = build_layer5(
        derived_demands=[demand],
        evidence_records=[],
        validated_credential_supply={"cd:hydro:1": [5]},
        output_dir=tmp_path / "eqf5",
        current_run_id="RUN-EQF5",
    ).hypothesis_results["H2"]
    assert eqf5["validated_covered_demand_count"] == 0
    assert eqf5["validated_missing_demand_count"] == 1
    assert eqf5["interpretation"] == "supported"

    eqf6 = build_layer5(
        derived_demands=[demand],
        evidence_records=[],
        validated_credential_supply={"cd:hydro:1": [6]},
        output_dir=tmp_path / "eqf6",
        current_run_id="RUN-EQF6",
    ).hypothesis_results["H2"]
    assert eqf6["validated_covered_demand_count"] == 1
    assert eqf6["validated_missing_demand_count"] == 0
    assert eqf6["interpretation"] == "not_supported"


def test_cli_returns_nonzero_for_candidate_only_registry(tmp_path: Path, capsys) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row(validation_status="candidate")])

    result = main(
        [
            "--registry",
            str(registry_path),
            "--derived-demands",
            str(demands_path),
            "--output",
            str(tmp_path / "map.json"),
            "--audit-output",
            str(tmp_path / "audit.json"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "candidate-only map" in captured.err
