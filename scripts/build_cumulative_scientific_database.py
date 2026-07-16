#!/usr/bin/env python3
"""Build the PR-190 live cumulative scientific database (Layers 2 & 3).

This CLI wraps
:func:`src.scientific_sources.cumulative_scientific_database
.build_cumulative_scientific_database` and materializes its outputs under
``<output_dir>/``.

It is intentionally a thin adapter — every non-trivial responsibility (dedup,
novelty classification, semantic scanning, manifest, checksums) lives inside
the library module so it can be reused from tests and from other pipelines.

Usage
-----

.. code-block:: bash

    python scripts/build_cumulative_scientific_database.py \\
        --archive-root outputs/run_archive \\
        --live-runs-root outputs/live_runs \\
        --current-run outputs \\
        --query-protocol config/live_query_protocol.yml \\
        --output-dir outputs/cumulative_database \\
        --current-run-id 28967267944.2

The script is safe to run when some inputs are missing:

* If ``--archive-root`` is empty, only the current run contributes rows.
* If ``--live-runs-root`` is empty, records fall back to the Layer 0
  protocol index for query binding.
* If ``--query-protocol`` is empty, all Layer 0 fallback bindings are
  disabled (records may still bind through Layer 1).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources.cumulative_scientific_database import (  # noqa: E402
    CumulativeDatabaseError,
    build_cumulative_scientific_database,
)


def _collect_workflow_context() -> Dict[str, Any]:
    """Gather commonly-present GitHub Actions env vars for provenance."""
    keys = (
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_RUN_NUMBER",
        "GITHUB_JOB",
        "GITHUB_WORKFLOW",
        "GITHUB_EVENT_NAME",
        "GITHUB_SHA",
        "GITHUB_REF",
    )
    context: Dict[str, Any] = {}
    for key in keys:
        value = os.environ.get(key)
        if value:
            context[key.lower()] = value
    return context


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the PR-190 live cumulative scientific database "
            "(Layer 2 evidence records + Layer 3 semantic signals)."
        ),
    )
    parser.add_argument(
        "--current-run",
        default="outputs",
        help=(
            "Directory containing the current run's outputs. Must contain "
            "research_sources/live_records.json. (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/cumulative_database",
        help=(
            "Directory into which the bundle files are written. Created if "
            "it does not exist. (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--archive-root",
        default="outputs/run_archive",
        help=(
            "Root for cross-run history (cumulative_runs_index.csv and "
            "runs/<run_id>/research_sources/live_records.json). When absent, "
            "only the current run contributes. (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--live-runs-root",
        default="outputs/live_runs",
        help=(
            "Root for Layer 1 raw acquisition bundles "
            "(<run_id>/raw/raw_acquisition_index.csv). Used to bind provider "
            "records to their originating query_id when protocol_binding == "
            "'bound'. (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--query-protocol",
        default="config/live_query_protocol.yml",
        help=(
            "Path to the Layer 0 live query protocol registry. When absent "
            "the Layer 0 fallback lookup is disabled. (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--current-run-id",
        default=None,
        help=(
            "Deterministic identifier for the current run. Should match the "
            "run_id used by scripts/archive_run_outputs.py and "
            "scripts/build_live_run_audit.py. Falls back to 'current' when "
            "omitted."
        ),
    )
    parser.add_argument(
        "--built-at-utc",
        default=None,
        help=(
            "ISO-8601 timestamp to freeze into the manifest for reproducible "
            "bundles. When omitted the current UTC time is used."
        ),
    )
    parser.add_argument(
        "--emit-summary",
        action="store_true",
        help="Print a one-line JSON summary to stdout when the build succeeds.",
    )
    return parser.parse_args(argv)


def _optional_path(value: str) -> Optional[Path]:
    if not value:
        return None
    path = Path(value)
    return path


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    archive_root = _optional_path(args.archive_root)
    live_runs_root = _optional_path(args.live_runs_root)
    protocol_path = _optional_path(args.query_protocol)

    if archive_root is not None and not archive_root.is_dir():
        print(
            f"warning: archive-root not found: {archive_root}; "
            "only the current run will contribute.",
            file=sys.stderr,
        )
        archive_root = None
    if live_runs_root is not None and not live_runs_root.is_dir():
        print(
            f"warning: live-runs-root not found: {live_runs_root}; "
            "provider records will bind through Layer 0 only.",
            file=sys.stderr,
        )
        live_runs_root = None
    if protocol_path is not None and not protocol_path.is_file():
        print(
            f"warning: query-protocol not found: {protocol_path}; "
            "Layer 0 fallback lookup disabled.",
            file=sys.stderr,
        )
        protocol_path = None

    try:
        result = build_cumulative_scientific_database(
            current_run_dir=args.current_run,
            output_dir=args.output_dir,
            archive_root=archive_root,
            live_runs_root=live_runs_root,
            protocol_path=protocol_path,
            current_run_id=args.current_run_id,
            built_at_utc=args.built_at_utc,
            workflow_context=_collect_workflow_context(),
        )
    except CumulativeDatabaseError as exc:
        print(f"error: failed to build cumulative scientific database: {exc}", file=sys.stderr)
        return 1

    print(
        f"wrote {len(result.files)} files to {result.output_dir} "
        f"({len(result.evidence_records)} evidence rows, "
        f"{len(result.competence_demand_signals)} semantic signals)."
    )
    if args.emit_summary:
        metrics = result.run_novelty_metrics.to_dict()
        summary = {
            "output_dir": str(result.output_dir),
            "current_run_id": metrics["current_run_id"],
            "previous_run_id": metrics["previous_run_id"],
            "evidence_records": len(result.evidence_records),
            "competence_demand_signals": len(result.competence_demand_signals),
            "new_unique_doi_count": metrics["new_unique_doi_count"],
            "repeated_doi_count": metrics["repeated_doi_count"],
            "semantic_new_signal_count": metrics["semantic_new_signal_count"],
            "jaccard_similarity_with_previous_run": metrics[
                "jaccard_similarity_with_previous_run"
            ],
        }
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
