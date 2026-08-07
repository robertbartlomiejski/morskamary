"""Cumulative Scientific Database — PR-190 Layers 2 & 3 plus schema-v2 foundations.

This module builds the *live cumulative scientific database* on top of the
Layer 0 (``config/live_query_protocol.yml``) and Layer 1
(``outputs/live_runs/<run_id>/``) artefacts. It is intentionally additive:

* **Layer 2 — Cumulative evidence records.** All live records ever observed
  across the run archive and the current run are deduplicated in priority
  order (DOI → normalized title → provider source_id), assigned a stable
  ``evidence_id``, and classified with a ``record_novelty_status`` relative
  to the previous run.

* **Layer 3 — Semantic competence-demand signals.** For every evidence row
  associated with the current run we apply a deterministic, rule-based
  scanner over the available metadata (title, subject_terms, abstract,
  full_text). When a competence-demand indicator is present we emit:

  - a versioned ``evidence_fragment`` with exact span offsets/text;
  - a versioned ``semantic_signal`` with explicit lineage to that fragment;
  - a versioned ``competence_candidate`` that retains fragment + provenance
    references and is always review-gated;
  - compatibility projections for the legacy ``competence_demand_signals``
    and downstream aggregate demand view.

  Canonical competences, sector assignments, and validation decisions are
  exported as separate versioned tables and remain empty unless explicit
  validation decisions are supplied. No automatic promotion from candidate to
  canonical competence is allowed.

The public entry point is :func:`build_cumulative_scientific_database`, which
returns a :class:`CumulativeDatabaseResult` and writes the following files
under ``<output_dir>/``::

    cumulative_database_manifest.json
    _checksums.sha256
    evidence_records.csv
    evidence_records.jsonl
    competence_demand_signals.csv
    competence_demand_signals.jsonl
    run_novelty_metrics.csv
    run_novelty_metrics.json

Determinism guarantees:

* All JSON outputs are written with ``sort_keys=True`` and a trailing newline.
* All CSV outputs use ``lineterminator="\\n"`` and rows are pre-sorted by a
  stable key.
* SHA-256 checksums are computed by chunked reads.
* Two invocations against the same inputs produce byte-identical outputs.

This module deliberately does **not** modify or replace the Layer 0 or
Layer 1 code paths — it only consumes their outputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
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
from urllib.parse import unquote as _url_unquote

from src.core import BlueDynamicsAxis
from src.scientific_sources.live_query_protocol import (
    LiveQuery,
    LiveQueryProtocol,
    load_live_query_protocol,
)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

DATABASE_SCHEMA_VERSION = "2.0.0"
"""Schema version stamped into every manifest produced by this module."""

CLASSIFIER_VERSION = "cumulative-db-semantic-v3"
"""Deterministic rule-based semantic classifier version tag."""

LEGACY_COMPATIBILITY_CLASSIFIER_VERSION = "cumulative-db-semantic-v1"
"""Frozen classifier identifier for the legacy demand-signal projection."""

EVIDENCE_RECORDS_CSV = "evidence_records.csv"
EVIDENCE_RECORDS_JSONL = "evidence_records.jsonl"
EVIDENCE_FRAGMENTS_CSV = "evidence_fragments.csv"
EVIDENCE_FRAGMENTS_JSONL = "evidence_fragments.jsonl"
SEMANTIC_SIGNALS_CSV = "semantic_signals.csv"
SEMANTIC_SIGNALS_JSONL = "semantic_signals.jsonl"
COMPETENCE_CANDIDATES_CSV = "competence_candidates.csv"
COMPETENCE_CANDIDATES_JSONL = "competence_candidates.jsonl"
CANONICAL_COMPETENCES_CSV = "canonical_competences.csv"
CANONICAL_COMPETENCES_JSONL = "canonical_competences.jsonl"
SECTOR_COMPETENCE_ASSIGNMENTS_CSV = "sector_competence_assignments.csv"
SECTOR_COMPETENCE_ASSIGNMENTS_JSONL = "sector_competence_assignments.jsonl"
VALIDATION_DECISIONS_CSV = "validation_decisions.csv"
VALIDATION_DECISIONS_JSONL = "validation_decisions.jsonl"
COMPETENCE_DEMAND_SIGNALS_CSV = "competence_demand_signals.csv"
COMPETENCE_DEMAND_SIGNALS_JSONL = "competence_demand_signals.jsonl"
HYPOTHESIS_SEMANTIC_FRAGMENTS_CSV = "hypothesis_semantic_fragments.csv"
HYPOTHESIS_SEMANTIC_FRAGMENTS_JSONL = "hypothesis_semantic_fragments.jsonl"
RUN_NOVELTY_METRICS_CSV = "run_novelty_metrics.csv"
RUN_NOVELTY_METRICS_JSON = "run_novelty_metrics.json"
DATABASE_MANIFEST_FILENAME = "cumulative_database_manifest.json"
DATABASE_CHECKSUMS_FILENAME = "_checksums.sha256"

EVIDENCE_RECORD_COLUMNS: Tuple[str, ...] = (
    "evidence_id",
    "canonical_doi",
    "canonical_title",
    "normalized_title_hash",
    "first_seen_run_id",
    "latest_seen_run_id",
    "first_seen_at_utc",
    "latest_seen_at_utc",
    "providers_seen",
    "provider_count",
    "query_ids_seen",
    "query_families_seen",
    "sector_candidates",
    "axis_candidates",
    "year",
    "journal",
    "citation_count",
    "record_novelty_status",
    "record_recurrence_count",
    "jaccard_group_id",
    "validity_warning",
)

EVIDENCE_FRAGMENT_COLUMNS: Tuple[str, ...] = (
    "fragment_id",
    "evidence_id",
    "run_id",
    "source_provenance_id",
    "source_provider",
    "source_provider_id",
    "source_retrieved_at_utc",
    "source_query_id",
    "source_query_text",
    "source_field",
    "language",
    "fragment_text",
    "span_start_offset",
    "span_end_offset",
    "surface_text_hash",
    "provenance_hash",
)

SEMANTIC_SIGNAL_COLUMNS: Tuple[str, ...] = (
    "signal_id",
    "fragment_id",
    "evidence_id",
    "run_id",
    "source_provenance_id",
    "sector",
    "axis_group",
    "axis_code",
    "query_id",
    "query_family",
    "signal_type",
    "signal_category_label",
    "signal_category_description",
    "matched_phrase",
    "confidence_score",
    "classifier_version",
    "negation_status",
    "speculation_status",
    "actor_text",
    "action_text",
    "object_text",
    "context_text",
    "manual_review_status",
    "validity_warning",
)

COMPETENCE_CANDIDATE_COLUMNS: Tuple[str, ...] = (
    "candidate_id",
    "signal_id",
    "fragment_id",
    "evidence_id",
    "run_id",
    "sector",
    "axis_group",
    "axis_code",
    "source_provenance_ids",
    "fragment_ids",
    "candidate_label",
    "candidate_definition",
    "capability_proposition",
    "knowledge_dimension",
    "skill_dimension",
    "responsibility_autonomy_dimension",
    "candidate_status",
    "review_status",
    "exact_evidence_span",
    "exact_span_start_offset",
    "exact_span_end_offset",
)

CANONICAL_COMPETENCE_COLUMNS: Tuple[str, ...] = (
    "canonical_competence_id",
    "validation_decision_id",
    "source_candidate_id",
    "preferred_label",
    "canonical_definition",
    "aliases",
    "validation_status",
    "schema_version",
    "provenance_guard_status",
)

SECTOR_COMPETENCE_ASSIGNMENT_COLUMNS: Tuple[str, ...] = (
    "assignment_id",
    "canonical_competence_id",
    "validation_decision_id",
    "source_candidate_id",
    "sector",
    "axis_group",
    "axis_code",
    "evidence_ids",
)

VALIDATION_DECISION_COLUMNS: Tuple[str, ...] = (
    "validation_decision_id",
    "target_candidate_id",
    "canonical_label",
    "decision_status",
    "reviewer",
    "decision_at_utc",
    "decision_reason",
    "evidence_ids",
    "fragment_ids",
    "source_provenance_ids",
    "superseded_validation_decision_id",
)

COMPETENCE_DEMAND_SIGNAL_COLUMNS: Tuple[str, ...] = (
    "signal_id",
    "evidence_id",
    "run_id",
    "sector",
    "axis_group",
    "axis_code",
    "query_id",
    "query_family",
    "semantic_scope",
    "signal_type",
    "competence_label",
    "competence_description",
    "demand_phrase",
    "learning_outcome_candidate",
    "evidence_text_scope",
    "evidence_text_hash",
    "confidence_score",
    "classifier_version",
    "manual_review_status",
    "validity_warning",
)

HYPOTHESIS_SEMANTIC_FRAGMENT_COLUMNS: Tuple[str, ...] = (
    "fragment_id",
    "hypothesis_id",
    "hypothesis_label",
    "hypothesis_ids",
    "signal_id",
    "evidence_id",
    "run_id",
    "sector",
    "axis_group",
    "axis_code",
    "signal_type",
    "demand_phrase",
    "matched_hypothesis_phrase",
    "theory_term_family",
    "indicator_family",
    "semantic_fragment",
    "evidence_surface",
    "semantic_scope",
    "evidence_text_hash",
    "classifier_version",
    "manual_review_status",
    "validity_warning",
)

ALLOWED_RECORD_NOVELTY_STATUS: Tuple[str, ...] = (
    "new_record",
    "repeated_record",
    "updated_metadata",
    "provider_enriched",
    "semantic_enriched",
    "duplicate_only",
    "review_required",
)

ALLOWED_SIGNAL_TYPES: Tuple[str, ...] = (
    "explicit_competence_demand",
    "implicit_competence_demand",
    "workforce_skill",
    "technical_skill",
    "governance_skill",
    "social_science_skill",
    "sustainability_skill",
    "digital_skill",
    "safety_risk_skill",
    "policy_regulation_skill",
    "education_training_signal",
    "learning_outcome_signal",
    "credential_translation_signal",
)

ALLOWED_MANUAL_REVIEW_STATUSES: Tuple[str, ...] = (
    "auto_accepted",
    "review_required",
    "manually_reviewed",
    "rejected",
)

_REVIEWER_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")


class CumulativeDatabaseError(RuntimeError):
    """Raised when the cumulative-database builder cannot produce a bundle."""


# ---------------------------------------------------------------------------
# Semantic pattern registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _SignalPattern:
    """One deterministic keyword pattern for the semantic scanner."""

    signal_type: str
    label: str
    description: str
    phrases: Tuple[str, ...]


@dataclass(frozen=True)
class _SignalMatch:
    """One exact retained match used to build v2 fragment/signal rows."""

    pattern: _SignalPattern
    matched_phrase: str
    span_text: str
    source_field: str
    source_text: str
    span_start: int
    span_end: int


@dataclass(frozen=True)
class _SignalComponent:
    """A bundled v2 construct-validity chain for one observation match."""

    evidence_fragment: "EvidenceFragment"
    semantic_signal: "SemanticSignal"
    competence_candidate: "CompetenceCandidate"


# Patterns are frozen and ordered — the scanner iterates them deterministically.
_SIGNAL_PATTERNS: Tuple[_SignalPattern, ...] = (
    _SignalPattern(
        signal_type="explicit_competence_demand",
        label="Explicit competence demand",
        description="Direct mention of a competence, competency, or skill demand.",
        phrases=(
            "competence",
            "competences",
            "competency",
            "competencies",
            "skill demand",
            "skills demand",
            "skills need",
            "skill need",
            "skills gap",
            "skills gaps",
            "skills mismatch",
            "skill shortage",
            "skills shortage",
        ),
    ),
    _SignalPattern(
        signal_type="workforce_skill",
        label="Workforce skill signal",
        description="Mentions of workforce, labour, employment, and human-capital dimensions.",
        phrases=(
            "workforce",
            "labour force",
            "labor force",
            "human capital",
            "employment",
            "career",
            "profession",
            "professional development",
            "professionalisation",
            "professionalization",
        ),
    ),
    _SignalPattern(
        signal_type="education_training_signal",
        label="Education and training signal",
        description="Formal or informal education, training, curriculum, or capacity building.",
        phrases=(
            "training",
            "curriculum",
            "curricula",
            "education",
            "capacity building",
            "capacity-building",
            "capacity development",
            "qualification",
            "qualifications",
            "vocational",
            "vet ",
            "cpd",
            "continuing professional development",
        ),
    ),
    _SignalPattern(
        signal_type="learning_outcome_signal",
        label="Learning outcome signal",
        description="Learning outcomes, learning objectives, or competence descriptors.",
        phrases=(
            "learning outcome",
            "learning outcomes",
            "learning objective",
            "learning objectives",
            "descriptor",
            "descriptors",
            "eqf",
            "ects",
        ),
    ),
    _SignalPattern(
        signal_type="credential_translation_signal",
        label="Credential translation signal",
        description="Micro-credentials, credential recognition, or cross-border translation.",
        phrases=(
            "micro-credential",
            "microcredential",
            "micro credential",
            "credential recognition",
            "credential translation",
            "recognition of prior learning",
            "rpl",
            "validation of non-formal",
        ),
    ),
    _SignalPattern(
        signal_type="digital_skill",
        label="Digital or data skill",
        description="Digital, data, AI, autonomy, and cyber-technical skill signals.",
        phrases=(
            "digital",
            "digitalisation",
            "digitalization",
            "data science",
            "data literacy",
            "ai ",
            "artificial intelligence",
            "machine learning",
            "autonomy",
            "autonomous",
            "cyber",
        ),
    ),
    _SignalPattern(
        signal_type="technical_skill",
        label="Technical or engineering skill",
        description="Engineering, technology, and operations skill signals.",
        phrases=(
            "engineering",
            "technology",
            "operations",
            "operator",
            "operators",
            "maintenance",
            "technician",
            "robotics",
            "sensor",
        ),
    ),
    _SignalPattern(
        signal_type="governance_skill",
        label="Governance or policy skill",
        description="Governance, institutional, and stakeholder coordination skills.",
        phrases=(
            "governance",
            "policy",
            "policies",
            "institutional",
            "stakeholder",
            "co-management",
            "co management",
            "multi-level",
        ),
    ),
    _SignalPattern(
        signal_type="policy_regulation_skill",
        label="Policy or regulation skill",
        description="Regulatory, legal, and compliance skill signals.",
        phrases=(
            "regulation",
            "regulatory",
            "compliance",
            "law",
            "legal",
            "convention",
            "directive",
            "protocol",
        ),
    ),
    _SignalPattern(
        signal_type="social_science_skill",
        label="Social-science or literacy skill",
        description="Ocean literacy, blue citizenship, and social-science skill signals.",
        phrases=(
            "literacy",
            "ocean literacy",
            "blue citizenship",
            "social science",
            "social sciences",
            "sociology",
            "community",
            "public engagement",
        ),
    ),
    _SignalPattern(
        signal_type="sustainability_skill",
        label="Sustainability, resilience, or adaptation skill",
        description="Sustainability, resilience, and adaptation skill signals.",
        phrases=(
            "sustainability",
            "sustainable",
            "resilience",
            "resilient",
            "adaptation",
            "adaptive",
            "just transition",
            "circular economy",
            "climate",
        ),
    ),
    _SignalPattern(
        signal_type="safety_risk_skill",
        label="Safety or risk-management skill",
        description="Safety, risk, hazard, and emergency-response skill signals.",
        phrases=(
            "safety",
            "risk",
            "hazard",
            "emergency",
            "search and rescue",
            "sar ",
            "occupational health",
        ),
    ),
    _SignalPattern(
        signal_type="implicit_competence_demand",
        label="Implicit competence demand",
        description="Broader skilling, upskilling, reskilling, and know-how signals.",
        phrases=(
            "upskilling",
            "up-skilling",
            "reskilling",
            "re-skilling",
            "know-how",
            "knowhow",
            "know how",
            "expertise",
            "professional skills",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRecord:
    """A deduplicated evidence row for the cumulative database."""

    evidence_id: str
    canonical_doi: str
    canonical_title: str
    normalized_title_hash: str
    first_seen_run_id: str
    latest_seen_run_id: str
    first_seen_at_utc: str
    latest_seen_at_utc: str
    providers_seen: str
    provider_count: int
    query_ids_seen: str
    query_families_seen: str
    sector_candidates: str
    axis_candidates: str
    year: str
    journal: str
    citation_count: int
    record_novelty_status: str
    record_recurrence_count: int
    jaccard_group_id: str
    validity_warning: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly ordered dict of this evidence row."""
        return {col: getattr(self, col) for col in EVIDENCE_RECORD_COLUMNS}


@dataclass(frozen=True)
class EvidenceFragment:
    """A retained exact evidence span tied to one observation provenance."""

    fragment_id: str
    evidence_id: str
    run_id: str
    source_provenance_id: str
    source_provider: str
    source_provider_id: str
    source_retrieved_at_utc: str
    source_query_id: str
    source_query_text: str
    source_field: str
    language: str
    fragment_text: str
    span_start_offset: int
    span_end_offset: int
    surface_text_hash: str
    provenance_hash: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly ordered dict of this evidence-fragment row."""
        return {col: getattr(self, col) for col in EVIDENCE_FRAGMENT_COLUMNS}


@dataclass(frozen=True)
class SemanticSignal:
    """Versioned semantic signal with explicit fragment lineage."""

    signal_id: str
    fragment_id: str
    evidence_id: str
    run_id: str
    source_provenance_id: str
    sector: str
    axis_group: str
    axis_code: str
    query_id: str
    query_family: str
    signal_type: str
    signal_category_label: str
    signal_category_description: str
    matched_phrase: str
    confidence_score: float
    classifier_version: str
    negation_status: str
    speculation_status: str
    actor_text: str
    action_text: str
    object_text: str
    context_text: str
    manual_review_status: str
    validity_warning: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly ordered dict of this semantic-signal row."""
        return {col: getattr(self, col) for col in SEMANTIC_SIGNAL_COLUMNS}


@dataclass(frozen=True)
class CompetenceCandidate:
    """Review-gated competence candidate derived from one semantic signal."""

    candidate_id: str
    signal_id: str
    fragment_id: str
    evidence_id: str
    run_id: str
    sector: str
    axis_group: str
    axis_code: str
    source_provenance_ids: str
    fragment_ids: str
    candidate_label: str
    candidate_definition: str
    capability_proposition: str
    knowledge_dimension: str
    skill_dimension: str
    responsibility_autonomy_dimension: str
    candidate_status: str
    review_status: str
    exact_evidence_span: str
    exact_span_start_offset: int
    exact_span_end_offset: int

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly ordered dict of this candidate row."""
        return {col: getattr(self, col) for col in COMPETENCE_CANDIDATE_COLUMNS}


@dataclass(frozen=True)
class ValidationDecision:
    """Explicit reviewer decision required before canonicalization."""

    validation_decision_id: str
    target_candidate_id: str
    canonical_label: str
    decision_status: str
    reviewer: str
    decision_at_utc: str
    decision_reason: str
    evidence_ids: str
    fragment_ids: str
    source_provenance_ids: str
    superseded_validation_decision_id: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly ordered dict of this validation-decision row."""
        return {col: getattr(self, col) for col in VALIDATION_DECISION_COLUMNS}


@dataclass(frozen=True)
class CanonicalCompetence:
    """Validation-backed canonical competence."""

    canonical_competence_id: str
    validation_decision_id: str
    source_candidate_id: str
    preferred_label: str
    canonical_definition: str
    aliases: str
    validation_status: str
    schema_version: str
    provenance_guard_status: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly ordered dict of this canonical-competence row."""
        return {col: getattr(self, col) for col in CANONICAL_COMPETENCE_COLUMNS}


@dataclass(frozen=True)
class SectorCompetenceAssignment:
    """Explicit sector linkage for one canonical competence."""

    assignment_id: str
    canonical_competence_id: str
    validation_decision_id: str
    source_candidate_id: str
    sector: str
    axis_group: str
    axis_code: str
    evidence_ids: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly ordered dict of this sector-assignment row."""
        return {
            col: getattr(self, col)
            for col in SECTOR_COMPETENCE_ASSIGNMENT_COLUMNS
        }


@dataclass(frozen=True)
class CompetenceDemandSignal:
    """A single semantic competence-demand signal row."""

    signal_id: str
    evidence_id: str
    run_id: str
    sector: str
    axis_group: str
    axis_code: str
    query_id: str
    query_family: str
    semantic_scope: str
    signal_type: str
    competence_label: str
    competence_description: str
    demand_phrase: str
    learning_outcome_candidate: str
    evidence_text_scope: str
    evidence_text_hash: str
    confidence_score: float
    classifier_version: str
    manual_review_status: str
    validity_warning: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly ordered dict of this signal row."""
        return {col: getattr(self, col) for col in COMPETENCE_DEMAND_SIGNAL_COLUMNS}


@dataclass(frozen=True)
class RunNoveltyMetrics:
    """Per-run novelty counters exported alongside evidence rows."""

    current_run_id: str
    previous_run_id: str
    new_unique_doi_count: int
    repeated_doi_count: int
    updated_metadata_count: int
    provider_enriched_count: int
    semantic_new_signal_count: int
    provider_record_count_by_provider: Dict[str, int]
    provider_health_ok_zero_records: List[str]
    jaccard_similarity_with_previous_run: float
    provider_diversity_score: float
    query_diversity_score: float
    query_families_seen: List[str]
    crossref_dominance_ratio: float
    validity_warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-friendly ordered dict of this novelty metrics row."""
        return {
            "current_run_id": self.current_run_id,
            "previous_run_id": self.previous_run_id,
            "new_unique_doi_count": self.new_unique_doi_count,
            "repeated_doi_count": self.repeated_doi_count,
            "updated_metadata_count": self.updated_metadata_count,
            "provider_enriched_count": self.provider_enriched_count,
            "semantic_new_signal_count": self.semantic_new_signal_count,
            "provider_record_count_by_provider": dict(
                sorted(self.provider_record_count_by_provider.items())
            ),
            "provider_health_ok_zero_records": sorted(
                self.provider_health_ok_zero_records
            ),
            "jaccard_similarity_with_previous_run": (
                self.jaccard_similarity_with_previous_run
            ),
            "provider_diversity_score": self.provider_diversity_score,
            "query_diversity_score": self.query_diversity_score,
            "query_families_seen": sorted(
                {
                    str(query_family).strip()
                    for query_family in self.query_families_seen
                    if str(query_family).strip()
                }
            ),
            "crossref_dominance_ratio": self.crossref_dominance_ratio,
            "validity_warnings": sorted(self.validity_warnings),
        }


@dataclass
class CumulativeDatabaseResult:
    """Output surface returned by :func:`build_cumulative_scientific_database`."""

    output_dir: Path
    evidence_records: List[EvidenceRecord]
    competence_demand_signals: List[CompetenceDemandSignal]
    run_novelty_metrics: RunNoveltyMetrics
    evidence_fragments: List[EvidenceFragment] = field(default_factory=list)
    semantic_signals: List[SemanticSignal] = field(default_factory=list)
    competence_candidates: List[CompetenceCandidate] = field(default_factory=list)
    canonical_competences: List[CanonicalCompetence] = field(default_factory=list)
    sector_competence_assignments: List[SectorCompetenceAssignment] = field(
        default_factory=list
    )
    validation_decisions: List[ValidationDecision] = field(default_factory=list)
    files: List[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization + hashing helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")
_TITLE_KEEP_RE = re.compile(r"[^a-z0-9 ]+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_PROVIDER_ALIAS_TO_CANONICAL: Dict[str, str] = {
    "crossref": "crossref",
    "cr": "crossref",
    "scopus": "scopus",
    "elsevier scopus": "scopus",
    "wos": "wos",
    "web of science": "wos",
    "web of science clarivate": "wos",
    "web of science (clarivate)": "wos",
    "web_of_science": "wos",
    "web_of_science_clarivate": "wos",
    "clarivate": "wos",
    "clarivate wos": "wos",
    "clarivate web of science": "wos",
    "clarivate_web_of_science": "wos",
    "scival": "scival",
    "microsoft graph": "microsoft_graph",
    "microsoft_graph": "microsoft_graph",
    "google drive": "google_drive",
    "google_drive": "google_drive",
}


def _normalize_doi(doi: Any) -> str:
    """Return a canonicalized DOI payload or '' if the value is empty.

    Strips common resolver prefixes (``doi:``, ``https://doi.org/``,
    ``http://doi.org/``, ``https://dx.doi.org/``, ``http://dx.doi.org/``),
    URL-decodes the resulting payload, trims surrounding whitespace, and
    lowercases so that URL-form and bare-form DOIs collapse to a single
    stable identity key.
    """
    if not isinstance(doi, str):
        return ""
    s = doi.strip()
    _DOI_PREFIXES = (
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "https://doi.org/",
        "http://doi.org/",
        "doi:",
    )
    for prefix in _DOI_PREFIXES:
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix):]
            break
    return _url_unquote(s).strip().lower()


def _normalize_title(title: Any) -> str:
    """Return a canonicalized (ASCII, lowercased, whitespace-collapsed) title."""
    if not isinstance(title, str):
        return ""
    ascii_title = unicodedata.normalize("NFKD", title).encode(
        "ascii", "ignore"
    ).decode("ascii")
    lowered = ascii_title.lower()
    cleaned = _TITLE_KEEP_RE.sub(" ", lowered)
    collapsed = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return collapsed


def _title_hash(normalized_title: str) -> str:
    """Return a 16-char hex prefix of the SHA-256 of the normalized title."""
    if not normalized_title:
        return ""
    digest = hashlib.sha256(normalized_title.encode("utf-8")).hexdigest()
    return digest[:16]


def _normalize_source_id(source_id: Any) -> str:
    """Return the lowercased trimmed source_id, or '' if empty."""
    if not isinstance(source_id, str):
        return ""
    return source_id.strip().lower()


def _canonical_provider_name(value: Any) -> str:
    """Return canonical provider slug for stable cross-layer comparisons."""
    token = str(value or "").strip().lower()
    if not token:
        return ""
    normalized = re.sub(r"\s+", " ", token)
    if normalized in _PROVIDER_ALIAS_TO_CANONICAL:
        return _PROVIDER_ALIAS_TO_CANONICAL[normalized]
    fallback = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    if fallback in _PROVIDER_ALIAS_TO_CANONICAL:
        return _PROVIDER_ALIAS_TO_CANONICAL[fallback]
    return fallback


def _title_tokens(normalized_title: str) -> Set[str]:
    """Return the set of alphanumeric tokens present in a normalized title."""
    if not normalized_title:
        return set()
    return set(_TOKEN_RE.findall(normalized_title))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    """Return the Jaccard similarity of two token sets."""
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return intersection / union


def _sha256_bytes(payload: bytes) -> str:
    """SHA-256 hex digest of a byte string."""
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    """Chunked SHA-256 of a file's contents (matches Layer 1 convention)."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _write_json_sorted(path: Path, payload: Any) -> None:
    """Write a JSON file deterministically (sorted keys, trailing newline)."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    """Write JSON Lines deterministically (one sorted-keys record per line)."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _write_csv(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[Dict[str, Any]],
) -> None:
    """Write a UTF-8 CSV with LF line-endings and quoted string fields."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(columns),
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Protocol query indexing (Layer 0)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ProtocolBinding:
    """A lightweight lookup for one protocol query."""

    query_id: str
    sector_slug: str
    sector_label: str
    axis_code: str
    axis_group: str
    query_family: str


def _build_protocol_index(
    protocol: Optional[LiveQueryProtocol],
) -> Dict[str, _ProtocolBinding]:
    """Return a mapping from lowercased query_text → _ProtocolBinding.

    The Layer 0 protocol is optional; when absent, an empty index is returned
    and every source_query lookup falls through to the "unbound" fallback.
    """
    if protocol is None:
        return {}
    index: Dict[str, _ProtocolBinding] = {}
    for query in protocol.all_queries():
        binding = _protocol_binding_for(query)
        key = query.query_text.strip().lower()
        if key and key not in index:
            index[key] = binding
    return index


def _protocol_binding_for(query: LiveQuery) -> _ProtocolBinding:
    return _ProtocolBinding(
        query_id=query.query_id,
        sector_slug=query.sector_slug,
        sector_label=query.sector,
        axis_code=query.axis_target.value,
        axis_group=query.axis_target.name,
        query_family=query.query_family.value,
    )


_UNBOUND_BINDING = _ProtocolBinding(
    query_id="",
    sector_slug="",
    sector_label="",
    axis_code="",
    axis_group="",
    query_family="",
)


# ---------------------------------------------------------------------------
# Run enumeration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _RunObservation:
    """One live_records row from one run, decorated with the source run_id."""

    run_id: str
    timestamp_utc: str
    record: Mapping[str, Any]
    binding: _ProtocolBinding


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CumulativeDatabaseError(f"failed to read JSON {path}: {exc}") from exc


def _iter_live_records(path: Path) -> List[Mapping[str, Any]]:
    """Return the list of records from a live_records.json, coercing shapes."""
    if not path.is_file() or path.stat().st_size == 0:
        return []
    payload = _load_json(path)
    if isinstance(payload, list):
        return [rec for rec in payload if isinstance(rec, Mapping)]
    if isinstance(payload, Mapping):
        records = payload.get("records")
        if isinstance(records, list):
            return [rec for rec in records if isinstance(rec, Mapping)]
    return []


def _enumerate_archived_runs(
    archive_root: Optional[Path],
) -> List[Tuple[str, str, Path]]:
    """Return `(run_id, timestamp_utc, run_path)` tuples for archived runs.

    The list is sorted by timestamp_utc (ascending) so that the "latest"
    previous run is always the second-to-last entry once the current run is
    appended by the caller.
    """
    if archive_root is None or not archive_root.is_dir():
        return []
    index_path = archive_root / "cumulative_runs_index.csv"
    if not index_path.is_file():
        return []

    runs: List[Tuple[str, str, Path]] = []
    with index_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            run_id = (row.get("run_id") or "").strip()
            run_path_rel = (row.get("run_path") or "").strip()
            timestamp_utc = (row.get("timestamp_utc") or "").strip()
            if not run_id or not run_path_rel:
                continue
            candidate = archive_root / run_path_rel.replace("runs/", "runs/", 1)
            if not candidate.is_dir():
                candidate = archive_root / "runs" / run_id
            runs.append((run_id, timestamp_utc, candidate))
    runs.sort(key=lambda tup: (tup[1], tup[0]))
    return runs


def _resolve_records_path(run_dir: Path) -> Path:
    """Return the canonical live-records path inside an archived run directory.

    Prefers ``live_records_triangulated.json`` (which includes supporting
    provider provenance) over the legacy ``live_records.json`` fallback so
    that cross-run deduplication retains triangulated provider metadata.
    """
    triangulated = run_dir / "research_sources" / "live_records_triangulated.json"
    if triangulated.is_file():
        return triangulated
    return run_dir / "research_sources" / "live_records.json"


def _load_layer1_bindings(
    live_runs_root: Optional[Path],
    run_id: str,
) -> Dict[str, _ProtocolBinding]:
    """Return `{query_text_lower: binding}` learned from a Layer 1 bundle.

    Only rows whose ``protocol_binding == 'bound'`` contribute a lookup entry.
    Missing bundles are ignored (the current-run fallback still works via the
    Layer 0 protocol index).
    """
    if live_runs_root is None:
        return {}
    bundle_dir = live_runs_root / run_id
    audit_csv = bundle_dir / "raw" / "raw_acquisition_index.csv"
    if not audit_csv.is_file():
        return {}

    def _decode_axis_fields(row: Mapping[str, str]) -> Tuple[str, str]:
        raw_axis_group = str(row.get("axis_group") or "").strip().upper()
        raw_axis_code = str(row.get("axis_code") or "").strip().upper()
        raw_axis_target = str(row.get("axis_target") or "").strip()
        raw_axis_target_upper = raw_axis_target.upper()

        axis_group = raw_axis_group
        axis_code = raw_axis_code

        if axis_group in BlueDynamicsAxis.__members__:
            if not axis_code:
                axis_code = BlueDynamicsAxis[axis_group].value
            return axis_group, axis_code

        if raw_axis_target_upper in BlueDynamicsAxis.__members__:
            axis_group = raw_axis_target_upper
            axis_code = BlueDynamicsAxis[axis_group].value
            return axis_group, axis_code

        if raw_axis_target_upper:
            for axis in BlueDynamicsAxis:
                if axis.value == raw_axis_target_upper:
                    return axis.name, axis.value

        if axis_code:
            for axis in BlueDynamicsAxis:
                if axis.value == axis_code:
                    return axis.name, axis.value

        return "", ""

    lookup: Dict[str, _ProtocolBinding] = {}
    with audit_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (row.get("protocol_binding") or "").strip() != "bound":
                continue
            query_text = (row.get("query_text") or "").strip().lower()
            if not query_text:
                continue
            axis_group, axis_code = _decode_axis_fields(row)
            binding = _ProtocolBinding(
                query_id=(row.get("query_id") or "").strip(),
                sector_slug=(row.get("sector_slug") or "").strip(),
                sector_label=(row.get("sector_label") or "").strip(),
                axis_code=axis_code,
                axis_group=axis_group,
                query_family=(row.get("query_family") or "").strip(),
            )
            if binding.query_id and query_text not in lookup:
                lookup[query_text] = binding
    return lookup


def _bind_record(
    record: Mapping[str, Any],
    protocol_index: Mapping[str, _ProtocolBinding],
    layer1_index: Mapping[str, _ProtocolBinding],
) -> _ProtocolBinding:
    """Resolve a record's source_query to a protocol binding.

    Layer 1 bindings (from the run's ``raw_acquisition_index.csv``) take
    precedence because they reflect the queries that actually issued the
    provider request. When no Layer 1 evidence exists (e.g. for archived
    pre-PR-190 runs) we fall back to the Layer 0 protocol registry, and
    finally to the "unbound" sentinel.
    """
    source_query = str(record.get("source_query") or "").strip().lower()
    if source_query:
        if source_query in layer1_index:
            return layer1_index[source_query]
        if source_query in protocol_index:
            return protocol_index[source_query]
    return _UNBOUND_BINDING


def _record_timestamp(
    record: Mapping[str, Any], fallback: str
) -> str:
    """Return the record's retrieval timestamp or `fallback` if absent."""
    stamp = str(record.get("retrieval_timestamp") or "").strip()
    return stamp or fallback


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _dedupe_key(record: Mapping[str, Any]) -> Tuple[str, str, str]:
    """Return the (doi_key, title_key, source_id_key) triple for dedup.

    A record with a non-empty DOI dedupes on that DOI. A record without a DOI
    dedupes on its normalized title. A record without a DOI or title dedupes
    on its provider source_id. Empty values are represented as empty strings.
    """
    doi_key = _normalize_doi(record.get("doi"))
    normalized_title = _normalize_title(record.get("title"))
    source_id = _normalize_source_id(record.get("source_id"))
    if source_id:
        provider = _canonical_provider_name(record.get("provider")) or "unknown"
        source_id = f"{provider}:{source_id}"
    return doi_key, normalized_title, source_id


def _dedupe_bucket(triple: Tuple[str, str, str]) -> Tuple[str, str]:
    """Reduce a dedupe triple to a single ``(kind, key)`` bucket."""
    doi_key, title_key, source_id_key = triple
    if doi_key:
        return ("doi", doi_key)
    if title_key:
        title_hash = _title_hash(title_key)
        return ("title", title_hash)
    if source_id_key:
        return ("source_id", source_id_key)
    return ("unknown", "")


def _make_evidence_id(bucket: Tuple[str, str]) -> str:
    """Return a stable, deterministic evidence_id from a dedupe bucket."""
    kind, key = bucket
    if not key:
        return "evidence:unknown:none"
    if kind == "doi":
        return f"evidence:doi:{key}"
    if kind == "title":
        return f"evidence:title:{key}"
    if kind == "source_id":
        return f"evidence:source:{key}"
    return f"evidence:{kind}:{key}"


# ---------------------------------------------------------------------------
# Novelty classification
# ---------------------------------------------------------------------------

def _classify_novelty(
    run_ids: Sequence[str],
    providers: Sequence[str],
    current_run_id: str,
    canonical_doi: str,
    canonical_title: str,
) -> Tuple[str, str]:
    """Return ``(record_novelty_status, validity_warning)`` for one evidence row.

    The classifier is deterministic and additive. It:

    * marks records whose only appearance is in a run prior to the current
      one as ``repeated_record`` (they were already known before this run);
    * marks records that first appear in the current run as ``new_record``;
    * upgrades to ``provider_enriched`` when the current run adds a provider
      that never observed the record in previous runs;
    * upgrades to ``updated_metadata`` when both DOI and title are present but
      previous runs saw the same evidence without a DOI (i.e. this run added
      a DOI to a previously title-only record);
    * leaves repeated records as ``repeated_record`` at this stage; semantic
      enrichment is reconciled later only for genuinely new stable signal IDs;
    * downgrades to ``review_required`` when neither DOI nor title is present.
    """
    warning = ""
    seen_previous = any(run_id != current_run_id for run_id in run_ids)
    seen_current = current_run_id in run_ids

    if not canonical_doi and not canonical_title:
        return "review_required", "no_stable_dedupe_key"

    if not seen_previous and seen_current:
        return "new_record", warning

    if seen_current and seen_previous:
        # Determine whether the current run adds a provider that never appeared before.
        return _upgrade_if_enriched(
            run_ids,
            providers,
            current_run_id,
        )

    # seen_previous only — repeated record.
    return "repeated_record", warning


def _upgrade_if_enriched(
    run_ids: Sequence[str],
    providers: Sequence[str],
    current_run_id: str,
) -> Tuple[str, str]:
    """Return a possibly-upgraded status for a record seen in both runs."""
    # If only one provider ever saw the record and it was the current run, and
    # previous runs saw the record with different providers, mark provider_enriched.
    provider_history = [(rid, provider) for rid, provider in zip(run_ids, providers)]
    prev_providers = {p for rid, p in provider_history if rid != current_run_id}
    curr_providers = {p for rid, p in provider_history if rid == current_run_id}
    new_providers = curr_providers - prev_providers
    if new_providers:
        return "provider_enriched", ""

    return "repeated_record", ""


# ---------------------------------------------------------------------------
# Semantic scanner (Layer 3)
# ---------------------------------------------------------------------------

_NEGATION_CUE_RE = re.compile(
    r"\b(?:no|not(?!\s+only\b)|never|without|neither|nor|"
    r"lack(?:ing|ed|s)?)\b",
    flags=re.IGNORECASE,
)
_SPECULATION_CUE_RE = re.compile(
    r"\b(?:may|might|could|possibly|potentially|likely|unlikely|"
    r"suggest(?:s|ed|ing)?|appear(?:s|ed|ing)?|expected)\b",
    flags=re.IGNORECASE,
)


def _has_negation_or_speculation_cue(
    source_text: str,
    span_start: int,
    span_end: int,
) -> bool:
    """Return whether a match's clause has a qualifying inference cue.

    The scanner only emits automatic demand candidates for unqualified positive
    claims. Negated and speculative clauses need human interpretation and are
    therefore excluded rather than mislabeled as positive demand evidence.
    """
    delimiters = (".", "?", "!", ";", "\n")
    clause_start = (
        max(source_text.rfind(delimiter, 0, span_start) for delimiter in delimiters)
        + 1
    )
    following_delimiters = [
        index
        for delimiter in delimiters
        if (index := source_text.find(delimiter, span_end)) != -1
    ]
    clause_end = min(following_delimiters) if following_delimiters else len(source_text)
    clause = source_text[clause_start:clause_end]
    return bool(
        _NEGATION_CUE_RE.search(clause) or _SPECULATION_CUE_RE.search(clause)
    )


def _scan_semantic_signals(
    surfaces: Sequence[Tuple[str, str]],
    source_query: str,
) -> List[_SignalMatch]:
    """Return every exact retained match for every semantic pattern.

    ``source_query`` remains provenance-only and must not contribute to
    positive semantic matching.
    """
    del source_query
    normalized_surfaces = [
        (name, text)
        for name, text in surfaces
        if str(text or "").strip()
    ]
    results: List[_SignalMatch] = []
    seen_matches: Set[Tuple[str, str, int, int]] = set()
    for pattern in _SIGNAL_PATTERNS:
        for source_field, source_text in normalized_surfaces:
            for phrase in pattern.phrases:
                phrase_token = phrase.strip()
                if not phrase_token:
                    continue
                for phrase_match in re.finditer(
                    rf"(?<!\w){re.escape(phrase_token)}(?!\w)",
                    source_text,
                    flags=re.IGNORECASE,
                ):
                    start, end = phrase_match.span()
                    match_key = (pattern.signal_type, source_field, start, end)
                    if match_key in seen_matches:
                        continue
                    if _has_negation_or_speculation_cue(source_text, start, end):
                        continue
                    seen_matches.add(match_key)
                    results.append(
                        _SignalMatch(
                            pattern=pattern,
                            matched_phrase=phrase_token,
                            span_text=source_text[start:end],
                            source_field=source_field,
                            source_text=source_text,
                            span_start=start,
                            span_end=end,
                        )
                    )
    return results


def _scan_legacy_compatibility_signals(
    text: str,
    subject_terms: str,
    source_query: str,
) -> List[Tuple[_SignalPattern, str]]:
    """Return the frozen v1 matches for the legacy demand-signal export.

    Schema-v2 construct-validity tables intentionally use the stricter v3
    scanner above. The legacy table remains a compatibility projection and
    therefore preserves its v1 substring matching, one-row-per-pattern
    cardinality, and signal identity.
    """
    del source_query
    haystack = f"{text} || {subject_terms}".lower()
    results: List[Tuple[_SignalPattern, str]] = []
    for pattern in _SIGNAL_PATTERNS:
        for phrase in pattern.phrases:
            if phrase in haystack:
                results.append((pattern, phrase.strip()))
                break
    return results


def _make_signal_id(
    evidence_id: str,
    signal_type: str,
    matched_phrase: str,
    evidence_text_hash: str,
    classifier_version: str,
) -> str:
    """Return a stable cross-run semantic signal identity.

    Run identifiers and query metadata are deliberately excluded: recurrence
    of the same evidence-bound semantic signal must retain the same identity.
    """
    normalized_phrase = re.sub(r"\s+", " ", matched_phrase).strip().lower()
    payload = "\x1f".join(
        (
            evidence_id,
            signal_type,
            normalized_phrase,
            evidence_text_hash,
            classifier_version,
        )
    )
    return f"signal:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _make_fragment_id(
    *,
    evidence_id: str,
    signal_id: str,
    provenance_id: str,
    source_field: str,
    span_start: int,
    span_end: int,
) -> str:
    payload = "\x1f".join(
        (
            evidence_id,
            signal_id,
            provenance_id,
            source_field,
            str(span_start),
            str(span_end),
        )
    )
    return f"fragment:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _make_candidate_id(*, signal_id: str, evidence_id: str) -> str:
    """Return a stable cross-run candidate identity for one semantic signal."""
    payload = "\x1f".join((signal_id, evidence_id, "candidate"))
    return f"candidate:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _source_provenance_fields(
    *,
    obs: _RunObservation,
    evidence_id: str,
) -> Dict[str, str]:
    """Return the published preimage fields for one source occurrence."""
    return {
        "run_id": obs.run_id,
        "evidence_id": evidence_id,
        "source_provider": (
            _canonical_provider_name(obs.record.get("provider")) or "unknown"
        ),
        "source_provider_id": str(obs.record.get("source_id") or "").strip(),
        "source_retrieved_at_utc": _record_timestamp(
            obs.record, obs.timestamp_utc
        ),
        "source_query_id": obs.binding.query_id,
        "source_query_text": str(obs.record.get("source_query") or "").strip(),
    }


def _make_provenance_id_from_fields(fields: Mapping[str, str]) -> str:
    """Return the stable identifier for published source-occurrence fields."""
    payload = "\x1f".join(
        (
            fields["run_id"],
            fields["evidence_id"],
            fields["source_retrieved_at_utc"],
            fields["source_provider"],
            _normalize_source_id(fields["source_provider_id"]),
            fields["source_query_id"],
            re.sub(r"\s+", " ", fields["source_query_text"]).strip().lower(),
        )
    )
    return f"prov:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _make_provenance_id(*, obs: _RunObservation, evidence_id: str) -> str:
    """Return a stable source-occurrence identifier with a published preimage."""
    return _make_provenance_id_from_fields(
        _source_provenance_fields(obs=obs, evidence_id=evidence_id)
    )


def _candidate_label(pattern: _SignalPattern, span_text: str) -> str:
    token = re.sub(r"\s+", " ", str(span_text or "").strip())
    if token:
        return token
    return pattern.label


def _candidate_capability_proposition(
    *, pattern: _SignalPattern, span_text: str, source_field: str
) -> str:
    span = re.sub(r"\s+", " ", str(span_text or "").strip())
    source = source_field or "retained_text"
    return f"{pattern.label} evidenced by exact {source} span: {span}"


def _candidate_knowledge_dimension(pattern: _SignalPattern) -> str:
    if pattern.signal_type in {
        "governance_skill",
        "policy_regulation_skill",
        "social_science_skill",
        "sustainability_skill",
    }:
        return "knowledge"
    return "hybrid"


def _candidate_skill_dimension(pattern: _SignalPattern) -> str:
    if pattern.signal_type in {
        "digital_skill",
        "technical_skill",
        "safety_risk_skill",
        "education_training_signal",
    }:
        return "skill"
    return "hybrid"


def _candidate_ra_dimension(pattern: _SignalPattern) -> str:
    if pattern.signal_type in {
        "governance_skill",
        "policy_regulation_skill",
        "credential_translation_signal",
    }:
        return "responsibility_autonomy"
    return "hybrid"


def canonical_label_is_allowed(
    label: str,
    *,
    retained_source_titles: Sequence[str] = (),
) -> Tuple[bool, str]:
    """Return canonical-promotion eligibility and any guard rejection reason."""
    token = re.sub(r"\s+", " ", str(label or "").strip())
    if not token:
        return False, "empty_label"
    lowered = token.lower()
    provider_token = re.sub(r"[_\s]+", " ", lowered).strip()
    provider_aliases = {
        re.sub(r"[_\s]+", " ", alias).strip()
        for alias in _PROVIDER_ALIAS_TO_CANONICAL
    }
    if any(
        provider_token == alias
        or provider_token.startswith(f"{alias}:")
        or provider_token.startswith(f"{alias} ")
        for alias in provider_aliases
    ):
        return False, "provider_metadata_prefix"
    if "..." in token or "\u2026" in token:
        return False, "truncation_ellipsis"
    if len(token) > 180:
        return False, "length_over_180"
    if token.count(" ") >= 8:
        return False, "space_count_at_least_8"
    metadata_match = re.search(r"\b(doi|journal|conference|article|paper)\b", lowered)
    if metadata_match:
        return False, f"metadata_term:{metadata_match.group(1)}"
    normalized_label = _normalize_title(token)
    label_token_count = len(normalized_label.split())
    for source_title in retained_source_titles:
        normalized_title = _normalize_title(source_title)
        if not normalized_title or not normalized_label:
            continue
        if normalized_label == normalized_title:
            return False, "source_title_exact"
        if (
            label_token_count >= 3
            and f" {normalized_label} " in f" {normalized_title} "
        ):
            return False, "source_title_fragment"
    return True, ""


def _text_hash(text: str) -> str:
    """SHA-256 of normalized retained evidence text (empty text → empty hash)."""
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_cumulative_scientific_database(
    *,
    current_run_dir: Union[str, Path],
    output_dir: Union[str, Path],
    archive_root: Union[str, Path, None] = None,
    live_runs_root: Union[str, Path, None] = None,
    protocol_path: Union[str, Path, None] = None,
    current_run_id: Optional[str] = None,
    built_at_utc: Optional[str] = None,
    workflow_context: Optional[Mapping[str, Any]] = None,
    validation_decisions: Optional[Sequence[Mapping[str, Any]]] = None,
) -> CumulativeDatabaseResult:
    """Build the Layer 2 + 3 cumulative scientific database.

    Args:
        current_run_dir: Directory containing the current run's outputs
            (e.g. ``outputs/``). Must contain
            ``research_sources/live_records.json`` at minimum.
        output_dir: Directory into which the bundle files are written.
            Created if it does not exist.
        archive_root: Optional root for cross-run history (e.g.
            ``outputs/run_archive``). When absent, only the current run
            contributes to the cumulative database.
        live_runs_root: Optional root for Layer 1 raw acquisition bundles
            (e.g. ``outputs/live_runs``). Used to bind provider records to
            their originating ``query_id`` when ``protocol_binding == 'bound'``.
        protocol_path: Optional path to ``config/live_query_protocol.yml``.
            When absent, Layer 0 fallback bindings are disabled.
        current_run_id: Optional deterministic identifier for the current run.
            When omitted, ``current`` is used so the builder is reproducible in
            local development.
        built_at_utc: Optional ISO-8601 timestamp to stamp into the manifest.
        workflow_context: Optional mapping of GitHub Actions env vars.
        validation_decisions: Optional explicit reviewer decision payloads. Each
            payload must include a generated ``target_candidate_id`` and a
            ``decision_status`` of ``accepted``, ``rejected``,
            ``review_required``, or ``superseded``. Reviewer, decision time,
            and reason are explicit audit fields. An unknown candidate target,
            malformed audit field, or invalid status raises
            :class:`CumulativeDatabaseError`.

    Returns:
        A :class:`CumulativeDatabaseResult` describing every file written.

    Raises:
        CumulativeDatabaseError: on any I/O or schema failure.
    """
    current_run_path = Path(current_run_dir)
    output_path = Path(output_dir)
    archive_root_path = Path(archive_root) if archive_root else None
    live_runs_root_path = Path(live_runs_root) if live_runs_root else None
    protocol_path_obj = Path(protocol_path) if protocol_path else None

    resolved_run_id = (current_run_id or "current").strip() or "current"
    built_at = built_at_utc or datetime.now(timezone.utc).isoformat()
    workflow_ctx: Dict[str, Any] = dict(workflow_context or {})

    protocol = _load_protocol_or_none(protocol_path_obj)
    protocol_index = _build_protocol_index(protocol)

    output_path.mkdir(parents=True, exist_ok=True)

    observations, run_timestamps, _ = _collect_observations(
        current_run_path=current_run_path,
        current_run_id=resolved_run_id,
        current_run_timestamp=built_at,
        archive_root=archive_root_path,
        live_runs_root=live_runs_root_path,
        protocol_index=protocol_index,
    )

    buckets = _group_observations(observations)

    evidence_records, evidence_index = _make_evidence_records(
        buckets=buckets,
        current_run_id=resolved_run_id,
        run_timestamps=run_timestamps,
    )

    current_signal_components = _build_current_signal_components(
        buckets=buckets,
        evidence_index=evidence_index,
        current_run_id=resolved_run_id,
    )
    competence_demand_signals = _make_signals(
        buckets=buckets,
        evidence_index=evidence_index,
        current_run_id=resolved_run_id,
    )
    historical_signal_ids = _historical_signal_ids(
        buckets=buckets,
        evidence_index=evidence_index,
        current_run_id=resolved_run_id,
    )
    new_signal_ids = {
        signal.signal_id for signal in competence_demand_signals
    } - historical_signal_ids

    _reconcile_semantic_enrichment(
        evidence_records,
        competence_demand_signals,
        new_signal_ids,
    )

    novelty_metrics = _compute_novelty_metrics(
        evidence_records=evidence_records,
        competence_demand_signals=competence_demand_signals,
        current_run_id=resolved_run_id,
        buckets=buckets,
        run_timestamps=run_timestamps,
        historical_signal_ids=historical_signal_ids,
    )
    construct_validity_components = _build_construct_validity_signal_components(
        buckets=buckets,
        evidence_index=evidence_index,
        current_run_id=resolved_run_id,
        current_signal_components=current_signal_components,
    )
    evidence_titles_by_id = {
        row.evidence_id: row.canonical_title for row in evidence_records
    }
    (
        evidence_fragments,
        semantic_signals,
        competence_candidates,
        validation_decision_rows,
        canonical_competences,
        sector_competence_assignments,
    ) = _build_construct_validity_tables(
        signal_components=construct_validity_components,
        validation_decision_payloads=tuple(validation_decisions or ()),
        built_at_utc=built_at,
        evidence_titles_by_id=evidence_titles_by_id,
    )

    written = _write_bundle(
        output_dir=output_path,
        evidence_records=evidence_records,
        evidence_fragments=evidence_fragments,
        semantic_signals=semantic_signals,
        competence_candidates=competence_candidates,
        canonical_competences=canonical_competences,
        sector_competence_assignments=sector_competence_assignments,
        validation_decisions=validation_decision_rows,
        competence_demand_signals=competence_demand_signals,
        novelty_metrics=novelty_metrics,
        current_run_id=resolved_run_id,
        built_at_utc=built_at,
        workflow_context=workflow_ctx,
        archive_root=archive_root_path,
        live_runs_root=live_runs_root_path,
        protocol_path=protocol_path_obj,
        protocol=protocol,
        current_run_dir=current_run_path,
    )

    return CumulativeDatabaseResult(
        output_dir=output_path,
        evidence_records=evidence_records,
        competence_demand_signals=competence_demand_signals,
        run_novelty_metrics=novelty_metrics,
        evidence_fragments=evidence_fragments,
        semantic_signals=semantic_signals,
        competence_candidates=competence_candidates,
        canonical_competences=canonical_competences,
        sector_competence_assignments=sector_competence_assignments,
        validation_decisions=validation_decision_rows,
        files=written,
    )


def _load_protocol_or_none(
    protocol_path: Optional[Path],
) -> Optional[LiveQueryProtocol]:
    if protocol_path is None or not protocol_path.is_file():
        return None
    try:
        return load_live_query_protocol(protocol_path)
    except Exception as exc:  # pragma: no cover - defensive
        raise CumulativeDatabaseError(
            f"failed to load Layer 0 protocol {protocol_path}: {exc}"
        ) from exc


def _collect_observations(
    *,
    current_run_path: Path,
    current_run_id: str,
    current_run_timestamp: str,
    archive_root: Optional[Path],
    live_runs_root: Optional[Path],
    protocol_index: Mapping[str, _ProtocolBinding],
) -> Tuple[
    List[_RunObservation],
    Dict[str, str],
    List[Mapping[str, Any]],
]:
    """Return `(observations, run_timestamps, current_records)`."""
    observations: List[_RunObservation] = []
    run_timestamps: Dict[str, str] = {}

    # Archived runs first, in ascending timestamp order.
    for run_id, timestamp_utc, run_dir in _enumerate_archived_runs(archive_root):
        if run_id == current_run_id:
            # The current run is inserted from live outputs, not from the archive
            # copy, so we skip an archived twin to avoid double-counting.
            continue
        triangulated_path = (
            run_dir / "research_sources" / "live_records_triangulated.json"
        )
        fallback_path = run_dir / "research_sources" / "live_records.json"
        records = _iter_live_records(triangulated_path)
        used_fallback = False
        if not records:
            records = _iter_live_records(fallback_path)
            used_fallback = bool(records)
        if not records:
            continue
        run_timestamps[run_id] = timestamp_utc or current_run_timestamp
        layer1_index = _load_layer1_bindings(live_runs_root, run_id)
        for source_record in records:
            record = dict(source_record)
            if used_fallback:
                record["_triangulation_fallback"] = True
            binding = _bind_record(record, protocol_index, layer1_index)
            observations.append(
                _RunObservation(
                    run_id=run_id,
                    timestamp_utc=_record_timestamp(record, timestamp_utc),
                    record=record,
                    binding=binding,
                )
            )

    # Then the current run.  Prefer live_records_triangulated.json (includes
    # supporting-provider provenance from multi-provider triangulation) over
    # the legacy live_records.json so that triangulated metadata is not lost
    # when the cumulative database is built immediately after acquisition.
    _triangulated = current_run_path / "research_sources" / "live_records_triangulated.json"
    _fallback = current_run_path / "research_sources" / "live_records.json"
    preferred_records = _iter_live_records(_triangulated)
    if not preferred_records:
        preferred_records = _iter_live_records(_fallback)
    current_records: List[Mapping[str, Any]] = []
    run_timestamps[current_run_id] = current_run_timestamp
    layer1_current = _load_layer1_bindings(live_runs_root, current_run_id)
    for source_record in preferred_records:
        record = dict(source_record)
        current_records.append(record)
        binding = _bind_record(record, protocol_index, layer1_current)
        observations.append(
            _RunObservation(
                run_id=current_run_id,
                timestamp_utc=_record_timestamp(record, current_run_timestamp),
                record=record,
                binding=binding,
            )
        )

    return observations, run_timestamps, current_records


def _group_observations(
    observations: Sequence[_RunObservation],
) -> Dict[Tuple[str, str], List[_RunObservation]]:
    """Group observations with deterministic DOI-upgrade reconciliation.

    A DOI-less title is upgraded into a DOI bucket only when that normalized
    title maps to exactly one DOI across the corpus. Ambiguous same-title
    records with distinct DOIs remain separate.
    """
    dois_by_title: Dict[str, Set[str]] = {}
    for obs in observations:
        doi_key, title_key, _ = _dedupe_key(obs.record)
        if doi_key and title_key:
            dois_by_title.setdefault(title_key, set()).add(doi_key)

    grouped: Dict[Tuple[str, str], List[_RunObservation]] = {}
    for obs in observations:
        triple = _dedupe_key(obs.record)
        doi_key, title_key, _ = triple
        title_dois = dois_by_title.get(title_key, set()) if title_key else set()
        if not doi_key and len(title_dois) == 1:
            bucket = ("doi", next(iter(title_dois)))
        else:
            bucket = _dedupe_bucket(triple)
        grouped.setdefault(bucket, []).append(obs)
    return grouped


def _make_evidence_records(
    *,
    buckets: Dict[Tuple[str, str], List[_RunObservation]],
    current_run_id: str,
    run_timestamps: Mapping[str, str],
) -> Tuple[List[EvidenceRecord], Dict[Tuple[str, str], str]]:
    """Return sorted evidence records plus a bucket→evidence_id index.

    Fixes applied in this implementation:

    * **Fix 6** — year, journal, and citation_count are taken from the
      *latest* non-empty observation (not the first), preserving first-seen
      provenance timestamps while preferring richer later enrichment.
    * **Fix 7** — buckets whose Jaccard root differs from their own
      evidence_id are designated non-root duplicates and receive
      ``record_novelty_status = duplicate_only``.  This prevents them from
      inflating scientific-growth counts or demand scores.  The
      ``jaccard_group_id`` field retains the root evidence_id for the full
      duplicate crosswalk so auditors can trace every non-root member.
    """
    jaccard_group_index = _compute_jaccard_groups(buckets)
    records: List[EvidenceRecord] = []
    index: Dict[Tuple[str, str], str] = {}

    for bucket, observations in buckets.items():
        evidence_id = _make_evidence_id(bucket)
        index[bucket] = evidence_id

        # Sort observations by timestamp for deterministic first/latest.
        obs_sorted = sorted(observations, key=lambda o: (o.timestamp_utc, o.run_id))
        first_obs = obs_sorted[0]
        latest_obs = obs_sorted[-1]

        canonical_doi = _pick_canonical_doi(obs_sorted)
        canonical_title = _pick_canonical_title(obs_sorted)
        normalized_title = _normalize_title(canonical_title)
        normalized_title_hash = _title_hash(normalized_title)

        run_ids_ordered: List[str] = []
        providers_ordered: List[str] = []
        for observation in obs_sorted:
            normalized_providers = sorted(_providers_for_record(observation.record))
            if not normalized_providers:
                continue
            for provider in normalized_providers:
                run_ids_ordered.append(observation.run_id)
                providers_ordered.append(provider)
        query_ids = sorted({o.binding.query_id for o in obs_sorted if o.binding.query_id})
        query_families = sorted(
            {o.binding.query_family for o in obs_sorted if o.binding.query_family}
        )
        sectors = sorted(
            {o.binding.sector_slug for o in obs_sorted if o.binding.sector_slug}
        )
        axes = sorted({o.binding.axis_code for o in obs_sorted if o.binding.axis_code})

        providers = sorted(
            {
                provider
                for observation in obs_sorted
                for provider in _providers_for_record(observation.record)
            }
        )
        provider_count = len(providers)

        # Fix 6: prefer the latest non-empty value for enrichable metadata.
        year = _pick_latest_nonempty_str(obs_sorted, "year")
        journal = _pick_latest_nonempty_str(obs_sorted, "journal")
        citation_count_str = _pick_latest_nonempty_str(obs_sorted, "citation_count")
        citation_count = _coerce_int(citation_count_str) if citation_count_str else 0

        status, warning = _classify_novelty(
            run_ids_ordered,
            providers_ordered,
            current_run_id,
            canonical_doi,
            canonical_title,
        )

        prior_title_only = any(
            observation.run_id != current_run_id
            and bool(_normalize_title(observation.record.get("title")))
            and not bool(_normalize_doi(observation.record.get("doi")))
            for observation in obs_sorted
        )
        current_has_doi = any(
            observation.run_id == current_run_id
            and bool(_normalize_doi(observation.record.get("doi")))
            for observation in obs_sorted
        )
        if prior_title_only and current_has_doi:
            status = "updated_metadata"

        if any(
            bool(observation.record.get("_triangulation_fallback"))
            for observation in obs_sorted
        ):
            warning = "|".join(
                item for item in (warning, "triangulation_fallback") if item
            )

        # Fix 7: non-root Jaccard members become duplicate_only so they
        # cannot inflate scientific-growth or demand-strength scores.
        jaccard_gid = jaccard_group_index.get(bucket, "")
        if jaccard_gid and jaccard_gid != evidence_id:
            status = "duplicate_only"
            if warning:
                warning = f"{warning}|jaccard_nonroot"
            else:
                warning = "jaccard_nonroot"

        records.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                canonical_doi=canonical_doi,
                canonical_title=canonical_title,
                normalized_title_hash=normalized_title_hash,
                first_seen_run_id=first_obs.run_id,
                latest_seen_run_id=latest_obs.run_id,
                first_seen_at_utc=first_obs.timestamp_utc,
                latest_seen_at_utc=latest_obs.timestamp_utc,
                providers_seen="|".join(providers),
                provider_count=provider_count,
                query_ids_seen="|".join(query_ids),
                query_families_seen="|".join(query_families),
                sector_candidates="|".join(sectors),
                axis_candidates="|".join(axes),
                year=year,
                journal=journal,
                citation_count=citation_count,
                record_novelty_status=status,
                record_recurrence_count=len(observations),
                jaccard_group_id=jaccard_gid,
                validity_warning=warning,
            )
        )

    records.sort(key=lambda r: r.evidence_id)
    return records, index


def _previous_run_id(run_timestamps: Mapping[str, str], current_run_id: str) -> str:
    """Return the run_id immediately preceding the current one, or ''."""
    ordered = sorted(
        run_timestamps.items(), key=lambda kv: (kv[1], kv[0])
    )
    prior = [rid for rid, _ in ordered if rid != current_run_id]
    return prior[-1] if prior else ""


def _pick_canonical_doi(observations: Sequence[_RunObservation]) -> str:
    for obs in observations:
        doi = _normalize_doi(obs.record.get("doi"))
        if doi:
            return doi
    return ""


def _pick_canonical_title(observations: Sequence[_RunObservation]) -> str:
    for obs in observations:
        title = str(obs.record.get("title") or "").strip()
        if title:
            return title
    return ""


def _pick_latest_nonempty_str(
    observations: Sequence[_RunObservation], field: str
) -> str:
    """Return the latest (most-recent) non-empty string value for *field*.

    Observations are expected to be sorted ascending by timestamp; this
    function iterates in reverse to find the most-recently-enriched value,
    preserving first-seen provenance while preferring richer later records.
    """
    for obs in reversed(list(observations)):
        val = str(obs.record.get(field) or "").strip()
        if val:
            return val
    return ""


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return 0


def _compute_jaccard_groups(
    buckets: Dict[Tuple[str, str], List[_RunObservation]],
    threshold: float = 0.85,
) -> Dict[Tuple[str, str], str]:
    """Assign jaccard_group_id to near-duplicate titles across buckets."""
    if not buckets:
        return {}

    # Compute a normalized-title token set per bucket (using the earliest title).
    bucket_tokens: Dict[Tuple[str, str], Set[str]] = {}
    for bucket, observations in buckets.items():
        canonical_title = _pick_canonical_title(observations)
        bucket_tokens[bucket] = _title_tokens(_normalize_title(canonical_title))

    ordered_buckets = sorted(bucket_tokens.keys(), key=_bucket_sort_key)
    parent: Dict[Tuple[str, str], Tuple[str, str]] = {b: b for b in ordered_buckets}

    def find(node: Tuple[str, str]) -> Tuple[str, str]:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: Tuple[str, str], b: Tuple[str, str]) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if _bucket_sort_key(ra) < _bucket_sort_key(rb):
            parent[rb] = ra
        else:
            parent[ra] = rb

    for i, bucket_a in enumerate(ordered_buckets):
        tokens_a = bucket_tokens[bucket_a]
        if not tokens_a:
            continue
        for bucket_b in ordered_buckets[i + 1:]:
            tokens_b = bucket_tokens[bucket_b]
            if not tokens_b:
                continue
            if _jaccard(tokens_a, tokens_b) >= threshold:
                union(bucket_a, bucket_b)

    groups: Dict[Tuple[str, str], str] = {}
    for bucket in ordered_buckets:
        root = find(bucket)
        groups[bucket] = _make_evidence_id(root)
    return groups


def _bucket_sort_key(bucket: Tuple[str, str]) -> Tuple[str, str]:
    kind, key = bucket
    kind_order = {"doi": "0", "title": "1", "source_id": "2", "unknown": "3"}
    return (kind_order.get(kind, "9"), key)


def _build_current_signal_components(
    *,
    buckets: Mapping[Tuple[str, str], Sequence[_RunObservation]],
    evidence_index: Mapping[Tuple[str, str], str],
    current_run_id: str,
) -> List[_SignalComponent]:
    """Build each current-run observation's signal components exactly once."""
    components: List[_SignalComponent] = []
    for bucket, observations in sorted(buckets.items(), key=lambda item: item[0]):
        evidence_id = evidence_index[bucket]
        current_obs = sorted(
            (
                observation
                for observation in observations
                if observation.run_id == current_run_id
            ),
            key=lambda observation: (
                observation.binding.query_id,
                str(observation.record.get("provider") or ""),
                observation.timestamp_utc,
            ),
        )
        for observation in current_obs:
            components.extend(
                _build_signal_components_for_observation(
                    obs=observation,
                    evidence_id=evidence_id,
                )
            )
    return components


def _build_construct_validity_signal_components(
    *,
    buckets: Mapping[Tuple[str, str], Sequence[_RunObservation]],
    evidence_index: Mapping[Tuple[str, str], str],
    current_run_id: str,
    current_signal_components: Sequence[_SignalComponent],
) -> List[_SignalComponent]:
    """Return historical construct-validity components plus reused current rows."""
    components = list(current_signal_components)
    for bucket, observations in sorted(buckets.items(), key=lambda item: item[0]):
        evidence_id = evidence_index[bucket]
        historical_observations = sorted(
            (
                observation
                for observation in observations
                if observation.run_id != current_run_id
            ),
            key=lambda observation: (
                observation.run_id,
                observation.binding.query_id,
                _canonical_provider_name(observation.record.get("provider")),
                _normalize_source_id(observation.record.get("source_id")),
                observation.timestamp_utc,
            ),
        )
        for observation in historical_observations:
            components.extend(
                _build_signal_components_for_observation(
                    obs=observation,
                    evidence_id=evidence_id,
                )
            )
    return components


def _make_signals(
    *,
    buckets: Mapping[Tuple[str, str], Sequence[_RunObservation]],
    evidence_index: Mapping[Tuple[str, str], str],
    current_run_id: str,
) -> List[CompetenceDemandSignal]:
    """Return the frozen-v1, de-duplicated compatibility projection."""
    signals_by_id: Dict[str, CompetenceDemandSignal] = {}
    for bucket, observations in sorted(buckets.items(), key=lambda item: item[0]):
        evidence_id = evidence_index[bucket]
        current_observations = sorted(
            (
                observation
                for observation in observations
                if observation.run_id == current_run_id
            ),
            key=lambda observation: (
                observation.binding.query_id,
                str(observation.record.get("provider") or ""),
                observation.timestamp_utc,
            ),
        )
        for observation in current_observations:
            for signal in _build_signals_for_observation(
                obs=observation,
                evidence_id=evidence_id,
            ):
                signals_by_id.setdefault(signal.signal_id, signal)

    return [signals_by_id[key] for key in sorted(signals_by_id)]


def _historical_signal_ids(
    *,
    buckets: Dict[Tuple[str, str], List[_RunObservation]],
    evidence_index: Mapping[Tuple[str, str], str],
    current_run_id: str,
) -> Set[str]:
    """Reconstruct stable signal identities from every prior observation."""
    signal_ids: Set[str] = set()
    for bucket, observations in buckets.items():
        evidence_id = evidence_index[bucket]
        for obs in observations:
            if obs.run_id == current_run_id:
                continue
            signal_ids.update(
                signal.signal_id
                for signal in _build_signals_for_observation(
                    obs=obs,
                    evidence_id=evidence_id,
                )
            )
    return signal_ids


def _build_signals_for_observation(
    *,
    obs: _RunObservation,
    evidence_id: str,
) -> List[CompetenceDemandSignal]:
    """Build the frozen-v1 signals for the legacy compatibility projection."""
    record = obs.record
    title = str(record.get("title") or "").strip()
    subject_terms = _flatten_subject_terms(record.get("subject_terms"))
    abstract = _flatten_text_surface(record.get("abstract"))
    full_text = _flatten_text_surface(record.get("full_text"))
    source_query = str(record.get("source_query") or "").strip()

    surfaces = [
        ("title", title),
        ("subject", subject_terms),
        ("abstract", abstract),
        ("full_text", full_text),
    ]
    text_scope = " || ".join(text for _, text in surfaces if text)
    semantic_scope = "+".join(name for name, text in surfaces if text)
    if not text_scope:
        return []

    matches = _scan_legacy_compatibility_signals(
        " || ".join(part for part in (title, abstract, full_text) if part),
        subject_terms,
        source_query,
    )
    if not matches:
        return []

    evidence_text_hash = _text_hash(text_scope)
    is_metadata_only = _is_metadata_only(record)
    warning = "metadata_only_limitation" if is_metadata_only else ""
    signals: List[CompetenceDemandSignal] = []
    for pattern, matched_phrase in matches:
        confidence, review_status = _score_confidence(
            pattern=pattern,
            title=title,
            subject_terms=subject_terms,
            abstract=abstract,
            full_text=full_text,
            source_query=source_query,
            metadata_only=is_metadata_only,
        )
        signals.append(
            CompetenceDemandSignal(
                signal_id=_make_signal_id(
                    evidence_id,
                    pattern.signal_type,
                    matched_phrase,
                    evidence_text_hash,
                    LEGACY_COMPATIBILITY_CLASSIFIER_VERSION,
                ),
                evidence_id=evidence_id,
                run_id=obs.run_id,
                sector=obs.binding.sector_slug,
                axis_group=obs.binding.axis_group,
                axis_code=obs.binding.axis_code,
                query_id=obs.binding.query_id,
                query_family=obs.binding.query_family,
                semantic_scope=semantic_scope,
                signal_type=pattern.signal_type,
                competence_label=pattern.label,
                competence_description=pattern.description,
                demand_phrase=matched_phrase,
                learning_outcome_candidate=_learning_outcome_candidate(
                    pattern, matched_phrase, title
                ),
                evidence_text_scope=text_scope,
                evidence_text_hash=evidence_text_hash,
                confidence_score=confidence,
                classifier_version=LEGACY_COMPATIBILITY_CLASSIFIER_VERSION,
                manual_review_status=review_status,
                validity_warning=warning,
            )
        )
    return signals


def _build_signal_components_for_observation(
    *,
    obs: _RunObservation,
    evidence_id: str,
) -> List[_SignalComponent]:
    record = obs.record
    title = str(record.get("title") or "").strip()
    subject_terms = _flatten_subject_terms(record.get("subject_terms"))
    abstract = _flatten_text_surface(record.get("abstract"))
    full_text = _flatten_text_surface(record.get("full_text"))
    source_query = str(record.get("source_query") or "").strip()

    surfaces = [
        ("title", title),
        ("subject_terms", subject_terms),
        ("abstract", abstract),
        ("full_text", full_text),
    ]
    text_scope = " || ".join(text for _, text in surfaces if text)
    if not text_scope:
        return []

    matches = _scan_semantic_signals(surfaces, source_query)
    if not matches:
        return []

    evidence_text_hash = _text_hash(text_scope)
    is_metadata_only = _is_metadata_only(record)
    warning = "metadata_only_limitation" if is_metadata_only else ""
    source_provenance = _source_provenance_fields(
        obs=obs,
        evidence_id=evidence_id,
    )
    provenance_id = _make_provenance_id_from_fields(source_provenance)
    provenance_hash = hashlib.sha256(provenance_id.encode("utf-8")).hexdigest()

    components: List[_SignalComponent] = []
    for match in matches:
        pattern = match.pattern
        matched_phrase = match.matched_phrase
        confidence, review_status = _score_confidence(
            pattern=pattern,
            title=title,
            subject_terms=subject_terms,
            abstract=abstract,
            full_text=full_text,
            source_query=source_query,
            metadata_only=is_metadata_only,
        )
        signal_id = _make_signal_id(
            evidence_id,
            pattern.signal_type,
            matched_phrase,
            evidence_text_hash,
            CLASSIFIER_VERSION,
        )
        fragment_id = _make_fragment_id(
            evidence_id=evidence_id,
            signal_id=signal_id,
            provenance_id=provenance_id,
            source_field=match.source_field,
            span_start=match.span_start,
            span_end=match.span_end,
        )
        candidate_id = _make_candidate_id(
            signal_id=signal_id,
            evidence_id=evidence_id,
        )
        capability_proposition = _candidate_capability_proposition(
            pattern=pattern,
            span_text=match.span_text,
            source_field=match.source_field,
        )
        components.append(
            _SignalComponent(
                evidence_fragment=EvidenceFragment(
                    fragment_id=fragment_id,
                    evidence_id=evidence_id,
                    run_id=obs.run_id,
                    source_provenance_id=provenance_id,
                    source_provider=source_provenance["source_provider"],
                    source_provider_id=source_provenance["source_provider_id"],
                    source_retrieved_at_utc=source_provenance[
                        "source_retrieved_at_utc"
                    ],
                    source_query_id=source_provenance["source_query_id"],
                    source_query_text=source_provenance["source_query_text"],
                    source_field=match.source_field,
                    language=str(record.get("language") or "und").strip() or "und",
                    fragment_text=match.span_text,
                    span_start_offset=match.span_start,
                    span_end_offset=match.span_end,
                    surface_text_hash=_text_hash(match.source_text),
                    provenance_hash=provenance_hash,
                ),
                semantic_signal=SemanticSignal(
                    signal_id=signal_id,
                    fragment_id=fragment_id,
                    evidence_id=evidence_id,
                    run_id=obs.run_id,
                    source_provenance_id=provenance_id,
                    sector=obs.binding.sector_slug,
                    axis_group=obs.binding.axis_group,
                    axis_code=obs.binding.axis_code,
                    query_id=obs.binding.query_id,
                    query_family=obs.binding.query_family,
                    signal_type=pattern.signal_type,
                    signal_category_label=pattern.label,
                    signal_category_description=pattern.description,
                    matched_phrase=match.span_text,
                    confidence_score=confidence,
                    classifier_version=CLASSIFIER_VERSION,
                    negation_status="not_assessed",
                    speculation_status="not_assessed",
                    actor_text="",
                    action_text=matched_phrase,
                    object_text="",
                    context_text=match.source_text,
                    manual_review_status=review_status,
                    validity_warning=warning,
                ),
                competence_candidate=CompetenceCandidate(
                    candidate_id=candidate_id,
                    signal_id=signal_id,
                    fragment_id=fragment_id,
                    evidence_id=evidence_id,
                    run_id=obs.run_id,
                    sector=obs.binding.sector_slug,
                    axis_group=obs.binding.axis_group,
                    axis_code=obs.binding.axis_code,
                    source_provenance_ids=provenance_id,
                    fragment_ids=fragment_id,
                    candidate_label=_candidate_label(pattern, match.span_text),
                    candidate_definition=pattern.description,
                    capability_proposition=capability_proposition,
                    knowledge_dimension=_candidate_knowledge_dimension(pattern),
                    skill_dimension=_candidate_skill_dimension(pattern),
                    responsibility_autonomy_dimension=_candidate_ra_dimension(pattern),
                    candidate_status="candidate",
                    review_status="review_required",
                    exact_evidence_span=match.span_text,
                    exact_span_start_offset=match.span_start,
                    exact_span_end_offset=match.span_end,
                ),
            )
        )
    return components


def _build_construct_validity_tables(
    *,
    signal_components: Sequence[_SignalComponent],
    validation_decision_payloads: Sequence[Mapping[str, Any]],
    built_at_utc: str,
    evidence_titles_by_id: Mapping[str, str],
) -> Tuple[
    List[EvidenceFragment],
    List[SemanticSignal],
    List[CompetenceCandidate],
    List[ValidationDecision],
    List[CanonicalCompetence],
    List[SectorCompetenceAssignment],
]:
    fragments_by_id: Dict[str, EvidenceFragment] = {}
    semantic_by_id: Dict[Tuple[str, str], SemanticSignal] = {}
    candidates_by_id: Dict[str, CompetenceCandidate] = {}
    candidate_fragment_ids: Dict[str, Set[str]] = {}
    candidate_provenance_ids: Dict[str, Set[str]] = {}

    for component in signal_components:
        fragments_by_id.setdefault(
            component.evidence_fragment.fragment_id,
            component.evidence_fragment,
        )
        semantic_key = (
            component.semantic_signal.signal_id,
            component.semantic_signal.fragment_id,
        )
        semantic_by_id.setdefault(semantic_key, component.semantic_signal)
        candidate = component.competence_candidate
        candidate_fragment_ids.setdefault(candidate.candidate_id, set()).add(
            candidate.fragment_id
        )
        candidate_provenance_ids.setdefault(candidate.candidate_id, set()).add(
            candidate.source_provenance_ids
        )
        existing_candidate = candidates_by_id.get(candidate.candidate_id)
        # Candidate identity is cross-run stable. Select the lexicographically
        # smallest fragment deterministically as its scalar foreign-key reference.
        if (
            existing_candidate is None
            or candidate.fragment_id < existing_candidate.fragment_id
        ):
            candidates_by_id[candidate.candidate_id] = candidate

    for candidate_id, candidate in candidates_by_id.items():
        candidates_by_id[candidate_id] = replace(
            candidate,
            source_provenance_ids="|".join(
                sorted(candidate_provenance_ids[candidate_id])
            ),
            fragment_ids="|".join(sorted(candidate_fragment_ids[candidate_id])),
        )

    validation_decisions = _build_validation_decisions(
        candidates_by_id=candidates_by_id,
        payloads=validation_decision_payloads,
        built_at_utc=built_at_utc,
    )
    active_validation_decisions = _active_validation_decisions(validation_decisions)
    canonical_competences = _build_canonical_competences(
        candidates_by_id=candidates_by_id,
        validation_decisions=active_validation_decisions,
        evidence_titles_by_id=evidence_titles_by_id,
    )
    semantic_signal_rows = [
        semantic_by_id[key] for key in sorted(semantic_by_id)
    ]
    sector_assignments = _build_sector_competence_assignments(
        candidates_by_id=candidates_by_id,
        canonical_competences=canonical_competences,
        validation_decisions=active_validation_decisions,
        semantic_signals=semantic_signal_rows,
    )
    return (
        [fragments_by_id[key] for key in sorted(fragments_by_id)],
        semantic_signal_rows,
        [candidates_by_id[key] for key in sorted(candidates_by_id)],
        validation_decisions,
        canonical_competences,
        sector_assignments,
    )


def _build_validation_decisions(
    *,
    candidates_by_id: Mapping[str, CompetenceCandidate],
    payloads: Sequence[Mapping[str, Any]],
    built_at_utc: str,
) -> List[ValidationDecision]:
    decisions: List[ValidationDecision] = []
    decision_ids: Set[str] = set()
    allowed_statuses = {"accepted", "rejected", "review_required", "superseded"}
    for payload in payloads:
        candidate_id = str(payload.get("target_candidate_id") or "").strip()
        if not candidate_id or candidate_id not in candidates_by_id:
            raise CumulativeDatabaseError(
                f"unknown validation decision target candidate: {candidate_id or '<empty>'}"
            )
        candidate = candidates_by_id[candidate_id]
        decision_status = str(
            payload.get("decision_status") or payload.get("decision") or ""
        ).strip()
        if decision_status not in allowed_statuses:
            raise CumulativeDatabaseError(
                f"invalid validation decision status for {candidate_id}: {decision_status}"
            )
        canonical_label = str(payload.get("canonical_label") or "").strip()
        if decision_status == "accepted" and not canonical_label:
            raise CumulativeDatabaseError(
                "accepted validation decision requires canonical_label"
            )
        reviewer = str(payload.get("reviewer") or "").strip()
        if not reviewer:
            raise CumulativeDatabaseError("validation decision requires reviewer")
        if not _REVIEWER_IDENTIFIER_RE.fullmatch(reviewer):
            raise CumulativeDatabaseError(
                "invalid reviewer identifier; use a stable pseudonymous identifier"
            )
        decision_at = str(payload.get("decision_at_utc") or "").strip()
        if not decision_at:
            raise CumulativeDatabaseError(
                "validation decision requires decision_at_utc"
            )
        try:
            parsed_decision_at = datetime.fromisoformat(
                decision_at.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise CumulativeDatabaseError(
                "invalid decision_at_utc; require an ISO-8601 UTC timestamp"
            ) from exc
        utc_offset = parsed_decision_at.utcoffset()
        if (
            parsed_decision_at.tzinfo is None
            or utc_offset is None
            or utc_offset.total_seconds() != 0
        ):
            raise CumulativeDatabaseError(
                "invalid decision_at_utc; require an ISO-8601 UTC timestamp"
            )
        decision_reason = str(payload.get("decision_reason") or "").strip()
        if not decision_reason:
            raise CumulativeDatabaseError(
                "validation decision requires decision_reason"
            )
        superseded_id = str(
            payload.get("superseded_validation_decision_id") or ""
        ).strip()
        decision_id = str(payload.get("validation_decision_id") or "").strip()
        if not decision_id:
            seed = "\x1f".join(
                (candidate_id, canonical_label, decision_status, reviewer, decision_at)
            )
            decision_id = f"decision:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"
        if decision_id in decision_ids:
            raise CumulativeDatabaseError(
                f"duplicate validation decision identifier: {decision_id}"
            )
        decision_ids.add(decision_id)
        decisions.append(
            ValidationDecision(
                validation_decision_id=decision_id,
                target_candidate_id=candidate_id,
                canonical_label=canonical_label,
                decision_status=decision_status,
                reviewer=reviewer,
                decision_at_utc=decision_at,
                decision_reason=decision_reason,
                evidence_ids=candidate.evidence_id,
                fragment_ids=candidate.fragment_ids,
                source_provenance_ids=candidate.source_provenance_ids,
                superseded_validation_decision_id=superseded_id,
            )
        )

    decisions_by_id = {
        decision.validation_decision_id: decision for decision in decisions
    }
    for decision in decisions:
        superseded_id = decision.superseded_validation_decision_id
        if not superseded_id:
            continue
        if superseded_id == decision.validation_decision_id:
            raise CumulativeDatabaseError(
                "validation decision cannot supersede itself"
            )
        superseded_decision = decisions_by_id.get(superseded_id)
        if superseded_decision is None:
            raise CumulativeDatabaseError(
                f"unknown superseded validation decision: {superseded_id}"
            )
        if superseded_decision.target_candidate_id != decision.target_candidate_id:
            raise CumulativeDatabaseError(
                "superseded validation decision must target the same candidate"
            )
    decisions.sort(key=lambda row: row.validation_decision_id)
    return decisions


def _active_validation_decisions(
    validation_decisions: Sequence[ValidationDecision],
) -> List[ValidationDecision]:
    """Return decisions not superseded by a later ledger entry."""
    decisions_by_id = {
        decision.validation_decision_id: decision for decision in validation_decisions
    }
    for decision in validation_decisions:
        path_ids: Set[str] = set()
        current: Optional[ValidationDecision] = decision
        while current is not None:
            current_id = current.validation_decision_id
            if current_id in path_ids:
                raise CumulativeDatabaseError(
                    "validation decision supersession graph cannot contain cycles"
                )
            path_ids.add(current_id)
            superseded_id = current.superseded_validation_decision_id
            if not superseded_id:
                current = None
                continue
            current = decisions_by_id.get(superseded_id)
    superseded_ids = {
        decision.superseded_validation_decision_id
        for decision in validation_decisions
        if decision.superseded_validation_decision_id
    }
    active_decisions = [
        decision
        for decision in validation_decisions
        if decision.validation_decision_id not in superseded_ids
    ]
    active_decisions_by_candidate: Dict[str, int] = {}
    for decision in active_decisions:
        candidate_id = decision.target_candidate_id
        count = active_decisions_by_candidate.get(candidate_id, 0) + 1
        active_decisions_by_candidate[candidate_id] = count
        if count > 1:
            raise CumulativeDatabaseError(
                "validation decision set must not contain multiple active "
                f"decisions for candidate: {candidate_id}"
            )
    return active_decisions


def _build_canonical_competences(
    *,
    candidates_by_id: Mapping[str, CompetenceCandidate],
    validation_decisions: Sequence[ValidationDecision],
    evidence_titles_by_id: Mapping[str, str],
) -> List[CanonicalCompetence]:
    rows: Dict[str, CanonicalCompetence] = {}
    for decision in validation_decisions:
        if decision.decision_status != "accepted":
            continue
        label = re.sub(r"\s+", " ", decision.canonical_label).strip()
        candidate = candidates_by_id[decision.target_candidate_id]
        label_allowed, rejection_reason = canonical_label_is_allowed(
            label,
            retained_source_titles=(
                evidence_titles_by_id.get(candidate.evidence_id, ""),
            ),
        )
        if not label_allowed:
            raise CumulativeDatabaseError(
                "invalid canonical competence label blocked by provenance guard "
                f"({rejection_reason}): {label}"
            )
        canonical_id = (
            "canonical:"
            + hashlib.sha256(label.lower().encode("utf-8")).hexdigest()
        )
        rows.setdefault(
            canonical_id,
            CanonicalCompetence(
                canonical_competence_id=canonical_id,
                validation_decision_id=decision.validation_decision_id,
                source_candidate_id=candidate.candidate_id,
                preferred_label=label,
                canonical_definition=candidate.candidate_definition,
                aliases=(
                    candidate.candidate_label
                    if candidate.candidate_label != label
                    else ""
                ),
                validation_status="accepted",
                schema_version=DATABASE_SCHEMA_VERSION,
                provenance_guard_status="passed",
            ),
        )
    return [rows[key] for key in sorted(rows)]


def _build_sector_competence_assignments(
    *,
    candidates_by_id: Mapping[str, CompetenceCandidate],
    canonical_competences: Sequence[CanonicalCompetence],
    validation_decisions: Sequence[ValidationDecision],
    semantic_signals: Sequence[SemanticSignal],
) -> List[SectorCompetenceAssignment]:
    canonical_by_label = {
        re.sub(r"\s+", " ", row.preferred_label).strip().lower(): row
        for row in canonical_competences
    }
    semantic_by_fragment = {
        (signal.signal_id, signal.fragment_id): signal
        for signal in semantic_signals
    }
    assignments: Dict[str, SectorCompetenceAssignment] = {}
    for decision in validation_decisions:
        if decision.decision_status != "accepted":
            continue
        normalized_label = re.sub(r"\s+", " ", decision.canonical_label).strip().lower()
        canonical = canonical_by_label.get(normalized_label)
        if canonical is None:
            continue
        candidate = candidates_by_id[decision.target_candidate_id]
        contexts: Dict[Tuple[str, str, str], SemanticSignal] = {}
        for fragment_id in sorted(
            fragment_id
            for fragment_id in candidate.fragment_ids.split("|")
            if fragment_id
        ):
            signal = semantic_by_fragment.get((candidate.signal_id, fragment_id))
            if signal is None:
                continue
            context_key = (
                signal.sector.strip(),
                signal.axis_group.strip().upper(),
                signal.axis_code.strip().upper(),
            )
            contexts.setdefault(context_key, signal)

        for (sector, axis_group, axis_code), _signal in sorted(contexts.items()):
            try:
                canonical_axis = BlueDynamicsAxis[axis_group]
            except KeyError:
                continue
            if not sector or axis_code != canonical_axis.value:
                continue
            seed = "\x1f".join(
                (
                    canonical.canonical_competence_id,
                    decision.validation_decision_id,
                    sector,
                    axis_group,
                    axis_code,
                )
            )
            assignment_id = (
                "assignment:"
                + hashlib.sha256(seed.encode("utf-8")).hexdigest()
            )
            assignments.setdefault(
                assignment_id,
                SectorCompetenceAssignment(
                    assignment_id=assignment_id,
                    canonical_competence_id=canonical.canonical_competence_id,
                    validation_decision_id=decision.validation_decision_id,
                    source_candidate_id=candidate.candidate_id,
                    sector=sector,
                    axis_group=axis_group,
                    axis_code=axis_code,
                    evidence_ids=candidate.evidence_id,
                ),
            )
    return [assignments[key] for key in sorted(assignments)]


def _flatten_subject_terms(value: Any) -> str:
    if isinstance(value, list):
        return " ; ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return value.strip()
    return ""


def _flatten_text_surface(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, Mapping):
        return " ".join(
            str(value[key]).strip()
            for key in sorted(value)
            if str(value[key]).strip()
        )
    return str(value or "").strip()


def _providers_for_record(record: Mapping[str, Any]) -> Set[str]:
    providers: Set[str] = set()
    primary = _canonical_provider_name(record.get("provider"))
    if primary:
        providers.add(primary)
    supporting = record.get("supporting_providers")
    if isinstance(supporting, Mapping):
        values: Iterable[Any] = supporting.keys()
    elif isinstance(supporting, (list, tuple, set)):
        values = supporting
    elif isinstance(supporting, str):
        values = re.split(r"[|;,]", supporting)
    else:
        values = ()
    providers.update(
        canonical
        for value in values
        for canonical in [_canonical_provider_name(value)]
        if canonical
    )
    return providers


def _is_metadata_only(record: Mapping[str, Any]) -> bool:
    abstract = _flatten_text_surface(record.get("abstract"))
    full_text = _flatten_text_surface(record.get("full_text"))
    return not abstract and not full_text


def _score_confidence(
    *,
    pattern: _SignalPattern,
    title: str,
    subject_terms: str,
    abstract: str,
    full_text: str,
    source_query: str,
    metadata_only: bool,
) -> Tuple[float, str]:
    """Score signal confidence deterministically from where the match landed.

    Only title and subject_terms contribute to the positive evidence score.
    ``source_query`` is provenance-only and must not award confidence points.
    """
    title_lc = title.lower()
    subject_lc = subject_terms.lower()
    abstract_lc = abstract.lower()
    full_text_lc = full_text.lower()

    matched_in_title = any(phrase in title_lc for phrase in pattern.phrases)
    matched_in_subject = any(phrase in subject_lc for phrase in pattern.phrases)
    matched_in_abstract = any(phrase in abstract_lc for phrase in pattern.phrases)
    matched_in_full_text = any(phrase in full_text_lc for phrase in pattern.phrases)

    score = 0.0
    if matched_in_title:
        score += 0.55
    if matched_in_subject:
        score += 0.20
    if matched_in_abstract:
        score += 0.20
    if matched_in_full_text:
        score += 0.25

    if metadata_only:
        score -= 0.10

    score = max(0.05, min(0.95, round(score, 3)))
    review_status = "auto_accepted" if score >= 0.50 else "review_required"
    return score, review_status


def _learning_outcome_candidate(
    pattern: _SignalPattern, matched_phrase: str, title: str
) -> str:
    """Return a short suggested learning-outcome descriptor.

    The candidate is a deterministic string built from the matched phrase and
    the record title, without inventing pedagogical content.
    """
    if not title:
        return ""
    return f"{pattern.label} evidenced in: {title}"


def _reconcile_semantic_enrichment(
    evidence_records: List[EvidenceRecord],
    competence_demand_signals: Sequence[CompetenceDemandSignal],
    new_signal_ids: Set[str],
) -> None:
    """Upgrade recurrence only when a genuinely new stable signal was emitted."""
    if not new_signal_ids:
        return
    signals_by_evidence: Set[str] = {
        signal.evidence_id
        for signal in competence_demand_signals
        if signal.signal_id in new_signal_ids
    }
    for idx, record in enumerate(evidence_records):
        if (
            record.record_novelty_status == "repeated_record"
            and record.evidence_id in signals_by_evidence
        ):
            evidence_records[idx] = _replace_status(record, "semantic_enriched")


def _replace_status(record: EvidenceRecord, new_status: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=record.evidence_id,
        canonical_doi=record.canonical_doi,
        canonical_title=record.canonical_title,
        normalized_title_hash=record.normalized_title_hash,
        first_seen_run_id=record.first_seen_run_id,
        latest_seen_run_id=record.latest_seen_run_id,
        first_seen_at_utc=record.first_seen_at_utc,
        latest_seen_at_utc=record.latest_seen_at_utc,
        providers_seen=record.providers_seen,
        provider_count=record.provider_count,
        query_ids_seen=record.query_ids_seen,
        query_families_seen=record.query_families_seen,
        sector_candidates=record.sector_candidates,
        axis_candidates=record.axis_candidates,
        year=record.year,
        journal=record.journal,
        citation_count=record.citation_count,
        record_novelty_status=new_status,
        record_recurrence_count=record.record_recurrence_count,
        jaccard_group_id=record.jaccard_group_id,
        validity_warning=record.validity_warning,
    )


# ---------------------------------------------------------------------------
# Novelty metrics (Layer 2 → 3 bridge)
# ---------------------------------------------------------------------------

def _compute_novelty_metrics(
    *,
    evidence_records: Sequence[EvidenceRecord],
    competence_demand_signals: Sequence[CompetenceDemandSignal],
    current_run_id: str,
    buckets: Dict[Tuple[str, str], List[_RunObservation]],
    run_timestamps: Mapping[str, str],
    historical_signal_ids: Set[str],
) -> RunNoveltyMetrics:
    previous_run_id = _previous_run_id(run_timestamps, current_run_id)

    new_unique_doi = 0
    repeated_doi = 0
    updated_metadata = 0
    provider_enriched = 0
    semantic_new_signal = 0

    for record in evidence_records:
        if record.record_novelty_status == "new_record" and record.canonical_doi:
            new_unique_doi += 1
        if record.record_novelty_status == "repeated_record" and record.canonical_doi:
            repeated_doi += 1
        if record.record_novelty_status == "updated_metadata":
            updated_metadata += 1
        if record.record_novelty_status == "provider_enriched":
            provider_enriched += 1

    growth_eligible_evidence_ids = {
        record.evidence_id
        for record in evidence_records
        if record.record_novelty_status != "duplicate_only"
    }
    current_signal_ids = {
        signal.signal_id
        for signal in competence_demand_signals
        if signal.evidence_id in growth_eligible_evidence_ids
    }
    semantic_new_signal = len(current_signal_ids - historical_signal_ids)

    provider_counts: Dict[str, int] = {}
    for observations in buckets.values():
        for obs in observations:
            if obs.run_id != current_run_id:
                continue
            for provider in _providers_for_record(obs.record):
                provider_counts[provider] = provider_counts.get(provider, 0) + 1

    # provider_health_ok_zero_records: providers not present in the current run.
    active_providers = set(provider_counts.keys())
    known_providers = _known_providers_from_bindings(buckets)
    provider_health_ok_zero_records = sorted(known_providers - active_providers)

    total_current = sum(provider_counts.values())
    crossref_count = provider_counts.get("crossref", 0)
    crossref_dominance_ratio = (
        crossref_count / total_current if total_current else 0.0
    )

    provider_diversity_score = _diversity_score(provider_counts)
    query_counts = _current_query_counts(buckets, current_run_id)
    query_diversity_score = _diversity_score(query_counts)
    query_families_seen = _current_query_families(buckets, current_run_id)

    jaccard = _run_jaccard_similarity(buckets, current_run_id, previous_run_id)

    validity_warnings: List[str] = []
    if any(r.validity_warning for r in evidence_records):
        validity_warnings.append("evidence_row_warnings_present")
    if any(s.validity_warning for s in competence_demand_signals):
        validity_warnings.append("signal_row_warnings_present")
    if total_current == 0:
        validity_warnings.append("current_run_no_records")

    return RunNoveltyMetrics(
        current_run_id=current_run_id,
        previous_run_id=previous_run_id,
        new_unique_doi_count=new_unique_doi,
        repeated_doi_count=repeated_doi,
        updated_metadata_count=updated_metadata,
        provider_enriched_count=provider_enriched,
        semantic_new_signal_count=semantic_new_signal,
        provider_record_count_by_provider=provider_counts,
        provider_health_ok_zero_records=provider_health_ok_zero_records,
        jaccard_similarity_with_previous_run=jaccard,
        provider_diversity_score=provider_diversity_score,
        query_diversity_score=query_diversity_score,
        query_families_seen=query_families_seen,
        crossref_dominance_ratio=round(crossref_dominance_ratio, 4),
        validity_warnings=validity_warnings,
    )


def _known_providers_from_bindings(
    buckets: Dict[Tuple[str, str], List[_RunObservation]],
) -> Set[str]:
    providers: Set[str] = set()
    for observations in buckets.values():
        for obs in observations:
            providers.update(_providers_for_record(obs.record))
    return providers


def _current_query_counts(
    buckets: Dict[Tuple[str, str], List[_RunObservation]],
    current_run_id: str,
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for observations in buckets.values():
        for obs in observations:
            if obs.run_id != current_run_id or not obs.binding.query_id:
                continue
            counts[obs.binding.query_id] = counts.get(obs.binding.query_id, 0) + 1
    return counts


def _current_query_families(
    buckets: Dict[Tuple[str, str], List[_RunObservation]],
    current_run_id: str,
) -> List[str]:
    families: Set[str] = set()
    for observations in buckets.values():
        for obs in observations:
            if obs.run_id != current_run_id:
                continue
            family = str(obs.binding.query_family or "").strip()
            if family:
                families.add(family)
    return sorted(families)


def _diversity_score(counts: Mapping[str, int]) -> float:
    """Normalized entropy diversity score in [0, 1] rounded to 4 dp."""
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    n = len(counts)
    if n <= 1:
        return 0.0
    from math import log

    entropy = 0.0
    for value in counts.values():
        if value <= 0:
            continue
        p = value / total
        entropy -= p * log(p)
    max_entropy = log(n)
    if max_entropy == 0:
        return 0.0
    return round(entropy / max_entropy, 4)


def _run_jaccard_similarity(
    buckets: Dict[Tuple[str, str], List[_RunObservation]],
    current_run_id: str,
    previous_run_id: str,
) -> float:
    if not previous_run_id:
        return 0.0
    current: Set[Tuple[str, str]] = set()
    previous: Set[Tuple[str, str]] = set()
    for bucket, observations in buckets.items():
        run_ids = {obs.run_id for obs in observations}
        if current_run_id in run_ids:
            current.add(bucket)
        if previous_run_id in run_ids:
            previous.add(bucket)
    if not current and not previous:
        return 0.0
    intersection = len(current & previous)
    union = len(current | previous)
    if union == 0:
        return 0.0
    return round(intersection / union, 4)


def _match_registry_phrase(
    text_scope: str,
    registry: Mapping[str, Sequence[str]],
) -> Optional[Tuple[str, str]]:
    for family in sorted(registry):
        phrases = registry.get(family, ())
        for raw_phrase in phrases:
            phrase = str(raw_phrase or "").strip().lower()
            if not phrase:
                continue
            if phrase in text_scope:
                return family, phrase
    return None


# ---------------------------------------------------------------------------
# Serialization + manifest
# ---------------------------------------------------------------------------

def _hypothesis_fragment_rows(
    signals: Sequence[CompetenceDemandSignal],
    protocol: Optional[LiveQueryProtocol],
) -> List[Dict[str, Any]]:
    """Project evidence-bound signals into an auditable hypothesis-fragment ledger.

    This function operates on the frozen-v1 ``CompetenceDemandSignal`` projection
    rather than on schema-v2 entities directly.  Each row it emits is keyed to a
    signal produced by ``_make_signals`` and therefore to the same evidence record
    and canonical record identifier that anchors the corresponding schema-v2
    ``evidence_fragment`` and ``semantic_signal`` rows.  Downstream consumers
    should join on ``evidence_id`` to cross-reference with schema-v2 tables.
    """
    hypothesis_registry = protocol.hypotheses if protocol is not None else {}
    if not hypothesis_registry:
        return []

    rows: List[Dict[str, Any]] = []
    for signal in signals:
        text_scope = str(signal.evidence_text_scope or "").strip().lower()
        if not text_scope:
            continue
        signal_axis = str(signal.axis_group or "").strip().upper()
        semantic_fragment = (
            str(signal.demand_phrase or "").strip()
            or str(signal.competence_label or "").strip()
        )
        evidence_surface = str(signal.semantic_scope or "").strip()
        for hypothesis_id, declaration in sorted(hypothesis_registry.items()):
            required_axes = {axis.name for axis in declaration.required_axes}
            if required_axes and signal_axis not in required_axes:
                continue
            matched_indicator = _match_registry_phrase(
                text_scope,
                declaration.indicator_registry,
            )
            if matched_indicator is None:
                continue
            indicator_family, matched_phrase = matched_indicator
            matched_theory = _match_registry_phrase(
                text_scope,
                declaration.theory_registry,
            )
            theory_term_family = matched_theory[0] if matched_theory is not None else ""
            fragment_suffix = hashlib.sha256(
                "|".join(
                    (
                        signal.signal_id,
                        hypothesis_id,
                        indicator_family,
                        matched_phrase,
                        theory_term_family,
                    )
                ).encode("utf-8")
            ).hexdigest()[:12]
            rows.append(
                {
                    "fragment_id": (
                        f"fragment:{signal.signal_id}:{hypothesis_id}:{fragment_suffix}"
                    ),
                    "hypothesis_id": hypothesis_id,
                    "hypothesis_label": declaration.label,
                    "hypothesis_ids": hypothesis_id,
                    "signal_id": signal.signal_id,
                    "evidence_id": signal.evidence_id,
                    "run_id": signal.run_id,
                    "sector": signal.sector,
                    "axis_group": signal.axis_group,
                    "axis_code": signal.axis_code,
                    "signal_type": signal.signal_type,
                    "demand_phrase": signal.demand_phrase,
                    "matched_hypothesis_phrase": matched_phrase,
                    "theory_term_family": theory_term_family,
                    "indicator_family": indicator_family,
                    "semantic_fragment": semantic_fragment,
                    "evidence_surface": evidence_surface,
                    "semantic_scope": signal.semantic_scope,
                    "evidence_text_hash": signal.evidence_text_hash,
                    "classifier_version": signal.classifier_version,
                    "manual_review_status": signal.manual_review_status,
                    "validity_warning": signal.validity_warning,
                }
            )
    return sorted(rows, key=lambda row: str(row["fragment_id"]))


def _write_bundle(
    *,
    output_dir: Path,
    evidence_records: Sequence[EvidenceRecord],
    evidence_fragments: Sequence[EvidenceFragment],
    semantic_signals: Sequence[SemanticSignal],
    competence_candidates: Sequence[CompetenceCandidate],
    canonical_competences: Sequence[CanonicalCompetence],
    sector_competence_assignments: Sequence[SectorCompetenceAssignment],
    validation_decisions: Sequence[ValidationDecision],
    competence_demand_signals: Sequence[CompetenceDemandSignal],
    novelty_metrics: RunNoveltyMetrics,
    current_run_id: str,
    built_at_utc: str,
    workflow_context: Mapping[str, Any],
    archive_root: Optional[Path],
    live_runs_root: Optional[Path],
    protocol_path: Optional[Path],
    protocol: Optional[LiveQueryProtocol],
    current_run_dir: Path,
) -> List[Path]:
    evidence_rows = [r.to_dict() for r in evidence_records]
    fragment_v2_rows = [r.to_dict() for r in evidence_fragments]
    semantic_signal_rows = [r.to_dict() for r in semantic_signals]
    candidate_rows = [r.to_dict() for r in competence_candidates]
    canonical_rows = [r.to_dict() for r in canonical_competences]
    assignment_rows = [r.to_dict() for r in sector_competence_assignments]
    decision_rows = [r.to_dict() for r in validation_decisions]
    signal_rows = [s.to_dict() for s in competence_demand_signals]
    fragment_rows = _hypothesis_fragment_rows(competence_demand_signals, protocol)
    metrics_row = novelty_metrics.to_dict()

    files: List[Path] = []
    tabular_outputs = (
        (
            EVIDENCE_RECORDS_CSV,
            EVIDENCE_RECORDS_JSONL,
            EVIDENCE_RECORD_COLUMNS,
            evidence_rows,
        ),
        (
            EVIDENCE_FRAGMENTS_CSV,
            EVIDENCE_FRAGMENTS_JSONL,
            EVIDENCE_FRAGMENT_COLUMNS,
            fragment_v2_rows,
        ),
        (
            SEMANTIC_SIGNALS_CSV,
            SEMANTIC_SIGNALS_JSONL,
            SEMANTIC_SIGNAL_COLUMNS,
            semantic_signal_rows,
        ),
        (
            COMPETENCE_CANDIDATES_CSV,
            COMPETENCE_CANDIDATES_JSONL,
            COMPETENCE_CANDIDATE_COLUMNS,
            candidate_rows,
        ),
        (
            CANONICAL_COMPETENCES_CSV,
            CANONICAL_COMPETENCES_JSONL,
            CANONICAL_COMPETENCE_COLUMNS,
            canonical_rows,
        ),
        (
            SECTOR_COMPETENCE_ASSIGNMENTS_CSV,
            SECTOR_COMPETENCE_ASSIGNMENTS_JSONL,
            SECTOR_COMPETENCE_ASSIGNMENT_COLUMNS,
            assignment_rows,
        ),
        (
            VALIDATION_DECISIONS_CSV,
            VALIDATION_DECISIONS_JSONL,
            VALIDATION_DECISION_COLUMNS,
            decision_rows,
        ),
        (
            COMPETENCE_DEMAND_SIGNALS_CSV,
            COMPETENCE_DEMAND_SIGNALS_JSONL,
            COMPETENCE_DEMAND_SIGNAL_COLUMNS,
            signal_rows,
        ),
    )
    for csv_name, jsonl_name, columns, rows in tabular_outputs:
        csv_path = output_dir / csv_name
        _write_csv(csv_path, columns, rows)
        files.append(csv_path)
        jsonl_path = output_dir / jsonl_name
        _write_jsonl(jsonl_path, rows)
        files.append(jsonl_path)

    fragments_csv = output_dir / HYPOTHESIS_SEMANTIC_FRAGMENTS_CSV
    _write_csv(
        fragments_csv,
        HYPOTHESIS_SEMANTIC_FRAGMENT_COLUMNS,
        fragment_rows,
    )
    files.append(fragments_csv)

    fragments_jsonl = output_dir / HYPOTHESIS_SEMANTIC_FRAGMENTS_JSONL
    _write_jsonl(fragments_jsonl, fragment_rows)
    files.append(fragments_jsonl)

    metrics_json = output_dir / RUN_NOVELTY_METRICS_JSON
    _write_json_sorted(metrics_json, metrics_row)
    files.append(metrics_json)

    metrics_csv = output_dir / RUN_NOVELTY_METRICS_CSV
    _write_metrics_csv(metrics_csv, metrics_row)
    files.append(metrics_csv)

    manifest_path = output_dir / DATABASE_MANIFEST_FILENAME
    manifest = _build_manifest(
        output_dir=output_dir,
        files=files,
        current_run_id=current_run_id,
        built_at_utc=built_at_utc,
        workflow_context=workflow_context,
        archive_root=archive_root,
        live_runs_root=live_runs_root,
        protocol_path=protocol_path,
        current_run_dir=current_run_dir,
        evidence_row_count=len(evidence_records),
        evidence_fragment_count=len(evidence_fragments),
        semantic_signal_count=len(semantic_signals),
        competence_candidate_count=len(competence_candidates),
        canonical_competence_count=len(canonical_competences),
        sector_competence_assignment_count=len(sector_competence_assignments),
        validation_decision_count=len(validation_decisions),
        signal_row_count=len(competence_demand_signals),
        hypothesis_fragment_count=len(fragment_rows),
    )
    _write_json_sorted(manifest_path, manifest)
    files.append(manifest_path)

    checksums_path = output_dir / DATABASE_CHECKSUMS_FILENAME
    _write_checksums(checksums_path, files, output_dir)
    files.append(checksums_path)

    return files


def _write_metrics_csv(path: Path, metrics_row: Mapping[str, Any]) -> None:
    """Serialize the metrics dict as a single-row CSV with scalar fields."""
    flat = {}
    for key, value in metrics_row.items():
        if isinstance(value, (dict, list)):
            flat[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            flat[key] = value
    columns = sorted(flat.keys())
    _write_csv(path, columns, [flat])


def _build_manifest(
    *,
    output_dir: Path,
    files: Sequence[Path],
    current_run_id: str,
    built_at_utc: str,
    workflow_context: Mapping[str, Any],
    archive_root: Optional[Path],
    live_runs_root: Optional[Path],
    protocol_path: Optional[Path],
    current_run_dir: Path,
    evidence_row_count: int,
    evidence_fragment_count: int,
    semantic_signal_count: int,
    competence_candidate_count: int,
    canonical_competence_count: int,
    sector_competence_assignment_count: int,
    validation_decision_count: int,
    signal_row_count: int,
    hypothesis_fragment_count: int,
) -> Dict[str, Any]:
    return {
        "schema_version": DATABASE_SCHEMA_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "built_at_utc": built_at_utc,
        "current_run_id": current_run_id,
        "inputs": {
            "archive_root": str(archive_root).replace("\\", "/") if archive_root else "",
            "live_runs_root": (
                str(live_runs_root).replace("\\", "/") if live_runs_root else ""
            ),
            "protocol_path": (
                str(protocol_path).replace("\\", "/") if protocol_path else ""
            ),
            "current_run_dir": str(current_run_dir).replace("\\", "/"),
        },
        "outputs": sorted(
            str(f.relative_to(output_dir)).replace("\\", "/") for f in files
        ),
        "counts": {
            "evidence_records": evidence_row_count,
            "evidence_fragments": evidence_fragment_count,
            "semantic_signals": semantic_signal_count,
            "competence_candidates": competence_candidate_count,
            "canonical_competences": canonical_competence_count,
            "sector_competence_assignments": sector_competence_assignment_count,
            "validation_decisions": validation_decision_count,
            "competence_demand_signals": signal_row_count,
            "hypothesis_semantic_fragments": hypothesis_fragment_count,
        },
        "workflow_context": dict(sorted(workflow_context.items())),
        "allowed_record_novelty_status": list(ALLOWED_RECORD_NOVELTY_STATUS),
        "allowed_signal_types": list(ALLOWED_SIGNAL_TYPES),
        "allowed_manual_review_statuses": list(ALLOWED_MANUAL_REVIEW_STATUSES),
    }


def _write_checksums(
    path: Path, files: Sequence[Path], output_dir: Path
) -> None:
    """Write a `_checksums.sha256` file for every generated artefact."""
    entries: List[Tuple[str, str]] = []
    for file_path in files:
        if file_path == path:
            continue
        rel = str(file_path.relative_to(output_dir)).replace("\\", "/")
        entries.append((rel, _sha256_file(file_path)))
    entries.sort(key=lambda kv: kv[0])
    lines = [f"{digest}  {rel}" for rel, digest in entries]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(line + "\n")


# ---------------------------------------------------------------------------
# Convenience re-exports (for tests / CLI wrappers)
# ---------------------------------------------------------------------------

def evidence_record_from_dict(payload: Mapping[str, Any]) -> EvidenceRecord:
    """Reconstruct an :class:`EvidenceRecord` from a JSONL/CSV dict."""
    kwargs = {col: payload.get(col, "") for col in EVIDENCE_RECORD_COLUMNS}
    kwargs["provider_count"] = _coerce_int(kwargs.get("provider_count", 0))
    kwargs["citation_count"] = _coerce_int(kwargs.get("citation_count", 0))
    kwargs["record_recurrence_count"] = _coerce_int(
        kwargs.get("record_recurrence_count", 0)
    )
    return EvidenceRecord(**kwargs)


def competence_demand_signal_from_dict(
    payload: Mapping[str, Any],
) -> CompetenceDemandSignal:
    """Reconstruct a :class:`CompetenceDemandSignal` from a JSONL/CSV dict."""
    kwargs = {col: payload.get(col, "") for col in COMPETENCE_DEMAND_SIGNAL_COLUMNS}
    confidence = kwargs.get("confidence_score", 0.0)
    if isinstance(confidence, str) and confidence.strip():
        try:
            kwargs["confidence_score"] = float(confidence)
        except ValueError:
            kwargs["confidence_score"] = 0.0
    elif not isinstance(confidence, (int, float)):
        kwargs["confidence_score"] = 0.0
    return CompetenceDemandSignal(**kwargs)


__all__ = [
    "ALLOWED_MANUAL_REVIEW_STATUSES",
    "ALLOWED_RECORD_NOVELTY_STATUS",
    "ALLOWED_SIGNAL_TYPES",
    "CANONICAL_COMPETENCES_CSV",
    "CANONICAL_COMPETENCES_JSONL",
    "CLASSIFIER_VERSION",
    "COMPETENCE_CANDIDATES_CSV",
    "COMPETENCE_CANDIDATES_JSONL",
    "COMPETENCE_DEMAND_SIGNALS_CSV",
    "COMPETENCE_DEMAND_SIGNALS_JSONL",
    "COMPETENCE_DEMAND_SIGNAL_COLUMNS",
    "CANONICAL_COMPETENCE_COLUMNS",
    "COMPETENCE_CANDIDATE_COLUMNS",
    "CanonicalCompetence",
    "CompetenceCandidate",
    "CompetenceDemandSignal",
    "CumulativeDatabaseError",
    "CumulativeDatabaseResult",
    "DATABASE_CHECKSUMS_FILENAME",
    "DATABASE_MANIFEST_FILENAME",
    "DATABASE_SCHEMA_VERSION",
    "EVIDENCE_FRAGMENTS_CSV",
    "EVIDENCE_FRAGMENTS_JSONL",
    "EVIDENCE_FRAGMENT_COLUMNS",
    "EvidenceFragment",
    "EVIDENCE_RECORDS_CSV",
    "EVIDENCE_RECORDS_JSONL",
    "EVIDENCE_RECORD_COLUMNS",
    "EvidenceRecord",
    "LEGACY_COMPATIBILITY_CLASSIFIER_VERSION",
    "RUN_NOVELTY_METRICS_CSV",
    "RUN_NOVELTY_METRICS_JSON",
    "RunNoveltyMetrics",
    "SECTOR_COMPETENCE_ASSIGNMENTS_CSV",
    "SECTOR_COMPETENCE_ASSIGNMENTS_JSONL",
    "SECTOR_COMPETENCE_ASSIGNMENT_COLUMNS",
    "SEMANTIC_SIGNALS_CSV",
    "SEMANTIC_SIGNALS_JSONL",
    "SEMANTIC_SIGNAL_COLUMNS",
    "SectorCompetenceAssignment",
    "SemanticSignal",
    "VALIDATION_DECISIONS_CSV",
    "VALIDATION_DECISIONS_JSONL",
    "VALIDATION_DECISION_COLUMNS",
    "ValidationDecision",
    "build_cumulative_scientific_database",
    "canonical_label_is_allowed",
    "competence_demand_signal_from_dict",
    "evidence_record_from_dict",
]
