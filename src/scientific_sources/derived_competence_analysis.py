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


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

LAYER4_SCHEMA_VERSION = "1.0.0"
LAYER5_SCHEMA_VERSION = "1.0.0"

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

LAYER4_STATS_DIR = "layer4_statistics"
QMBD_CROSS_TABLES_CSV = "qmbd_cross_tables.csv"
SECTOR_GAP_MATRICES_JSON = "sector_gap_matrices.json"
MULTIVARIATE_RESULTS_JSON = "multivariate_induction_results.json"
TAXONOMIC_CLUSTERS_CSV = "taxonomic_clusters.csv"

DERIVED_DEMAND_COLUMNS: Tuple[str, ...] = (
    "competence_demand_id",
    "competence_label",
    "competence_definition",
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

    demands.sort(key=lambda d: (d.sector, d.axis_group, d.competence_label))

    # QMBD cross-tables (frequency of demand rows by sector × axis).
    qmbd_cross = _build_qmbd_cross_tables(demands)
    sector_gap = _build_sector_gap_matrices(demands, growth_evidence)
    multivariate = _build_multivariate_induction(demands, growth_evidence)
    taxonomy_signals = [
        signal
        for signal in competence_signals
        if str(signal.get("evidence_id", "")) in growth_eligible_ids
    ]
    taxonomy = _induce_taxonomic_clusters(taxonomy_signals)
    indices = _compute_global_indices(demands, evidence_records)

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
        "derived_demand_count": len(demands),
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
    """Build the Layer 5 gap model, credential translation, and outcomes."""
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
        live_demand = len(demands)
        validated = sum(1 for d in demands if d.status not in ("review_required", "duplicate_artifact"))
        covered = int(coverage_map.get((sector, axis), 0))
        baseline_val = int(baseline_map.get(sector, 0))
        uncovered = max(0, validated - covered)
        gap_ratio = round(uncovered / max(1, validated), 6)
        avg_conf = sum(d.semantic_confidence_mean for d in demands) / max(1, len(demands))
        warns: List[str] = []
        if baseline_val == 0 and live_demand == 0:
            warns.append("empty_cell")
        if baseline_val > 0 and live_demand == 0:
            warns.append("static_baseline_only")
        if live_demand > 0 and all(d.status == "review_required" for d in demands):
            warns.append("all_review_required")
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
        by_eqf: Dict[int, List[DerivedCompetenceDemand]] = {}
        for d in demands:
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
        ("gap_ratio", "uncovered_demand_count / max(1, validated_demand_count)."),
        ("eqf_level", "European Qualifications Framework level (4-7)."),
        ("ects", "European Credit Transfer and Accumulation System points."),
    ]
    val_labels = [
        ("status", "high_demand", "Score >= 0.70 with at least 2 evidence records."),
        ("status", "medium_demand", "Score >= 0.40 with at least 1 evidence record."),
        ("status", "low_demand", "Score < 0.40 with sufficient evidence."),
        ("status", "review_required", "Insufficient evidence, ambiguous provenance, or thin metadata."),
        ("status", "duplicate_artifact", "Row exists only because of Jaccard duplicate merging."),
        ("status", "provider_bias_warning", "All evidence sourced from a single provider."),
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
    ]
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

    Only files that are direct children of (or nested under) ``output_dir``
    are included; stats-dir files that live in a sibling directory are
    silently skipped so the checksum file remains self-contained.

    Returns the path to the written checksum file.
    """
    out = Path(output_dir)
    entries: List[Tuple[str, str]] = []
    for file_path in files:
        if not file_path.exists():
            continue
        try:
            rel = str(file_path.relative_to(out)).replace("\\", "/")
        except ValueError:
            # File is outside output_dir (e.g. stats_dir); skip it.
            continue
        entries.append((rel, _sha256_file(file_path)))
    entries.sort(key=lambda kv: kv[0])
    checksum_path = out / LAYER45_CHECKSUMS_FILENAME
    with checksum_path.open("w", encoding="utf-8", newline="\n") as fh:
        for rel, digest in entries:
            fh.write(f"{digest}  {rel}\n")
    return checksum_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
        str(s.get("competence_description", "")).lower() +
        " " + str(s.get("demand_phrase", "")).lower()
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
    if any(demand.status == "review_required" for demand in demands):
        return "review_required"
    if validated_credential_supply is None:
        return "candidate_translation"

    covered_count = 0
    for demand in demands:
        levels = {
            int(level)
            for level in validated_credential_supply.get(
                demand.competence_demand_id, []
            )
            if str(level).strip().isdigit()
        }
        if eqf_level in levels:
            covered_count += 1
    if covered_count == len(demands):
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
        if demand.axis_group == "MARITIME"
    ]
    oceanic_scores = [
        demand.demand_strength_score
        for demand in demands
        if demand.axis_group == "OCEANIC"
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
    validated_covered_count = len(hydro_ids & validated_covered_ids)
    missing_ratio: Optional[float]
    if supply_map_provided and hydro_ids:
        validated_missing_count = len(hydro_ids) - validated_covered_count
        ratio = validated_missing_count / len(hydro_ids)
        missing_ratio = ratio
        if ratio >= 0.5:
            h2_interpretation = "supported"
        elif ratio >= 0.25:
            h2_interpretation = "partially_supported"
        else:
            h2_interpretation = "not_supported"
    else:
        validated_missing_count = len(hydro_ids)
        missing_ratio = None
        h2_interpretation = "not_computable"

    h2_warnings: List[str] = []
    if not supply_map_provided:
        h2_warnings.append("no_validated_supply_map")
    if len(hydro_ids) < 5:
        h2_warnings.append("small_cell_stability")
    h2 = {
        "hypothesis_id": "H2",
        "hypothesis_label": "Hydronization Lag",
        "unit_of_analysis": "competence_demand_id",
        "validated_supply_map_provided": supply_map_provided,
        "matched_fragment_count": len(h2_fragments),
        "hydronization_demand_count": len(hydro_ids),
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
