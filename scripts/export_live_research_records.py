#!/usr/bin/env python3
"""
Export live research records from configured providers.

Fetches literature metadata from Crossref and other configured providers
based on query groups defined in config/research_queries.yml.

Outputs:
  - outputs/research_sources/live_records.json (triangulated winners; Stage 1)
  - outputs/research_sources/live_records_triangulated.json (winners + loop metadata)
  - outputs/research_sources/live_records.csv (flattened CSV)
  - outputs/research_sources/crossref_records.json (Crossref-only records)
  - outputs/research_sources/raw_provider_records.json (raw provider rows pre-merge)
  - outputs/research_sources/enrichment_records.json (non-identity provider rows)
  - outputs/research_sources/live_provenance.json (provenance metadata)
  - outputs/research_sources/live_source_coverage.csv (coverage by sector/provider)
  - outputs/research_sources/scopus_query_diagnostics.json
    (per-query Scopus returned/normalized/contributed diagnostics)
  - outputs/research_sources/low_confidence_live_records.json (records with confidence < 0.8)
  - outputs/research_sources/triangulation_identity_loop.json (loop-1 identity audit)
  - outputs/research_sources/triangulation_thematic_loop.json (loop-2 QMBD audit)

Features:
  - Explicit provider-priority identity triangulation (loop 1)
  - Thematic/QMBD validation audit (loop 2)
  - Includes full provenance tracking (provider, query, timestamp, endpoint, DOI)
  - Does not store abstracts or full text (licence compliance)
  - Supports offline mode for testing (no network calls)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources.models import (  # noqa: E402
    LiteratureRecord,
    SourceEvidence,
)
from src.scientific_sources.source_registry import SourceRegistry  # noqa: E402
from src.scientific_sources.live_query_protocol import (  # noqa: E402
    LiveQueryProtocolError,
    load_live_query_protocol,
    validate_complete_authoritative_protocol_projection,
)
from src.axis_classifier import AxisClassifier  # noqa: E402
from src.cumulative_analysis.triangulator import (  # noqa: E402
    CumulativeTriangulator,
    TriangulatedRecord,
)
from src.literature_extraction import extract_sentence_records  # noqa: E402

DEFAULT_PROVIDER_POLICY_PATH = REPO_ROOT / "config" / "research_provider_policy.yml"

QUERY_EXECUTION_FIELDS: Tuple[str, ...] = (
    "query_id",
    "sector_slug",
    "query_family",
    "query_text",
    "provider",
    "provider_canonical",
    "execution_status",
    "returned_record_count",
    "normalized_record_count",
    "contributed_record_count",
    "raw_record_count",
    "accepted_record_count",
    "excluded_outside_time_window_count",
    "excluded_missing_year_count",
    "from_year",
    "to_year",
    "declared_sort_strategy",
    "applied_sort_strategy",
    "sort_strategy_source",
    "sort_status",
    "declared_sampling_mode",
    "declared_pages",
    "declared_rows_per_page",
    "sampling_status",
    "time_window_status",
    "requested_constraint_filters",
    "applied_constraint_filters",
    "unsupported_constraint_filters",
    "unapplied_constraint_filters",
    "validity_warnings",
    "errors",
    "warnings",
    "logical_pages_attempted",
    "logical_pages_completed",
    "physical_request_count",
    "pagination_warning_count",
)


def _safe_page_int(value: Any) -> int:
    """Tolerantly parse a page-number value; return 0 for any unparseable input.

    Malformed provider diagnostics must never crash after paid acquisition.
    """
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalise_page_diagnostics(
    diagnostics: Sequence[Any],
    *,
    provider_name: str,
    query: str,
) -> List[Dict[str, Any]]:
    """Return mapping-only diagnostics, replacing malformed entries fail closed.

    Provider acquisition has already happened by the time diagnostics are
    exported. A non-mapping value must therefore never raise from ``dict(value)``
    and discard the run. Instead, preserve the audit boundary with a stable
    canonical failed row that records the malformed-entry index without
    serialising the original arbitrary object.
    """
    normalised: List[Dict[str, Any]] = []
    provider_canonical = normalize_provider_name(provider_name)
    for index, diagnostic in enumerate(diagnostics, start=1):
        if isinstance(diagnostic, Mapping):
            normalised.append(dict(diagnostic))
            continue
        normalised.append(
            {
                "provider": provider_canonical,
                "query": query,
                "logical_page": 0,
                "physical_request_index": 0,
                "cursor_or_offset": "",
                "requested_rows": 0,
                "returned_rows": 0,
                "normalized_rows": 0,
                "pagination_status": "failed",
                "errors": "malformed_page_diagnostic_non_mapping",
                "warnings": f"malformed_page_diagnostic_index:{index}",
            }
        )
    return normalised


# Diagnostic status values that represent zero actual paid requests.
_ZERO_ATTEMPT_STATUSES = frozenset(
    {"provider_not_configured", "not_configured", "no_credentials", "skipped"}
)


def _parse_canonical_positive_int(raw: Any) -> Optional[int]:
    """Return a positive canonical integer from *raw*, or ``None`` for any invalid input.

    Accepted: plain Python ``int`` that is positive (not ``bool``, not ``float``).
    For string inputs, only canonical ASCII-digit sequences (``[0-9]+``) are
    accepted; ``+1``, ``1_0``, ``-1``, ``1.0``, ``True`` and similar non-canonical
    forms are all rejected.  Never raises.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, float):
        return None
    if isinstance(raw, str):
        if not re.fullmatch(r"[0-9]+", raw):
            return None
        v = int(raw)
    else:
        try:
            v = int(raw)
        except (TypeError, ValueError):
            return None
    return v if v > 0 else None


def _count_physical_requests(diagnostics: Sequence[Mapping[str, Any]]) -> int:
    """Deterministically count physical provider requests from page diagnostics.

    Precedence contract per logical page:

    1. If **all** rows for that logical page have a zero-attempt
       ``pagination_status`` (``provider_not_configured``, ``not_configured``,
       ``no_credentials``, ``skipped``), contribute **0** regardless of any
       reported ``physical_requests`` or ``physical_request_index`` values.
    2. Otherwise, ignore zero-attempt rows when calculating actual attempts.
    3. Use the maximum valid **positive canonical integer** ``physical_requests``
       from attempted rows.
    4. Where no valid ``physical_requests`` exists, count unique valid positive
       canonical ``physical_request_index`` values from attempted rows.
    5. Use a one-attempt fallback when at least one attempted-status row exists
       but no valid counts are available.
    6. Malformed, non-positive, bool, float, signed, underscore-separated, or
       otherwise non-canonical values are ignored and never crash.
    """
    if not diagnostics:
        return 0

    by_page: Dict[int, List[Mapping[str, Any]]] = {}
    for row in diagnostics:
        page = _safe_page_int(row.get("logical_page", 0))
        by_page.setdefault(page, []).append(row)

    total = 0
    for page_rows in by_page.values():
        if all(
            str(row.get("pagination_status", "")) in _ZERO_ATTEMPT_STATUSES
            for row in page_rows
        ):
            continue

        attempted_rows = [
            row
            for row in page_rows
            if str(row.get("pagination_status", "")) not in _ZERO_ATTEMPT_STATUSES
        ]

        valid_totals: List[int] = []
        for row in attempted_rows:
            v = _parse_canonical_positive_int(row.get("physical_requests"))
            if v is not None:
                valid_totals.append(v)

        if valid_totals:
            total += max(valid_totals)
            continue

        valid_indexes: set = set()
        for row in attempted_rows:
            v = _parse_canonical_positive_int(row.get("physical_request_index"))
            if v is not None:
                valid_indexes.add(v)

        if valid_indexes:
            total += len(valid_indexes)
            continue

        total += 1

    return total


_DEFAULT_PROVIDER_POLICY: Dict[str, Any] = {
    "precedence": [
        "crossref",
        "scopus",
        "openalex",
        "wos",
        "scival",
        "microsoft_graph",
        "google_drive",
    ],
    "classes": {
        "crossref": "bibliographic",
        "scopus": "bibliographic",
        "openalex": "bibliographic",
        "wos": "bibliographic",
        "scival": "enrichment",
        "microsoft_graph": "workspace",
        "google_drive": "workspace",
    },
    "primary_identity_providers": ["crossref", "scopus", "openalex", "wos"],
}

# Remaining file content preserved from branch head.
