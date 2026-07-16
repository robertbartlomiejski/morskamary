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
  - outputs/research_sources/scopus_query_diagnostics.json (per-query Scopus returned/normalized/contributed diagnostics)
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
import json
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
)

_DEFAULT_PROVIDER_POLICY: Dict[str, Any] = {
    "precedence": [
        "crossref",
        "scopus",
        "wos",
        "scival",
        "microsoft_graph",
        "google_drive",
    ],
    "classes": {
        "crossref": "bibliographic",
        "scopus": "bibliographic",
        "wos": "bibliographic",
        "scival": "enrichment",
        "microsoft_graph": "workspace",
        "google_drive": "workspace",
    },
    "primary_identity_providers": ["crossref", "scopus", "wos"],
}

DEFAULT_QUERY_FILE_PATH = Path("config/research_queries.yml")
DEFAULT_QUERY_CONSTRAINTS_PATH = Path(
    "outputs/research_sources/query_protocol_constraints.json"
)
PROTOCOL_PROJECTED_QUERY_FILE_NAME = "research_queries_from_protocol.yml"


@dataclass(frozen=True)
class _ScopedTextSegment:
    """Scoped segment within a concatenated live API text block."""

    text_scope: str
    text: str
    start: int
    end: int


class LiveContextClassificationRepository:
    """Repository-style access to sentence-level live API classifications."""

    def __init__(self, classifier: AxisClassifier | None = None) -> None:
        self._classifier = classifier or AxisClassifier()
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    @staticmethod
    def _extract_abstract(rec: LiteratureRecord) -> str:
        value = getattr(rec, "abstract", "")
        return str(value).strip() if value else ""

    def _build_scoped_context(
        self, rec: LiteratureRecord
    ) -> Tuple[str, List[_ScopedTextSegment]]:
        title = str(rec.title).strip()
        abstract = self._extract_abstract(rec)
        subject_text = " ".join(
            str(term).strip() for term in rec.subject_terms if str(term).strip()
        )
        raw_segments = [
            ("live_api_title_sentence", title),
            ("live_api_abstract_sentence", abstract),
            ("live_api_subject_terms_sentence", subject_text),
        ]

        chunks: List[str] = []
        scoped: List[_ScopedTextSegment] = []
        cursor = 0
        for text_scope, raw in raw_segments:
            normalized = re.sub(r"\s+", " ", raw).strip()
            if not normalized:
                continue
            if chunks:
                chunks.append(" ")
                cursor += 1
            start = cursor
            chunks.append(normalized)
            cursor += len(normalized)
            scoped.append(
                _ScopedTextSegment(
                    text_scope=text_scope,
                    text=normalized,
                    start=start,
                    end=cursor,
                )
            )

        return "".join(chunks), scoped

    @staticmethod
    def _scope_for_sentence(
        sentence_start: int,
        sentence_end: int,
        scoped_segments: List[_ScopedTextSegment],
    ) -> str:
        for segment in scoped_segments:
            if sentence_start >= segment.start and sentence_end <= segment.end:
                return segment.text_scope
        return "live_api_context_sentence"

    def classify_record_sentences(self, rec: LiteratureRecord) -> List[Dict[str, Any]]:
        """Return sentence-level classifications for one live record."""
        cache_key = rec.source_id or f"{rec.provider}:{normalize_title(rec.title)}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return [dict(item) for item in cached]

        combined_text, scoped_segments = self._build_scoped_context(rec)
        sentence_records = extract_sentence_records(combined_text)
        classifications: List[Dict[str, Any]] = []
        for sentence_record in sentence_records:
            scope = self._scope_for_sentence(
                sentence_record.start, sentence_record.end, scoped_segments
            )
            classification = self._classifier.classify_context(
                sentence_record.sentence,
                text_scope=scope,
            )
            classification["sentence_index"] = len(classifications) + 1
            classifications.append(classification)
        self._cache[cache_key] = [dict(item) for item in classifications]
        return [dict(item) for item in classifications]

    @staticmethod
    def dominant_axis_from_classifications(
        classifications: List[Dict[str, Any]],
    ) -> Tuple[str, str]:
        """Return dominant axis name/code from sentence-level classifications."""
        axis_count: Dict[str, int] = {}
        axis_code: Dict[str, str] = {}
        for item in classifications:
            axis_name = str(item.get("axis", "")).strip().upper()
            if not axis_name:
                continue
            axis_count[axis_name] = axis_count.get(axis_name, 0) + 1
            axis_code[axis_name] = str(item.get("axis_code", "")).strip()
        if not axis_count:
            return "OCEANIC", "O"
        winner = max(axis_count.items(), key=lambda pair: pair[1])[0]
        return winner, axis_code.get(winner, "")


def normalize_title(title: str) -> str:
    """
    Normalize a title for deduplication.

    Lowercases, removes punctuation, and collapses whitespace.
    """
    title_lower = title.lower()
    # Remove punctuation and special characters
    title_clean = re.sub(r"[^\w\s]", "", title_lower)
    # Collapse whitespace
    title_normalized = re.sub(r"\s+", " ", title_clean).strip()
    return title_normalized


def normalize_provider_name(provider: str) -> str:
    """Normalize provider labels to SourceRegistry capability names."""
    text = provider.strip().lower()
    if "crossref" in text:
        return "crossref"
    if "scopus" in text:
        return "scopus"
    if "web of science" in text or text == "wos" or "clarivate" in text:
        return "wos"
    if "scival" in text:
        return "scival"
    if "microsoft graph" in text or "onedrive" in text or "sharepoint" in text:
        return "microsoft_graph"
    if "google drive" in text:
        return "google_drive"
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def load_provider_policy(path: Path) -> Dict[str, Any]:
    """Load explicit provider-priority and class policy from YAML."""
    if not path.exists():
        return dict(_DEFAULT_PROVIDER_POLICY)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = payload.get("provider_policy", {})
    if not isinstance(section, dict):
        return dict(_DEFAULT_PROVIDER_POLICY)
    merged = dict(_DEFAULT_PROVIDER_POLICY)
    merged.update({k: v for k, v in section.items() if v})
    return merged


def _load_query_constraints(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load and index the authoritative per-query acquisition constraints."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("queries"), list):
        raise ValueError("query constraints must contain a queries list")
    indexed: Dict[str, Dict[str, Any]] = {}
    for raw in payload["queries"]:
        if not isinstance(raw, dict):
            raise ValueError("each query constraint must be an object")
        query_text = str(raw.get("query_text", "")).strip()
        query_id = str(raw.get("query_id", "")).strip()
        if not query_text or not query_id:
            raise ValueError("each query constraint requires query_id and query_text")
        key = query_text.lower()
        if key in indexed:
            raise ValueError(f"duplicate query constraint: {query_text}")
        indexed[key] = dict(raw)
    declared_count = int(payload.get("query_count", len(indexed)))
    if declared_count != len(indexed):
        raise ValueError(
            f"constraint query_count={declared_count} but indexed {len(indexed)}"
        )
    return indexed


def _build_ad_hoc_constraints_from_query_groups(
    query_groups: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Build deterministic fallback constraints for ad-hoc query files."""
    constraints: Dict[str, Dict[str, Any]] = {}
    for sector_slug, sector_data in query_groups.items():
        queries = sector_data.get("queries", [])
        if not isinstance(queries, list):
            continue
        for index, query_text in enumerate(queries, start=1):
            normalized_query = str(query_text).strip()
            if not normalized_query:
                continue
            constraints[normalized_query.lower()] = {
                "query_id": f"ad_hoc:{sector_slug}:{index:03d}",
                "query_text": normalized_query,
                "sector_slug": str(sector_slug),
                "query_family": "ad_hoc",
                "time_window": {},
                "sort_strategy": {},
                "sampling_strategy": {},
            }
    return constraints


def _record_year(record: LiteratureRecord) -> Optional[int]:
    raw_year = str(getattr(record, "year", "") or "").strip()
    if not raw_year:
        return None
    match = re.search(r"\b(\d{4})\b", raw_year)
    return int(match.group(1)) if match else None


def _apply_query_constraint(
    records: Sequence[LiteratureRecord],
    constraint: Mapping[str, Any],
    provider_name: str,
    max_results: int,
) -> Tuple[List[LiteratureRecord], Dict[str, Any]]:
    """Apply auditable post-fetch time, sort, and sampling constraints."""
    time_window = constraint.get("time_window", {})
    if not isinstance(time_window, Mapping):
        time_window = {}
    from_year = int(time_window.get("from_year", 0) or 0)
    to_year = int(time_window.get("to_year", 9999) or 9999)

    accepted: List[LiteratureRecord] = []
    excluded_outside = 0
    excluded_missing_year = 0
    for record in records:
        year = _record_year(record)
        if year is None:
            excluded_missing_year += 1
            continue
        if year < from_year or year > to_year:
            excluded_outside += 1
            continue
        accepted.append(record)

    sort_strategy = constraint.get("sort_strategy", {})
    if not isinstance(sort_strategy, Mapping):
        sort_strategy = {}
    provider_key = normalize_provider_name(provider_name)
    declared_sort = str(sort_strategy.get(provider_key, "")).strip()
    if declared_sort in ("published-desc", "date-desc"):
        accepted.sort(
            key=lambda record: (
                -(_record_year(record) or 0),
                normalize_title(record.title),
                record.doi.lower(),
                record.source_id,
            )
        )
        sort_status = "applied_post_fetch"
    elif declared_sort:
        sort_status = "unsupported_strategy"
    else:
        sort_status = "not_declared_for_provider"

    sampling = constraint.get("sampling_strategy", {})
    if not isinstance(sampling, Mapping):
        sampling = {}
    mode = str(sampling.get("mode", "")).strip()
    pages = int(sampling.get("pages", 1) or 1)
    rows_per_page = int(sampling.get("rows_per_page", max_results) or max_results)
    declared_capacity = max(1, pages) * max(1, rows_per_page)
    applied_limit = min(max_results, declared_capacity)
    accepted = accepted[:applied_limit]
    sampling_status = (
        "applied_single_request_limit"
        if pages <= 1 and applied_limit >= declared_capacity
        else "partially_applied_registry_has_no_page_cursor"
    )

    validity_warnings: List[str] = []
    if sort_status.startswith("unsupported") or sort_status.startswith("not_declared"):
        validity_warnings.append("filter_not_applied:sort_strategy")
    if sampling_status.startswith("partially"):
        validity_warnings.append("filter_not_applied:multi_page_sampling")

    requested_filters: List[str] = ["time_window", "sampling_strategy"]
    if declared_sort:
        requested_filters.append("sort_strategy")
    applied_filters: List[str] = ["time_window"]
    unsupported_filters: List[str] = []
    unapplied_filters: List[str] = []
    if sort_status == "applied_post_fetch":
        applied_filters.append("sort_strategy")
    elif sort_status == "unsupported_strategy":
        unsupported_filters.append("sort_strategy")
    elif sort_status == "not_declared_for_provider":
        unapplied_filters.append("sort_strategy")
    if sampling_status == "applied_single_request_limit":
        applied_filters.append("sampling_strategy")
    elif sampling_status.startswith("partially"):
        unapplied_filters.append("sampling_strategy")
    return accepted, {
        "raw_record_count": len(records),
        "accepted_record_count": len(accepted),
        "excluded_outside_time_window_count": excluded_outside,
        "excluded_missing_year_count": excluded_missing_year,
        "from_year": from_year,
        "to_year": to_year,
        "declared_sort_strategy": declared_sort,
        "sort_status": sort_status,
        "declared_sampling_mode": mode,
        "declared_pages": pages,
        "declared_rows_per_page": rows_per_page,
        "sampling_status": sampling_status,
        "time_window_status": "applied_post_fetch",
        "requested_constraint_filters": "|".join(sorted(set(requested_filters))),
        "applied_constraint_filters": "|".join(sorted(set(applied_filters))),
        "unsupported_constraint_filters": "|".join(sorted(set(unsupported_filters))),
        "unapplied_constraint_filters": "|".join(sorted(set(unapplied_filters))),
        "validity_warnings": "|".join(validity_warnings),
    }


def export_query_execution_log(
    rows: Sequence[Mapping[str, Any]],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=QUERY_EXECUTION_FIELDS,
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in sorted(
            rows,
            key=lambda item: (
                str(item.get("query_id", "")),
                str(item.get("provider", "")),
            ),
        ):
            writer.writerow(
                {
                    field: row.get(field, "")
                    for field in QUERY_EXECUTION_FIELDS
                }
            )


def _identity_key_from_record(rec: LiteratureRecord) -> str:
    """Return deterministic deduplication key (DOI → title → provider source_id)."""
    doi = rec.doi.strip().lower()
    if doi:
        return f"doi:{doi}"
    normalized_title = normalize_title(rec.title)
    if normalized_title:
        return f"title:{normalized_title}"
    source_id = rec.source_id.strip()
    if source_id:
        provider_key = normalize_provider_name(rec.provider) or "unknown"
        return f"source_id:{provider_key}:{source_id}"
    return "unknown:missing-identity"


def _identity_key_from_triangulated(rec: TriangulatedRecord) -> str:
    doi = rec.doi.strip().lower()
    if doi:
        return f"doi:{doi}"
    normalized_title = normalize_title(rec.title)
    if normalized_title:
        return f"title:{normalized_title}"
    source_id = str(getattr(rec, "source_id", "")).strip()
    provider = str(getattr(rec, "provider", "")).strip()
    if source_id:
        provider_key = normalize_provider_name(provider) or "unknown"
        return f"source_id:{provider_key}:{source_id}"
    return "unknown:missing-identity"


def _triangulated_to_literature(rec: TriangulatedRecord) -> LiteratureRecord:
    """Convert TriangulatedRecord back to LiteratureRecord for existing exporters."""
    return LiteratureRecord(
        title=rec.title,
        authors=rec.authors,
        year=rec.year,
        doi=rec.doi,
        source_id=rec.source_id
        or f"{normalize_provider_name(rec.provider)}:{rec.doi or rec.title[:40]}",
        provider=rec.provider,
        language=rec.language,
        journal=rec.journal,
        url=rec.url,
        subject_terms=list(rec.subject_terms),
        source_query=rec.source_query,
        retrieval_timestamp=rec.retrieval_timestamp,
        licence_note=rec.licence_note,
    )


def triangulate_identity_loop(
    records: List[LiteratureRecord],
    policy: Dict[str, Any],
) -> Tuple[
    List[LiteratureRecord],
    List[TriangulatedRecord],
    Dict[str, Any],
    Dict[str, int],
    Dict[str, List[str]],
]:
    """Triangulate live records using explicit provider priority and emit identity audit."""
    precedence = list(policy.get("precedence", _DEFAULT_PROVIDER_POLICY["precedence"]))
    rank = {name: idx for idx, name in enumerate(precedence)}
    primary_identity = set(
        policy.get(
            "primary_identity_providers",
            _DEFAULT_PROVIDER_POLICY["primary_identity_providers"],
        )
    )

    identity_records = [
        rec
        for rec in records
        if normalize_provider_name(rec.provider) in primary_identity
    ]
    non_identity_records = [
        rec
        for rec in records
        if normalize_provider_name(rec.provider) not in primary_identity
    ]
    if not identity_records:
        deduped, stats = deduplicate_records(records)
        empty_audit = {
            "policy_precedence": precedence,
            "primary_identity_providers": sorted(primary_identity),
            "collision_events": [],
            "dedup_stats": stats,
        }
        return deduped, [], empty_audit, stats, {}

    indexed = list(enumerate(identity_records))
    indexed.sort(
        key=lambda pair: (
            rank.get(normalize_provider_name(pair[1].provider), len(rank)),
            pair[0],
        )
    )
    sorted_identity = [rec for _, rec in indexed]

    triangulator = CumulativeTriangulator()
    triangulator.ingest_dynamic_records(sorted_identity)
    merged = triangulator.triangulate()
    merged_records = [_triangulated_to_literature(rec) for rec in merged]

    winner_by_identity = {_identity_key_from_triangulated(rec): rec for rec in merged}
    merged_record_by_identity = {
        _identity_key_from_record(rec): rec for rec in merged_records
    }
    grouped_candidates: Dict[str, List[LiteratureRecord]] = defaultdict(list)
    for rec in records:
        grouped_candidates[_identity_key_from_record(rec)].append(rec)

    support_by_identity: Dict[str, List[str]] = {}
    collision_events: List[Dict[str, Any]] = []
    doi_dups = 0
    title_dups = 0
    for identity_key, candidates in grouped_candidates.items():
        candidates_with_norm = [
            (rec, normalize_provider_name(rec.provider)) for rec in candidates
        ]
        candidates_sorted = sorted(
            candidates_with_norm,
            key=lambda pair: rank.get(pair[1], len(rank)),
        )
        support_by_identity[identity_key] = sorted(
            {norm for _, norm in candidates_sorted}
        )
        if len(candidates) <= 1:
            continue
        if identity_key.startswith("doi:"):
            doi_dups += len(candidates) - 1
        else:
            title_dups += len(candidates) - 1
        winner = winner_by_identity.get(identity_key)
        if winner is None:
            continue
        preferred_language = next(
            (rec.language for rec, _ in candidates_sorted if rec.language.strip()),
            "",
        )
        if preferred_language and not winner.language.strip():
            winner.language = preferred_language
        merged_record = merged_record_by_identity.get(identity_key)
        if merged_record is not None and preferred_language:
            if not merged_record.language.strip():
                merged_record.language = preferred_language
        winner_norm = normalize_provider_name(winner.provider)
        losers = [
            {
                "provider": rec.provider,
                "provider_name": provider_name,
                "source_id": rec.source_id,
                "doi": rec.doi,
            }
            for rec, provider_name in candidates_sorted
            if rec.source_id != winner.source_id
        ]
        collision_events.append(
            {
                "identity_key": identity_key,
                "winner": {
                    "provider": winner.provider,
                    "provider_name": winner_norm,
                    "source_id": winner.source_id,
                    "doi": winner.doi,
                    "reason": "highest-provider-priority",
                },
                "losers": losers,
                "candidate_count": len(candidates),
            }
        )

    unmatched_non_identity: List[LiteratureRecord] = []
    winner_keys = set(winner_by_identity)
    for rec in non_identity_records:
        identity_key = _identity_key_from_record(rec)
        if identity_key not in winner_keys:
            unmatched_non_identity.append(rec)
    deduped_unmatched_non_identity, _ = deduplicate_records(unmatched_non_identity)
    merged_records.extend(deduped_unmatched_non_identity)

    stats = {"doi_duplicates": doi_dups, "title_duplicates": title_dups}
    audit = {
        "policy_precedence": precedence,
        "primary_identity_providers": sorted(primary_identity),
        "collision_events": collision_events,
        "dedup_stats": stats,
    }
    return merged_records, merged, audit, stats, support_by_identity


def build_thematic_loop_audit(
    records: List[LiteratureRecord],
    provenance: List[SourceEvidence],
    support_by_identity: Dict[str, List[str]],
    provider_classes: Dict[str, str],
    sectors_by_identity_key: Dict[str, Set[str]] | None = None,
    classification_repo: LiveContextClassificationRepository | None = None,
) -> Dict[str, Any]:
    """Build loop-2 thematic/QMBD audit for triangulated records."""
    classification_repo = classification_repo or LiveContextClassificationRepository()
    confidence_by_record: Dict[str, float] = {}
    for ev in provenance:
        prev = confidence_by_record.get(ev.record_id, 0.0)
        confidence_by_record[ev.record_id] = max(prev, float(ev.confidence_score))

    rows: List[Dict[str, Any]] = []
    for rec in records:
        sentence_classifications = classification_repo.classify_record_sentences(rec)
        axis_name, axis_code = classification_repo.dominant_axis_from_classifications(
            sentence_classifications
        )
        identity_key = _identity_key_from_record(rec)
        support = support_by_identity.get(
            identity_key, [normalize_provider_name(rec.provider)]
        )
        overlap_status = "multi-source" if len(set(support)) > 1 else "single-source"
        confidence = confidence_by_record.get(rec.source_id, 0.0)
        sectors = (
            sorted(sectors_by_identity_key.get(identity_key, set()))
            if sectors_by_identity_key
            else []
        )
        manual_review_flags: List[str] = []
        if not rec.doi:
            manual_review_flags.append("missing-doi")
        if confidence < 0.8:
            manual_review_flags.append("low-confidence")
        if overlap_status == "single-source":
            manual_review_flags.append("single-source-evidence")

        rows.append(
            {
                "source_id": rec.source_id,
                "title": rec.title,
                "provider": rec.provider,
                "provider_class": provider_classes.get(
                    normalize_provider_name(rec.provider), "unknown"
                ),
                "sectors": sectors,
                "qmbd_axis": axis_name,
                "qmbd_axis_code": axis_code,
                "sentence_classifications": _sanitize_persisted_sentence_classifications(
                    sentence_classifications
                ),
                "confidence_score": confidence,
                "overlap_status": overlap_status,
                "supporting_providers": support,
                "manual_review_flags": manual_review_flags,
            }
        )
    return {
        "loop_2_name": "thematic-qmbd-validation",
        "records": rows,
    }


def _sanitize_persisted_sentence_classifications(
    sentence_classifications: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove raw sentence text before persisting sentence-level audit payloads."""
    sanitized: List[Dict[str, Any]] = []
    for item in sentence_classifications:
        sentence = str(item.get("sentence", "")).strip()
        sanitized_item: Dict[str, Any] = {
            "axis": item.get("axis", ""),
            "axis_code": item.get("axis_code", ""),
            "text_scope": item.get("text_scope", ""),
        }
        if "matched_keywords" in item:
            sanitized_item["matched_keywords"] = item.get("matched_keywords", [])
        if "confidence_score" in item:
            sanitized_item["confidence_score"] = item.get("confidence_score", 0.0)
        if "sentence_index" in item:
            sanitized_item["sentence_index"] = item.get("sentence_index")
        if sentence:
            sanitized_item["sentence_hash"] = hashlib.sha256(
                sentence.encode("utf-8")
            ).hexdigest()
            sanitized_item["sentence_length"] = len(sentence)
        sanitized.append(sanitized_item)
    return sanitized


def deduplicate_records(
    records: List[LiteratureRecord],
) -> Tuple[List[LiteratureRecord], Dict[str, int]]:
    """
    Deduplicate records by DOI first, then by normalized title.

    Args:
        records: List of LiteratureRecord objects.

    Returns:
        Tuple of (deduplicated_records, dedup_stats).
    """
    seen_dois: Set[str] = set()
    seen_titles: Set[str] = set()
    doi_idx: Dict[str, int] = {}
    # Maps norm_title → index in `deduped` for records accepted without a DOI.
    # When a DOI-bearing record for the same title arrives later we upgrade the
    # slot in-place so the DOI record wins (DOI-first policy).
    nondoi_title_idx: Dict[str, int] = {}
    deduped: List[LiteratureRecord] = []
    stats = {"doi_duplicates": 0, "title_duplicates": 0}

    for rec in records:
        norm_title = normalize_title(rec.title)
        title_key = norm_title
        if not title_key:
            source_id = rec.source_id.strip()
            provider_key = normalize_provider_name(rec.provider) or "unknown"
            if source_id:
                title_key = f"source_id:{provider_key}:{source_id}"
            else:
                title_key = "unknown:missing-title-and-source-id"
        if rec.doi:
            doi_key = rec.doi.strip().lower()
            if doi_key in seen_dois:
                stats["doi_duplicates"] += 1
                existing_idx = doi_idx.get(doi_key)
                if existing_idx is not None:
                    existing = deduped[existing_idx]
                    if not existing.language.strip() and rec.language.strip():
                        existing.language = rec.language
                continue
            # A no-DOI record with the same title was accepted earlier: upgrade
            # it with this DOI-bearing record so the DOI version wins.
            if title_key in nondoi_title_idx:
                idx = nondoi_title_idx.pop(title_key)
                existing = deduped[idx]
                if not rec.language.strip() and existing.language.strip():
                    rec.language = existing.language
                deduped[idx] = rec
                seen_dois.add(doi_key)
                doi_idx[doi_key] = idx
                # Count as a title duplicate: the incoming record was matched
                # by title (not DOI) against a previously accepted no-DOI slot.
                stats["title_duplicates"] += 1
                continue
            # Distinct DOIs identify distinct papers even if titles happen to
            # match, so keep the record regardless of seen_titles.
            seen_dois.add(doi_key)
            seen_titles.add(title_key)
            doi_idx[doi_key] = len(deduped)
            deduped.append(rec)
        else:
            # No DOI: skip if an accepted record (DOI or no-DOI) shares this title.
            if title_key in seen_titles:
                stats["title_duplicates"] += 1
                continue
            idx = len(deduped)
            nondoi_title_idx[title_key] = idx
            seen_titles.add(title_key)
            deduped.append(rec)

    return deduped, stats


def build_coverage_report(all_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build a coverage report showing records per sector and provider.

    Args:
        all_results: List of dicts with keys: sector, query, provider, record_count

    Returns:
        List of coverage rows with sector, provider, query, record_count
    """
    coverage: List[Dict[str, Any]] = []
    for item in all_results:
        coverage.append(
            {
                "sector": item["sector"],
                "provider": item["provider"],
                "query": item["query"],
                "record_count": item["record_count"],
            }
        )
    return coverage


def _to_stage1_compliant_dict(rec: LiteratureRecord) -> Dict[str, Any]:
    """
    Return a compliance-filtered dictionary for a single LiteratureRecord.

    Only the fields explicitly listed in docs/licensing_and_compliance.md
    ("What you are always allowed to store") are included.  Fields that may
    carry restricted content under institutional-provider licences are
    intentionally excluded here, even when they are present on the model:

    - ``citation_count`` is omitted: Web of Science and SciVal counts are
      restricted by institutional licence (docs/licensing_and_compliance.md,
      Category 2 — Institutional providers, and Category 3 — SciVal).
    - ``abstract_available`` / ``abstract_stored`` are omitted from the
      serialised output: their boolean values are internal provenance flags
      only; exporting them would imply an abstract is accessible, which could
      create a misleading impression for third parties reusing this dataset.
      (docs/licensing_and_compliance.md — "What you are never allowed to
      store": Full abstract text.)

    Fields retained and their docs/licensing_and_compliance.md basis:
    - title, authors, year, doi    → "Bibliographic fact; not copyright-protected"
    - language                     → "Bibliographic metadata field (when available)"
    - journal                       → "Bibliographic fact"
    - url                           → "Pointer, not content"
    - subject_terms                 → "Aggregated classification, not full text"
    - provider                      → "Source provider name — Internal metadata"
    - source_id, source_query,
      retrieval_timestamp           → "Internal metadata generated by this repository"
    - licence_note                  → "Internal metadata generated by this repository"
    """
    # Stage 1 — bibliographic-metadata-only fields
    # (docs/licensing_and_compliance.md: "What you are always allowed to store")
    return {
        "title": rec.title,
        "authors": rec.authors,
        "year": rec.year,
        "doi": rec.doi,
        "source_id": rec.source_id,
        "provider": rec.provider,
        "language": rec.language,
        "journal": rec.journal,
        "url": rec.url,
        "subject_terms": rec.subject_terms,
        "source_query": rec.source_query,
        "retrieval_timestamp": rec.retrieval_timestamp,
        "licence_note": rec.licence_note,
    }


# Stage 1 governance: CSV columns are the bibliographic-metadata-only subset
# permitted for all providers, including institutional ones.  Note that
# subject_terms is intentionally excluded from the CSV (it is a list, not a
# flat scalar) but is present in the JSON export via _to_stage1_compliant_dict.
# (docs/licensing_and_compliance.md — Category 1/2/3 constraints.)
STAGE1_CSV_FIELDS: List[str] = [
    "title",
    "authors",
    "year",
    "doi",
    "source_id",
    "provider",
    "language",
    "journal",
    "url",
    "source_query",
    "retrieval_timestamp",
    "licence_note",
]


def export_records_json(records: List[LiteratureRecord], output_path: Path) -> None:
    """Export records as JSON using Stage 1 compliance filtering.

    Uses ``_to_stage1_compliant_dict`` to ensure only bibliographic metadata
    fields permitted by docs/licensing_and_compliance.md are written to disk.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Stage 1 governance: serialize only permitted bibliographic fields.
    # Full-text, abstract content, and institution-restricted analytics are
    # never written here (docs/licensing_and_compliance.md — Category 1/2/3).
    data = [_to_stage1_compliant_dict(rec) for rec in records]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported {len(records)} records to {output_path}")


def export_records_csv(records: List[LiteratureRecord], output_path: Path) -> None:
    """Export records as CSV using Stage 1 compliance filtering.

    Column set is deliberately limited to the fields in ``STAGE1_CSV_FIELDS``
    which are safe to commit and redistribute under all provider licence
    categories (docs/licensing_and_compliance.md — "What you are always
    allowed to store").

    Excluded fields (citation_count, abstract_available, abstract_stored) are
    omitted here for the same reasons documented in
    ``_to_stage1_compliant_dict``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        # Write empty CSV with headers only
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=STAGE1_CSV_FIELDS)
            writer.writeheader()
        print(f"Exported 0 records to {output_path}")
        return

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STAGE1_CSV_FIELDS)
        writer.writeheader()
        for rec in records:
            compliant = _to_stage1_compliant_dict(rec)
            # subject_terms is excluded from CSV (list type, not a flat scalar);
            # it is available in the JSON export.
            writer.writerow({k: compliant[k] for k in STAGE1_CSV_FIELDS})
    print(f"Exported {len(records)} records to {output_path}")


def export_provenance_json(provenance: List[SourceEvidence], output_path: Path) -> None:
    """Export provenance as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [p.to_dict() for p in provenance]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported {len(provenance)} provenance entries to {output_path}")


def export_coverage_csv(coverage: List[Dict[str, Any]], output_path: Path) -> None:
    """Export coverage report as CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not coverage:
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["sector", "provider", "query", "record_count"]
            )
            writer.writeheader()
        print(f"Exported 0 coverage rows to {output_path}")
        return

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["sector", "provider", "query", "record_count"]
        )
        writer.writeheader()
        for row in coverage:
            writer.writerow(row)
    print(f"Exported {len(coverage)} coverage rows to {output_path}")


def export_raw_api_payloads(
    payload_triples: List[Dict[str, Any]],
    output_dir: Path,
) -> int:
    """Write raw API payloads to *output_dir*/raw_api_payloads/ for cold-cache archiving.

    Each payload is stored in a self-describing envelope so the file can be
    replayed without the original query context:

    .. code-block:: json

        {
            "provider": "crossref",
            "query": "offshore wind energy",
            "captured_at": "2026-07-03T12:00:00+00:00",
            "payload_sha256": "<sha256 of serialised payload key>",
            "payload": { ... }
        }

    The filename is ``<provider>_<sha256(query)[:8]>.json`` so different
    queries for the same provider produce distinct files.  If two calls
    produce identical (provider, query) pairs the later one overwrites the
    earlier — within a single run this indicates a duplicate query.

    Args:
        payload_triples: List of ``{"provider", "query", "raw_payload"}`` dicts
            collected during the provider search loop.
        output_dir: Base output directory (e.g. ``outputs/research_sources``).

    Returns:
        Number of payload files written.
    """
    from datetime import datetime, timezone

    if not payload_triples:
        return 0
    raw_dir = output_dir / "raw_api_payloads"
    raw_dir.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    written = 0
    for triple in payload_triples:
        provider = str(triple.get("provider", "unknown")).lower()
        query = str(triple.get("query", ""))
        raw_payload = triple.get("raw_payload")
        if raw_payload is None:
            continue
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]
        filename = f"{provider}_{query_hash}.json"
        serialised = json.dumps(raw_payload, ensure_ascii=False, sort_keys=True)
        payload_sha256 = hashlib.sha256(serialised.encode("utf-8")).hexdigest()
        envelope: Dict[str, Any] = {
            "provider": provider,
            "query": query,
            "captured_at": captured_at,
            "payload_sha256": payload_sha256,
            "payload": raw_payload,
        }
        dest = raw_dir / filename
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(envelope, fh, indent=2, ensure_ascii=False)
        written += 1
    print(f"Exported {written} raw API payload file(s) to {raw_dir}")
    return written


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Export live research records from configured providers"
    )
    parser.add_argument(
        "--providers",
        default="crossref",
        help="Comma-separated list of provider names (default: crossref)",
    )
    parser.add_argument(
        "--query-file",
        default="config/research_queries.yml",
        help="Path to YAML file with query groups",
    )
    parser.add_argument(
        "--max-results-per-query",
        type=int,
        default=50,
        help="Maximum results per query (default: 50)",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/research_sources",
        help="Output directory for exported files",
    )
    parser.add_argument(
        "--offline",
        default="false",
        help="Offline mode: skip network calls (default: false)",
    )
    parser.add_argument(
        "--provider-policy-file",
        default=str(DEFAULT_PROVIDER_POLICY_PATH),
        help="Path to provider precedence/class policy YAML.",
    )
    parser.add_argument(
        "--query-constraints-file",
        default="outputs/research_sources/query_protocol_constraints.json",
        help="Authoritative per-query acquisition constraints JSON.",
    )

    args = parser.parse_args()

    # Parse providers — normalize to lowercase and drop empty tokens so that
    # case variants like "Crossref" match the registry's canonical names and
    # an accidental empty string (e.g. --providers "") produces a clear error.
    provider_list = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    if not provider_list:
        print(
            "Error: --providers must not be empty. "
            "Specify one or more provider names (e.g. crossref).",
            file=sys.stderr,
        )
        return 1

    # Parse offline mode
    offline = args.offline.lower() in ("true", "1", "yes")

    # Load query file
    query_file_path = Path(args.query_file)
    if not query_file_path.exists():
        print(f"Error: Query file not found: {query_file_path}", file=sys.stderr)
        return 1

    try:
        with open(query_file_path, "r", encoding="utf-8") as f:
            query_config_raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        print(
            f"Error: Failed to parse '{query_file_path}'. Syntactically invalid YAML:\n{exc}",
            file=sys.stderr,
        )
        return 1

    if query_config_raw is None or not isinstance(query_config_raw, dict):
        print(
            f"Error: '{query_file_path}' is empty or not a valid YAML mapping.",
            file=sys.stderr,
        )
        return 1

    query_config: Dict[str, Any] = query_config_raw

    query_groups = query_config.get("query_groups")
    if not isinstance(query_groups, dict) or not query_groups:
        print(
            f"Error: No research queries found in query file: {query_file_path}",
            file=sys.stderr,
        )
        return 1

    validated_query_groups: Dict[str, Dict[str, Any]] = {}
    runnable_query_count = 0
    for group_name, sector_data in query_groups.items():
        if not isinstance(sector_data, dict):
            print(
                "Error: Query group "
                f"'{group_name}' must be a mapping with the shape "
                "{label?, queries: [str, ...]}",
                file=sys.stderr,
            )
            return 1

        label = sector_data.get("label")
        if label is not None and not isinstance(label, str):
            print(
                f"Error: Query group '{group_name}' has a non-string label",
                file=sys.stderr,
            )
            return 1

        queries = sector_data.get("queries")
        if not isinstance(queries, list):
            print(
                f"Error: Query group '{group_name}' must define "
                "'queries' as a non-empty list of strings",
                file=sys.stderr,
            )
            return 1

        normalized_queries = [
            query.strip()
            for query in queries
            if isinstance(query, str) and query.strip()
        ]
        if len(normalized_queries) != len(queries) or not normalized_queries:
            print(
                f"Error: Query group '{group_name}' must define "
                "'queries' as a non-empty list of non-empty strings",
                file=sys.stderr,
            )
            return 1

        validated_query_groups[group_name] = dict(sector_data)
        validated_query_groups[group_name]["queries"] = normalized_queries
        runnable_query_count += len(normalized_queries)

    if runnable_query_count == 0:
        print(
            f"Error: No runnable research queries found in query file: {query_file_path}",
            file=sys.stderr,
        )
        return 1

    query_groups = validated_query_groups
    query_config["query_groups"] = query_groups

    constraints_path = Path(args.query_constraints_file)
    if not constraints_path.is_file():
        print(
            f"Error: Query constraints file not found: {constraints_path}",
            file=sys.stderr,
        )
        return 1
    try:
        constraints_by_query = _load_query_constraints(constraints_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: Invalid query constraints: {exc}", file=sys.stderr)
        return 1

    projected_sector_by_query = {
        query.lower(): str(group_name)
        for group_name, sector_data in query_groups.items()
        for query in sector_data["queries"]
    }
    is_legacy_default = query_file_path.name == "research_queries.yml"
    protocol_projected_query = (
        query_file_path.name == PROTOCOL_PROJECTED_QUERY_FILE_NAME
    )
    should_fallback_to_ad_hoc_constraints = (
        not protocol_projected_query
        and (query_file_path != DEFAULT_QUERY_FILE_PATH or is_legacy_default)
        and constraints_path == DEFAULT_QUERY_CONSTRAINTS_PATH
        and "--query-constraints-file" not in sys.argv[1:]
    )
    if set(projected_sector_by_query) != set(constraints_by_query):
        if should_fallback_to_ad_hoc_constraints:
            constraints_by_query = _build_ad_hoc_constraints_from_query_groups(
                query_groups
            )
        else:
            missing_constraints = sorted(
                set(projected_sector_by_query) - set(constraints_by_query)
            )
            extra_constraints = sorted(
                set(constraints_by_query) - set(projected_sector_by_query)
            )
            print(
                "Error: authoritative protocol projection and constraints differ; "
                f"missing={missing_constraints}, extra={extra_constraints}",
                file=sys.stderr,
            )
            return 1
    sector_mismatches = sorted(
        query_text
        for query_text, sector_slug in projected_sector_by_query.items()
        if str(constraints_by_query[query_text].get("sector_slug", ""))
        != sector_slug
    )
    if sector_mismatches:
        print(
            "Error: projected sector/query bindings differ from constraints: "
            f"{sector_mismatches}",
            file=sys.stderr,
        )
        return 1

    # Initialize registry
    registry = SourceRegistry()
    provider_policy = load_provider_policy(Path(args.provider_policy_file))

    # --providers all => query every registered provider in registry order.
    if len(provider_list) == 1 and provider_list[0] == "all":
        provider_list = [cap.name for cap in registry.list_capabilities()]

    # Validate that every requested provider name is known to the registry.
    known_names: Set[str] = {cap.name for cap in registry.list_capabilities()}
    unknown = [p for p in provider_list if p not in known_names]
    if unknown:
        print(
            f"Error: Unknown provider(s): {unknown}. "
            f"Valid names are: {sorted(known_names)}",
            file=sys.stderr,
        )
        return 1

    # Derive the ordered list of provider names as the registry will return them.
    # registry.search() filters _providers by name membership in provider_list but
    # preserves the registry's internal order — NOT the order of provider_list itself.
    ordered_provider_names: List[str] = [
        cap.name for cap in registry.list_capabilities() if cap.name in provider_list
    ]

    # Storage for all results
    all_records: List[LiteratureRecord] = []
    all_provenance: List[SourceEvidence] = []
    all_coverage_items: List[Dict[str, Any]] = []
    sectors_by_identity_key: Dict[str, Set[str]] = defaultdict(set)
    # Raw API payloads for cold-cache archiving — stored before any normalisation.
    raw_api_payload_triples: List[Dict[str, Any]] = []
    query_execution_rows: List[Dict[str, Any]] = []
    query_provider_identity_keys: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    # Execute exactly the authoritative projected query universe.
    if offline:
        print("Offline mode enabled. Skipping all network calls.")
        for sector_key, sector_data in query_groups.items():
            for query in sector_data.get("queries", []):
                constraint = constraints_by_query[query.lower()]
                for provider_name in ordered_provider_names:
                    provider_key = normalize_provider_name(provider_name)
                    declared_sort = str(
                        constraint.get("sort_strategy", {}).get(provider_key, "")
                    ).strip()
                    requested_filters = ["time_window", "sampling_strategy"]
                    if declared_sort:
                        requested_filters.append("sort_strategy")
                    query_execution_rows.append(
                        {
                            "query_id": constraint["query_id"],
                            "sector_slug": sector_key,
                            "query_family": constraint.get("query_family", ""),
                            "query_text": query,
                            "provider": provider_name,
                            "provider_canonical": provider_key,
                            "execution_status": "offline_not_executed",
                            "returned_record_count": 0,
                            "normalized_record_count": 0,
                            "contributed_record_count": 0,
                            "from_year": constraint.get("time_window", {}).get(
                                "from_year", ""
                            ),
                            "to_year": constraint.get("time_window", {}).get(
                                "to_year", ""
                            ),
                            "declared_sort_strategy": constraint.get(
                                "sort_strategy", {}
                            ).get(provider_key, ""),
                            "declared_sampling_mode": constraint.get(
                                "sampling_strategy", {}
                            ).get("mode", ""),
                            "declared_pages": constraint.get(
                                "sampling_strategy", {}
                            ).get("pages", ""),
                            "declared_rows_per_page": constraint.get(
                                "sampling_strategy", {}
                            ).get("rows_per_page", ""),
                            "sampling_status": "offline_not_executed",
                            "time_window_status": "offline_not_executed",
                            "sort_status": "offline_not_executed",
                            "requested_constraint_filters": "|".join(
                                sorted(set(requested_filters))
                            ),
                            "applied_constraint_filters": "",
                            "unsupported_constraint_filters": "",
                            "unapplied_constraint_filters": "|".join(
                                sorted(set(requested_filters))
                            ),
                        }
                    )
    else:
        print(
            f"Fetching records for {len(query_groups)} sectors with providers: "
            f"{ordered_provider_names}"
        )
        for sector_key, sector_data in query_groups.items():
            sector_label = sector_data.get("label", sector_key)
            queries = sector_data.get("queries", [])
            print(f"\nSector: {sector_label} ({len(queries)} queries)")

            for query in queries:
                constraint = constraints_by_query[query.lower()]
                print(f"  Query: {query}")
                results = registry.search(
                    query,
                    max_results=args.max_results_per_query,
                    providers=provider_list,
                )

                for index, result in enumerate(results):
                    provider_name = (
                        ordered_provider_names[index]
                        if index < len(ordered_provider_names)
                        else (
                            result.records[0].provider
                            if result.records
                            else (
                                result.provenance[0].source_provider
                                if result.provenance
                                else "unknown"
                            )
                        )
                    )
                    accepted_records, constraint_audit = _apply_query_constraint(
                        result.records,
                        constraint,
                        provider_name,
                        args.max_results_per_query,
                    )
                    if result.errors:
                        print(f"    Errors: {result.errors}", file=sys.stderr)
                    if result.warnings:
                        print(f"    Warnings: {result.warnings}")

                    execution_row: Dict[str, Any] = {
                        "query_id": constraint["query_id"],
                        "sector_slug": sector_key,
                        "query_family": constraint.get("query_family", ""),
                        "query_text": query,
                        "provider": provider_name,
                        "provider_canonical": normalize_provider_name(provider_name),
                        "execution_status": (
                            "completed_with_errors"
                            if result.errors
                            else "completed"
                        ),
                        "returned_record_count": len(result.records),
                        "normalized_record_count": len(accepted_records),
                        "contributed_record_count": 0,
                        "errors": "|".join(str(error) for error in result.errors),
                        "warnings": "|".join(
                            str(warning) for warning in result.warnings
                        ),
                        **constraint_audit,
                    }
                    query_execution_rows.append(execution_row)
                    all_coverage_items.append(
                        {
                            "sector": sector_label,
                            "provider": provider_name,
                            "query": query,
                            "record_count": len(accepted_records),
                        }
                    )

                    for record in accepted_records:
                        query_provider_identity_keys[
                            (
                                constraint["query_id"],
                                normalize_provider_name(provider_name),
                            )
                        ].add(_identity_key_from_record(record))
                        sectors_by_identity_key[
                            _identity_key_from_record(record)
                        ].add(str(sector_label))
                    all_records.extend(accepted_records)
                    all_provenance.extend(result.provenance)

                    if result.raw_payload is not None:
                        raw_api_payload_triples.append(
                            {
                                "provider": provider_name,
                                "query": query,
                                "raw_payload": result.raw_payload,
                            }
                        )

                    print(
                        "    Accepted "
                        f"{len(accepted_records)}/{len(result.records)} records"
                    )

    # Loop 1: identity triangulation with explicit provider priority policy
    print(f"\nLoop 1 identity triangulation for {len(all_records)} records...")
    (
        deduped_records,
        _triangulated_identity,
        identity_audit,
        dedup_stats,
        support_by_identity,
    ) = triangulate_identity_loop(all_records, provider_policy)
    print(
        f"Triangulated: {len(deduped_records)} unique records "
        f"(removed {dedup_stats['doi_duplicates']} DOI duplicates, "
        f"{dedup_stats['title_duplicates']} title duplicates)"
    )

    deduped_identity_keys = {_identity_key_from_record(rec) for rec in deduped_records}
    for row in query_execution_rows:
        query_id = str(row.get("query_id", "")).strip()
        provider_key = normalize_provider_name(row.get("provider_canonical") or row.get("provider", ""))
        identity_keys = query_provider_identity_keys.get((query_id, provider_key), set())
        row["provider_canonical"] = provider_key
        row["contributed_record_count"] = len(identity_keys & deduped_identity_keys)
        if row.get("normalized_record_count", "") == "":
            row["normalized_record_count"] = row.get("accepted_record_count", 0)
        if row.get("returned_record_count", "") == "":
            row["returned_record_count"] = row.get("raw_record_count", 0)

    # Filter by provider for provider-specific exports
    crossref_records = [r for r in deduped_records if r.provider == "Crossref"]

    # Filter low-confidence records
    low_confidence_record_ids: Set[str] = {
        p.record_id for p in all_provenance if p.confidence_score < 0.8
    }
    low_confidence_records = [
        r for r in deduped_records if r.source_id in low_confidence_record_ids
    ]

    # Build coverage report
    coverage = build_coverage_report(all_coverage_items)
    provider_classes = provider_policy.get("classes", {})

    # Loop 2: thematic QMBD validation audit over triangulated winners
    classification_repo = LiveContextClassificationRepository()
    thematic_audit = build_thematic_loop_audit(
        deduped_records,
        all_provenance,
        support_by_identity,
        provider_classes,
        sectors_by_identity_key=sectors_by_identity_key,
        classification_repo=classification_repo,
    )

    # Raw/enrichment artifacts for explicit provenance workflows.
    primary_identity = set(
        provider_policy.get(
            "primary_identity_providers",
            _DEFAULT_PROVIDER_POLICY["primary_identity_providers"],
        )
    )
    enrichment_records = [
        _to_stage1_compliant_dict(rec)
        for rec in all_records
        if normalize_provider_name(rec.provider) not in primary_identity
    ]
    raw_records = [_to_stage1_compliant_dict(rec) for rec in all_records]
    triangulated_payload: List[Dict[str, Any]] = []
    confidence_by_record: Dict[str, float] = {}
    classification_repo = LiveContextClassificationRepository()
    sentence_classifications_by_record: Dict[str, List[Dict[str, Any]]] = {}
    axis_by_record: Dict[str, Tuple[str, str]] = {}
    for ev in all_provenance:
        confidence_by_record[ev.record_id] = max(
            confidence_by_record.get(ev.record_id, 0.0), float(ev.confidence_score)
        )
    for rec in deduped_records:
        sentence_classifications = classification_repo.classify_record_sentences(rec)
        sentence_classifications_by_record[rec.source_id] = sentence_classifications
        axis_by_record[rec.source_id] = (
            classification_repo.dominant_axis_from_classifications(
                sentence_classifications
            )
        )
    for rec in deduped_records:
        sentence_classifications = sentence_classifications_by_record.get(
            rec.source_id, []
        )
        axis_name, axis_code = axis_by_record.get(rec.source_id, ("Unknown", "unknown"))
        identity_key = _identity_key_from_record(rec)
        support = support_by_identity.get(
            identity_key, [normalize_provider_name(rec.provider)]
        )
        sectors = sorted(sectors_by_identity_key.get(identity_key, set()))
        overlap_status = "multi-source" if len(set(support)) > 1 else "single-source"
        row = _to_stage1_compliant_dict(rec)
        row["confidence_score"] = confidence_by_record.get(rec.source_id, 0.0)
        row["overlap_status"] = overlap_status
        row["supporting_providers"] = support
        row["sectors"] = sectors
        row["provider_class"] = provider_classes.get(
            normalize_provider_name(rec.provider), "unknown"
        )
        row["qmbd_axis"] = axis_name
        row["qmbd_axis_code"] = axis_code
        row["sentence_classifications"] = _sanitize_persisted_sentence_classifications(
            sentence_classifications
        )
        triangulated_payload.append(row)

    # Export outputs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nExporting to {output_dir}/...")

    export_records_json(deduped_records, output_dir / "live_records.json")
    export_records_csv(deduped_records, output_dir / "live_records.csv")
    with open(
        output_dir / "live_records_triangulated.json", "w", encoding="utf-8"
    ) as f:
        json.dump(triangulated_payload, f, indent=2, ensure_ascii=False)
    export_records_json(crossref_records, output_dir / "crossref_records.json")
    export_provenance_json(all_provenance, output_dir / "live_provenance.json")
    export_coverage_csv(coverage, output_dir / "live_source_coverage.csv")
    export_query_execution_log(
        query_execution_rows,
        output_dir / "query_execution_log.csv",
    )
    scopus_rows = [
        row for row in query_execution_rows
        if str(row.get("provider_canonical", "")).strip() == "scopus"
    ]
    with open(
        output_dir / "scopus_query_diagnostics.json", "w", encoding="utf-8"
    ) as f:
        json.dump(
            sorted(
                scopus_rows,
                key=lambda row: (str(row.get("query_id", "")), str(row.get("provider", ""))),
            ),
            f,
            indent=2,
            ensure_ascii=False,
        )
    export_records_json(
        low_confidence_records, output_dir / "low_confidence_live_records.json"
    )
    with open(output_dir / "raw_provider_records.json", "w", encoding="utf-8") as f:
        json.dump(raw_records, f, indent=2, ensure_ascii=False)
    with open(output_dir / "enrichment_records.json", "w", encoding="utf-8") as f:
        json.dump(enrichment_records, f, indent=2, ensure_ascii=False)
    with open(
        output_dir / "triangulation_identity_loop.json", "w", encoding="utf-8"
    ) as f:
        json.dump(identity_audit, f, indent=2, ensure_ascii=False)
    with open(
        output_dir / "triangulation_thematic_loop.json", "w", encoding="utf-8"
    ) as f:
        json.dump(thematic_audit, f, indent=2, ensure_ascii=False)

    # Cold-cache: persist raw provider API payloads before any normalisation.
    export_raw_api_payloads(raw_api_payload_triples, output_dir)

    print("\nExport complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
