"""Cumulative Scientific Database — PR-190 Layers 2 & 3.

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
  scanner over the available metadata (title, subject_terms, source_query)
  and, if any competence-demand indicator is present, we emit one signal
  per matched category. The scanner never invents abstracts or citations —
  when the evidence is thin the signal is flagged with
  ``manual_review_status='review_required'`` and, where warranted, a
  ``metadata_only_limitation`` validity warning is attached.

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
from dataclasses import dataclass, field
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

DATABASE_SCHEMA_VERSION = "1.0.0"
"""Schema version stamped into every manifest produced by this module."""

CLASSIFIER_VERSION = "cumulative-db-semantic-v1"
"""Deterministic rule-based semantic classifier version tag."""

EVIDENCE_RECORDS_CSV = "evidence_records.csv"
EVIDENCE_RECORDS_JSONL = "evidence_records.jsonl"
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
    "hypothesis_ids",
    "signal_id",
    "evidence_id",
    "run_id",
    "sector",
    "axis_group",
    "axis_code",
    "signal_type",
    "demand_phrase",
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
    files: List[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization + hashing helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")
_TITLE_KEEP_RE = re.compile(r"[^a-z0-9 ]+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


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
    lookup: Dict[str, _ProtocolBinding] = {}
    with audit_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (row.get("protocol_binding") or "").strip() != "bound":
                continue
            query_text = (row.get("query_text") or "").strip().lower()
            if not query_text:
                continue
            axis_name = (row.get("axis_target") or "").strip()
            axis_code = ""
            axis_group = axis_name
            if axis_name:
                try:
                    axis_code = BlueDynamicsAxis[axis_name].value
                except KeyError:
                    axis_code = ""
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
        provider = re.sub(
            r"[^a-z0-9]+",
            "_",
            str(record.get("provider") or "unknown").strip().lower(),
        ).strip("_") or "unknown"
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
    query_ids: Sequence[str],
    current_run_id: str,
    previous_run_id: str,
    canonical_doi: str,
    canonical_title: str,
    query_ids_seen_semantic: bool,
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
    * upgrades to ``semantic_enriched`` when the record was already known but
      the current run also produced a semantic competence-demand signal;
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
            query_ids,
            current_run_id,
            previous_run_id,
            canonical_doi,
            query_ids_seen_semantic,
        )

    # seen_previous only — repeated record.
    return "repeated_record", warning


def _upgrade_if_enriched(
    run_ids: Sequence[str],
    providers: Sequence[str],
    query_ids: Sequence[str],
    current_run_id: str,
    previous_run_id: str,
    canonical_doi: str,
    query_ids_seen_semantic: bool,
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

    if query_ids_seen_semantic:
        return "semantic_enriched", ""

    if canonical_doi and previous_run_id:
        # Check whether previous runs had the same DOI or only saw the title.
        # We can't observe historical DOIs here without extra state, so we
        # conservatively return repeated_record; the caller sets
        # updated_metadata upstream if it detected a DOI upgrade.
        return "repeated_record", ""

    return "repeated_record", ""


# ---------------------------------------------------------------------------
# Semantic scanner (Layer 3)
# ---------------------------------------------------------------------------

def _scan_semantic_signals(
    text: str,
    subject_terms: str,
    source_query: str,
) -> List[Tuple[_SignalPattern, str]]:
    """Return `(pattern, matched_phrase)` tuples for every matching pattern.

    The scan is case-insensitive and inspects retained evidence surfaces:
    title, subject terms, and legally stored abstract/full text. ``source_query``
    is provenance metadata and must NOT contribute to positive
    semantic matching: query-only matches are not empirical evidence and must
    not produce competence signals, hypothesis fragments, demand scores, or gap
    evidence.  The ``source_query`` parameter is accepted (and retained) for
    provenance logging only.
    """
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

    observations, run_timestamps, current_records = _collect_observations(
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

    competence_demand_signals = _make_signals(
        buckets=buckets,
        evidence_index=evidence_index,
        current_run_id=resolved_run_id,
        current_records=current_records,
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

    written = _write_bundle(
        output_dir=output_path,
        evidence_records=evidence_records,
        competence_demand_signals=competence_demand_signals,
        novelty_metrics=novelty_metrics,
        current_run_id=resolved_run_id,
        built_at_utc=built_at,
        workflow_context=workflow_ctx,
        archive_root=archive_root_path,
        live_runs_root=live_runs_root_path,
        protocol_path=protocol_path_obj,
        current_run_dir=current_run_path,
    )

    return CumulativeDatabaseResult(
        output_dir=output_path,
        evidence_records=evidence_records,
        competence_demand_signals=competence_demand_signals,
        run_novelty_metrics=novelty_metrics,
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
    current_records = []
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

        run_ids_ordered = [o.run_id for o in obs_sorted]
        providers_ordered = [
            str(o.record.get("provider") or "").strip() for o in obs_sorted
        ]
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

        previous_run_id = _previous_run_id(run_timestamps, current_run_id)
        status, warning = _classify_novelty(
            run_ids_ordered,
            providers_ordered,
            query_ids,
            current_run_id,
            previous_run_id,
            canonical_doi,
            canonical_title,
            query_ids_seen_semantic=False,
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


def _make_signals(
    *,
    buckets: Dict[Tuple[str, str], List[_RunObservation]],
    evidence_index: Mapping[Tuple[str, str], str],
    current_run_id: str,
    current_records: Sequence[Mapping[str, Any]],
) -> List[CompetenceDemandSignal]:
    """Return de-duplicated semantic signals for the current run only."""
    del current_records  # retained for backward-compatible public call shape
    signals_by_id: Dict[str, CompetenceDemandSignal] = {}

    for bucket, observations in sorted(buckets.items(), key=lambda item: item[0]):
        current_obs = sorted(
            (o for o in observations if o.run_id == current_run_id),
            key=lambda o: (
                o.binding.query_id,
                str(o.record.get("provider") or ""),
                o.timestamp_utc,
            ),
        )
        evidence_id = evidence_index[bucket]
        for obs in current_obs:
            for signal in _build_signals_for_observation(
                obs=obs,
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

    matches = _scan_semantic_signals(
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
                    CLASSIFIER_VERSION,
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
                classifier_version=CLASSIFIER_VERSION,
                manual_review_status=review_status,
                validity_warning=warning,
            )
        )
    return signals


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
    primary = str(record.get("provider") or "").strip()
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
    providers.update(str(value).strip() for value in values if str(value).strip())
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
    crossref_count = provider_counts.get("Crossref", 0)
    crossref_dominance_ratio = (
        crossref_count / total_current if total_current else 0.0
    )

    provider_diversity_score = _diversity_score(provider_counts)
    query_counts = _current_query_counts(buckets, current_run_id)
    query_diversity_score = _diversity_score(query_counts)

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


# ---------------------------------------------------------------------------
# Serialization + manifest
# ---------------------------------------------------------------------------

def _hypothesis_fragment_rows(
    signals: Sequence[CompetenceDemandSignal],
) -> List[Dict[str, Any]]:
    """Project evidence-bound signals into an auditable hypothesis ledger."""
    rows: List[Dict[str, Any]] = []
    for signal in signals:
        hypothesis_ids: List[str] = []
        if signal.axis_group in ("MARITIME", "OCEANIC"):
            hypothesis_ids.append("H1")
        if signal.axis_group == "HYDRONIZATION":
            hypothesis_ids.append("H2")
        if signal.axis_group in ("MARINE", "OCEANIC"):
            hypothesis_ids.append("H3")
        if not hypothesis_ids:
            continue
        rows.append(
            {
                "fragment_id": f"fragment:{signal.signal_id}",
                "hypothesis_ids": "|".join(hypothesis_ids),
                "signal_id": signal.signal_id,
                "evidence_id": signal.evidence_id,
                "run_id": signal.run_id,
                "sector": signal.sector,
                "axis_group": signal.axis_group,
                "axis_code": signal.axis_code,
                "signal_type": signal.signal_type,
                "demand_phrase": signal.demand_phrase,
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
    competence_demand_signals: Sequence[CompetenceDemandSignal],
    novelty_metrics: RunNoveltyMetrics,
    current_run_id: str,
    built_at_utc: str,
    workflow_context: Mapping[str, Any],
    archive_root: Optional[Path],
    live_runs_root: Optional[Path],
    protocol_path: Optional[Path],
    current_run_dir: Path,
) -> List[Path]:
    evidence_rows = [r.to_dict() for r in evidence_records]
    signal_rows = [s.to_dict() for s in competence_demand_signals]
    fragment_rows = _hypothesis_fragment_rows(competence_demand_signals)
    metrics_row = novelty_metrics.to_dict()

    files: List[Path] = []

    evidence_csv = output_dir / EVIDENCE_RECORDS_CSV
    _write_csv(evidence_csv, EVIDENCE_RECORD_COLUMNS, evidence_rows)
    files.append(evidence_csv)

    evidence_jsonl = output_dir / EVIDENCE_RECORDS_JSONL
    _write_jsonl(evidence_jsonl, evidence_rows)
    files.append(evidence_jsonl)

    signals_csv = output_dir / COMPETENCE_DEMAND_SIGNALS_CSV
    _write_csv(signals_csv, COMPETENCE_DEMAND_SIGNAL_COLUMNS, signal_rows)
    files.append(signals_csv)

    signals_jsonl = output_dir / COMPETENCE_DEMAND_SIGNALS_JSONL
    _write_jsonl(signals_jsonl, signal_rows)
    files.append(signals_jsonl)

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
    "CLASSIFIER_VERSION",
    "COMPETENCE_DEMAND_SIGNALS_CSV",
    "COMPETENCE_DEMAND_SIGNALS_JSONL",
    "COMPETENCE_DEMAND_SIGNAL_COLUMNS",
    "CompetenceDemandSignal",
    "CumulativeDatabaseError",
    "CumulativeDatabaseResult",
    "DATABASE_CHECKSUMS_FILENAME",
    "DATABASE_MANIFEST_FILENAME",
    "DATABASE_SCHEMA_VERSION",
    "EVIDENCE_RECORDS_CSV",
    "EVIDENCE_RECORDS_JSONL",
    "EVIDENCE_RECORD_COLUMNS",
    "EvidenceRecord",
    "RUN_NOVELTY_METRICS_CSV",
    "RUN_NOVELTY_METRICS_JSON",
    "RunNoveltyMetrics",
    "build_cumulative_scientific_database",
    "competence_demand_signal_from_dict",
    "evidence_record_from_dict",
]
