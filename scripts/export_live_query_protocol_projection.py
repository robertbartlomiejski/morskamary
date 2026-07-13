#!/usr/bin/env python3
"""Export deterministic legacy `query_groups` projection from live protocol."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources.live_query_protocol import (  # noqa: E402
    LiveQueryProtocolError,
    load_live_query_protocol,
    validate_legacy_projection_matches_protocol,
)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project config/live_query_protocol.yml into legacy query_groups YAML."
    )
    parser.add_argument(
        "--protocol-path",
        default="config/live_query_protocol.yml",
        help="Path to authoritative live protocol YAML.",
    )
    parser.add_argument(
        "--output-path",
        default="outputs/research_sources/research_queries_from_protocol.yml",
        help="Path for generated legacy query_groups projection.",
    )
    parser.add_argument(
        "--min-total-queries",
        type=int,
        default=120,
        help="Fail if protocol has fewer executable queries than this threshold.",
    )
    parser.add_argument(
        "--emit-summary-path",
        default="outputs/research_sources/research_queries_from_protocol_summary.json",
        help="JSON summary output path for protocol/projection counts.",
    )
    parser.add_argument(
        "--emit-constraints-path",
        default="outputs/research_sources/query_protocol_constraints.json",
        help=(
            "JSON path for the per-query protocol constraints log "
            "(time_window, sort_strategy, sampling_strategy).  "
            "Consumed by the Layer 1 audit bundle to record applied vs "
            "unsupported filters."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    protocol = load_live_query_protocol(args.protocol_path)
    projection = protocol.to_legacy_query_groups()
    validate_legacy_projection_matches_protocol(protocol, projection)

    all_queries = protocol.all_queries()
    if len(all_queries) < args.min_total_queries:
        raise LiveQueryProtocolError(
            f"protocol query count {len(all_queries)} is below required minimum "
            f"{args.min_total_queries}"
        )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(projection, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    # Re-validate generated file by reading from disk.
    projection_from_disk = yaml.safe_load(output_path.read_text(encoding="utf-8")) or {}
    validate_legacy_projection_matches_protocol(protocol, projection_from_disk)

    family_counts = Counter(q.query_family.value for q in all_queries)
    sector_counts = {slug: len(sector.queries) for slug, sector in protocol.sectors.items()}
    summary = {
        "protocol_path": str(Path(args.protocol_path)),
        "projection_path": str(output_path),
        "protocol_query_count": len(all_queries),
        "projected_query_count": len(protocol.flattened_query_texts()),
        "family_counts": dict(sorted(family_counts.items())),
        "sector_counts": dict(sorted(sector_counts.items())),
    }

    summary_path = Path(args.emit_summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    # Fix 1: write per-query protocol constraints so downstream audit bundles
    # can record which time_window / sort_strategy / sampling_strategy values
    # were declared vs applied.  Provider adapters that do not support a given
    # filter should emit validity_warning = "filter_not_applied:<constraint>".
    constraints = protocol.to_query_constraints()
    constraints_payload = {
        "protocol_version": protocol.protocol_version,
        "query_count": len(constraints),
        "queries": constraints,
    }
    constraints_path = Path(args.emit_constraints_path)
    constraints_path.parent.mkdir(parents=True, exist_ok=True)
    constraints_path.write_text(
        json.dumps(constraints_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary["constraints_path"] = str(constraints_path)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LiveQueryProtocolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
