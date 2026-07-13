#!/usr/bin/env python3
"""Build Layer 4 (derived competence-demand database + statistics) and
Layer 5 (gap model, credential translation, learning outcomes) on top of
the Layer 2-3 cumulative scientific database.

CLI::

    python scripts/build_layer4_5_scientific_analysis.py \\
      --database-dir outputs/cumulative_database \\
      --output-dir outputs/cumulative_database \\
      --stats-dir outputs/layer4_statistics \\
      --current-run-id RUN-XYZ

Reads:
    <database-dir>/evidence_records.jsonl
    <database-dir>/competence_demand_signals.jsonl

Writes:
    <output-dir>/derived_competence_demands.{csv,jsonl}
    <output-dir>/sector_axis_gap_model.csv
    <output-dir>/credential_translation_eqf4_7.csv
    <output-dir>/learning_outcomes.csv
    <output-dir>/VARIABLE_LABELS.csv
    <output-dir>/VALUE_LABELS.csv
    <output-dir>/layer4_manifest.json
    <output-dir>/layer5_manifest.json
    <output-dir>/layer_readiness_report.json
    <stats-dir>/qmbd_cross_tables.csv
    <stats-dir>/sector_gap_matrices.json
    <stats-dir>/multivariate_induction_results.json
    <stats-dir>/taxonomic_clusters.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.scientific_sources.derived_competence_analysis import (  # noqa: E402
    build_layer4,
    build_layer5,
    build_layer_readiness_report,
    write_variable_and_value_labels,
)


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _load_static_baseline_by_sector(path: Optional[Path]) -> Dict[str, int]:
    """Load a static baseline sector→count mapping if a JSON file is provided.

    The file format is either:
        {"sector_slug": count, ...}
    or:
        {"baseline_count_by_sector": {"sector_slug": count, ...}}
    """
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict) and "baseline_count_by_sector" in data:
        data = data["baseline_count_by_sector"]
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v or 0) for k, v in data.items()}


def _load_validated_supply_map(
    path: Optional[Path],
) -> Optional[Dict[str, List[int]]]:
    """Load an explicitly validated demand-level EQF supply map."""
    if path is None:
        return None
    if not path.is_file():
        raise ValueError(f"validated supply map does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("validated supply map must be a JSON object")
    if str(payload.get("validation_status", "")).lower() != "validated":
        raise ValueError(
            "validated supply map must declare validation_status='validated'"
        )
    rows = payload.get("validated_supply_by_demand_id")
    if not isinstance(rows, dict):
        raise ValueError(
            "validated supply map must contain validated_supply_by_demand_id"
        )

    validated: Dict[str, List[int]] = {}
    for demand_id, raw_entry in rows.items():
        if isinstance(raw_entry, dict):
            if str(raw_entry.get("validation_status", "")).lower() != "validated":
                raise ValueError(
                    f"supply entry {demand_id!r} is not explicitly validated"
                )
            raw_levels = raw_entry.get("eqf_levels", [])
        else:
            raw_levels = raw_entry
        if isinstance(raw_levels, (str, int)):
            raw_levels = [raw_levels]
        if not isinstance(raw_levels, list):
            raise ValueError(f"supply entry {demand_id!r} has invalid eqf_levels")
        levels = sorted(
            {
                int(level)
                for level in raw_levels
                if str(level).strip().isdigit()
            }
        )
        if any(level < 4 or level > 8 for level in levels):
            raise ValueError(f"supply entry {demand_id!r} has invalid EQF level")
        validated[str(demand_id)] = levels
    return validated


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--database-dir",
                   default="outputs/cumulative_database",
                   help="Layer 2-3 output directory (source of evidence + signals).")
    p.add_argument("--output-dir",
                   default="outputs/cumulative_database",
                   help="Destination directory for Layer 4-5 outputs.")
    p.add_argument("--stats-dir",
                   default="outputs/layer4_statistics",
                   help="Destination directory for Layer 4 statistical files.")
    p.add_argument("--repository-root", default=".",
                   help="Repository root (for layer readiness audit).")
    p.add_argument("--outputs-root", default="outputs",
                   help="Outputs root (for layer readiness audit).")
    p.add_argument("--static-baseline-by-sector", default=None,
                   help="Optional JSON mapping of sector → static baseline count.")
    p.add_argument(
        "--validated-supply-map",
        default=None,
        help="Optional explicitly validated demand-level EQF supply JSON.",
    )
    p.add_argument(
        "--analysis-timestamp-utc",
        default=None,
        help="Fixed ISO-8601 timestamp used for deterministic recency scoring.",
    )
    p.add_argument("--current-run-id", default="")
    args = p.parse_args(argv)

    db_dir = Path(args.database_dir)
    out_dir = Path(args.output_dir)
    stats_dir = Path(args.stats_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_dir.mkdir(parents=True, exist_ok=True)

    evidence = _load_jsonl(db_dir / "evidence_records.jsonl")
    signals = _load_jsonl(db_dir / "competence_demand_signals.jsonl")

    # Layer readiness audit written first — captures the state before build.
    build_layer_readiness_report(
        repository_root=args.repository_root,
        outputs_root=args.outputs_root,
        output_path=out_dir / "layer_readiness_report.json",
    )

    if not evidence:
        print(
            "WARNING: no evidence records found; Layer 4-5 will emit empty files.",
            file=sys.stderr,
        )

    layer4 = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out_dir,
        current_run_id=args.current_run_id,
        stats_dir=stats_dir,
        analysis_timestamp_utc=args.analysis_timestamp_utc,
    )

    baseline_map = _load_static_baseline_by_sector(
        Path(args.static_baseline_by_sector) if args.static_baseline_by_sector else None
    )
    validated_supply = _load_validated_supply_map(
        Path(args.validated_supply_map) if args.validated_supply_map else None
    )
    layer5 = build_layer5(
        derived_demands=layer4.derived_demands,
        evidence_records=evidence,
        static_baseline_count_by_sector=baseline_map,
        existing_credential_coverage=None,
        validated_credential_supply=validated_supply,
        output_dir=out_dir,
        current_run_id=args.current_run_id,
        built_at_utc=args.analysis_timestamp_utc,
    )

    write_variable_and_value_labels(out_dir)

    summary = {
        "derived_demand_count": len(layer4.derived_demands),
        "gap_row_count": len(layer5.gap_rows),
        "credential_count": len(layer5.credentials),
        "learning_outcome_count": len(layer5.learning_outcomes),
        "hypothesis_results": layer5.hypothesis_results,
        "indices": layer4.indices,
        "analysis_timestamp_utc": args.analysis_timestamp_utc or "",
        "validated_supply_map_provided": validated_supply is not None,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
