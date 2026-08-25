#!/usr/bin/env python3
"""Build the evidence-level Morskamary sector/axis/realm analysis package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence, cast

import pandas as pd
import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources.performative_demand_analysis import (  # noqa: E402
    AXES,
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
                    "realm": realm,
                    "title_fragment_count": (
                        title_counts[realm] if axis == "OCEANIC" else 0
                    ),
                    "validated_demand_count": 0,
                    "validated_bridge_count": 0,
                    "evidence_surface": "title",
                    "manual_validation_status": "not_started",
                    "source_note": (
                        "aggregate realm recoding supplied in the empirical brief; "
                        "repository H3 rows contain no realm field"
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
        matrix.rename_axis(index="sector", columns="axis_group").stack(
            future_stack=True
        ),
    )
    long_series.name = value_name
    long = long_series.reset_index()
    long.to_csv(path, index=False)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    protocol = yaml.safe_load(args.protocol.read_text(encoding="utf-8"))
    sector_labels = {
        sector: str(config["label"])
        for sector, config in protocol["sectors"].items()
    }
    database = args.database_dir
    demands = pd.read_csv(database / "derived_competence_demands.csv")
    evidence = pd.read_csv(database / "evidence_records.csv")
    signals = pd.read_csv(database / "competence_demand_signals.csv")

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
    _write_long_matrix(
        analysis.observed, "observed_evidence_count", output / "sector_axis_observed.csv"
    )
    _write_long_matrix(
        analysis.expected, "expected_evidence_count", output / "sector_axis_expected.csv"
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
    analysis.sector_profile.to_csv(output / "sector_deficit_profile.csv", index=False)
    _tourism_case_table().to_csv(
        output / "coastal_tourism_axis_realm_case.csv", index=False
    )
    (output / "statistics_summary.json").write_text(
        json.dumps(analysis.summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(analysis.summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
