"""Compatibility-named tests for the external H2 supply contract."""

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


def _write_demands(path: Path, demand_ids: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["competence_demand_id", "sector"])
        writer.writeheader()
        for demand_id in demand_ids:
            writer.writerow({"competence_demand_id": demand_id, "sector": "desalination"})


def _row(**overrides: str) -> dict[str, str]:
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
        "mapping_evidence": "published learning outcome explicitly covers hydronization planning",
        "mapping_confidence": "high",
        "validation_status": "validated",
        "validated_by": "reviewer-a",
        "validation_date": "2026-07-25",
        "notes": "",
    }
    row.update(overrides)
    return row


def _write_registry(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REGISTRY_FIELDS))
        writer.writeheader()
        writer.writerows(rows)


def test_candidate_only_registry_is_not_computable(tmp_path: Path) -> None:
    demands = tmp_path / "derived_competence_demands.csv"
    registry = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands, ["cd:hydro:1"])
    _write_registry(registry, [_row(validation_status="candidate")])

    with pytest.raises(ValueError, match="no explicitly validated mappings"):
        build_validated_supply_map(
            registry_path=registry,
            derived_demands_path=demands,
            output_path=tmp_path / "map.json",
            audit_output_path=tmp_path / "audit.json",
        )


def test_validated_supply_is_keyed_by_demand_id_and_eqf(tmp_path: Path) -> None:
    demands = tmp_path / "derived_competence_demands.csv"
    registry = tmp_path / "credential_supply_registry.csv"
    output = tmp_path / "map.json"
    audit = tmp_path / "audit.json"
    _write_demands(demands, ["cd:hydro:1", "cd:hydro:2"])
    _write_registry(
        registry,
        [
            _row(),
            _row(
                credential_supply_id="SUP-002",
                competence_demand_id="cd:hydro:1",
                eqf_level="7",
            ),
            _row(
                credential_supply_id="SUP-003",
                competence_demand_id="cd:hydro:2",
                validation_status="review_required",
            ),
        ],
    )

    result = build_validated_supply_map(
        registry_path=registry,
        derived_demands_path=demands,
        output_path=output,
        audit_output_path=audit,
        built_at_utc="2026-07-25T00:00:00+00:00",
    )

    assert result["validation_status"] == "validated"
    assert result["unit_of_analysis"] == "competence_demand_id"
    assert result["validated_supply_by_demand_id"]["cd:hydro:1"]["eqf_levels"] == [6, 7]
    assert "cd:hydro:2" not in result["validated_supply_by_demand_id"]
    assert json.loads(audit.read_text(encoding="utf-8"))["excluded_row_count"] == 1


def test_validated_row_requires_source_and_mapping_evidence(tmp_path: Path) -> None:
    demands = tmp_path / "derived_competence_demands.csv"
    registry = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands, ["cd:hydro:1"])
    _write_registry(registry, [_row(programme_url="")])

    with pytest.raises(ValueError, match="missing required field"):
        build_validated_supply_map(
            registry_path=registry,
            derived_demands_path=demands,
            output_path=tmp_path / "map.json",
            audit_output_path=tmp_path / "audit.json",
        )


def test_cli_rejects_unknown_demand_id(tmp_path: Path) -> None:
    demands = tmp_path / "derived_competence_demands.csv"
    registry = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands, ["cd:hydro:1"])
    _write_registry(registry, [_row(competence_demand_id="cd:unknown")])

    assert (
        main(
            [
                "--registry",
                str(registry),
                "--derived-demands",
                str(demands),
                "--output",
                str(tmp_path / "map.json"),
                "--audit-output",
                str(tmp_path / "audit.json"),
            ]
        )
        == 1
    )
