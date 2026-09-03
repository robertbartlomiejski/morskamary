#!/usr/bin/env python3
"""Build the evidence-level Morskamary sector/axis/realm analysis package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

import pandas as pd
import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources.performative_demand_analysis import (  # noqa: E402
    AXES,
    AXIS_CODES,
    REALMS,
    build_performative_demand_analysis,
)

DEFAULT_DATABASE = REPO_ROOT / "outputs" / "cumulative_database"
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "performative_demand_cross_axis"
DEFAULT_PROTOCOL = REPO_ROOT / "config" / "live_query_protocol.yml"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-dir", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--permutations", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=20_260_825)
    return parser.parse_args(argv)


def _tourism_case_table() -> pd.DataFrame:
    """Return the supplied H3 aggregate recoding as an explicit 4 x 4 table."""
    title_counts = {
        "ECONOMY": 1,
        "TECHNOLOGY": 2,
        "POLICY_GOVERNANCE": 11,
        "CULTURE_LEARNING": 7,
    }
    rows: list[dict[str, object]] = []
    for axis in AXES:
        for realm in REALMS:
            rows.append(
                {
                    "sector": "coastal_tourism",
                    "axis_group": axis,
                    "axis_code": AXIS_CODES[axis],
                    "realm": realm,
                    "title_fragment_count": (
                        title_counts[realm] if axis == "OCEANIC" else 0
                    ),
                    "validated_demand_count": 0,
                    "validated_bridge_count": 0,
                    "evidence_surface": "title",
                    "manual_validation_status": "not_started",
                    "citation_needed": True,
                    "source_status": "comparison_data_not_repository_evidence",
                    "source_note": (
                        "aggregate realm recoding supplied outside retained repository "
                        "evidence; no retained citable source is available"
                    ),
                }
            )
    table = pd.DataFrame(rows)
    if int(table["title_fragment_count"].sum()) != 21:
        raise RuntimeError("coastal-tourism H3 case must contain 21 title fragments")
    return cast(pd.DataFrame, table)


def _write_long_matrix(
    matrix: pd.DataFrame,
    value_name: str,
    path: Path,
) -> None:
    long_series = cast(
        pd.Series,
        matrix.rename_axis(index="sector", columns="axis_group").stack(),
    )
    long_series.name = value_name
    long = long_series.reset_index()
    long["axis_code"] = long["axis_group"].map(AXIS_CODES)
    if long["axis_code"].isna().any():
        raise RuntimeError("matrix contains a non-canonical axis without axis_code")
    long = long[["sector", "axis_group", "axis_code", value_name]]
    long.to_csv(path, index=False)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_provenance(
    database: Path, frames: Mapping[str, pd.DataFrame]
) -> dict[str, Any]:
    manifest_path = database / "cumulative_database_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(
            "cumulative database manifest is required for analysis provenance"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_names = [
        "derived_competence_demands.csv",
        "evidence_records.csv",
        "competence_demand_signals.csv",
    ]
    observed: dict[str, dict[str, str]] = {}
    for table_name, frame in frames.items():
        for field in ("current_run_id", "run_id", "classifier_version"):
            if field not in frame.columns:
                continue
            values = {
                str(v).strip() for v in frame[field].dropna().tolist() if str(v).strip()
            }
            if len(values) > 1:
                raise RuntimeError(
                    f"{table_name} mixes multiple {field} values: {sorted(values)}"
                )
            if values:
                observed.setdefault(field, {})[table_name] = next(iter(values))
    for field, by_table in observed.items():
        values = set(by_table.values())
        if len(values) > 1:
            raise RuntimeError(f"input tables disagree on {field}: {sorted(values)}")
        manifest_value = str(manifest.get(field, "")).strip()
        if manifest_value and manifest_value not in values:
            raise RuntimeError(
                f"cumulative manifest {field} conflicts with table lineage"
            )
    return {
        "cumulative_manifest_schema_version": manifest.get("schema_version"),
        "cumulative_manifest_generated_at_utc": manifest.get("generated_at_utc"),
        "cumulative_manifest_generated_by": manifest.get("generated_by"),
        "cumulative_manifest_status": manifest.get("status"),
        "qmbd_assignment_methodology": manifest.get("qmbd_assignment_methodology"),
        "evidence_map_exact_rows": manifest.get("evidence_map_exact_rows"),
        "demand_profile_rows": manifest.get("demand_profile_rows"),
        "joined_evidence_id_count": manifest.get("joined_evidence_id_count"),
        "records_in_database": manifest.get("records_in_database"),
        "source_file_sha256": {name: _sha256(database / name) for name in source_names},
        "run_classifier_identity": {
            "status": (
                "verified_from_available_fields"
                if observed
                else "not_exposed_in_frozen_snapshot"
            ),
            "observed_fields": observed,
            "current_run_id": manifest.get("current_run_id"),
            "classifier_version": manifest.get("classifier_version"),
        },
    }


def _hypothesis_outcomes(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    reasons = {
        "H1": "this evidence-structure package does not recompute demand_strength_score effect sizes",
        "H2": "independently validated EQF 6-7 supply is unavailable in this package",
        "H3": "validated semantic translation bridges are unavailable in this package",
    }
    rows = []
    for hypothesis_id, config in protocol.get("hypotheses", {}).items():
        result_fields: dict[str, Any] = {
            str(field): None for field in config.get("required_result_fields", [])
        }
        result_fields["hypothesis_id"] = hypothesis_id
        result_fields["hypothesis_label"] = config.get("label")
        result_fields["interpretation"] = reasons.get(
            hypothesis_id, "required evidence is outside this package"
        )
        rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "hypothesis_label": config.get("label"),
                "definition": config.get("definition"),
                "test": config.get("test"),
                "direction": config.get("direction"),
                "required_axes": config.get("required_axes", []),
                "declared_outcomes": config.get("declared_outcomes", []),
                "status": "not_computable",
                "result_fields": result_fields,
                "warning": reasons.get(
                    hypothesis_id, "required evidence is outside this package"
                ),
            }
        )
    return rows


def _write_governance_artifacts(
    output: Path, protocol: Mapping[str, Any], source_provenance: Mapping[str, Any]
) -> None:
    (output / "validity_threats.json").write_text(
        json.dumps(
            {
                "claim_boundary": [
                    "association describes the acquired/classified corpus, not population prevalence",
                    "screening signal is not a validated competence demand",
                    "co-occurrence is not a directional translation bridge",
                    "translation is not validated performativity",
                    "demand is not independently validated supply or a supply gap",
                    "coastal-tourism comparison is not retained repository evidence",
                ],
                "known_design_threats": [
                    "retrieval/classification design confounds prevalence interpretation",
                    "semantic signals require exact-span human validation",
                    "multi-label screening is not an independent-event design",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "value_labels.json").write_text(
        json.dumps(
            {
                "axis_group_to_axis_code": AXIS_CODES,
                "review_status_contract": {
                    "review_required": "eligible for deterministic screening only",
                    "rejected": "excluded from positive screening aggregates",
                    "other": "fail closed until accepted validation ledger is ingested",
                },
                "zero_interpretation": "not observed in declared screening state, not absent in reality",
                "supply_gap_status": "not_computable_no_independent_supply",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "hypothesis_outcomes.json").write_text(
        json.dumps(_hypothesis_outcomes(protocol), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    files = {}
    for artifact in sorted(output.iterdir()):
        if artifact.is_file() and artifact.name != "package_manifest.json":
            files[artifact.name] = {
                "sha256": _sha256(artifact),
                "bytes": artifact.stat().st_size,
            }
    (output / "package_manifest.json").write_text(
        json.dumps(
            {
                "package_schema_version": "1.0",
                "generated_by": "scripts/build_performative_demand_cross_axis_analysis.py",
                "protocol_version": protocol.get("protocol_version"),
                "source_provenance": source_provenance,
                "files": files,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    protocol = yaml.safe_load(args.protocol.read_text(encoding="utf-8"))
    sector_labels = {
        sector: str(config["label"]) for sector, config in protocol["sectors"].items()
    }
    database = args.database_dir
    demands = pd.read_csv(database / "derived_competence_demands.csv")
    evidence = pd.read_csv(database / "evidence_records.csv")
    signals = pd.read_csv(database / "competence_demand_signals.csv")
    source_provenance = _source_provenance(
        database, {"demands": demands, "evidence": evidence, "signals": signals}
    )

    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        sector_labels,
        permutations=args.permutations,
        seed=args.seed,
    )
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    legacy_profile = output / "sector_deficit_profile.csv"
    if legacy_profile.exists():
        legacy_profile.unlink()
    _write_long_matrix(
        analysis.observed,
        "observed_evidence_count",
        output / "sector_axis_observed.csv",
    )
    _write_long_matrix(
        analysis.expected,
        "expected_evidence_count",
        output / "sector_axis_expected.csv",
    )
    analysis.residuals.to_csv(output / "sector_axis_residuals.csv", index=False)
    analysis.sector_axis_features.to_csv(
        output / "sector_axis_screening_features.csv", index=False
    )
    analysis.sector_axis_realms.to_csv(
        output / "sector_axis_realm_screening.csv", index=False
    )
    analysis.axis_features.to_csv(
        output / "axis_screening_feature_shares.csv", index=False
    )
    analysis.sector_profile.to_csv(output / "sector_screening_profile.csv", index=False)
    lineage = analysis.evidence_map.copy()
    lineage["axis_code"] = lineage["axis_group"].map(AXIS_CODES)
    lineage = lineage[["evidence_id", "sector", "axis_group", "axis_code"]]
    lineage.sort_values(["evidence_id", "sector", "axis_group"]).to_csv(
        output / "linked_evidence_sector_axis_lineage.csv", index=False
    )
    _tourism_case_table().to_csv(
        output / "coastal_tourism_axis_realm_case.csv", index=False
    )
    summary = dict(analysis.summary)
    summary["source_provenance"] = source_provenance
    (output / "statistics_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_governance_artifacts(output, protocol, source_provenance)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
