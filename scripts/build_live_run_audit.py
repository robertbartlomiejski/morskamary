#!/usr/bin/env python3
"""Build a Layer 1 raw-provider-acquisition audit bundle for one live run.

This script is the CLI wrapper around
:func:`src.scientific_sources.live_run_audit.build_live_run_audit`. It reads
the outputs already emitted by ``scripts/export_live_research_records.py``
(``outputs/research_sources/…``) and constructs a deterministic, per-run
audit bundle under ``outputs/live_runs/<run_id>/`` that preserves raw
provider acquisition separately from normalized evidence.

The exporter is **not modified** by this script — Layer 1 is a purely
additive downstream builder. Every existing PR-186/187/189 safeguard
(archive integrity, deterministic outputs, manifest/checksum discipline,
sync-gate hardening) remains untouched.

Usage
-----

.. code-block:: bash

    python scripts/build_live_run_audit.py \
        --run-id 28967267944.2 \
        --research-sources-dir outputs/research_sources \
        --output-root outputs/live_runs \
        --protocol-path config/live_query_protocol.yml
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

from src.scientific_sources.live_run_audit import (  # noqa: E402
    LiveRunAuditError,
    build_live_run_audit,
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
            "Build the Layer 1 raw-provider-acquisition audit bundle "
            "(outputs/live_runs/<run_id>/)."
        ),
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help=(
            "Deterministic identifier for this run. Must match the run_id "
            "used by scripts/archive_run_outputs.py so that downstream layers "
            "can join the audit bundle to the run archive."
        ),
    )
    parser.add_argument(
        "--research-sources-dir",
        default="outputs/research_sources",
        help=(
            "Directory produced by scripts/export_live_research_records.py. "
            "Must contain raw_provider_records.json, live_records.json, and "
            "live_provenance.json. (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--output-root",
        default="outputs/live_runs",
        help=(
            "Root under which <output_root>/<run_id>/ will be created. "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--protocol-path",
        default="config/live_query_protocol.yml",
        help=(
            "Path to the Layer 0 live query protocol registry. When absent "
            "the bundle is still produced with protocol_binding='unbound'. "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--emit-summary",
        action="store_true",
        help="Print a one-line JSON summary to stdout when the build succeeds.",
    )
    parser.add_argument(
        "--built-at-utc",
        default=None,
        help=(
            "Optional ISO-8601 timestamp to freeze into the manifest for "
            "reproducible byte-identical bundles. When omitted the current "
            "UTC time is used."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    protocol_path = Path(args.protocol_path)
    protocol_arg: Optional[Path] = protocol_path if protocol_path.is_file() else None
    if protocol_arg is None:
        print(
            f"warning: protocol file not found at {protocol_path}; "
            "audit rows will be emitted with protocol_binding='unbound'.",
            file=sys.stderr,
        )

    try:
        result = build_live_run_audit(
            run_id=args.run_id,
            research_sources_dir=args.research_sources_dir,
            output_root=args.output_root,
            protocol_path=protocol_arg,
            workflow_context=_collect_workflow_context(),
            built_at_utc=args.built_at_utc,
        )
    except LiveRunAuditError as exc:
        print(f"error: failed to build live-run audit bundle: {exc}", file=sys.stderr)
        return 1

    bound = sum(1 for row in result.acquisition_rows if row.protocol_binding == "bound")
    unbound = sum(
        1 for row in result.acquisition_rows if row.protocol_binding == "unbound"
    )
    print(
        f"wrote {len(result.files)} files to {result.bundle_dir} "
        f"({result.raw_row_count} raw rows, {result.normalized_row_count} normalized, "
        f"{bound} bound / {unbound} unbound acquisition rows)."
    )
    if args.emit_summary:
        summary = {
            "run_id": result.run_id,
            "bundle_dir": str(result.bundle_dir),
            "file_count": len(result.files),
            "raw_records": result.raw_row_count,
            "normalized_records": result.normalized_row_count,
            "acquisition_rows_bound": bound,
            "acquisition_rows_unbound": unbound,
        }
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
