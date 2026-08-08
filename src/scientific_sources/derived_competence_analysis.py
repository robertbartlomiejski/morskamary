"""Layer 4 and Layer 5 — Derived competence-demand database, statistical
indices, gap model, and EQF 4-7 credential translation.

This module consumes the Layer 2/3 bundle produced by
``src.scientific_sources.cumulative_scientific_database`` (see
``docs/LIVE_CUMULATIVE_SCIENTIFIC_DATABASE.md``) and adds the downstream
scientific-validity layer required by PR-190 Task C.

The module is deliberately additive: it does not modify or replace the
outputs of Layers 0-3. All computation is deterministic — no randomness,
no network, no external services.

Deterministic ``demand_strength_score`` formula (also documented in
``docs/STATISTICAL_REPORT_METHODOLOGY.md`` and the release manifest)::

    demand_strength_score =
        0.30 * normalized_unique_doi_count
      + 0.20 * provider_diversity_score
      + 0.20 * temporal_recency_score
      + 0.15 * query_diversity_score
      + 0.15 * semantic_confidence_mean

Reliability rule: records classified as ``duplicate_only`` are excluded
from statistical growth metrics. Growth indexes are recalculated only on
``new_record``, ``updated_metadata``, ``provider_enriched`` and
``semantic_enriched``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from src.scientific_sources.cumulative_scientific_database import (
    canonical_label_is_allowed,
)
from src.scientific_sources.schema_v2_identity import (
    make_canonical_competence_id as _make_canonical_competence_id,
    recompute_assignment_id_from_row as _recompute_assignment_id_from_row,
    recompute_candidate_id_from_row as _recompute_candidate_id_from_row,
    recompute_fragment_id_from_row as _recompute_fragment_id_from_row,
    recompute_provenance_id_from_row as _recompute_provenance_id_from_row,
    recompute_signal_id_from_row as _recompute_signal_id_from_row,
)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

LAYER4_SCHEMA_VERSION = "1.1.0"
LAYER5_SCHEMA_VERSION = "1.0.0"

# Layer-4 compatibility aggregates are deliberately not validation-backed
# canonical competences.  Accepted schema-v2 lineage is emitted as a separate
# view so that compatibility statistics stay distinct from reviewed construct
# validity.
LEGACY_DERIVED_DEMAND_VIEW_KIND = "legacy_category_aggregate_compatibility_view"
LEGACY_DERIVED_DEMAND_SCIENTIFIC_STATUS = (
    "legacy_not_validated_canonical_competence"
)
ACCEPTED_CANONICAL_LINEAGE_VIEW_KIND = "accepted_canonical_lineage_view"
VALIDATED_CANONICAL_DEMAND_SCIENTIFIC_STATUS = "validated_canonical_competence"
_LINEAGE_REVIEWER_IDENTIFIER_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}"
)
# Deterministic identity pattern: schema-v2 IDs use a typed-prefix + 64-char
# lowercase hex sha256 digest (e.g. "candidate:abc123...", "fragment:def456...").
# Empty strings, provider-prefixed labels, truncated tokens, or other formats
# indicate a corrupted or forged lineage chain.
# All hash builders and recomputation helpers are imported from
# src.scientific_sources.schema_v2_identity — the single authoritative source
# of the preimage contract.  These identifiers are *deterministically
# reconstructable* and *tamper-evident under the trusted validation boundary*.
_LINEAGE_HEX_ID_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]*:[0-9a-f]{64}$"
)
# _UNIT_SEP, hash builders, and recompute helpers are imported from
# src.scientific_sources.schema_v2_identity above.
_LINEAGE_UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d+)?)?(?:Z|\+00:00)$"
)

DERIVED_DEMANDS_CSV = "derived_competence_demands.csv"
DERIVED_DEMANDS_JSONL = "derived_competence_demands.jsonl"
SECTOR_AXIS_GAP_MODEL_CSV = "sector_axis_gap_model.csv"
CREDENTIAL_TRANSLATION_CSV = "credential_translation_eqf4_7.csv"
LEARNING_OUTCOMES_CSV = "learning_outcomes.csv"
VARIABLE_LABELS_CSV = "VARIABLE_LABELS.csv"
VALUE_LABELS_CSV = "VALUE_LABELS.csv"
LAYER4_MANIFEST = "layer4_manifest.json"
LAYER5_MANIFEST = "layer5_manifest.json"
LAYER45_CHECKSUMS_FILENAME = "_checksums_layer45.sha256"
CANONICAL_CHECKSUMS_FILENAME = "_checksums.sha256"
_CHECKSUM_LINE_RE = re.compile(r"^[0-9a-fA-F]{64}$")

LAYER4_STATS_DIR = "layer4_statistics"
QMBD_CROSS_TABLES_CSV = "qmbd_cross_tables.csv"
SECTOR_GAP_MATRICES_JSON = "sector_gap_matrices.json"
MULTIVARIATE_RESULTS_JSON = "multivariate_induction_results.json"
TAXONOMIC_CLUSTERS_CSV = "taxonomic_clusters.csv"

DERIVED_DEMAND_COLUMNS: Tuple[str, ...] = (
    "competence_demand_id",
    "competence_label",
    "competence_definition",
    "view_kind",
    "scientific_status",
    "canonical_competence_id",
    "validation_decision_ids",
    "source_candidate_ids",
    "assignment_ids",
    "sector",
    "axis_group",
    "axis_code",
    "eqf_relevance",
    "demand_strength_score",
    "evidence_record_count",
    "unique_doi_count",
    "record_occurrence_count",
    "provider_count",
    "providers_seen",
    "provider_diversity_score",
    "query_count",
    "query_families_seen",
    "query_diversity_score",
    "temporal_recency_score",
    "cross_sector_recurrence_score",
    "semantic_confidence_mean",
    "first_seen_run_id",
    "latest_seen_run_id",
    "first_seen_at_utc",
    "latest_seen_at_utc",
    "status",
    "manual_review_status",
    "validity_warning",
    "evidence_ids",
    "signal_types",
)

GAP_MODEL_COLUMNS: Tuple[str, ...] = (
    "sector",
    "axis_group",
    "static_baseline_available_count",
    "live_literature_demand_count",
    "validated_demand_count",
    "covered_by_existing_credentials_count",
    "uncovered_demand_count",
    "gap_ratio",
    "evidence_strength_score",
    "validity_warning",
)

CREDENTIAL_TRANSLATION_COLUMNS: Tuple[str, ...] = (
    "credential_id",
    "credential_title",
    "sector",
    "axis_group",
    "eqf_level",
    "ects",
    "competence_demand_ids",
    "learning_outcomes",
    "assessment_method",
    "evidence_record_count",
    "unique_doi_count",
    "confidence_score",
    "coverage_status",
    "validity_warning",
)

LEARNING_OUTCOME_COLUMNS: Tuple[str, ...] = (
    "outcome_id",
    "credential_id",
    "sector",
    "axis_group",
    "eqf_level",
    "outcome_statement",
    "evidence_id",
    "competence_demand_id",
    "hypothesis_ids",
    "signal_type",
    "confidence_score",
    "validity_warning",
)

ALLOWED_DEMAND_STATUS: Tuple[str, ...] = (
    "high_demand",
    "medium_demand",
    "low_demand",
    "review_required",
    "duplicate_artifact",
    "provider_bias_warning",
)

# Duplicate-only records are excluded from growth metrics (reliability rule).
GROWTH_ELIGIBLE_STATUSES: Tuple[str, ...] = (
    "new_record",
    "updated_metadata",
    "provider_enriched",
    "semantic_enriched",
)

# Deterministic taxonomic induction categories → QMBD axes.
TAXONOMIC_CATEGORIES: Tuple[Tuple[str, str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    # (category_label, axis_group, axis_codes, keyword phrases)
    ("Blue justice", "OCEANIC", ("O",),
     ("blue justice", "equity", "indigenous", "coastal community", "just transition")),
    ("Seafaring culture", "MARITIME", ("T",),
     ("seafarer", "seafaring", "crew", "shipboard", "port worker", "maritime labor")),
    ("Hydrosocial governance", "HYDRONIZATION", ("H",),
     ("hydrosocial", "water governance", "watershed", "hydrology", "hydronization",
      "water body")),
    ("Port-city interface", "MARITIME", ("T",),
     ("port-city", "port city", "waterfront", "harbour", "harbor", "port authority",
      "urban maritime")),
    ("Marine technical operations", "MARINE", ("M",),
     ("vessel operation", "marine engineering", "shipbuilding", "propulsion",
      "offshore installation", "underwater")),
    ("Blue digitalization", "MARITIME", ("T",),
     ("digital twin", "iot", "sensor", "smart port", "data platform",
      "digital ocean", "digitalization")),
    ("Climate adaptation", "OCEANIC", ("O",),
     ("climate adaptation", "climate resilience", "sea level rise", "ocean warming",
      "acidification", "extreme weather")),
    ("Safety and risk", "MARITIME", ("T",),
     ("safety", "risk assessment", "hazard", "occupational", "emergency response",
      "compliance")),
    ("Education and training", "MARITIME", ("T",),
     ("education", "training", "curriculum", "learning outcome", "micro-credential",
      "vocational", "eqf")),
    ("Research and innovation", "OCEANIC", ("O",),
     ("research", "innovation", "r&d", "living lab", "pilot study", "technology transfer")),
)

# EQF operational logic keywords.
EQF_KEYWORD_MAP: Tuple[Tuple[int, Tuple[str, ...]], ...] = (
    (4, ("operational", "technical task", "safety procedure", "compliance", "hands-on",
         "field work", "monitoring")),
    (5, ("technician", "coordinator", "data handling", "applied", "supervision",
         "installation", "maintenance")),
    (6, ("bachelor", "analytical", "planning", "sectoral", "problem solving",
         "diagnostic", "assessment")),
    (7, ("master", "governance", "research", "systems design", "policy",
         "transdisciplinary", "strategy", "leadership")),
)


class DerivedAnalysisError(RuntimeError):
    """Raised when Layer 4/5 build cannot proceed."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DerivedCompetenceDemand:
    competence_demand_id: str
    competence_label: str
    competence_definition: str
    view_kind: str
    scientific_status: str
    sector: str
    axis_group: str
    axis_code: str
    eqf_relevance: str
    demand_strength_score: float
    evidence_record_count: int
    unique_doi_count: int
    record_occurrence_count: int
    provider_count: int
    providers_seen: str
    provider_diversity_score: float
    query_count: int
    query_families_seen: str
    query_diversity_score: float
    temporal_recency_score: float
    cross_sector_recurrence_score: float
    semantic_confidence_mean: float
    first_seen_run_id: str
    latest_seen_run_id: str
    first_seen_at_utc: str
    latest_seen_at_utc: str
    status: str
    manual_review_status: str
    validity_warning: str
    evidence_ids: str = ""
    signal_types: str = ""
    canonical_competence_id: str = ""
    validation_decision_ids: str = ""
    source_candidate_ids: str = ""
    assignment_ids: str = ""


@dataclass
class SectorAxisGapRow:
    sector: str
    axis_group: str
    static_baseline_available_count: int
    live_literature_demand_count: int
    validated_demand_count: int
    covered_by_existing_credentials_count: int
    uncovered_demand_count: int
    gap_ratio: float
    evidence_strength_score: float
    validity_warning: str


@dataclass
class CredentialTranslation:
    credential_id: str
    credential_title: str
    sector: str
    axis_group: str
    eqf_level: int
    ects: float
    competence_demand_ids: str
    learning_outcomes: str
    assessment_method: str
    evidence_record_count: int
    unique_doi_count: int
    confidence_score: float
    coverage_status: str
    validity_warning: str


@dataclass
class LearningOutcome:
    outcome_id: str
    credential_id: str
    sector: str
    axis_group: str
    eqf_level: int
    outcome_statement: str
    evidence_id: str
    competence_demand_id: str
    hypothesis_ids: str
    signal_type: str
    confidence_score: float
    validity_warning: str


@dataclass
class Layer4Result:
    output_dir: Path
    stats_dir: Path
    derived_demands: List[DerivedCompetenceDemand]
    qmbd_cross_tables: Dict[str, Any]
    sector_gap_matrices: Dict[str, Any]
    multivariate_results: Dict[str, Any]
    taxonomic_clusters: List[Dict[str, Any]]
    indices: Dict[str, float]
    files: List[Path] = field(default_factory=list)


@dataclass
class Layer5Result:
    output_dir: Path
    gap_rows: List[SectorAxisGapRow]
    credentials: List[CredentialTranslation]
    learning_outcomes: List[LearningOutcome]
    hypothesis_results: Dict[str, Any]
    files: List[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Readiness audit (Layers 0-3)
# ---------------------------------------------------------------------------

# Minimum required columns for each CSV checked by the readiness validator.
_READINESS_CSV_REQUIRED_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "evidence_records.csv": (
        "evidence_id", "canonical_doi", "canonical_title",
        "record_novelty_status",
    ),
    "competence_demand_signals.csv": (
        "signal_id", "evidence_id", "run_id", "sector",
        "axis_group", "signal_type",
    ),
}

LAYER0_EXPECTED = ("config/live_query_protocol.yml",)
LAYER1_EXPECTED = ("live_runs/",)  # per-run subdirs
LAYER2_EXPECTED = (
    "cumulative_database/evidence_records.csv",
    "cumulative_database/evidence_records.jsonl",
)
LAYER3_EXPECTED = (
    "cumulative_database/competence_demand_signals.csv",
    "cumulative_database/competence_demand_signals.jsonl",
)


def build_layer_readiness_report(
    *,
    repository_root: Union[str, Path],
    outputs_root: Union[str, Path],
    output_path: Union[str, Path],
) -> Dict[str, Any]:
    """Produce a machine-readable readiness report for Layers 0-3.

    Returns the report dict and writes it deterministically to
    ``output_path`` as JSON.
    """
    repo = Path(repository_root)
    outs = Path(outputs_root)
    layers: List[Dict[str, Any]] = []

    def _check(name: str, expected: Sequence[str], root: Path) -> Dict[str, Any]:
        present: List[str] = []
        missing: List[str] = []
        validation_errors: List[str] = []
        for rel in expected:
            candidate = root / rel
            # Directory pattern with trailing slash: presence via any child
            if rel.endswith("/"):
                if candidate.exists() and any(candidate.iterdir()):
                    present.append(rel)
                else:
                    missing.append(rel)
            elif candidate.exists():
                present.append(rel)
                # Content validation for JSON, CSV, and checksum files.
                if candidate.is_dir():
                    validation_errors.append(f"{rel}:is_directory_not_file")
                elif rel.endswith(".json"):
                    try:
                        json.loads(candidate.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        validation_errors.append(f"{rel}:malformed_json:{exc}")
                elif rel.endswith(".sha256"):
                    try:
                        _HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
                        text = candidate.read_text(encoding="utf-8")
                        seen_refs: set[str] = set()
                        for line in text.strip().splitlines():
                            parts = line.split("  ", 1)
                            if len(parts) != 2 or not _HEX64.match(parts[0]):
                                validation_errors.append(
                                    f"{rel}:malformed_checksum_line"
                                )
                                break
                            declared_digest, ref_path = parts
                            if ref_path in seen_refs:
                                validation_errors.append(
                                    f"{rel}:duplicate_entry:{ref_path}"
                                )
                                break
                            seen_refs.add(ref_path)
                            ref_file = root / ref_path
                            if not ref_file.is_file():
                                validation_errors.append(
                                    f"{rel}:ref_missing:{ref_path}"
                                )
                                continue
                            actual = hashlib.sha256(
                                ref_file.read_bytes()
                            ).hexdigest()
                            if actual != declared_digest.lower():
                                validation_errors.append(
                                    f"{rel}:checksum_mismatch:{ref_path}"
                                )
                    except OSError as exc:
                        validation_errors.append(f"{rel}:unreadable:{exc}")
                elif rel.endswith(".csv"):
                    try:
                        text = candidate.read_text(encoding="utf-8")
                        reader = csv.reader(text.splitlines())
                        header = next(reader, None)
                        if not header:
                            validation_errors.append(f"{rel}:empty_csv")
                        else:
                            basename = rel.rsplit("/", 1)[-1]
                            req = _READINESS_CSV_REQUIRED_COLUMNS.get(
                                basename
                            )
                            if req is not None:
                                header_set = set(header)
                                missing_cols = sorted(
                                    c for c in req if c not in header_set
                                )
                                if missing_cols:
                                    validation_errors.append(
                                        f"{rel}:missing_columns:"
                                        + ",".join(missing_cols)
                                    )
                    except (OSError, csv.Error) as exc:
                        validation_errors.append(f"{rel}:malformed_csv:{exc}")
            else:
                missing.append(rel)
        schema_valid = not missing and not validation_errors
        return {
            "layer_name": name,
            "expected_files": list(expected),
            "files_present": sorted(present),
            "files_missing": sorted(missing),
            "validation_errors": sorted(validation_errors),
            "schema_valid": schema_valid,
            "usable_for_layer4": schema_valid,
            "action_taken": (
                "consumed_unchanged" if schema_valid else "compatible_adapter"
            ),
        }

    layers.append(_check("Layer 0", LAYER0_EXPECTED, repo))
    layers.append(_check("Layer 1", LAYER1_EXPECTED, outs))
    layers.append(_check("Layer 2", LAYER2_EXPECTED, outs))
    layers.append(_check("Layer 3", LAYER3_EXPECTED, outs))

    report = {
        "schema_version": "1.0.0",
        "generated_at_utc": _utc_now_iso(),
        "layers": layers,
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    _write_json(Path(output_path), report)
    return report


# ---------------------------------------------------------------------------
# Layer 4
# ---------------------------------------------------------------------------

def build_layer4(
    *,
    evidence_records: Sequence[Mapping[str, Any]],
    competence_signals: Sequence[Mapping[str, Any]],
    evidence_fragments: Optional[Sequence[Mapping[str, Any]]] = None,
    canonical_competences: Optional[Sequence[Mapping[str, Any]]] = None,
    sector_competence_assignments: Optional[Sequence[Mapping[str, Any]]] = None,
    validation_decisions: Optional[Sequence[Mapping[str, Any]]] = None,
    competence_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    semantic_signals: Optional[Sequence[Mapping[str, Any]]] = None,
    output_dir: Union[str, Path],
    current_run_id: str = "",
    stats_dir: Optional[Union[str, Path]] = None,
    analysis_timestamp_utc: Optional[str] = None,
    classifier_version: str = "",
) -> Layer4Result:
    """Build Layer 4 with an explicit reproducible analysis timestamp."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stats_path = Path(stats_dir) if stats_dir is not None else out.parent / LAYER4_STATS_DIR
    stats_path.mkdir(parents=True, exist_ok=True)

    evidence_by_id: Dict[str, Mapping[str, Any]] = {
        str(r.get("evidence_id", "")): r for r in evidence_records
    }
    growth_evidence = [
        r for r in evidence_records
        if str(r.get("record_novelty_status", "")) in GROWTH_ELIGIBLE_STATUSES
    ]

    # Build a set of growth-eligible evidence IDs — only these evidence
    # records should feed demand aggregation and hypothesis calculations.
    growth_eligible_ids: set[str] = {
        str(r.get("evidence_id", ""))
        for r in evidence_records
        if str(r.get("record_novelty_status", "")) in GROWTH_ELIGIBLE_STATUSES
    }

    # Group signals by (competence_label, sector, axis_group), skipping
    # signals whose evidence is not growth-eligible.
    groups: Dict[Tuple[str, str, str], List[Mapping[str, Any]]] = {}
    for sig in competence_signals:
        eid = str(sig.get("evidence_id", ""))
        if eid not in growth_eligible_ids:
            continue
        label = str(sig.get("competence_label", "")).strip()
        sector = str(sig.get("sector", "")).strip() or "_unassigned"
        axis = str(sig.get("axis_group", "")).strip() or "UNASSIGNED"
        if not label:
            continue
        groups.setdefault((label, sector, axis), []).append(sig)

    demands: List[DerivedCompetenceDemand] = []
    all_providers: set[str] = {
        provider
        for evidence in growth_evidence
        for provider in _split_list(evidence.get("providers_seen", ""))
    }
    all_families: set[str] = {
        family
        for signals in groups.values()
        for signal in signals
        for family in [str(signal.get("query_family", "")).strip()]
        if family
    }

    for (label, sector, axis), signals in sorted(groups.items()):
        ev_ids = sorted({str(s.get("evidence_id", "")) for s in signals if s.get("evidence_id")})
        evs = [evidence_by_id.get(eid, {}) for eid in ev_ids]
        # Aggregate only growth-eligible evidence in per-demand metrics.
        evs = [
            e for e in evs
            if e and str(e.get("record_novelty_status", "")) in GROWTH_ELIGIBLE_STATUSES
        ]
        dois = sorted({str(e.get("canonical_doi", "")).strip() for e in evs if e.get("canonical_doi")})
        providers = sorted({
            p for e in evs for p in _split_list(e.get("providers_seen", ""))
        })
        families = sorted({
            f for e in evs for f in _split_list(e.get("query_families_seen", ""))
        })
        confidences = [_safe_float(s.get("confidence_score", 0.0)) for s in signals]
        conf_mean = sum(confidences) / max(1, len(confidences))
        first_run = min((str(e.get("first_seen_run_id", "")) for e in evs), default="")
        latest_run = max((str(e.get("latest_seen_run_id", "")) for e in evs), default="")
        first_at = min((str(e.get("first_seen_at_utc", "")) for e in evs if e.get("first_seen_at_utc")), default="")
        latest_at = max((str(e.get("latest_seen_at_utc", "")) for e in evs if e.get("latest_seen_at_utc")), default="")

        provider_div = _diversity(len(providers), len(all_providers) or 1)
        query_div = _diversity(len(families), len(all_families) or 1)
        recency = _recency_score(latest_at, analysis_timestamp_utc)
        norm_doi = min(1.0, len(dois) / 10.0)
        # cross-sector recurrence: same label appears in how many distinct sectors
        sector_set = {k[1] for k in groups.keys() if k[0] == label}
        cross_sector = min(1.0, len(sector_set) / 12.0)

        # === MANDATED FORMULA (see docs/STATISTICAL_REPORT_METHODOLOGY.md) ===
        # demand_strength_score =
        #   0.30 * normalized_unique_doi_count
        # + 0.20 * provider_diversity_score
        # + 0.20 * temporal_recency_score
        # + 0.15 * query_diversity_score
        # + 0.15 * semantic_confidence_mean
        score = round(
            0.30 * norm_doi
            + 0.20 * provider_div
            + 0.20 * recency
            + 0.15 * query_div
            + 0.15 * conf_mean,
            6,
        )

        status = _classify_demand_status(
            score=score,
            evidence_count=len(evs),
            provider_count=len(providers),
            confidences=confidences,
        )
        signal_review_required = any(
            str(signal.get("manual_review_status", "")).strip() == "review_required"
            for signal in signals
        )
        if signal_review_required:
            status = "review_required"
        review = "review_required" if status == "review_required" else "auto_accepted"
        warnings = sorted({
            w for s in signals for w in _split_list(s.get("validity_warning", ""))
        })
        if signal_review_required and "propagated_review_required" not in warnings:
            warnings.append("propagated_review_required")
        if any(e.get("validity_warning") == "metadata_only_limitation" for e in evs):
            if "metadata_only_limitation" not in warnings:
                warnings.append("metadata_only_limitation")

        eqf = _infer_eqf_relevance(label, signals)
        cid = _make_id("cd", sector, axis, label)
        demands.append(DerivedCompetenceDemand(
            competence_demand_id=cid,
            competence_label=label,
            competence_definition=_first_nonempty(
                (str(s.get("competence_description", "")) for s in signals),
                default=label,
            ),
            view_kind=LEGACY_DERIVED_DEMAND_VIEW_KIND,
            scientific_status=LEGACY_DERIVED_DEMAND_SCIENTIFIC_STATUS,
            sector=sector,
            axis_group=axis,
            axis_code=_axis_group_to_code(axis),
            eqf_relevance=eqf,
            demand_strength_score=score,
            evidence_record_count=len(evs),
            unique_doi_count=len(dois),
            record_occurrence_count=sum(int(e.get("record_recurrence_count", 1) or 1) for e in evs),
            provider_count=len(providers),
            providers_seen="|".join(providers),
            provider_diversity_score=round(provider_div, 6),
            query_count=len({str(s.get("query_id", "")) for s in signals if s.get("query_id")}),
            query_families_seen="|".join(families),
            query_diversity_score=round(query_div, 6),
            temporal_recency_score=round(recency, 6),
            cross_sector_recurrence_score=round(cross_sector, 6),
            semantic_confidence_mean=round(conf_mean, 6),
            first_seen_run_id=first_run,
            latest_seen_run_id=latest_run,
            first_seen_at_utc=first_at,
            latest_seen_at_utc=latest_at,
            status=status,
            manual_review_status=review,
            validity_warning="|".join(warnings),
            evidence_ids="|".join(
                sorted(
                    str(e.get("evidence_id", ""))
                    for e in evs
                    if e.get("evidence_id")
                )
            ),
            signal_types="|".join(
                sorted(
                    {
                        str(signal.get("signal_type", "")).strip()
                        for signal in signals
                        if str(signal.get("signal_type", "")).strip()
                    }
                )
            ),
        ))

    demands.extend(
        _build_accepted_canonical_lineage_demands(
            evidence_records=evidence_records,
            evidence_fragments=evidence_fragments,
            canonical_competences=canonical_competences,
            sector_competence_assignments=sector_competence_assignments,
            validation_decisions=validation_decisions,
            competence_candidates=competence_candidates,
            semantic_signals=semantic_signals,
            analysis_timestamp_utc=analysis_timestamp_utc,
        )
    )

    demands.sort(key=lambda d: (d.sector, d.axis_group, d.competence_label))

    # Compatibility aggregates remain the empirical population for Layer-4
    # descriptive statistics.  Canonical lineage rows are a distinct reviewed
    # construct-validity view and must not double-count those measures.
    legacy_demands = _legacy_derived_demands(demands)

    # QMBD cross-tables (frequency of legacy demand rows by sector × axis).
    qmbd_cross = _build_qmbd_cross_tables(legacy_demands)
    sector_gap = _build_sector_gap_matrices(legacy_demands, growth_evidence)
    multivariate = _build_multivariate_induction(legacy_demands, growth_evidence)
    taxonomy_signals = [
        signal
        for signal in competence_signals
        if str(signal.get("evidence_id", "")) in growth_eligible_ids
    ]
    taxonomy = _induce_taxonomic_clusters(taxonomy_signals)
    indices = _compute_global_indices(legacy_demands, evidence_records)

    files: List[Path] = []
    files.append(_write_derived_demands_csv(out / DERIVED_DEMANDS_CSV, demands))
    files.append(_write_derived_demands_jsonl(out / DERIVED_DEMANDS_JSONL, demands))
    files.append(_write_csv_rows(
        stats_path / QMBD_CROSS_TABLES_CSV,
        header=("sector", "axis_group", "demand_row_count", "mean_score"),
        rows=[(k[0], k[1], v["count"], round(v["mean_score"], 6))
              for k, v in sorted(qmbd_cross.items())],
    ))
    files.append(_write_json(stats_path / SECTOR_GAP_MATRICES_JSON, sector_gap))
    files.append(_write_json(stats_path / MULTIVARIATE_RESULTS_JSON, multivariate))
    files.append(_write_csv_rows(
        stats_path / TAXONOMIC_CLUSTERS_CSV,
        header=(
            "category_label",
            "primary_axis",
            "primary_axis_code",
            "secondary_axes",
            "secondary_axis_codes",
            "axis_bridge_score",
            "matched_hypothesis_ids",
            "matched_signal_count",
            "matched_evidence_count",
        ),
        rows=[
            (
                t["category_label"],
                t["primary_axis"],
                t["primary_axis_code"],
                t["secondary_axes"],
                t["secondary_axis_codes"],
                t["axis_bridge_score"],
                t["matched_hypothesis_ids"],
                t["matched_signal_count"],
                t["matched_evidence_count"],
            )
            for t in taxonomy
        ],
    ))
    manifest = {
        "schema_version": LAYER4_SCHEMA_VERSION,
        "classifier_version": classifier_version,
        "built_at_utc": analysis_timestamp_utc or _utc_now_iso(),
        "analysis_timestamp_utc": analysis_timestamp_utc or "",
        "current_run_id": current_run_id,
        "demand_strength_formula": (
            "0.30*normalized_unique_doi_count + 0.20*provider_diversity_score "
            "+ 0.20*temporal_recency_score + 0.15*query_diversity_score "
            "+ 0.15*semantic_confidence_mean"
        ),
        "legacy_category_aggregate_view_count": len(legacy_demands),
        "accepted_canonical_lineage_view_count": len(demands) - len(legacy_demands),
        "derived_demand_count": len(demands),
        # Retain the legacy singular marker for existing manifest readers.  The
        # mapping below is the extensible view inventory introduced in 1.1.0.
        "derived_demand_view_kind": LEGACY_DERIVED_DEMAND_VIEW_KIND,
        "derived_demand_view_kinds": {
            LEGACY_DERIVED_DEMAND_VIEW_KIND: len(legacy_demands),
            ACCEPTED_CANONICAL_LINEAGE_VIEW_KIND: len(demands) - len(legacy_demands),
        },
        "indices": indices,
        "files": sorted(str(f.relative_to(out.parent)) for f in files),
    }
    files.append(_write_json(out / LAYER4_MANIFEST, manifest))

    return Layer4Result(
        output_dir=out,
        stats_dir=stats_path,
        derived_demands=demands,
        qmbd_cross_tables=_kv(qmbd_cross),
        sector_gap_matrices=sector_gap,
        multivariate_results=multivariate,
        taxonomic_clusters=taxonomy,
        indices=indices,
        files=files,
    )


# ---------------------------------------------------------------------------
# Layer 5
# ---------------------------------------------------------------------------

def build_layer5(
    *,
    derived_demands: Sequence[DerivedCompetenceDemand],
    evidence_records: Sequence[Mapping[str, Any]],
    static_baseline_count_by_sector: Optional[Mapping[str, int]] = None,
    existing_credential_coverage: Optional[Mapping[Tuple[str, str], int]] = None,
    validated_credential_supply: Optional[Mapping[str, Sequence[int]]] = None,
    hypothesis_fragments: Optional[Sequence[Mapping[str, Any]]] = None,
    output_dir: Union[str, Path],
    current_run_id: str = "",
    built_at_utc: Optional[str] = None,
    classifier_version: str = "",
) -> Layer5Result:
    """Build the Layer 5 gap model, credential translation, and outcomes.

    Legacy Layer-4 category aggregates remain visible as literature demand, but
    they do not enter validation-backed coverage or gap measures. Credential
    translation keeps sector-axis rows in one analytical view at a time
    (legacy compatibility preferred; accepted canonical fallback).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    baseline_map = dict(static_baseline_count_by_sector or {})
    coverage_map = dict(existing_credential_coverage or {})

    # Aggregate by sector × axis_group
    buckets: Dict[Tuple[str, str], List[DerivedCompetenceDemand]] = {}
    for d in derived_demands:
        buckets.setdefault((d.sector, d.axis_group), []).append(d)

    gap_rows: List[SectorAxisGapRow] = []
    gap_cells = set(buckets) | set(coverage_map)
    gap_cells.update(
        (sector, axis)
        for sector in baseline_map
        for axis in ("MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION")
    )
    for sector, axis in sorted(gap_cells):
        demands = buckets.get((sector, axis), [])
        legacy_demands = _legacy_derived_demands(demands)
        validated_demands = [
            demand
            for demand in demands
            if _accepted_canonical_lineage_required(demand)
            and demand.status not in ("review_required", "duplicate_artifact")
        ]
        # Legacy category aggregates are the literature-demand counter.  The
        # canonical projection is deliberately retained only for the separate
        # validation-backed count below.
        live_demand = len(legacy_demands)
        validated = len(validated_demands)
        # The coverage map counts validated demands, not independent supply
        # items.  Do not let it produce coverage for a cell without validated
        # canonical demand lineage.
        covered = min(int(coverage_map.get((sector, axis), 0)), validated)
        # When existing_credential_coverage is absent (production CLI default),
        # fall back to validated_credential_supply to count canonical demands
        # that have at least one validated EQF level.  This prevents canonical
        # demands from always showing covered=0 when the supply map is provided.
        if coverage_map.get((sector, axis)) is None and validated_credential_supply is not None:
            supply_covered = sum(
                1
                for demand in validated_demands
                if validated_credential_supply.get(demand.competence_demand_id)
            )
            covered = min(supply_covered, validated)
        baseline_val = int(baseline_map.get(sector, 0))
        uncovered = max(0, validated - covered)
        gap_ratio = round(uncovered / max(1, validated), 6)
        strength_demands = legacy_demands or validated_demands
        avg_conf = sum(
            demand.semantic_confidence_mean for demand in strength_demands
        ) / max(1, len(strength_demands))
        warns: List[str] = []
        if baseline_val == 0 and not demands:
            warns.append("empty_cell")
        if baseline_val > 0 and live_demand == 0:
            warns.append("static_baseline_only")
        if live_demand > 0 and all(
            demand.status == "review_required" for demand in legacy_demands
        ):
            warns.append("all_review_required")
        if live_demand > 0 and validated == 0:
            warns.append("no_validated_canonical_demand")
        gap_rows.append(SectorAxisGapRow(
            sector=sector,
            axis_group=axis,
            static_baseline_available_count=baseline_val,
            live_literature_demand_count=live_demand,
            validated_demand_count=validated,
            covered_by_existing_credentials_count=covered,
            uncovered_demand_count=uncovered,
            gap_ratio=gap_ratio,
            evidence_strength_score=round(avg_conf, 6),
            validity_warning="|".join(sorted(warns)),
        ))

    # Credential translation: one credential per (sector, axis, eqf_level) with demand
    credentials: List[CredentialTranslation] = []
    outcomes: List[LearningOutcome] = []
    for (sector, axis), demands in sorted(buckets.items()):
        translation_demands = _credential_translation_demands(demands)
        by_eqf: Dict[int, List[DerivedCompetenceDemand]] = {}
        for d in translation_demands:
            for lvl in _parse_eqf_levels(d.eqf_relevance):
                by_eqf.setdefault(lvl, []).append(d)
        for lvl, ds in sorted(by_eqf.items()):
            cid = _make_id("cred", sector, axis, f"eqf{lvl}")
            title = f"{sector} — {axis} competence pathway (EQF {lvl})"
            dois: set = set()
            confs: List[float] = []
            demand_ids: List[str] = []
            for d in ds:
                demand_ids.append(d.competence_demand_id)
                confs.append(d.semantic_confidence_mean)
                dois.update(_evidence_dois_for_demand(d, evidence_records))
            conf_avg = sum(confs) / max(1, len(confs))
            coverage = _coverage_status_for_credential(
                demands=ds,
                eqf_level=lvl,
                validated_credential_supply=validated_credential_supply,
            )
            outcomes_list = [
                _learning_outcome_statement(d, sector, lvl)
                for d in ds
            ]
            warns = sorted({
                w for d in ds for w in _split_list(d.validity_warning)
            })
            credentials.append(CredentialTranslation(
                credential_id=cid,
                credential_title=title,
                sector=sector,
                axis_group=axis,
                eqf_level=lvl,
                ects=round(2.0 * len(ds), 2),
                competence_demand_ids="|".join(demand_ids),
                learning_outcomes="||".join(outcomes_list),
                assessment_method="portfolio_and_case_study",
                evidence_record_count=sum(d.evidence_record_count for d in ds),
                unique_doi_count=len(dois),
                confidence_score=round(conf_avg, 6),
                coverage_status=coverage,
                validity_warning="|".join(warns),
            ))
            # emit one learning outcome per demand
            for d in ds:
                oid = _make_id("lo", cid, d.competence_demand_id)
                outcomes.append(LearningOutcome(
                    outcome_id=oid,
                    credential_id=cid,
                    sector=sector,
                    axis_group=axis,
                    eqf_level=lvl,
                    outcome_statement=_learning_outcome_statement(d, sector, lvl),
                    evidence_id=_first_evidence_id_for_demand(d, evidence_records),
                    competence_demand_id=d.competence_demand_id,
                    hypothesis_ids="|".join(
                        _matched_hypothesis_ids(d.evidence_ids, hypothesis_fragments)
                    ),
                    signal_type=_dominant_signal_type_for_demand(d, []),
                    confidence_score=d.semantic_confidence_mean,
                    validity_warning=d.validity_warning,
                ))

    credentials.sort(key=lambda c: (c.sector, c.axis_group, c.eqf_level, c.credential_id))
    outcomes.sort(key=lambda o: (o.sector, o.axis_group, o.eqf_level, o.outcome_id))

    hyp = _test_hypotheses(
        derived_demands,
        gap_rows,
        credentials,
        hypothesis_fragments=hypothesis_fragments,
        validated_credential_supply=validated_credential_supply,
    )

    files: List[Path] = []
    files.append(_write_csv_dataclass(
        out / SECTOR_AXIS_GAP_MODEL_CSV, GAP_MODEL_COLUMNS, gap_rows,
    ))
    files.append(_write_csv_dataclass(
        out / CREDENTIAL_TRANSLATION_CSV, CREDENTIAL_TRANSLATION_COLUMNS, credentials,
    ))
    files.append(_write_csv_dataclass(
        out / LEARNING_OUTCOMES_CSV, LEARNING_OUTCOME_COLUMNS, outcomes,
    ))
    manifest = {
        "schema_version": LAYER5_SCHEMA_VERSION,
        "classifier_version": classifier_version,
        "built_at_utc": built_at_utc or _utc_now_iso(),
        "current_run_id": current_run_id,
        "validated_supply_map_provided": validated_credential_supply is not None,
        "gap_row_count": len(gap_rows),
        "credential_count": len(credentials),
        "learning_outcome_count": len(outcomes),
        "hypothesis_results": hyp,
    }
    files.append(_write_json(out / LAYER5_MANIFEST, manifest))

    return Layer5Result(
        output_dir=out,
        gap_rows=gap_rows,
        credentials=credentials,
        learning_outcomes=outcomes,
        hypothesis_results=hyp,
        files=files,
    )


# ---------------------------------------------------------------------------
# Variable / value label writers
# ---------------------------------------------------------------------------

def write_variable_and_value_labels(output_dir: Union[str, Path]) -> Tuple[Path, Path]:
    """Write VARIABLE_LABELS.csv and VALUE_LABELS.csv into ``output_dir``."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    var_labels = [
        ("demand_strength_score",
         "Deterministic weighted composite of DOI, provider diversity, recency, query diversity, and semantic confidence."),
        ("provider_diversity_score", "Share of distinct providers per record set relative to total providers."),
        ("query_diversity_score", "Share of distinct query families per record set relative to all families."),
        ("temporal_recency_score", "Exponential decay score of latest_seen_at_utc relative to today."),
        ("cross_sector_recurrence_score", "Share of the 12 sectors in which the same competence label recurs."),
        ("semantic_confidence_mean", "Mean confidence_score of all Layer 3 signals for the demand."),
        ("view_kind", "Layer-4 analytical view that produced the demand row."),
        ("scientific_status", "Construct-validity status of the Layer-4 demand row."),
        ("canonical_competence_id", "Stable identity of the accepted schema-v2 canonical competence."),
        ("validation_decision_ids", "Pipe-delimited accepted validation-decision identifiers backing the demand."),
        ("source_candidate_ids", "Pipe-delimited schema-v2 candidate identifiers backing the demand."),
        ("assignment_ids", "Pipe-delimited sector-axis assignment identifiers backing the demand."),
        ("gap_ratio", "uncovered_demand_count / max(1, validated_demand_count)."),
        ("eqf_level", "European Qualifications Framework level (4-7)."),
        ("ects", "European Credit Transfer and Accumulation System points."),
        # schema-v2 fields
        ("source_field", "Evidence fragment source field within the evidence record."),
        ("negation_status", "Negation detection result for the semantic signal text span."),
        ("speculation_status", "Speculation detection result for the semantic signal text span."),
        ("manual_review_status", "Manual review status assigned to a semantic signal."),
        ("candidate_status", "Lifecycle status of a competence candidate record."),
        ("review_status", "Review status assigned to a competence candidate."),
        ("decision_status", "Validation decision outcome for a competence candidate."),
        ("validation_status", "Promotion status of a canonical competence (accepted only)."),
        ("provenance_guard_status", "Result of the canonical-label provenance guard check."),
    ]
    schema_v2_categories = {
        "source_field": (
            "Retained evidence surface containing the exact fragment.",
            ("title", "subject_terms", "abstract", "full_text"),
        ),
        "axis_group": (
            "Canonical QMBD axis name; blank means unbound where permitted.",
            ("MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION", ""),
        ),
        "axis_code": ("Canonical QMBD display code; blank means unbound where permitted.", ("M", "T", "O", "H", "")),
        "negation_status": ("Negation assessment status for the semantic signal.", ("not_detected",)),
        "speculation_status": ("Speculation assessment status for the semantic signal.", ("not_detected",)),
        "manual_review_status": (
            "Manual-review state of the semantic signal.",
            ("auto_accepted", "review_required", "manually_reviewed", "rejected"),
        ),
        "candidate_status": ("Construct status of the competence candidate.", ("candidate",)),
        "review_status": (
            "Review state of the competence candidate.",
            ("auto_accepted", "review_required", "manually_reviewed", "rejected"),
        ),
        "validation_status": ("Validation state required for canonical competence promotion.", ("accepted",)),
        "provenance_guard_status": ("Canonical-label provenance guard outcome.", ("passed",)),
        "decision_status": (
            "Explicit reviewer decision for a competence candidate.",
            ("accepted", "rejected", "review_required", "superseded"),
        ),
    }
    var_labels.extend(
        (variable_name, definition)
        for variable_name, (definition, _) in schema_v2_categories.items()
        if variable_name not in {name for name, _ in var_labels}
    )
    val_labels = [
        ("status", "high_demand", "Score >= 0.70 with at least 2 evidence records."),
        ("status", "medium_demand", "Score >= 0.40 with at least 1 evidence record."),
        ("status", "low_demand", "Score < 0.40 with sufficient evidence."),
        ("status", "review_required", "Insufficient evidence, ambiguous provenance, or thin metadata."),
        ("status", "duplicate_artifact", "Row exists only because of Jaccard duplicate merging."),
        ("status", "provider_bias_warning", "All evidence sourced from a single provider."),
        (
            "view_kind",
            LEGACY_DERIVED_DEMAND_VIEW_KIND,
            "Legacy category-aggregate compatibility projection.",
        ),
        (
            "view_kind",
            ACCEPTED_CANONICAL_LINEAGE_VIEW_KIND,
            "Accepted schema-v2 canonical-lineage projection.",
        ),
        (
            "scientific_status",
            LEGACY_DERIVED_DEMAND_SCIENTIFIC_STATUS,
            "Legacy compatibility row; not a validated canonical competence.",
        ),
        (
            "scientific_status",
            VALIDATED_CANONICAL_DEMAND_SCIENTIFIC_STATUS,
            "Reviewed accepted canonical competence with retained lineage.",
        ),
        (
            "coverage_status",
            "candidate_translation",
            "Coverage proposed from generated candidate translations; not externally validated.",
        ),
        (
            "coverage_status",
            "review_required",
            "Credential row requires manual review due to low-confidence or review-required demand inputs.",
        ),
        (
            "coverage_status",
            "validated_covered",
            "All competence_demand_ids are externally validated as covered at this EQF level.",
        ),
        (
            "coverage_status",
            "validated_partial",
            "Some but not all competence_demand_ids are externally validated as covered at this EQF level.",
        ),
        (
            "coverage_status",
            "validated_uncovered",
            "No competence_demand_id is externally validated as covered at this EQF level.",
        ),
        ("axis_group", "MARINE", "Biophysical / ecological agency and constraints."),
        ("axis_group", "MARITIME", "Techno-economic, infrastructural, labour, institutional mediation."),
        ("axis_group", "OCEANIC", "Planetary coupling, multi-level governance, hydrosocial subjectivity."),
        ("axis_group", "HYDRONIZATION", "Hydrosocial governance and water-body coupling."),
        # schema-v2 value labels
        ("source_field", "title", "Title field"),
        ("source_field", "subject_terms", "Subject terms / keywords field"),
        ("source_field", "abstract", "Abstract field"),
        ("source_field", "full_text", "Full text field"),
        ("negation_status", "not_detected", "Negation not detected in text span"),
        ("negation_status", "not_assessed", "Negation assessment not run"),
        ("speculation_status", "not_detected", "Speculation not detected in text span"),
        ("speculation_status", "not_assessed", "Speculation assessment not run"),
        ("manual_review_status", "auto_accepted", "Automatically accepted by classifier"),
        ("manual_review_status", "review_required", "Manual review required"),
        ("manual_review_status", "manually_reviewed", "Manually reviewed and accepted"),
        ("manual_review_status", "rejected", "Rejected after review"),
        ("candidate_status", "candidate", "Proposed competence candidate awaiting validation"),
        ("review_status", "auto_accepted", "Automatically accepted by classifier"),
        ("review_status", "review_required", "Manual review required"),
        ("review_status", "manually_reviewed", "Manually reviewed and accepted"),
        ("review_status", "rejected", "Rejected after review"),
        ("decision_status", "accepted", "Candidate accepted and promoted to canonical competence"),
        ("decision_status", "rejected", "Candidate rejected; not promoted"),
        ("decision_status", "review_required", "Decision deferred pending further review"),
        ("decision_status", "superseded", "Decision superseded by a later validation decision"),
        ("validation_status", "accepted", "Canonical competence accepted via validated decision"),
        ("provenance_guard_status", "passed", "Canonical-label provenance guard passed"),
    ]
    existing_values = {(name, code) for name, code, _ in val_labels}
    for variable_name, (_, codes) in schema_v2_categories.items():
        for code in codes:
            key = (variable_name, code)
            if key in existing_values:
                continue
            label = "Unbound" if code == "" else code.replace("_", " ").title()
            val_labels.append((variable_name, code, label))
            existing_values.add(key)
    var_path = _write_csv_rows(
        out / VARIABLE_LABELS_CSV,
        header=("variable_name", "variable_label"),
        rows=[(v[0], v[1]) for v in var_labels],
    )
    val_path = _write_csv_rows(
        out / VALUE_LABELS_CSV,
        header=("variable_name", "value_code", "value_label"),
        rows=[(v[0], v[1], v[2]) for v in val_labels],
    )
    return var_path, val_path


def write_layer45_checksums(
    files: Sequence[Path],
    output_dir: Union[str, Path],
) -> Path:
    """Write ``_checksums_layer45.sha256`` for every Layer 4-5 emitted file.

    Uses deterministic 1 MB chunked reads so large files are hashed without
    loading them fully into memory.  The output is a sorted, newline-terminated
    file in the same ``<sha256>  <relpath>`` format used by the Layer 2-3
    ``_checksums.sha256``.

    Returns the path to the written checksum file.
    """
    out = Path(output_dir)
    checksum_path = out / LAYER45_CHECKSUMS_FILENAME
    entries = _build_checksum_entries(
        files,
        output_dir=out,
        excluded_paths=(checksum_path, out / CANONICAL_CHECKSUMS_FILENAME),
    )
    return _write_checksum_manifest(checksum_path, entries)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _build_checksum_entries(
    files: Sequence[Path],
    output_dir: Union[str, Path],
    *,
    excluded_paths: Sequence[Path] = (),
) -> Dict[str, str]:
    out = Path(output_dir)
    excluded = {Path(path).resolve(strict=False) for path in excluded_paths}
    entries: Dict[str, str] = {}
    missing_errors: List[str] = []
    validation_errors: List[str] = []
    seen_paths: Set[Path] = set()

    for raw_path in files:
        file_path = Path(raw_path)
        resolved_path = file_path.resolve(strict=False)
        if resolved_path in excluded or resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        if not file_path.exists():
            missing_errors.append(f"missing_emitted_artifact:{file_path}")
            continue
        if not file_path.is_file():
            missing_errors.append(f"non_file_emitted_artifact:{file_path}")
            continue
        relpath = os.path.relpath(file_path, start=out).replace("\\", "/")
        if relpath in {"", "."}:
            validation_errors.append(f"invalid_checksum_relpath:{file_path}")
            continue
        if relpath in entries:
            validation_errors.append(f"duplicate_checksum_entry:{relpath}")
            continue
        entries[relpath] = _sha256_file(file_path)

    if missing_errors:
        raise FileNotFoundError("; ".join(missing_errors))
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    return dict(sorted(entries.items()))


def _parse_checksum_manifest(path: Path) -> Dict[str, str]:
    entries: Dict[str, str] = {}
    if not path.is_file():
        return entries
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split("  ", 1)
        if len(parts) != 2 or not _CHECKSUM_LINE_RE.match(parts[0]):
            raise ValueError(f"malformed_checksum_line:{path.name}:L{line_no}")
        digest, relpath = parts[0].lower(), parts[1]
        if relpath in entries:
            raise ValueError(f"duplicate_checksum_entry:{path.name}:{relpath}")
        entries[relpath] = digest
    return entries


def _write_checksum_manifest(path: Path, entries: Mapping[str, str]) -> Path:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for relpath in sorted(entries):
            fh.write(f"{entries[relpath]}  {relpath}\n")
    return path


def _sha256_file(path: Path) -> str:
    """Deterministic chunked SHA-256 of a file (1 MB reads)."""
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _write_json(path: Path, obj: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def _write_csv_rows(path: Path, *, header: Sequence[str],
                    rows: Sequence[Sequence[Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_rows = sorted(rows, key=lambda r: tuple(str(x) for x in r))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        for row in sorted_rows:
            writer.writerow(row)
    return path


def _write_csv_dataclass(path: Path, columns: Sequence[str],
                         rows: Sequence[Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = []
    for r in rows:
        d = asdict(r) if hasattr(r, "__dataclass_fields__") else dict(r)
        data.append([d.get(c, "") for c in columns])
    data.sort(key=lambda r: tuple(str(x) for x in r))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(list(columns))
        for row in data:
            writer.writerow(row)
    return path


def _write_derived_demands_csv(path: Path,
                               demands: Sequence[DerivedCompetenceDemand]) -> Path:
    return _write_csv_dataclass(path, DERIVED_DEMAND_COLUMNS, demands)


def _write_derived_demands_jsonl(path: Path,
                                 demands: Sequence[DerivedCompetenceDemand]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(demands, key=lambda d: (d.sector, d.axis_group, d.competence_label))
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(asdict(r), sort_keys=True, ensure_ascii=False))
            fh.write("\n")
    return path


def _split_list(value: Any) -> List[str]:
    if value is None:
        return []
    text = str(value)
    if not text:
        return []
    for sep in ("||", "|", ";", ","):
        if sep in text:
            return [s.strip() for s in text.split(sep) if s.strip()]
    return [text.strip()] if text.strip() else []


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _diversity(count: int, universe: int) -> float:
    if universe <= 0:
        return 0.0
    return max(0.0, min(1.0, count / universe))


def _recency_score(
    latest_at: str,
    analysis_timestamp_utc: Optional[str] = None,
) -> float:
    if not latest_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(latest_at.replace("Z", "+00:00"))
        reference = (
            datetime.fromisoformat(analysis_timestamp_utc.replace("Z", "+00:00"))
            if analysis_timestamp_utc
            else datetime.now(timezone.utc)
        )
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    delta_days = max(0.0, (reference - dt).total_seconds() / 86400.0)
    # exponential decay: 1.0 at 0 days, ~0.37 at 365 days, ~0.14 at 730 days
    return math.exp(-delta_days / 365.0)


def _classify_demand_status(*, score: float, evidence_count: int,
                            provider_count: int, confidences: Sequence[float]) -> str:
    if evidence_count == 0:
        return "review_required"
    if provider_count == 1 and evidence_count >= 3:
        return "provider_bias_warning"
    if any(c < 0.3 for c in confidences) and score < 0.4:
        return "review_required"
    if score >= 0.70 and evidence_count >= 2:
        return "high_demand"
    if score >= 0.40 and evidence_count >= 1:
        return "medium_demand"
    return "low_demand"


def _infer_eqf_relevance(label: str, signals: Sequence[Mapping[str, Any]]) -> str:
    text = " ".join([label.lower()] + [
        str(
            s.get(
                "competence_description",
                s.get("signal_category_description", ""),
            )
        ).lower()
        + " "
        + str(s.get("demand_phrase", s.get("matched_phrase", ""))).lower()
        for s in signals
    ])
    matched: List[int] = []
    for lvl, keywords in EQF_KEYWORD_MAP:
        if any(k in text for k in keywords):
            matched.append(lvl)
    if not matched:
        # default: EQF 5-6 for generic applied competences
        matched = [5, 6]
    return "|".join(str(x) for x in sorted(set(matched)))


def _parse_eqf_levels(field_value: str) -> List[int]:
    out: List[int] = []
    for tok in _split_list(field_value):
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return sorted(set(out))


def _axis_group_to_code(axis: str) -> str:
    mapping = {"MARINE": "M", "MARITIME": "T", "OCEANIC": "O", "HYDRONIZATION": "H"}
    return mapping.get(axis.upper(), "")


def _axis_code_to_group(code: str) -> str:
    mapping = {"M": "MARINE", "T": "MARITIME", "O": "OCEANIC", "H": "HYDRONIZATION"}
    return mapping.get(str(code or "").strip().upper(), "UNASSIGNED")


def _first_nonempty(iterable: Iterable[str], default: str = "") -> str:
    for v in iterable:
        if v:
            return v
    return default


def _make_id(prefix: str, *parts: str) -> str:
    key = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:40]
    return f"{prefix}-{slug}-{digest}" if slug else f"{prefix}-{digest}"


def _expected_canonical_competence_id(value: Any) -> str:
    """Return the schema-v2 canonical identifier for one preferred label.

    Delegates to :func:`schema_v2_identity.make_canonical_competence_id`.
    """
    return _make_canonical_competence_id(value)


def _normalized_lineage_label(value: Any) -> str:
    """Normalize a canonical label using the runtime identity preimage.

    Thin wrapper over :func:`schema_v2_identity.normalize_canonical_label`.
    """
    from src.scientific_sources.schema_v2_identity import normalize_canonical_label
    return normalize_canonical_label(value)


def _parse_lineage_utc(value: Any) -> Optional[datetime]:
    """Return a strict UTC lineage timestamp, or ``None`` when invalid."""
    token = str(value or "").strip()
    if not token or not _LINEAGE_UTC_TIMESTAMP_RE.fullmatch(token):
        return None
    try:
        parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError:
        return None
    offset = parsed.utcoffset()
    if (
        parsed.tzinfo is None
        or offset is None
        or offset.total_seconds() != 0
    ):
        return None
    return parsed.astimezone(timezone.utc)


def _lineage_row_id(row: Mapping[str, Any], field_name: str) -> str:
    return str(row.get(field_name, "") or "").strip()


def _require_exact_lineage_serialization(
    rows: Sequence[Mapping[str, Any]],
    *,
    table_name: str,
    scalar_fields: Sequence[str],
    list_fields: Sequence[str] = (),
) -> None:
    """Reject padded or duplicate retained schema-v2 lineage references."""
    for row in rows:
        row_id = _lineage_row_id(row, scalar_fields[0]) if scalar_fields else ""
        for field_name in scalar_fields:
            raw_value = row.get(field_name, "")
            if not isinstance(raw_value, str):
                raise DerivedAnalysisError(
                    "accepted canonical lineage contains a non-string "
                    f"{table_name}.{field_name}: {row_id}"
                )
            retained = raw_value
            if retained and retained != retained.strip():
                raise DerivedAnalysisError(
                    "accepted canonical lineage contains padded "
                    f"{table_name}.{field_name}: {row_id}"
                )
        for field_name in list_fields:
            raw_value = row.get(field_name, "")
            if not isinstance(raw_value, str):
                raise DerivedAnalysisError(
                    "accepted canonical lineage contains a non-string "
                    f"{table_name}.{field_name}: {row_id}"
                )
            retained = raw_value
            if not retained:
                continue
            tokens = retained.split("|")
            if (
                any(not token or token != token.strip() for token in tokens)
                or len(tokens) != len(set(tokens))
            ):
                raise DerivedAnalysisError(
                    "accepted canonical lineage contains malformed "
                    f"{table_name}.{field_name}: {row_id}"
                )


def _index_lineage_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    field_name: str,
    table_name: str,
) -> Dict[str, Mapping[str, Any]]:
    """Return a unique non-empty-key index or fail closed on malformed input."""
    indexed: Dict[str, Mapping[str, Any]] = {}
    for row in rows:
        row_id = _lineage_row_id(row, field_name)
        if not row_id:
            raise DerivedAnalysisError(
                f"accepted canonical lineage {table_name} row is missing {field_name}"
            )
        if row_id in indexed:
            raise DerivedAnalysisError(
                f"accepted canonical lineage contains duplicate {table_name} "
                f"identifier: {row_id}"
            )
        indexed[row_id] = row
    return indexed


def _accepted_canonical_lineage_required(
    demand: DerivedCompetenceDemand,
) -> bool:
    """Identify a fully traceable reviewed canonical demand projection."""
    return (
        demand.view_kind == ACCEPTED_CANONICAL_LINEAGE_VIEW_KIND
        and demand.scientific_status
        == VALIDATED_CANONICAL_DEMAND_SCIENTIFIC_STATUS
        and bool(demand.canonical_competence_id)
        and bool(demand.validation_decision_ids)
        and bool(demand.source_candidate_ids)
        and bool(demand.assignment_ids)
    )


def _legacy_derived_demands(
    demands: Sequence[DerivedCompetenceDemand],
) -> List[DerivedCompetenceDemand]:
    """Return only the legacy compatibility population for empirical metrics."""
    return [
        demand
        for demand in demands
        if (
            demand.view_kind == LEGACY_DERIVED_DEMAND_VIEW_KIND
            and demand.scientific_status
            == LEGACY_DERIVED_DEMAND_SCIENTIFIC_STATUS
        )
    ]


def _credential_translation_demands(
    demands: Sequence[DerivedCompetenceDemand],
) -> List[DerivedCompetenceDemand]:
    """Select one analytical view per sector-axis for credential translation."""
    legacy_demands = _legacy_derived_demands(demands)
    if legacy_demands:
        return legacy_demands
    return [
        demand
        for demand in demands
        if _accepted_canonical_lineage_required(demand)
    ]


def _providers_for_lineage_evidence(evidence: Mapping[str, Any]) -> List[str]:
    providers = _split_list(evidence.get("providers_seen", ""))
    if not providers:
        providers = _split_list(evidence.get("provider_source", ""))
    return providers


def _decision_cutoff_timestamp(decision_at_utc: str) -> datetime:
    """Return the accepted-decision cutoff timestamp for reviewed snapshot metrics."""
    return datetime.fromisoformat(decision_at_utc.replace("Z", "+00:00"))


def _timestamp_on_or_before_cutoff(
    row: Mapping[str, Any], field_name: str, cutoff: datetime
) -> str:
    """Return a lineage timestamp only when it belongs to the reviewed snapshot."""
    value = _lineage_row_id(row, field_name)
    if not value:
        return ""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if parsed <= cutoff else ""


def _accepted_lineage_snapshot_metrics(
    evidence: List[Mapping[str, Any]], decision_at_utc: str
) -> Dict[str, Any]:
    """Freeze accepted-lineage metrics to evidence retained at decision time."""
    cutoff = _decision_cutoff_timestamp(decision_at_utc)
    snapshot_rows = [
        row
        for row in evidence
        if _timestamp_on_or_before_cutoff(row, "first_seen_at_utc", cutoff)
    ]
    providers = sorted(
        {
            provider
            for row in snapshot_rows
            for provider in _split_list(row.get("provider_source", ""))
            if provider
        }
    )
    first_run = min(
        (_lineage_row_id(row, "first_seen_run_id") for row in snapshot_rows),
        default="",
    )
    latest_run = max(
        (
            _lineage_row_id(row, "latest_seen_run_id")
            if _timestamp_on_or_before_cutoff(row, "latest_seen_at_utc", cutoff)
            else _lineage_row_id(row, "first_seen_run_id")
            for row in snapshot_rows
        ),
        default="",
    )
    first_at = min(
        (_lineage_row_id(row, "first_seen_at_utc") for row in snapshot_rows),
        default="",
    )
    latest_at = max(
        (
            _timestamp_on_or_before_cutoff(row, "latest_seen_at_utc", cutoff)
            or _lineage_row_id(row, "first_seen_at_utc")
            for row in snapshot_rows
        ),
        default="",
    )
    return {
        "providers": providers,
        "first_run": first_run,
        "latest_run": latest_run,
        "first_at": first_at,
        "latest_at": latest_at,
        "occurrence_count": len(snapshot_rows),
    }


def _build_accepted_canonical_lineage_demands(
    *,
    evidence_records: Sequence[Mapping[str, Any]],
    evidence_fragments: Optional[Sequence[Mapping[str, Any]]],
    canonical_competences: Optional[Sequence[Mapping[str, Any]]],
    sector_competence_assignments: Optional[Sequence[Mapping[str, Any]]],
    validation_decisions: Optional[Sequence[Mapping[str, Any]]],
    competence_candidates: Optional[Sequence[Mapping[str, Any]]],
    semantic_signals: Optional[Sequence[Mapping[str, Any]]],
    analysis_timestamp_utc: Optional[str],
) -> List[DerivedCompetenceDemand]:
    """Emit reviewed canonical demands only from a complete schema-v2 chain.

    The compatibility view intentionally remains independent.  This adapter
    reconstructs accepted lineage from the cumulative schema-v2 tables and
    refuses partial or mismatched provenance instead of treating labels as
    proof of validation.
    """
    fragment_rows = list(evidence_fragments or ())
    canonical_rows = list(canonical_competences or ())
    assignment_rows = list(sector_competence_assignments or ())
    decision_rows = list(validation_decisions or ())
    candidate_rows = list(competence_candidates or ())
    signal_rows = list(semantic_signals or ())

    if not any(
        (
            fragment_rows,
            canonical_rows,
            assignment_rows,
            decision_rows,
            candidate_rows,
            signal_rows,
        )
    ):
        return []
    if not decision_rows:
        if canonical_rows or assignment_rows:
            raise DerivedAnalysisError(
                "accepted canonical lineage requires validation decisions"
            )
        return []

    decisions_by_id = _index_lineage_rows(
        decision_rows,
        field_name="validation_decision_id",
        table_name="validation_decisions",
    )
    for decision_id, decision in decisions_by_id.items():
        decision_at = _parse_lineage_utc(decision.get("decision_at_utc"))
        if decision_at is None:
            raise DerivedAnalysisError(
                "accepted canonical lineage decision has an invalid UTC "
                f"timestamp: {decision_id}"
            )
        reviewer = _lineage_row_id(decision, "reviewer")
        if not reviewer or not _lineage_row_id(decision, "decision_reason"):
            raise DerivedAnalysisError(
                "accepted canonical lineage decision is missing reviewer "
                f"provenance: {decision_id}"
            )
        if not _LINEAGE_REVIEWER_IDENTIFIER_RE.fullmatch(reviewer):
            raise DerivedAnalysisError(
                "accepted canonical lineage decision has an invalid reviewer "
                f"identifier: {decision_id}"
            )
        superseded_id = _lineage_row_id(
            decision, "superseded_validation_decision_id"
        )
        if not superseded_id:
            continue
        if superseded_id == decision_id:
            raise DerivedAnalysisError(
                "accepted canonical lineage decision supersession is self-"
                f"referential: {decision_id}"
            )
        superseded = decisions_by_id.get(superseded_id)
        if superseded is None:
            raise DerivedAnalysisError(
                "accepted canonical lineage decision supersession target is "
                f"missing: {decision_id}"
            )
        if _lineage_row_id(decision, "target_candidate_id") != _lineage_row_id(
            superseded, "target_candidate_id"
        ):
            raise DerivedAnalysisError(
                "accepted canonical lineage decision supersession crosses "
                f"candidates: {decision_id}"
            )
        superseded_at = _parse_lineage_utc(
            superseded.get("decision_at_utc")
        )
        if superseded_at is None or decision_at <= superseded_at:
            raise DerivedAnalysisError(
                "superseding validation decision must be chronologically later"
            )
    for decision_id in decisions_by_id:
        path_ids: Set[str] = set()
        current_id = decision_id
        while current_id:
            if current_id in path_ids:
                raise DerivedAnalysisError(
                    "accepted canonical lineage decision supersession contains "
                    f"a cycle: {decision_id}"
                )
            path_ids.add(current_id)
            current = decisions_by_id[current_id]
            current_id = _lineage_row_id(
                current, "superseded_validation_decision_id"
            )
    inactive_decision_ids = {
        _lineage_row_id(decision, "superseded_validation_decision_id")
        for decision in decision_rows
        if _lineage_row_id(decision, "superseded_validation_decision_id")
    }
    active_decisions = [
        decision
        for decision_id, decision in decisions_by_id.items()
        if decision_id not in inactive_decision_ids
    ]
    active_decision_by_candidate: Dict[str, Mapping[str, Any]] = {}
    for decision in active_decisions:
        candidate_id = _lineage_row_id(decision, "target_candidate_id")
        if candidate_id in active_decision_by_candidate:
            raise DerivedAnalysisError(
                "accepted canonical lineage has multiple active validation "
                f"decisions for candidate: {candidate_id}"
            )
        active_decision_by_candidate[candidate_id] = decision
    active_accepted_decisions = [
        decision
        for decision in active_decisions
        if _lineage_row_id(decision, "decision_status") == "accepted"
    ]
    if not active_accepted_decisions:
        if canonical_rows or assignment_rows:
            raise DerivedAnalysisError(
                "accepted canonical lineage contains canonical or assignment "
                "rows without an active accepted decision"
            )
        return []
    if not candidate_rows or not signal_rows or not fragment_rows:
        raise DerivedAnalysisError(
            "accepted canonical lineage requires candidates, evidence fragments, "
            "and semantic signals"
        )

    _require_exact_lineage_serialization(
        evidence_records,
        table_name="evidence_records",
        scalar_fields=("evidence_id",),
    )
    _require_exact_lineage_serialization(
        fragment_rows,
        table_name="evidence_fragments",
        scalar_fields=(
            "fragment_id",
            "evidence_id",
            "run_id",
            "source_provenance_id",
        ),
    )
    _require_exact_lineage_serialization(
        signal_rows,
        table_name="semantic_signals",
        scalar_fields=(
            "signal_id",
            "fragment_id",
            "evidence_id",
            "run_id",
            "source_provenance_id",
            "sector",
            "axis_group",
            "axis_code",
        ),
    )
    _require_exact_lineage_serialization(
        candidate_rows,
        table_name="competence_candidates",
        scalar_fields=(
            "candidate_id",
            "signal_id",
            "fragment_id",
            "evidence_id",
            "run_id",
            "sector",
            "axis_group",
            "axis_code",
        ),
        list_fields=("source_provenance_ids", "fragment_ids"),
    )
    _require_exact_lineage_serialization(
        decision_rows,
        table_name="validation_decisions",
        scalar_fields=(
            "validation_decision_id",
            "target_candidate_id",
            "superseded_validation_decision_id",
        ),
        list_fields=("evidence_ids", "fragment_ids", "source_provenance_ids"),
    )
    _require_exact_lineage_serialization(
        canonical_rows,
        table_name="canonical_competences",
        scalar_fields=(
            "canonical_competence_id",
            "validation_decision_id",
            "source_candidate_id",
        ),
    )
    _require_exact_lineage_serialization(
        assignment_rows,
        table_name="sector_competence_assignments",
        scalar_fields=(
            "assignment_id",
            "canonical_competence_id",
            "validation_decision_id",
            "source_candidate_id",
            "sector",
            "axis_group",
            "axis_code",
        ),
        list_fields=("evidence_ids",),
    )

    evidence_by_id = _index_lineage_rows(
        evidence_records,
        field_name="evidence_id",
        table_name="evidence_records",
    )
    fragments_by_id = _index_lineage_rows(
        fragment_rows,
        field_name="fragment_id",
        table_name="evidence_fragments",
    )
    canonicals_by_id = _index_lineage_rows(
        canonical_rows,
        field_name="canonical_competence_id",
        table_name="canonical_competences",
    )
    candidates_by_id = _index_lineage_rows(
        candidate_rows,
        field_name="candidate_id",
        table_name="competence_candidates",
    )
    assignments_by_id = _index_lineage_rows(
        assignment_rows,
        field_name="assignment_id",
        table_name="sector_competence_assignments",
    )

    # Guard: candidate_id and fragment_id values must be non-empty
    # typed-prefix hex-hash strings (e.g. "candidate:<64-hex>" /
    # "fragment:<64-hex>").  Empty strings, bare labels, provider-prefixed
    # tokens, or truncated values indicate a corrupted or forged chain and are
    # rejected before any cross-table resolution begins.
    # Note: recomputing the full deterministic hash from field content is
    # deferred — that requires mirroring helpers from
    # cumulative_scientific_database.py and carries regression risk.
    for candidate_id, candidate in candidates_by_id.items():
        if not _LINEAGE_HEX_ID_RE.fullmatch(candidate_id):
            raise DerivedAnalysisError(
                "accepted canonical lineage candidate_id is not a valid "
                f"typed-prefix hex-hash identity: {candidate_id!r}"
            )
        for fragment_id in _split_list(candidate.get("fragment_ids")):
            if not _LINEAGE_HEX_ID_RE.fullmatch(fragment_id):
                raise DerivedAnalysisError(
                    "accepted canonical lineage candidate contains a "
                    "fragment_id that is not a valid typed-prefix hex-hash "
                    f"identity: {fragment_id!r} (candidate: {candidate_id})"
                )
    for fragment_id in fragments_by_id:
        if not _LINEAGE_HEX_ID_RE.fullmatch(fragment_id):
            raise DerivedAnalysisError(
                "accepted canonical lineage fragment_id is not a valid "
                f"typed-prefix hex-hash identity: {fragment_id!r}"
            )

    signal_by_key: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for signal in signal_rows:
        signal_key = (
            _lineage_row_id(signal, "signal_id"),
            _lineage_row_id(signal, "fragment_id"),
        )
        if not all(signal_key):
            raise DerivedAnalysisError(
                "accepted canonical lineage semantic signal is missing its "
                "signal_id or fragment_id"
            )
        if signal_key in signal_by_key:
            raise DerivedAnalysisError(
                "accepted canonical lineage contains duplicate semantic "
                f"signal identity: {signal_key[0]}+{signal_key[1]}"
            )
        signal_by_key[signal_key] = signal

    # ------------------------------------------------------------------
    # Deterministic ID recomputation guards (best-effort: only fire when
    # all preimage fields are present; missing fields are skipped).
    # ------------------------------------------------------------------

    # Build reverse map: fragment_id -> first signal row that covers it,
    # needed for per-fragment provenance_id and fragment_id recomputation.
    signal_by_fragment_id: Dict[str, Mapping[str, Any]] = {}
    for (sig_id, frag_id), sig_row in signal_by_key.items():
        if frag_id not in signal_by_fragment_id:
            signal_by_fragment_id[frag_id] = sig_row

    # 1. Recompute signal_id for each semantic signal row.
    for signal in signal_rows:
        stored_signal_id = _lineage_row_id(signal, "signal_id")
        recomputed_signal_id = _recompute_signal_id_from_row(signal)
        if recomputed_signal_id and recomputed_signal_id != stored_signal_id:
            raise DerivedAnalysisError(
                "accepted canonical lineage signal_id does not match "
                f"recomputed identity: {stored_signal_id}"
            )

    # 2. Recompute provenance_id and fragment_id for each evidence fragment.
    for fragment_id, fragment in fragments_by_id.items():
        stored_provenance_id = _lineage_row_id(fragment, "source_provenance_id")
        recomputed_prov = _recompute_provenance_id_from_row(fragment)
        if recomputed_prov and recomputed_prov != stored_provenance_id:
            raise DerivedAnalysisError(
                "accepted canonical lineage fragment provenance_id does not "
                f"match recomputed identity: {fragment_id}"
            )
        covering_signal = signal_by_fragment_id.get(fragment_id)
        if covering_signal is not None:
            covering_signal_id = _lineage_row_id(covering_signal, "signal_id")
            prov_for_fragment = recomputed_prov or stored_provenance_id
            recomputed_frag = _recompute_fragment_id_from_row(
                fragment,
                signal_id=covering_signal_id,
                provenance_id=prov_for_fragment,
            )
            if recomputed_frag and recomputed_frag != fragment_id:
                raise DerivedAnalysisError(
                    "accepted canonical lineage fragment_id does not match "
                    f"recomputed identity: {fragment_id}"
                )

    # 3. Recompute candidate_id for each competence candidate row.
    for candidate_id, candidate in candidates_by_id.items():
        recomputed_cand = _recompute_candidate_id_from_row(candidate)
        if recomputed_cand and recomputed_cand != candidate_id:
            raise DerivedAnalysisError(
                "accepted canonical lineage candidate_id does not match "
                f"recomputed identity: {candidate_id}"
            )

    # 4. Span validation: verify fragment text matches context slice.
    for fragment_id, fragment in fragments_by_id.items():
        context_text = str(fragment.get("context_text") or "")
        fragment_text = str(fragment.get("fragment_text") or "")
        span_start_raw = fragment.get("span_start_offset")
        span_end_raw = fragment.get("span_end_offset")
        if not context_text or not fragment_text:
            continue
        if span_start_raw is None or span_end_raw is None:
            continue
        try:
            span_start = int(span_start_raw)
            span_end = int(span_end_raw)
        except (ValueError, TypeError):
            raise DerivedAnalysisError(
                "accepted canonical lineage fragment has invalid span offsets: "
                f"{fragment_id}"
            )
        if not (0 <= span_start < span_end <= len(context_text)):
            raise DerivedAnalysisError(
                "accepted canonical lineage fragment has out-of-bounds span "
                f"offsets: {fragment_id}"
            )
        if context_text[span_start:span_end] != fragment_text:
            raise DerivedAnalysisError(
                "accepted canonical lineage fragment span text does not match "
                f"context_text slice: {fragment_id}"
            )

    expected_contexts_by_decision_id: Dict[str, Set[Tuple[str, str, str]]] = {}
    expected_canonical_id_by_decision_id: Dict[str, str] = {}
    for decision in active_accepted_decisions:
        decision_id = _lineage_row_id(decision, "validation_decision_id")
        candidate_id = _lineage_row_id(decision, "target_candidate_id")
        _cand_lookup: Optional[Mapping[str, Any]] = candidates_by_id.get(candidate_id)
        if _cand_lookup is None:
            raise DerivedAnalysisError(
                "accepted canonical lineage decision references a missing "
                f"candidate: {decision_id}"
            )
        candidate = _cand_lookup
        candidate_evidence_id = _lineage_row_id(candidate, "evidence_id")
        candidate_signal_id = _lineage_row_id(candidate, "signal_id")
        candidate_fragment_tokens = _split_list(candidate.get("fragment_ids"))
        candidate_fragment_ids = set(candidate_fragment_tokens)
        candidate_fragment_id = _lineage_row_id(candidate, "fragment_id")
        if (
            not candidate_evidence_id
            or not candidate_signal_id
            or not candidate_fragment_ids
            or candidate_fragment_id not in candidate_fragment_ids
            or len(candidate_fragment_tokens) != len(candidate_fragment_ids)
        ):
            raise DerivedAnalysisError(
                "accepted canonical lineage candidate has an invalid retained "
                f"fragment snapshot: {candidate_id}"
            )
        expected_candidate_fragment_ids = {
            fragment_id
            for (signal_id, fragment_id), signal_row in signal_by_key.items()
            if (
                signal_id == candidate_signal_id
                and _lineage_row_id(signal_row, "evidence_id")
                == candidate_evidence_id
            )
        }
        if candidate_fragment_ids != expected_candidate_fragment_ids:
            raise DerivedAnalysisError(
                "accepted canonical lineage candidate fragment snapshot does "
                f"not retain every semantic occurrence: {candidate_id}"
            )
        expected_candidate_provenance_ids: Set[str] = set()
        contexts: Set[Tuple[str, str, str]] = set()
        for fragment_id in candidate_fragment_ids:
            _frag_lookup: Optional[Mapping[str, Any]] = fragments_by_id.get(fragment_id)
            if _frag_lookup is None:
                raise DerivedAnalysisError(
                    "accepted canonical lineage candidate references a missing "
                    f"evidence fragment: {candidate_id}:{fragment_id}"
                )
            fragment = _frag_lookup
            if (
                _lineage_row_id(fragment, "evidence_id") != candidate_evidence_id
                or candidate_evidence_id not in evidence_by_id
            ):
                raise DerivedAnalysisError(
                    "accepted canonical lineage candidate fragment does not "
                    f"resolve to retained evidence: {candidate_id}:{fragment_id}"
                )
            fragment_provenance_id = _lineage_row_id(
                fragment, "source_provenance_id"
            )
            if not fragment_provenance_id:
                raise DerivedAnalysisError(
                    "accepted canonical lineage fragment is missing provenance: "
                    f"{fragment_id}"
                )
            expected_candidate_provenance_ids.add(fragment_provenance_id)
            matched_signal = signal_by_key.get((candidate_signal_id, fragment_id))
            if matched_signal is None:
                raise DerivedAnalysisError(
                    "accepted canonical lineage candidate fragment has no "
                    f"matching semantic signal: {candidate_id}:{fragment_id}"
                )
            if (
                _lineage_row_id(matched_signal, "evidence_id")
                != candidate_evidence_id
                or _lineage_row_id(matched_signal, "source_provenance_id")
                != fragment_provenance_id
            ):
                raise DerivedAnalysisError(
                    "accepted canonical lineage semantic signal does not "
                    f"match its evidence fragment: {candidate_id}:{fragment_id}"
                )
            sector = _lineage_row_id(matched_signal, "sector")
            axis_group = _lineage_row_id(matched_signal, "axis_group").upper()
            axis_code = _lineage_row_id(matched_signal, "axis_code").upper()
            if not sector and not axis_group and not axis_code:
                continue
            if (
                not sector
                or axis_group not in {
                    "MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION"
                }
                or _axis_group_to_code(axis_group) != axis_code
            ):
                raise DerivedAnalysisError(
                    "accepted canonical lineage semantic signal has an invalid "
                    f"sector-axis context: {candidate_id}:{fragment_id}"
                )
            contexts.add((sector, axis_group, axis_code))
        if set(_split_list(candidate.get("source_provenance_ids"))) != (
            expected_candidate_provenance_ids
        ):
            raise DerivedAnalysisError(
                "accepted canonical lineage candidate provenance snapshot does "
                f"not match retained fragments: {candidate_id}"
            )
        decision_fragment_tokens = _split_list(decision.get("fragment_ids"))
        decision_fragment_ids = set(decision_fragment_tokens)
        if (
            not decision_fragment_ids
            or len(decision_fragment_tokens) != len(decision_fragment_ids)
            or not decision_fragment_ids.issubset(candidate_fragment_ids)
        ):
            raise DerivedAnalysisError(
                "accepted canonical lineage decision has an invalid fragment "
                f"snapshot: {decision_id}"
            )
        decision_provenance_ids = {
            _lineage_row_id(fragments_by_id[fragment_id], "source_provenance_id")
            for fragment_id in decision_fragment_ids
        }
        decision_at = _parse_lineage_utc(decision.get("decision_at_utc"))
        if decision_at is None:
            raise DerivedAnalysisError(
                "accepted canonical lineage decision has an invalid UTC "
                f"timestamp: {decision_id}"
            )
        built_at = _parse_lineage_utc(analysis_timestamp_utc)
        if built_at is not None and decision_at > built_at:
            raise DerivedAnalysisError(
                "accepted canonical lineage decision is dated after the "
                f"database built_at_utc: {decision_id}"
            )
        for fragment_id in decision_fragment_ids:
            retrieved_at = _parse_lineage_utc(
                fragments_by_id[fragment_id].get("source_retrieved_at_utc")
            )
            if retrieved_at is None or retrieved_at > decision_at:
                raise DerivedAnalysisError(
                    "accepted canonical lineage decision predates retained "
                    f"evidence retrieval: {decision_id}"
                )
        if (
            set(_split_list(decision.get("evidence_ids")))
            != {candidate_evidence_id}
            or set(_split_list(decision.get("source_provenance_ids")))
            != decision_provenance_ids
        ):
            raise DerivedAnalysisError(
                "accepted canonical lineage decision snapshot does not match "
                f"its candidate: {decision_id}"
            )
        canonical_label = _normalized_lineage_label(
            decision.get("canonical_label")
        )
        if not canonical_label:
            raise DerivedAnalysisError(
                "accepted canonical lineage decision is missing a canonical "
                f"label: {decision_id}"
            )
        label_allowed, _ = canonical_label_is_allowed(
            canonical_label,
            retained_source_titles=(
                _lineage_row_id(
                    evidence_by_id[candidate_evidence_id], "canonical_title"
                ),
            ),
        )
        if not label_allowed:
            raise DerivedAnalysisError(
                "accepted canonical lineage decision failed the canonical-label "
                f"provenance guard: {decision_id}"
            )
        expected_contexts_by_decision_id[decision_id] = contexts
        expected_canonical_id_by_decision_id[decision_id] = (
            _expected_canonical_competence_id(canonical_label)
        )

    for canonical_id, canonical in canonicals_by_id.items():
        preferred_label = _normalized_lineage_label(
            canonical.get("preferred_label")
        )
        if canonical_id != _expected_canonical_competence_id(preferred_label):
            raise DerivedAnalysisError(
                "accepted canonical lineage has an invalid "
                f"canonical_competence_id: {canonical_id}"
            )
        if (
            _lineage_row_id(canonical, "validation_status") != "accepted"
            or _lineage_row_id(canonical, "provenance_guard_status") != "passed"
            or not preferred_label
            or not _lineage_row_id(canonical, "canonical_definition")
        ):
            raise DerivedAnalysisError(
                "accepted canonical lineage contains a non-accepted or "
                f"incomplete canonical competence: {canonical_id}"
            )
        canonical_decision_id = _lineage_row_id(
            canonical, "validation_decision_id"
        )
        canonical_candidate_id = _lineage_row_id(
            canonical, "source_candidate_id"
        )
        canonical_decision = decisions_by_id.get(canonical_decision_id)
        canonical_candidate = candidates_by_id.get(canonical_candidate_id)
        if (
            canonical_decision is None
            or canonical_decision_id in inactive_decision_ids
            or _lineage_row_id(canonical_decision, "decision_status")
            != "accepted"
            or _lineage_row_id(canonical_decision, "target_candidate_id")
            != canonical_candidate_id
            or _normalized_lineage_label(
                canonical_decision.get("canonical_label")
            ).lower()
            != preferred_label.lower()
            or canonical_candidate is None
            or _lineage_row_id(canonical, "canonical_definition")
            != _lineage_row_id(canonical_candidate, "candidate_definition")
        ):
            raise DerivedAnalysisError(
                "accepted canonical lineage does not resolve its reviewed "
                f"decision and candidate: {canonical_id}"
            )

    for decision_id, expected_canonical_id in (
        expected_canonical_id_by_decision_id.items()
    ):
        if expected_canonical_id not in canonicals_by_id:
            raise DerivedAnalysisError(
                "accepted canonical lineage decision is missing its canonical "
                f"competence: {decision_id}"
            )

    grouped_assignments: Dict[
        Tuple[str, str, str], List[Tuple[Mapping[str, Any], List[Mapping[str, Any]]]]
    ] = {}
    assignments_by_decision_context: Dict[
        Tuple[str, Tuple[str, str, str]], List[Mapping[str, Any]]
    ] = {}
    for assignment in assignments_by_id.values():
        assignment_id = _lineage_row_id(assignment, "assignment_id")
        canonical_id = _lineage_row_id(assignment, "canonical_competence_id")
        decision_id = _lineage_row_id(assignment, "validation_decision_id")
        candidate_id = _lineage_row_id(assignment, "source_candidate_id")
        sector = _lineage_row_id(assignment, "sector")
        axis_group = _lineage_row_id(assignment, "axis_group").upper()
        axis_code = _lineage_row_id(assignment, "axis_code").upper()
        assigned_canonical = canonicals_by_id.get(canonical_id)
        linked_decision = decisions_by_id.get(decision_id)
        _cand_lookup2: Optional[Mapping[str, Any]] = candidates_by_id.get(candidate_id)
        if not all((assignment_id, canonical_id, decision_id, candidate_id, sector)):
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment is missing a required "
                "identifier or sector"
            )
        if (
            assigned_canonical is None
            or linked_decision is None
            or _cand_lookup2 is None
        ):
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment has an unresolved "
                f"foreign key: {assignment_id}"
            )
        candidate = _cand_lookup2
        if (
            decision_id in inactive_decision_ids
            or _lineage_row_id(linked_decision, "decision_status") != "accepted"
            or _lineage_row_id(linked_decision, "target_candidate_id")
            != candidate_id
            or _normalized_lineage_label(
                assigned_canonical.get("preferred_label")
            ).lower()
            != _normalized_lineage_label(
                linked_decision.get("canonical_label")
            ).lower()
        ):
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment is not backed by an "
                f"active accepted decision: {assignment_id}"
            )
        if axis_group not in {"MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION"}:
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment has an invalid axis "
                f"group: {assignment_id}"
            )
        if _axis_group_to_code(axis_group) != axis_code:
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment has a mismatched axis "
                f"code: {assignment_id}"
            )
        assignment_evidence_ids = set(_split_list(assignment.get("evidence_ids")))
        candidate_evidence_id = _lineage_row_id(candidate, "evidence_id")
        if assignment_evidence_ids != {candidate_evidence_id}:
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment evidence does not "
                f"match its candidate snapshot: {assignment_id}"
            )
        # 4b. Recompute assignment_id from its preimage fields to detect
        # forgery: a tampered sector/axis/canonical_id combination that
        # passes FK checks but was not issued by the canonical producer.
        recomputed_assignment_id = _recompute_assignment_id_from_row(assignment)
        if recomputed_assignment_id and recomputed_assignment_id != assignment_id:
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment_id does not match "
                f"recomputed identity: {assignment_id}"
            )
        if candidate_evidence_id not in evidence_by_id:
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment references missing "
                f"evidence: {assignment_id}"
            )
        # Use the immutable reviewed fragment snapshot from the decision row
        # rather than the current live candidate.fragment_ids.  The decision
        # snapshot was validated at review time and must gate which context
        # signals are eligible for metrics; reading the candidate's current
        # fragment_ids could include post-review additions.
        reviewed_decision = decisions_by_id[decision_id]
        candidate_fragment_ids = set(
            _split_list(reviewed_decision.get("fragment_ids"))
        )
        selected_context_signals = [
            signal
            for (signal_id, fragment_id), signal in signal_by_key.items()
            if (
                signal_id == _lineage_row_id(candidate, "signal_id")
                and fragment_id in candidate_fragment_ids
                and _lineage_row_id(signal, "evidence_id")
                == candidate_evidence_id
                and _lineage_row_id(signal, "sector") == sector
                and _lineage_row_id(signal, "axis_group").upper() == axis_group
                and _lineage_row_id(signal, "axis_code").upper() == axis_code
            )
        ]
        if not selected_context_signals:
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment has no matching "
                f"semantic context: {assignment_id}"
            )
        context = (sector, axis_group, axis_code)
        if context not in expected_contexts_by_decision_id.get(decision_id, set()):
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment has an unexpected "
                f"semantic context: {assignment_id}"
            )
        assignments_by_decision_context.setdefault(
            (decision_id, context), []
        ).append(assignment)
        key = (canonical_id, sector, axis_group)
        grouped_assignments.setdefault(key, []).append(
            (assignment, selected_context_signals)
        )

    for decision_id, contexts in expected_contexts_by_decision_id.items():
        expected_canonical_id = expected_canonical_id_by_decision_id[decision_id]
        for context in contexts:
            matching_assignments = assignments_by_decision_context.get(
                (decision_id, context), []
            )
            if len(matching_assignments) != 1:
                raise DerivedAnalysisError(
                    "accepted canonical lineage decision is missing or has "
                    f"duplicate sector-axis assignments: {decision_id}"
                )
            if (
                _lineage_row_id(
                    matching_assignments[0], "canonical_competence_id"
                )
                != expected_canonical_id
            ):
                raise DerivedAnalysisError(
                    "accepted canonical lineage assignment is linked to the "
                    f"wrong canonical competence: {decision_id}"
                )

    all_providers = {
        provider
        for evidence in evidence_records
        for provider in _providers_for_lineage_evidence(evidence)
    }
    all_query_families = {
        _lineage_row_id(signal, "query_family")
        for signal in signal_rows
        if _lineage_row_id(signal, "query_family")
    }
    canonical_sectors = {
        canonical_id: {
            sector
            for (current_canonical_id, sector, _axis) in grouped_assignments
            if current_canonical_id == canonical_id
        }
        for canonical_id in canonicals_by_id
    }

    demands: List[DerivedCompetenceDemand] = []
    for (canonical_id, sector, axis_group), components in sorted(
        grouped_assignments.items()
    ):
        canonical = canonicals_by_id[canonical_id]
        component_assignments = [component[0] for component in components]
        decision_ids = sorted(
            {
                _lineage_row_id(assignment, "validation_decision_id")
                for assignment in component_assignments
                if _lineage_row_id(assignment, "validation_decision_id")
            }
        )
        if len(decision_ids) != 1:
            raise DerivedAnalysisError(
                "accepted canonical lineage assignments must resolve to exactly one validation decision"
            )
        lineage_reviewed_decision: Mapping[str, Any] | None = decisions_by_id.get(
            decision_ids[0]
        )
        if lineage_reviewed_decision is None:
            raise DerivedAnalysisError(
                "accepted canonical lineage assignment is missing its reviewed decision"
            )
        context_signals = [
            signal
            for _assignment, selected_signals in components
            for signal in selected_signals
        ]
        evidence_ids = sorted(
            {
                evidence_id
                for assignment in component_assignments
                for evidence_id in _split_list(assignment.get("evidence_ids"))
            }
        )
        evidence = [evidence_by_id[evidence_id] for evidence_id in evidence_ids]
        dois = sorted(
            {
                _lineage_row_id(row, "canonical_doi")
                for row in evidence
                if _lineage_row_id(row, "canonical_doi")
            }
        )
        snapshot_metrics = _accepted_lineage_snapshot_metrics(
            evidence,
            _lineage_row_id(lineage_reviewed_decision, "decision_at_utc"),
        )
        providers = snapshot_metrics["providers"]
        query_families = sorted(
            {
                _lineage_row_id(signal, "query_family")
                for signal in context_signals
                if _lineage_row_id(signal, "query_family")
            }
        )
        confidences = [
            _safe_float(signal.get("confidence_score", 0.0))
            for signal in context_signals
        ]
        confidence_mean = sum(confidences) / max(1, len(confidences))
        first_run = snapshot_metrics["first_run"]
        latest_run = snapshot_metrics["latest_run"]
        first_at = snapshot_metrics["first_at"]
        latest_at = snapshot_metrics["latest_at"]
        provider_diversity = _diversity(len(providers), len(all_providers) or 1)
        query_diversity = _diversity(
            len(query_families), len(all_query_families) or 1
        )
        recency = _recency_score(latest_at, analysis_timestamp_utc)
        normalized_doi_count = min(1.0, len(dois) / 10.0)
        cross_sector = min(
            1.0, len(canonical_sectors[canonical_id]) / 12.0
        )
        score = round(
            0.30 * normalized_doi_count
            + 0.20 * provider_diversity
            + 0.20 * recency
            + 0.15 * query_diversity
            + 0.15 * confidence_mean,
            6,
        )
        status = _classify_demand_status(
            score=score,
            evidence_count=len(evidence),
            provider_count=len(providers),
            confidences=confidences,
        )
        # A reviewed accepted decision resolves the automatic-review gate, but
        # it does not erase evidence-surface limitations or score diagnostics.
        if status in {"review_required", "duplicate_artifact"}:
            status = "low_demand"
        warnings = sorted(
            {
                warning
                for signal in context_signals
                for warning in _split_list(signal.get("validity_warning", ""))
            }
            | {
                warning
                for row in evidence
                for warning in _split_list(row.get("validity_warning", ""))
            }
        )
        demand_id = _make_id("cd", canonical_id, sector, axis_group)
        demands.append(
            DerivedCompetenceDemand(
                competence_demand_id=demand_id,
                competence_label=_normalized_lineage_label(
                    canonical.get("preferred_label")
                ),
                competence_definition=_lineage_row_id(
                    canonical, "canonical_definition"
                ),
                view_kind=ACCEPTED_CANONICAL_LINEAGE_VIEW_KIND,
                scientific_status=VALIDATED_CANONICAL_DEMAND_SCIENTIFIC_STATUS,
                canonical_competence_id=canonical_id,
                validation_decision_ids="|".join(
                    decision_ids
                ),
                source_candidate_ids="|".join(
                    sorted(
                        {
                            _lineage_row_id(assignment, "source_candidate_id")
                            for assignment in component_assignments
                        }
                    )
                ),
                assignment_ids="|".join(
                    sorted(
                        {
                            _lineage_row_id(assignment, "assignment_id")
                            for assignment in component_assignments
                        }
                    )
                ),
                sector=sector,
                axis_group=axis_group,
                axis_code=_axis_group_to_code(axis_group),
                eqf_relevance=_infer_eqf_relevance(
                    _normalized_lineage_label(canonical.get("preferred_label")),
                    context_signals,
                ),
                demand_strength_score=score,
                evidence_record_count=len(evidence),
                unique_doi_count=len(dois),
                record_occurrence_count=snapshot_metrics["occurrence_count"],
                provider_count=len(providers),
                providers_seen="|".join(providers),
                provider_diversity_score=round(provider_diversity, 6),
                query_count=len(
                    {
                        _lineage_row_id(signal, "query_id")
                        for signal in context_signals
                        if _lineage_row_id(signal, "query_id")
                    }
                ),
                query_families_seen="|".join(query_families),
                query_diversity_score=round(query_diversity, 6),
                temporal_recency_score=round(recency, 6),
                cross_sector_recurrence_score=round(cross_sector, 6),
                semantic_confidence_mean=round(confidence_mean, 6),
                first_seen_run_id=first_run,
                latest_seen_run_id=latest_run,
                first_seen_at_utc=first_at,
                latest_seen_at_utc=latest_at,
                status=status,
                manual_review_status="manually_reviewed",
                validity_warning="|".join(warnings),
                evidence_ids="|".join(evidence_ids),
                signal_types="|".join(
                    sorted(
                        {
                            _lineage_row_id(signal, "signal_type")
                            for signal in context_signals
                            if _lineage_row_id(signal, "signal_type")
                        }
                    )
                ),
            )
        )
    return demands


def _build_qmbd_cross_tables(
    demands: Sequence[DerivedCompetenceDemand],
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    table: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for d in demands:
        key = (d.sector, d.axis_group)
        cell = table.setdefault(key, {"count": 0, "score_sum": 0.0, "mean_score": 0.0})
        cell["count"] += 1
        cell["score_sum"] += d.demand_strength_score
    for cell in table.values():
        cell["mean_score"] = cell["score_sum"] / max(1, cell["count"])
    return table


def _kv(nested: Dict[Tuple[str, str], Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for (a, b), v in nested.items():
        out.setdefault(a, {})[b] = v
    return out


def _build_sector_gap_matrices(
    demands: Sequence[DerivedCompetenceDemand],
    growth_evidence: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    axes = ["MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION"]
    sectors = sorted({d.sector for d in demands}) or ["_unassigned"]
    matrix: Dict[str, Dict[str, int]] = {s: {a: 0 for a in axes} for s in sectors}
    for d in demands:
        if d.sector in matrix and d.axis_group in matrix[d.sector]:
            matrix[d.sector][d.axis_group] += 1
    return {
        "axes": axes,
        "sectors": sectors,
        "demand_row_matrix": matrix,
        "growth_eligible_evidence_count": len(list(growth_evidence)),
    }


def _build_multivariate_induction(
    demands: Sequence[DerivedCompetenceDemand],
    growth_evidence: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    # Frequency tables, cross-tab, standardized residuals, Jaccard.
    axis_counts: Dict[str, int] = {}
    sector_counts: Dict[str, int] = {}
    for d in demands:
        axis_counts[d.axis_group] = axis_counts.get(d.axis_group, 0) + 1
        sector_counts[d.sector] = sector_counts.get(d.sector, 0) + 1
    total = sum(axis_counts.values()) or 1
    # sector × axis contingency
    contingency: Dict[str, Dict[str, int]] = {}
    for d in demands:
        contingency.setdefault(d.sector, {})[d.axis_group] = (
            contingency.setdefault(d.sector, {}).get(d.axis_group, 0) + 1
        )
    residuals: Dict[str, Dict[str, float]] = {}
    for sector, row in contingency.items():
        row_total = sum(row.values()) or 1
        for axis, obs in row.items():
            col_total = axis_counts.get(axis, 0) or 1
            expected = row_total * col_total / total
            if expected <= 0:
                std_res = 0.0
            else:
                std_res = (obs - expected) / math.sqrt(expected)
            residuals.setdefault(sector, {})[axis] = round(std_res, 6)
    # Jaccard between provider sets across sectors (upper triangle)
    provider_sets: Dict[str, set] = {}
    for d in demands:
        provider_sets.setdefault(d.sector, set()).update(_split_list(d.providers_seen))
    sec_names = sorted(provider_sets.keys())
    jaccard: List[Dict[str, Any]] = []
    for i, a in enumerate(sec_names):
        for b in sec_names[i + 1:]:
            inter = provider_sets[a] & provider_sets[b]
            union = provider_sets[a] | provider_sets[b]
            j = len(inter) / len(union) if union else 0.0
            jaccard.append({"sector_a": a, "sector_b": b, "jaccard": round(j, 6)})
    # Advanced methods (CA, PCA, K-means) explicitly skipped — no scipy/sklearn.
    method_status = {
        "chi_square": {
            "status": "computed",
            "note": "Computed via numpy fallback; see standardized residuals.",
        },
        "cramers_v": {
            "status": "computed_scalar",
            "note": "Computed as sqrt(chi2 / (n * (min(r,c) - 1))) with numpy.",
        },
        "correspondence_analysis": {
            "status": "skipped",
            "reason": "scipy/prince not installed as required dependency.",
        },
        "pca": {
            "status": "skipped",
            "reason": "scikit-learn not installed as required dependency.",
        },
        "kmeans": {
            "status": "skipped",
            "reason": "scikit-learn not installed; deterministic taxonomic induction used instead.",
        },
        "hierarchical_clustering": {
            "status": "skipped",
            "reason": "scipy not installed as required dependency.",
        },
    }
    chi2 = 0.0
    for sector, row in contingency.items():
        row_total = sum(row.values()) or 1
        for axis in ["MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION"]:
            obs = row.get(axis, 0)
            col_total = axis_counts.get(axis, 0) or 1
            expected = row_total * col_total / total
            if expected > 0:
                chi2 += (obs - expected) ** 2 / expected
    r = len(contingency)
    c = 4
    denom = max(1, total * (min(r, c) - 1)) if min(r, c) > 1 else 1
    cramers_v = math.sqrt(chi2 / denom) if denom > 0 else 0.0
    return {
        "frequency_axis_counts": axis_counts,
        "frequency_sector_counts": sector_counts,
        "contingency_sector_axis": contingency,
        "standardized_residuals": residuals,
        "chi_square_statistic": round(chi2, 6),
        "cramers_v": round(cramers_v, 6),
        "jaccard_provider_overlap": jaccard,
        "method_status": method_status,
    }


def _induce_taxonomic_clusters(
    signals: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for label, axis, codes, keywords in TAXONOMIC_CATEGORIES:
        matched_signals: List[Mapping[str, Any]] = []
        for s in signals:
            haystack = " ".join([
                str(s.get("competence_label", "")).lower(),
                str(s.get("competence_description", "")).lower(),
                str(s.get("demand_phrase", "")).lower(),
            ])
            if any(k in haystack for k in keywords):
                matched_signals.append(s)
        matched_evidence = {str(s.get("evidence_id", "")) for s in matched_signals}
        matched_evidence.discard("")
        primary_axis_code = codes[0] if codes else _axis_group_to_code(axis)
        secondary_axis_codes = list(codes[1:])
        secondary_axes = [
            _axis_code_to_group(code)
            for code in secondary_axis_codes
            if _axis_code_to_group(code) != "UNASSIGNED"
        ]
        axis_groups = [axis, *secondary_axes]
        hypothesis_ids = sorted(
            {
                hypothesis_id
                for axis_group in axis_groups
                for hypothesis_id in _hypothesis_ids_for_axis(axis_group)
            }
        )
        bridge_score = (
            round(len(secondary_axes) / 3.0, 6) if secondary_axes else 0.0
        )
        out.append({
            "category_label": label,
            "primary_axis": axis,
            "primary_axis_code": primary_axis_code,
            "secondary_axes": "|".join(secondary_axes),
            "secondary_axis_codes": "|".join(secondary_axis_codes),
            "axis_bridge_score": bridge_score,
            "matched_hypothesis_ids": "|".join(hypothesis_ids),
            "matched_signal_count": len(matched_signals),
            "matched_evidence_count": len(matched_evidence),
        })
    out.sort(key=lambda t: t["category_label"])
    return out


def _hypothesis_ids_for_axis(axis_group: str) -> Tuple[str, ...]:
    if axis_group == "MARITIME":
        return ("H1",)
    if axis_group == "HYDRONIZATION":
        return ("H2",)
    if axis_group == "MARINE":
        return ("H3",)
    if axis_group == "OCEANIC":
        return ("H1", "H3")
    return ()


def _matched_hypothesis_ids(
    evidence_ids: str, fragments: Optional[Sequence[Mapping[str, Any]]]
) -> Tuple[str, ...]:
    fragment_rows = list(fragments or [])
    if not fragment_rows:
        return ()
    evidence_id_set = set(_split_list(evidence_ids))
    if not evidence_id_set:
        return ()
    matched: Set[str] = set()
    for row in fragment_rows:
        row_evidence_id = str(row.get("evidence_id", "")).strip()
        if not row_evidence_id or row_evidence_id not in evidence_id_set:
            continue
        hypothesis_id = str(row.get("hypothesis_id", "")).strip()
        if hypothesis_id:
            matched.add(hypothesis_id)
            continue
        for token in _split_list(str(row.get("hypothesis_ids", ""))):
            matched.add(token)
    return tuple(sorted(matched))


def _compute_global_indices(
    demands: Sequence[DerivedCompetenceDemand],
    evidence_records: Sequence[Mapping[str, Any]],
    *,
    validated_credential_supply_provided: bool = False,
) -> Dict[str, Any]:
    # Blue Capability Gap Index — fraction of demands not meeting high/medium demand.
    if demands:
        gap = sum(1 for d in demands if d.status in ("review_required", "low_demand")) / len(demands)
    else:
        gap = 0.0
    # QMBD Skewness — Gini-like inequality of axis distribution.
    # Initialize all four canonical axes to zero so that missing axes
    # correctly contribute to the skewness calculation.
    canonical_axes = ("MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION")
    axis_counts: Dict[str, int] = {a: 0 for a in canonical_axes}
    for d in demands:
        if d.axis_group in axis_counts:
            axis_counts[d.axis_group] += 1
    total = sum(axis_counts.values())
    if total > 0:
        expected = total / len(canonical_axes)
        skew = sum(abs(c - expected) for c in axis_counts.values()) / (2 * total)
    else:
        skew = 0.0
    # Micro-credential coverage — this index is not computable without an
    # independently validated credential supply map, because _infer_eqf_relevance
    # always assigns at least a default EQF level so EQF assignment alone does
    # not constitute validated coverage.
    coverage: Any = None
    coverage_note = "not_computable_no_validated_supply_map"
    if validated_credential_supply_provided:
        non_review = [d for d in demands if d.status != "review_required"]
        covered = sum(1 for d in non_review if d.eqf_relevance)
        coverage = round(covered / len(non_review), 6) if non_review else 0.0
        coverage_note = ""
    # Provider diversity — mean of per-demand provider_diversity_score.
    prov_div = sum(d.provider_diversity_score for d in demands) / len(demands) if demands else 0.0
    # Query diversity — mean of per-demand query_diversity_score.
    q_div = sum(d.query_diversity_score for d in demands) / len(demands) if demands else 0.0
    # Temporal recency — mean of per-demand temporal_recency_score.
    recency = sum(d.temporal_recency_score for d in demands) / len(demands) if demands else 0.0
    # Cross-sector recurrence — mean of per-demand score.
    cross = sum(d.cross_sector_recurrence_score for d in demands) / len(demands) if demands else 0.0
    return {
        "blue_capability_gap_index": round(gap, 6),
        "qmbd_skewness_index": round(skew, 6),
        "micro_credential_coverage_index": coverage,
        "micro_credential_coverage_note": coverage_note,
        "provider_diversity_index": round(prov_div, 6),
        "query_diversity_index": round(q_div, 6),
        "temporal_recency_index": round(recency, 6),
        "cross_sector_recurrence_index": round(cross, 6),
    }


def _evidence_dois_for_demand(
    d: DerivedCompetenceDemand,
    evidence_records: Sequence[Mapping[str, Any]],
) -> set:
    demand_evidence_ids = set(_split_list(d.evidence_ids))
    return {
        str(e.get("canonical_doi", "")).strip()
        for e in evidence_records
        if e.get("canonical_doi")
        and (
            str(e.get("evidence_id", "")) in demand_evidence_ids
            if demand_evidence_ids
            else d.sector in _split_list(e.get("sector_candidates", ""))
        )
    }


def _learning_outcome_statement(
    demand: DerivedCompetenceDemand, sector: str, eqf_level: int
) -> str:
    """Return an evidence-linked, EQF-aware learning-outcome statement."""
    if eqf_level <= 4:
        verb = "Operate and monitor"
        dimension = "skills"
    elif eqf_level == 5:
        verb = "Apply and coordinate"
        dimension = "skills and social competence"
    elif eqf_level == 6:
        verb = "Analyse and design"
        dimension = "knowledge and skills"
    else:
        verb = "Evaluate and justify"
        dimension = "advanced knowledge and social competence"
    evidence_ref = demand.evidence_ids.strip() or "unavailable"
    return (
        f"{verb} {demand.competence_label} for {sector} contexts at EQF "
        f"{eqf_level}, demonstrating {dimension}; evidence={evidence_ref}; "
        f"demand={demand.competence_demand_id}; "
        f"confidence={demand.semantic_confidence_mean:.2f}"
    )


def _first_evidence_id_for_demand(
    d: DerivedCompetenceDemand,
    evidence_records: Sequence[Mapping[str, Any]],
) -> str:
    linked = sorted(set(_split_list(d.evidence_ids)))
    if linked:
        return linked[0]
    # Do not fabricate provenance by attaching an arbitrary record from the
    # same sector. Serialize explicit unavailability; the demand remains
    # review_required until genuine provenance is established.
    return "unavailable"


def _dominant_signal_type_for_demand(
    d: DerivedCompetenceDemand,
    signals: Sequence[Mapping[str, Any]],
) -> str:
    signal_types = _split_list(d.signal_types)
    if not signal_types and signals:
        signal_types = [
            str(signal.get("signal_type", "")).strip()
            for signal in signals
            if str(signal.get("signal_type", "")).strip()
        ]
    if not signal_types:
        return "implicit_competence_demand"
    counts = {
        signal_type: signal_types.count(signal_type)
        for signal_type in set(signal_types)
    }
    return sorted(counts, key=lambda item: (-counts[item], item))[0]


def _coverage_status_for_credential(
    *,
    demands: Sequence[DerivedCompetenceDemand],
    eqf_level: int,
    validated_credential_supply: Optional[Mapping[str, Sequence[int]]],
) -> str:
    if validated_credential_supply is None:
        if any(demand.status == "review_required" for demand in demands):
            return "review_required"
        return "candidate_translation"
    validated_demands = [
        demand
        for demand in demands
        if _accepted_canonical_lineage_required(demand)
    ]
    if any(demand.status == "review_required" for demand in validated_demands):
        return "review_required"
    if not validated_demands:
        return "candidate_translation"

    covered_count = 0
    for demand in validated_demands:
        levels = {
            int(level)
            for level in validated_credential_supply.get(
                demand.competence_demand_id, []
            )
            if str(level).strip().isdigit()
        }
        if eqf_level in levels:
            covered_count += 1
    if covered_count == len(validated_demands):
        return "validated_covered"
    if covered_count > 0:
        return "validated_partial"
    return "validated_uncovered"


def _test_hypotheses(
    demands: Sequence[DerivedCompetenceDemand],
    gap_rows: Sequence[SectorAxisGapRow],
    credentials: Sequence[CredentialTranslation],
    *,
    hypothesis_fragments: Optional[Sequence[Mapping[str, Any]]] = None,
    validated_credential_supply: Optional[Mapping[str, Sequence[int]]] = None,
) -> Dict[str, Any]:
    del gap_rows  # retained in the signature for stable downstream integrations
    fragment_rows = list(hypothesis_fragments or [])
    h1_fragments = [
        row for row in fragment_rows
        if str(row.get("hypothesis_id", "")).strip() == "H1"
    ]
    h2_fragments = [
        row for row in fragment_rows
        if str(row.get("hypothesis_id", "")).strip() == "H2"
    ]
    h3_fragments = [
        row for row in fragment_rows
        if str(row.get("hypothesis_id", "")).strip() == "H3"
    ]

    # H1 — Maritimisation Shift is directional: only MARITIME > OCEANIC
    # supports the declared hypothesis.
    maritime_scores = [
        demand.demand_strength_score
        for demand in demands
        if (
            demand.axis_group == "MARITIME"
            and demand.view_kind == LEGACY_DERIVED_DEMAND_VIEW_KIND
            and demand.scientific_status
            == LEGACY_DERIVED_DEMAND_SCIENTIFIC_STATUS
        )
    ]
    oceanic_scores = [
        demand.demand_strength_score
        for demand in demands
        if (
            demand.axis_group == "OCEANIC"
            and demand.view_kind == LEGACY_DERIVED_DEMAND_VIEW_KIND
            and demand.scientific_status
            == LEGACY_DERIVED_DEMAND_SCIENTIFIC_STATUS
        )
    ]
    n_m, n_o = len(maritime_scores), len(oceanic_scores)
    mean_m = sum(maritime_scores) / n_m if n_m else 0.0
    mean_o = sum(oceanic_scores) / n_o if n_o else 0.0
    difference = mean_m - mean_o
    if n_m > 1 and n_o > 1:
        var_m = sum((value - mean_m) ** 2 for value in maritime_scores) / (n_m - 1)
        var_o = sum((value - mean_o) ** 2 for value in oceanic_scores) / (n_o - 1)
        pooled_var = (
            ((n_m - 1) * var_m) + ((n_o - 1) * var_o)
        ) / (n_m + n_o - 2)
        pooled_sd = math.sqrt(pooled_var) if pooled_var > 0 else 0.0
    else:
        pooled_sd = 0.0
    # When pooled_sd is zero, Cohen's d is undefined — report not_computable
    # rather than converting to 0.0 which would misreport a structural
    # statistical failure as a negative scientific result.
    if pooled_sd > 0:
        cohens_d: Any = round(difference / pooled_sd, 6)
    else:
        cohens_d = None
    h1_validity_extra = ""
    if n_m == 0 or n_o == 0:
        h1_interpretation = "not_computable"
    elif cohens_d is None:
        h1_interpretation = "not_computable"
        h1_validity_extra = "zero_pooled_sd"
    elif cohens_d >= 0.5:
        h1_interpretation = "supported_maritime_dominance"
    elif cohens_d >= 0.2:
        h1_interpretation = "partially_supported_maritime"
    else:
        h1_interpretation = "not_supported"
    h1_warnings: List[str] = []
    if min(n_m, n_o) < 5:
        h1_warnings.append("small_cell_stability")
    if h1_validity_extra:
        h1_warnings.append(h1_validity_extra)
    h1 = {
        "hypothesis_id": "H1",
        "hypothesis_label": "Maritimisation Shift",
        "test_used": "Cohen's d (signed) on demand_strength_score by axis group",
        "direction_note": (
            "positive cohens_d = MARITIME > OCEANIC; "
            "negative cohens_d does not support H1"
        ),
        "sample_size_maritime": n_m,
        "sample_size_oceanic": n_o,
        "matched_fragment_count": len(h1_fragments),
        "mean_maritime": round(mean_m, 6),
        "mean_oceanic": round(mean_o, 6),
        "effect_size_cohens_d": cohens_d,
        "interpretation": h1_interpretation,
        "validity_warning": "|".join(h1_warnings) if h1_warnings else "",
    }

    # H2 — Hydronization Lag uses an independently validated, demand-level
    # credential supply map. Generated candidate credentials are informational.
    hydro_demands = [
        demand for demand in demands if demand.axis_group == "HYDRONIZATION"
    ]
    hydro_ids = {demand.competence_demand_id for demand in hydro_demands}
    # Legacy category aggregates remain useful compatibility projections, but
    # they are not canonical competences and must never enter the denominator
    # for a validation-backed hypothesis result.  Keep the all-demand set for
    # the informational candidate-coverage count, while every field prefixed
    # ``validated_`` is derived exclusively from accepted canonical lineage.
    validated_hydro_ids = {
        demand.competence_demand_id
        for demand in hydro_demands
        if _accepted_canonical_lineage_required(demand)
        and demand.status not in ("review_required", "duplicate_artifact")
    }
    candidate_covered_ids = {
        demand_id.strip()
        for credential in credentials
        if credential.axis_group == "HYDRONIZATION"
        and credential.eqf_level in (6, 7)
        for demand_id in credential.competence_demand_ids.split("|")
        if demand_id.strip()
    }
    candidate_covered_count = len(hydro_ids & candidate_covered_ids)

    supply_map_provided = validated_credential_supply is not None
    validated_covered_ids: set[str] = set()
    if validated_credential_supply is not None:
        for demand_id, raw_levels in validated_credential_supply.items():
            if isinstance(raw_levels, (str, int)):
                level_values: Sequence[Any] = [raw_levels]
            else:
                level_values = raw_levels
            levels = {
                int(level)
                for level in level_values
                if str(level).strip().isdigit()
            }
            if levels & {6, 7}:
                validated_covered_ids.add(str(demand_id))
    validated_covered_count = len(validated_hydro_ids & validated_covered_ids)
    missing_ratio: Optional[float]
    if supply_map_provided and validated_hydro_ids:
        validated_missing_count = (
            len(validated_hydro_ids) - validated_covered_count
        )
        ratio = validated_missing_count / len(validated_hydro_ids)
        missing_ratio = ratio
        if ratio >= 0.5:
            h2_interpretation = "supported"
        elif ratio >= 0.25:
            h2_interpretation = "partially_supported"
        else:
            h2_interpretation = "not_supported"
    else:
        validated_missing_count = len(validated_hydro_ids)
        missing_ratio = None
        h2_interpretation = "not_computable"

    h2_warnings: List[str] = []
    if not supply_map_provided:
        h2_warnings.append("no_validated_supply_map")
    if len(validated_hydro_ids) < 5:
        h2_warnings.append("small_cell_stability")
    h2 = {
        "hypothesis_id": "H2",
        "hypothesis_label": "Hydronization Lag",
        "unit_of_analysis": "competence_demand_id",
        "validated_supply_map_provided": supply_map_provided,
        "matched_fragment_count": len(h2_fragments),
        "hydronization_demand_count": len(hydro_ids),
        "validated_hydronization_demand_count": len(validated_hydro_ids),
        "validated_covered_demand_count": validated_covered_count,
        "validated_missing_demand_count": validated_missing_count,
        "candidate_covered_demand_count": candidate_covered_count,
        "association_metric_missing_ratio": (
            round(missing_ratio, 6) if missing_ratio is not None else None
        ),
        "effect_size": (
            round(missing_ratio, 6) if missing_ratio is not None else None
        ),
        "interpretation": h2_interpretation,
        "coverage_note": (
            "Validated coverage is computed only from the separately supplied "
            "demand-level EQF map; candidate_covered_demand_count reports "
            "generated candidate translations and is never validated supply."
        ),
        "validity_warning": "|".join(h2_warnings),
    }

    # H3 — MARINE vs OCEANIC Differential Coverage from matched fragments.
    marine_fragment_rows = [
        row for row in h3_fragments
        if str(row.get("axis_group", "")).strip() == "MARINE"
    ]
    oceanic_fragment_rows = [
        row for row in h3_fragments
        if str(row.get("axis_group", "")).strip() == "OCEANIC"
    ]
    marine_fragments = len(marine_fragment_rows)
    oceanic_fragments = len(oceanic_fragment_rows)
    total_fragments = marine_fragments + oceanic_fragments
    balance_score = (
        1.0 - abs(marine_fragments - oceanic_fragments) / total_fragments
        if total_fragments
        else 0.0
    )
    marine_sectors = sorted(
        {str(row.get("sector", "")).strip() for row in marine_fragment_rows if str(row.get("sector", "")).strip()}
    )
    oceanic_sectors = sorted(
        {str(row.get("sector", "")).strip() for row in oceanic_fragment_rows if str(row.get("sector", "")).strip()}
    )
    marine_evidence = {
        str(row.get("evidence_id", "")).strip()
        for row in marine_fragment_rows
        if str(row.get("evidence_id", "")).strip()
    }
    oceanic_evidence = {
        str(row.get("evidence_id", "")).strip()
        for row in oceanic_fragment_rows
        if str(row.get("evidence_id", "")).strip()
    }
    marine_signals = {
        str(row.get("signal_id", "")).strip()
        for row in marine_fragment_rows
        if str(row.get("signal_id", "")).strip()
    }
    oceanic_signals = {
        str(row.get("signal_id", "")).strip()
        for row in oceanic_fragment_rows
        if str(row.get("signal_id", "")).strip()
    }
    semantic_bridge_count = len((marine_evidence & oceanic_evidence) | (marine_signals & oceanic_signals))
    normalized_difference = (
        (marine_fragments - oceanic_fragments) / total_fragments
        if total_fragments
        else 0.0
    )
    if not marine_fragment_rows or not oceanic_fragment_rows:
        h3_interpretation = "not_computable"
    elif balance_score >= 0.8 and semantic_bridge_count > 0:
        h3_interpretation = "supported"
    elif balance_score >= 0.5 or semantic_bridge_count > 0:
        h3_interpretation = "partially_supported"
    else:
        h3_interpretation = "not_supported"
    h3_warnings: List[str] = []
    if min(len(marine_fragment_rows), len(oceanic_fragment_rows)) < 5:
        h3_warnings.append("small_cell_stability")
    if marine_fragment_rows and oceanic_fragment_rows and semantic_bridge_count == 0:
        h3_warnings.append("no_semantic_bridges")
    h3 = {
        "hypothesis_id": "H3",
        "hypothesis_label": "MARINE vs OCEANIC Differential Coverage",
        "test_used": (
            "normalized MARINE-OCEANIC matched-fragment difference, balance, "
            "sector coverage, and evidence/signal-level bridge overlap"
        ),
        "sample_size_marine": len(marine_fragment_rows),
        "sample_size_oceanic": len(oceanic_fragment_rows),
        "marine_fragment_count": marine_fragments,
        "oceanic_fragment_count": oceanic_fragments,
        "balance_score": round(balance_score, 6),
        "marine_sector_count": len(marine_sectors),
        "oceanic_sector_count": len(oceanic_sectors),
        "marine_sectors": marine_sectors,
        "oceanic_sectors": oceanic_sectors,
        "axis_distribution": {
            "MARINE": marine_fragments,
            "OCEANIC": oceanic_fragments,
        },
        "semantic_bridge_count": semantic_bridge_count,
        "matched_fragment_count": len(h3_fragments),
        "effect_size_normalized_difference": round(normalized_difference, 6),
        "interpretation": h3_interpretation,
        "validity_warning": "|".join(h3_warnings),
    }
    return {"H1": h1, "H2": h2, "H3": h3}
