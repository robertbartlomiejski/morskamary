"""
gap_model.py — Explicit multi-layer gap model for Blue Economy competence analysis.

Implements the four-layer gap model:
  1. demand_evidence  — static literature + live API-derived competences, by sector × QMBD axis
  2. supply_evidence  — baseline competences + existing coursework/credential/curriculum files
  3. missing_clusters — demand clusters not covered by supply
  4. priority_score   — composite score (7 equal-weight factors):
       gap_ratio + missing_count_normalized + evidence_frequency + recency
       + provider_confidence + multi_source_support + QMBD_axis_undercoverage

Each evidence item carries full provenance: origin, source_file, source_row,
provider, doi, title, year, sector, qmbd_axis, confidence_score, overlap_status,
supporting_providers.

Supply origin taxonomy
----------------------
static_baseline               — verified Univ. Szczecin Blue Social Competences baseline
existing_microcredential      — parsed from existing curriculum/microcredential CSV
generated_credential_previous_run — from outputs/credentials_database.json of a prior run
                                    (recommended, not verified institutional supply)
supply_file_unparsed          — supply file detected but not yet parsed into evidence
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Provenance-rich evidence item
# ---------------------------------------------------------------------------


@dataclass
class GapEvidence:
    """A single evidence item (demand or supply side) with full provenance.

    Attributes:
        competence_id: Unique ID of the source competence.
        name: Human-readable competence name.
        description: Short description or focus statement.
        sector: Blue economy sector this evidence applies to.
        qmbd_axis: QMBD axis name (MARINE, MARITIME, OCEANIC, HYDRONIZATION).
        origin: Provenance origin tag.
            Values: 'static_baseline' | 'static_literature' | 'live' | 'supply_file'
        source_file: Relative repo path (or URL) of the originating file.
        source_row: 1-based row index in source file; 0 for live / derived records.
        provider: Research provider or data source identifier (e.g. 'crossref',
            'scopus', 'baseline', 'credentials_database').
        doi: DOI string if available, else empty string.
        title: Paper or document title if available, else competence name.
        year: Publication/creation year string (e.g. '2023'), or empty string.
        confidence_score: Reliability score in [0.0, 1.0].
        overlap_status: 'demand_only' | 'covered' | 'supply_only'.
        supporting_providers: Additional provider IDs that corroborate this item.
        matched_supply_id: ID of the supply item that covered this demand item
            (set when overlap_status == 'covered'); None otherwise.
        matched_supply_origin: Origin of the matched supply item; None if not covered.
        match_method: How this item was matched: 'exact_id' | 'name_similarity';
            None if not covered.
        match_score: Jaccard similarity score for 'name_similarity' matches (0–1);
            1.0 for 'exact_id' matches; None if not covered.
    """

    competence_id: str
    name: str
    description: str
    sector: str
    qmbd_axis: str
    origin: str  # see supply origin taxonomy in module docstring
    source_file: str
    source_row: int
    provider: str
    doi: str
    title: str
    year: str
    confidence_score: float
    overlap_status: str  # 'demand_only' | 'covered' | 'supply_only'
    supporting_providers: List[str] = field(default_factory=list)
    # Item-level match provenance (populated when overlap_status == 'covered')
    matched_supply_id: Optional[str] = field(default=None)
    matched_supply_origin: Optional[str] = field(default=None)
    match_method: Optional[str] = field(default=None)  # 'exact_id' | 'name_similarity'
    match_score: Optional[float] = field(default=None)  # Jaccard score for name_similarity

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dictionary."""
        return {
            "competence_id": self.competence_id,
            "name": self.name,
            "description": self.description,
            "sector": self.sector,
            "qmbd_axis": self.qmbd_axis,
            "origin": self.origin,
            "source_file": self.source_file,
            "source_row": self.source_row,
            "provider": self.provider,
            "doi": self.doi,
            "title": self.title,
            "year": self.year,
            "confidence_score": self.confidence_score,
            "overlap_status": self.overlap_status,
            "supporting_providers": self.supporting_providers,
            "matched_supply_id": self.matched_supply_id,
            "matched_supply_origin": self.matched_supply_origin,
            "match_method": self.match_method,
            "match_score": self.match_score,
        }


# ---------------------------------------------------------------------------
# Cluster (sector × QMBD axis)
# ---------------------------------------------------------------------------


@dataclass
class GapCluster:
    """Gap cluster for one sector × QMBD axis combination.

    Attributes:
        sector: Blue economy sector name.
        qmbd_axis: QMBD axis name.
        demand_items: Evidence items representing demand for competences.
        supply_items: Evidence items representing available supply.
        missing_items: Demand items NOT covered by any supply item.
        priority_score: Composite priority score in [0.0, 1.0].
        coverage_method: How covered items were matched.
            Values: 'exact_id' | 'name_similarity' | 'mixed' | 'uncovered' | 'no_demand'
    """

    sector: str
    qmbd_axis: str
    demand_items: List[GapEvidence] = field(default_factory=list)
    supply_items: List[GapEvidence] = field(default_factory=list)
    missing_items: List[GapEvidence] = field(default_factory=list)
    priority_score: float = 0.0
    coverage_method: str = "no_demand"

    @property
    def gap_ratio(self) -> float:
        """Fraction of demand items not covered by supply."""
        if not self.demand_items:
            return 0.0
        return len(self.missing_items) / len(self.demand_items)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dictionary."""
        return {
            "sector": self.sector,
            "qmbd_axis": self.qmbd_axis,
            "demand_count": len(self.demand_items),
            "supply_count": len(self.supply_items),
            "missing_count": len(self.missing_items),
            "gap_ratio": round(self.gap_ratio, 4),
            "priority_score": round(self.priority_score, 4),
            "coverage_method": self.coverage_method,
            "demand_items": [e.to_dict() for e in self.demand_items],
            "supply_items": [e.to_dict() for e in self.supply_items],
            "missing_items": [e.to_dict() for e in self.missing_items],
        }


# ---------------------------------------------------------------------------
# Full model result
# ---------------------------------------------------------------------------


@dataclass
class GapModelResult:
    """Complete gap model result across all sectors and QMBD axes.

    Attributes:
        demand_evidence: Demand items grouped by sector.
        supply_evidence: Supply items grouped by sector.
        all_clusters: All sector × axis clusters (including zero-gap ones).
        missing_clusters: Clusters where gap_ratio > 0.
    """

    demand_evidence: Dict[str, List[GapEvidence]]
    supply_evidence: Dict[str, List[GapEvidence]]
    all_clusters: List[GapCluster]
    missing_clusters: List[GapCluster]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to plain dictionary (compact: counts only for evidence maps)."""
        return {
            "demand_sector_counts": {
                sector: len(items) for sector, items in self.demand_evidence.items()
            },
            "supply_sector_counts": {
                sector: len(items) for sector, items in self.supply_evidence.items()
            },
            "all_clusters": [c.to_dict() for c in self.all_clusters],
            "missing_clusters": [c.to_dict() for c in self.missing_clusters],
        }


# ---------------------------------------------------------------------------
# Priority score computation
# ---------------------------------------------------------------------------

_QMBD_AXES = ["MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION"]


def _normalise(value: float, minimum: float, maximum: float) -> float:
    """Linearly normalise *value* to [0, 1]; returns 0.5 if range is zero."""
    span = maximum - minimum
    if span == 0.0:
        return 0.5
    return (value - minimum) / span


def compute_priority_score(
    cluster: GapCluster,
    all_clusters: Sequence[GapCluster],
) -> float:
    """Compute a composite priority score in [0.0, 1.0] for *cluster*.

    The score is the equal-weight average of seven factors:

    1. gap_ratio                — fraction of demand not covered (cluster.gap_ratio)
    2. missing_count_normalized — missing item count normalised across all clusters
    3. evidence_frequency       — demand item count normalised across all clusters
    4. recency                  — average year of demand items (normalised)
    5. provider_confidence      — average confidence_score of demand items
    6. multi_source_support     — fraction of demand items with ≥1 supporting provider
    7. QMBD_axis_undercoverage  — fraction of sectors where this axis has >0 missing items

    Note: ``uniform_sector_weight`` (formerly ``sector_relevance``) has been
    removed from the formula because a constant 1.0 adds no discriminating power.
    If sector-specific weights are needed in future, they should be supplied via
    a dedicated mapping argument.

    Args:
        cluster: The cluster to score.
        all_clusters: Full set of clusters (used for normalisation and axis stats).

    Returns:
        Priority score as float in [0.0, 1.0].
    """
    demand_counts = [len(c.demand_items) for c in all_clusters]
    min_dc, max_dc = (
        (min(demand_counts), max(demand_counts)) if demand_counts else (0, 0)
    )
    missing_counts = [len(c.missing_items) for c in all_clusters]
    min_mc, max_mc = (
        (min(missing_counts), max(missing_counts)) if missing_counts else (0, 0)
    )

    # 1. gap_ratio
    f_gap_ratio = cluster.gap_ratio

    # 2. missing_count_normalized
    f_missing = _normalise(len(cluster.missing_items), min_mc, max_mc)

    # 3. evidence_frequency
    f_evidence = _normalise(len(cluster.demand_items), min_dc, max_dc)

    # 4. recency — parse years from demand items
    years: List[int] = []
    for item in cluster.demand_items:
        try:
            years.append(int(item.year))
        except (ValueError, TypeError):
            pass
    avg_year = sum(years) / len(years) if years else 0.0
    all_years: List[int] = []
    for c in all_clusters:
        for item in c.demand_items:
            try:
                all_years.append(int(item.year))
            except (ValueError, TypeError):
                pass
    min_y = min(all_years) if all_years else 0
    max_y = max(all_years) if all_years else 0
    f_recency = _normalise(avg_year, min_y, max_y) if avg_year else 0.5

    # 5. provider_confidence
    if cluster.demand_items:
        f_confidence = sum(i.confidence_score for i in cluster.demand_items) / len(
            cluster.demand_items
        )
    else:
        f_confidence = 0.0

    # 6. multi_source_support — fraction with at least one supporting_provider
    if cluster.demand_items:
        multi = sum(
            1 for i in cluster.demand_items if i.supporting_providers
        ) / len(cluster.demand_items)
    else:
        multi = 0.0

    # 7. QMBD_axis_undercoverage — fraction of sectors where this axis has missing items
    axis = cluster.qmbd_axis
    sectors_with_gap = sum(
        1
        for c in all_clusters
        if c.qmbd_axis == axis and c.missing_items
    )
    total_sectors_for_axis = sum(1 for c in all_clusters if c.qmbd_axis == axis)
    f_axis = (
        sectors_with_gap / total_sectors_for_axis
        if total_sectors_for_axis > 0
        else 0.0
    )

    score = (
        f_gap_ratio + f_missing + f_evidence + f_recency + f_confidence + multi + f_axis
    ) / 7.0
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Core model computation
# ---------------------------------------------------------------------------

_COVERAGE_STOPWORDS: frozenset = frozenset(
    {
        "and", "the", "for", "with", "from", "into", "that", "this", "are",
        "its", "has", "was", "not", "have", "been", "also", "their", "will",
        "can", "may", "use", "used", "using", "based", "blue", "ocean",
        "marine", "maritime", "oceanic", "sea", "water",
        # generic competence vocabulary — too common to be discriminating
        "skills", "skill", "competence", "competences", "competency",
        "ability", "abilities", "understanding", "awareness", "knowledge",
        "management", "development", "sector", "approach", "practice",
        "practices", "systems", "system", "process", "processes",
    }
)
_NAME_SIM_THRESHOLD: float = 0.30  # minimum Jaccard similarity for name-based coverage
_NAME_SIM_MIN_SHARED: int = 2      # minimum shared meaningful tokens required


def _name_tokens(name: str) -> frozenset:
    """Return meaningful lowercased tokens from *name* with stopwords removed.

    Tokenization uses word characters only (handles punctuation such as
    hyphens, slashes, and trailing commas transparently).
    """
    return frozenset(
        t
        for t in re.findall(r"[a-zA-Z]+", name.lower())
        if len(t) > 3 and t not in _COVERAGE_STOPWORDS
    )


def _name_similarity_covers(demand_tokens: frozenset, supply_tokens: frozenset) -> bool:
    """Return True if supply tokens adequately cover demand tokens.

    Both the Jaccard threshold AND a minimum shared-token count must be met so
    that names sharing only one generic term (e.g. "digital skills" vs
    "business skills") are not falsely marked as covered.
    """
    shared = demand_tokens & supply_tokens
    if len(shared) < _NAME_SIM_MIN_SHARED:
        return False
    return _jaccard(demand_tokens, supply_tokens) >= _NAME_SIM_THRESHOLD


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Jaccard similarity between two token sets; returns 0.0 if both empty."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def compute_gap_model(
    demand_evidence: Dict[str, List[GapEvidence]],
    supply_evidence: Dict[str, List[GapEvidence]],
    sectors: Optional[List[str]] = None,
    qmbd_axes: Optional[List[str]] = None,
) -> GapModelResult:
    """Build the full gap model from pre-collected demand and supply evidence.

    Coverage rule (axis-sensitive):
      A demand item is considered *covered* if, within the **same sector × axis**:

      1. **Exact ID match** — supply contains an item with the same competence_id.
      2. **Name similarity** — at least one supply item's name tokens overlap with
         the demand item's name tokens with a Jaccard similarity ≥
         ``_NAME_SIM_THRESHOLD`` (default 0.30) after stopword removal.

    Cross-axis coverage is intentionally **not** applied: a supply item on the
    MARITIME axis cannot cover a demand item on the MARINE axis within the same
    sector, preventing axis-leakage false positives.

    Args:
        demand_evidence: Dict mapping sector → list of demand GapEvidence items.
        supply_evidence: Dict mapping sector → list of supply GapEvidence items.
        sectors: Optional list of sector names to include. Defaults to all sectors
            present in demand_evidence.
        qmbd_axes: Optional list of axis names to include. Defaults to all four
            canonical QMBD axes.

    Returns:
        GapModelResult with clusters and gap metrics.
    """
    if qmbd_axes is None:
        qmbd_axes = _QMBD_AXES
    if sectors is None:
        sectors = sorted(set(demand_evidence) | set(supply_evidence))

    all_clusters: List[GapCluster] = []

    for sector in sectors:
        d_items = demand_evidence.get(sector, [])
        s_items = supply_evidence.get(sector, [])

        for axis in qmbd_axes:
            d_axis = [i for i in d_items if i.qmbd_axis == axis]
            s_axis = [i for i in s_items if i.qmbd_axis == axis]
            supply_axis_ids = {i.competence_id for i in s_axis}

            # Pre-compute token sets for axis-scoped supply items only
            supply_token_sets: List[frozenset] = [
                _name_tokens(si.name) for si in s_axis
            ]
            supply_id_to_item: Dict[str, GapEvidence] = {
                si.competence_id: si for si in s_axis
            }

            missing: List[GapEvidence] = []
            exact_covered = 0
            sim_covered = 0
            # Track indices of supply items used for name-similarity coverage
            sim_covered_supply_indices: set = set()
            for item in d_axis:
                if item.competence_id in supply_axis_ids:
                    # Rule 1: exact ID match within same sector × axis
                    exact_covered += 1
                    matched_si = supply_id_to_item[item.competence_id]
                    item.matched_supply_id = matched_si.competence_id
                    item.matched_supply_origin = matched_si.origin
                    item.match_method = "exact_id"
                    item.match_score = 1.0
                else:
                    # Rule 2: name-similarity match within same sector × axis
                    item_tokens = _name_tokens(item.name)
                    matched = False
                    for s_idx, st in enumerate(supply_token_sets):
                        if st and _name_similarity_covers(item_tokens, st):
                            sim_covered += 1
                            sim_covered_supply_indices.add(s_idx)
                            matched = True
                            score = _jaccard(item_tokens, st)
                            item.matched_supply_id = s_axis[s_idx].competence_id
                            item.matched_supply_origin = s_axis[s_idx].origin
                            item.match_method = "name_similarity"
                            item.match_score = round(score, 4)
                            break
                    if not matched:
                        missing.append(item)

            # Determine dominant coverage method for this cluster
            if not d_axis:
                coverage_method = "no_demand"
            elif exact_covered > 0 and sim_covered > 0:
                coverage_method = "mixed"
            elif exact_covered > 0:
                coverage_method = "exact_id"
            elif sim_covered > 0:
                coverage_method = "name_similarity"
            else:
                coverage_method = "uncovered"

            cluster = GapCluster(
                sector=sector,
                qmbd_axis=axis,
                demand_items=d_axis,
                supply_items=s_axis,
                missing_items=missing,
                coverage_method=coverage_method,
            )
            # Annotate overlap_status on supply items while indices are available
            d_ids = {i.competence_id for i in d_axis}
            for s_idx, item in enumerate(s_axis):
                if item.competence_id in d_ids or s_idx in sim_covered_supply_indices:
                    item.overlap_status = "covered"
                else:
                    item.overlap_status = "supply_only"
            all_clusters.append(cluster)

    # Update overlap_status on demand items
    for cluster in all_clusters:
        missing_ids = {i.competence_id for i in cluster.missing_items}
        for item in cluster.demand_items:
            if item.competence_id in missing_ids:
                item.overlap_status = "demand_only"
            else:
                item.overlap_status = "covered"

    # Compute priority scores
    for cluster in all_clusters:
        cluster.priority_score = compute_priority_score(cluster, all_clusters)

    missing_clusters = [c for c in all_clusters if c.missing_items]

    return GapModelResult(
        demand_evidence=demand_evidence,
        supply_evidence=supply_evidence,
        all_clusters=all_clusters,
        missing_clusters=missing_clusters,
    )
