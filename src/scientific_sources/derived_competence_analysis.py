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
        for rel in expected:
            candidate = root / rel
            # Directory pattern with trailing slash: presence via any child
            if rel.endswith("/"):
                if candidate.exists() and any(candidate.iterdir()):
                    present.append(rel)
                else:
                    missing.append(rel)
            else:
                (present if candidate.exists() else missing).append(rel)
        schema_valid = not missing
        return {
            "layer_name": name,
            "expected_files": list(expected),
            "files_present": sorted(present),
            "files_missing": sorted(missing),
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
) -> Layer4Result:
    """Build the Layer 4 derived competence-demand database + statistics."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stats_dir = out.parent / LAYER4_STATS_DIR
    stats_dir.mkdir(parents=True, exist_ok=True)

    evidence_by_id: Dict[str, Mapping[str, Any]] = {
        str(r.get("evidence_id", "")): r for r in evidence_records
    }
    growth_evidence = [
        r for r in evidence_records
        if str(r.get("record_novelty_status", "")) in GROWTH_ELIGIBLE_STATUSES
    ]

    # Group signals by (competence_label, sector, axis_group)
    groups: Dict[Tuple[str, str, str], List[Mapping[str, Any]]] = {}
    for sig in competence_signals:
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
        evs = [e for e in evs if e]
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
        recency = _recency_score(latest_at)
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
        review = "review_required" if status == "review_required" else "auto_accepted"
        warnings = sorted({
            w for s in signals for w in _split_list(s.get("validity_warning", ""))
        })
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
        ))

    demands.sort(key=lambda d: (d.sector, d.axis_group, d.competence_label))

    # QMBD cross-tables (frequency of demand rows by sector × axis).
    qmbd_cross = _build_qmbd_cross_tables(demands)
    sector_gap = _build_sector_gap_matrices(demands, growth_evidence)
    multivariate = _build_multivariate_induction(demands, growth_evidence)
    taxonomy = _induce_taxonomic_clusters(competence_signals)
    indices = _compute_global_indices(demands, evidence_records)

    files: List[Path] = []
    files.append(_write_derived_demands_csv(out / DERIVED_DEMANDS_CSV, demands))
    files.append(_write_derived_demands_jsonl(out / DERIVED_DEMANDS_JSONL, demands))
    files.append(_write_csv_rows(
        stats_dir / QMBD_CROSS_TABLES_CSV,
        header=("sector", "axis_group", "demand_row_count", "mean_score"),
        rows=[(k[0], k[1], v["count"], round(v["mean_score"], 6))
              for k, v in sorted(qmbd_cross.items())],
    ))
    files.append(_write_json(stats_dir / SECTOR_GAP_MATRICES_JSON, sector_gap))
    files.append(_write_json(stats_dir / MULTIVARIATE_RESULTS_JSON, multivariate))
    files.append(_write_csv_rows(
        stats_dir / TAXONOMIC_CLUSTERS_CSV,
        header=("category_label", "axis_group", "axis_code", "matched_signal_count",
                "matched_evidence_count"),
        rows=[(t["category_label"], t["axis_group"], t["axis_code"],
               t["matched_signal_count"], t["matched_evidence_count"])
              for t in taxonomy],
    ))
    manifest = {
        "schema_version": LAYER4_SCHEMA_VERSION,
        "built_at_utc": _utc_now_iso(),
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
        stats_dir=stats_dir,
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
    output_dir: Union[str, Path],
    current_run_id: str = "",
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
    for (sector, axis), demands in sorted(buckets.items()):
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
            coverage = "covered" if coverage_map.get((sector, axis), 0) >= len(ds) else "uncovered"
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
                    signal_type=_dominant_signal_type_for_demand(d, []),
                    confidence_score=d.semantic_confidence_mean,
                    validity_warning=d.validity_warning,
                ))

    credentials.sort(key=lambda c: (c.sector, c.axis_group, c.eqf_level, c.credential_id))
    outcomes.sort(key=lambda o: (o.sector, o.axis_group, o.eqf_level, o.outcome_id))

    hyp = _test_hypotheses(derived_demands, gap_rows, credentials)

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
        "built_at_utc": _utc_now_iso(),
        "current_run_id": current_run_id,
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
        ("coverage_status", "covered", "Existing credential coverage >= demand row count."),
        ("coverage_status", "uncovered", "Existing credential coverage < demand row count."),
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _recency_score(latest_at: str) -> float:
    if not latest_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(latest_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta_days = max(0.0, (now - dt).total_seconds() / 86400.0)
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
        out.append({
            "category_label": label,
            "axis_group": axis,
            "axis_code": ",".join(codes),
            "matched_signal_count": len(matched_signals),
            "matched_evidence_count": len(matched_evidence),
        })
    out.sort(key=lambda t: t["category_label"])
    return out


def _compute_global_indices(
    demands: Sequence[DerivedCompetenceDemand],
    evidence_records: Sequence[Mapping[str, Any]],
) -> Dict[str, float]:
    # Blue Capability Gap Index — fraction of demands not meeting high/medium demand.
    if demands:
        gap = sum(1 for d in demands if d.status in ("review_required", "low_demand")) / len(demands)
    else:
        gap = 0.0
    # QMBD Skewness — Gini-like inequality of axis distribution.
    axis_counts: Dict[str, int] = {}
    for d in demands:
        axis_counts[d.axis_group] = axis_counts.get(d.axis_group, 0) + 1
    total = sum(axis_counts.values())
    if total > 0 and len(axis_counts) > 1:
        expected = total / len(axis_counts)
        skew = sum(abs(c - expected) for c in axis_counts.values()) / (2 * total)
    else:
        skew = 0.0
    # Micro-credential coverage — share of demands with EQF level assigned.
    covered = sum(1 for d in demands if d.eqf_relevance)
    coverage = covered / len(demands) if demands else 0.0
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
        "micro_credential_coverage_index": round(coverage, 6),
        "provider_diversity_index": round(prov_div, 6),
        "query_diversity_index": round(q_div, 6),
        "temporal_recency_index": round(recency, 6),
        "cross_sector_recurrence_index": round(cross, 6),
    }


def _evidence_dois_for_demand(
    d: DerivedCompetenceDemand,
    evidence_records: Sequence[Mapping[str, Any]],
) -> set:
    return {
        str(e.get("canonical_doi", "")).strip()
        for e in evidence_records
        if e.get("canonical_doi") and d.sector in str(e.get("sector_candidates", ""))
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
    evidence_ref = "see_learning_outcomes_evidence_id"
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
    for e in evidence_records:
        if d.sector in str(e.get("sector_candidates", "")):
            return str(e.get("evidence_id", ""))
    return ""


def _dominant_signal_type_for_demand(
    d: DerivedCompetenceDemand,
    signals: Sequence[Mapping[str, Any]],
) -> str:
    # Fallback to a generic type when we don't have direct access to signals here.
    return "implicit_competence_demand"


def _test_hypotheses(
    demands: Sequence[DerivedCompetenceDemand],
    gap_rows: Sequence[SectorAxisGapRow],
    credentials: Sequence[CredentialTranslation],
) -> Dict[str, Any]:
    # H1 — Maritimisation Shift: separation of MARITIME vs OCEANIC sectors.
    maritime_scores = [d.demand_strength_score for d in demands if d.axis_group == "MARITIME"]
    oceanic_scores = [d.demand_strength_score for d in demands if d.axis_group == "OCEANIC"]
    n_m, n_o = len(maritime_scores), len(oceanic_scores)
    mean_m = sum(maritime_scores) / n_m if n_m else 0.0
    mean_o = sum(oceanic_scores) / n_o if n_o else 0.0
    diff = mean_m - mean_o
    if n_m > 1 and n_o > 1:
        var_m = sum((x - mean_m) ** 2 for x in maritime_scores) / (n_m - 1)
        var_o = sum((x - mean_o) ** 2 for x in oceanic_scores) / (n_o - 1)
        pooled_var = (((n_m - 1) * var_m) + ((n_o - 1) * var_o)) / (n_m + n_o - 2)
        sd = math.sqrt(pooled_var) if pooled_var > 0 else 0.0
    else:
        sd = 0.0
    cohens_d = (diff / sd) if sd > 0 else 0.0
    if n_m == 0 or n_o == 0:
        h1_interp = "not_computable"
    elif abs(cohens_d) >= 0.5:
        h1_interp = "supported"
    elif abs(cohens_d) >= 0.2:
        h1_interp = "partially_supported"
    else:
        h1_interp = "not_supported"
    h1 = {
        "hypothesis_id": "H1",
        "hypothesis_label": "Maritimisation Shift",
        "test_used": "Cohen's d on demand_strength_score by axis group",
        "sample_size_maritime": n_m,
        "sample_size_oceanic": n_o,
        "mean_maritime": round(mean_m, 6),
        "mean_oceanic": round(mean_o, 6),
        "effect_size_cohens_d": round(cohens_d, 6),
        "interpretation": h1_interp,
        "validity_warning": "small_cell_stability" if min(n_m, n_o) < 5 else "",
    }

    # H2 — Hydronization Lag: HYDRONIZATION signals + missing EQF 6/7 outcomes.
    hydro_demands = [d for d in demands if d.axis_group == "HYDRONIZATION"]
    hydro_signal_count = len(hydro_demands)
    hydro_creds_67 = [
        c for c in credentials
        if c.axis_group == "HYDRONIZATION" and c.eqf_level in (6, 7)
    ]
    missing_67 = hydro_signal_count - len(hydro_creds_67)
    if hydro_signal_count == 0:
        h2_interp = "not_computable"
        assoc = 0.0
    else:
        assoc = missing_67 / hydro_signal_count
        if assoc >= 0.5:
            h2_interp = "supported"
        elif assoc >= 0.25:
            h2_interp = "partially_supported"
        else:
            h2_interp = "not_supported"
    h2 = {
        "hypothesis_id": "H2",
        "hypothesis_label": "Hydronization Lag",
        "hydronization_signal_count": hydro_signal_count,
        "missing_eqf6_7_outcome_count": max(0, missing_67),
        "association_metric_missing_ratio": round(assoc, 6),
        "effect_size": round(assoc, 6),
        "interpretation": h2_interp,
        "validity_warning": "small_cell_stability" if hydro_signal_count < 5 else "",
    }
    return {"H1": h1, "H2": h2}
