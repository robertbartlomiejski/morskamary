"""
gap_model.py — Explicit multi-layer gap model for Blue Economy competence analysis.

Implements the four-layer gap model:
  1. demand_evidence  — static literature + live API-derived competences, by sector × QMBD axis
  2. supply_evidence  — baseline competences + existing coursework/credential/curriculum files
  3. missing_clusters — demand clusters not covered by supply
  4. priority_score   — composite score:
       evidence_frequency + recency + provider_confidence
       + multi_source_support + sector_relevance + QMBD_axis_undercoverage

Each evidence item carries full provenance: origin, source_file, source_row,
provider, doi, title, year, sector, qmbd_axis, confidence_score, overlap_status,
supporting_providers.
"""

from __future__ import annotations

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
    """

    competence_id: str
    name: str
    description: str
    sector: str
    qmbd_axis: str
    origin: str  # 'static_baseline' | 'static_literature' | 'live' | 'supply_file'
    source_file: str
    source_row: int
    provider: str
    doi: str
    title: str
    year: str
    confidence_score: float
    overlap_status: str  # 'demand_only' | 'covered' | 'supply_only'
    supporting_providers: List[str] = field(default_factory=list)

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
    """

    sector: str
    qmbd_axis: str
    demand_items: List[GapEvidence] = field(default_factory=list)
    supply_items: List[GapEvidence] = field(default_factory=list)
    missing_items: List[GapEvidence] = field(default_factory=list)
    priority_score: float = 0.0

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

    The score is the unweighted average of six factors:

    1. evidence_frequency     — demand item count normalised across all clusters
    2. recency                — average year of demand items (normalised)
    3. provider_confidence    — average confidence_score of demand items
    4. multi_source_support   — fraction of demand items with >1 supporting provider
    5. sector_relevance       — 1.0 (equal weight; reserved for future weighting)
    6. QMBD_axis_undercoverage— fraction of sectors where this axis has > 0 missing items

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

    # 1. evidence_frequency
    f_evidence = _normalise(len(cluster.demand_items), min_dc, max_dc)

    # 2. recency — parse years from demand items
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

    # 3. provider_confidence
    if cluster.demand_items:
        f_confidence = sum(i.confidence_score for i in cluster.demand_items) / len(
            cluster.demand_items
        )
    else:
        f_confidence = 0.0

    # 4. multi_source_support — fraction with at least one supporting_provider
    if cluster.demand_items:
        multi = sum(
            1 for i in cluster.demand_items if i.supporting_providers
        ) / len(cluster.demand_items)
    else:
        multi = 0.0

    # 5. sector_relevance (uniform)
    f_sector = 1.0

    # 6. QMBD_axis_undercoverage — fraction of sectors where this axis has missing items
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

    score = (f_evidence + f_recency + f_confidence + multi + f_sector + f_axis) / 6.0
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Core model computation
# ---------------------------------------------------------------------------


def _supply_ids_for_sector(supply_items: List[GapEvidence]) -> set[str]:
    """Return the set of competence IDs from supply items."""
    return {item.competence_id for item in supply_items}


def _supply_axes_for_sector(supply_items: List[GapEvidence]) -> set[str]:
    """Return the set of QMBD axes covered by supply for a sector."""
    return {item.qmbd_axis for item in supply_items}


def compute_gap_model(
    demand_evidence: Dict[str, List[GapEvidence]],
    supply_evidence: Dict[str, List[GapEvidence]],
    sectors: Optional[List[str]] = None,
    qmbd_axes: Optional[List[str]] = None,
) -> GapModelResult:
    """Build the full gap model from pre-collected demand and supply evidence.

    A demand item is considered *covered* if the same sector's supply evidence
    contains an item sharing its competence_id, OR if the supply already covers
    the same sector × axis combination AND the demand item's name tokens overlap
    with at least one supply item's name tokens.

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

        supply_ids = _supply_ids_for_sector(s_items)

        for axis in qmbd_axes:
            d_axis = [i for i in d_items if i.qmbd_axis == axis]
            s_axis = [i for i in s_items if i.qmbd_axis == axis]
            supply_axis_ids = {i.competence_id for i in s_axis}

            # Build supply name-token sets for soft matching
            supply_name_tokens: set[str] = set()
            for si in s_axis:
                supply_name_tokens.update(si.name.lower().split())

            missing: List[GapEvidence] = []
            covered_ids: List[str] = []
            for item in d_axis:
                if item.competence_id in supply_axis_ids or item.competence_id in supply_ids:
                    covered_ids.append(item.competence_id)
                else:
                    # Soft name-token overlap check
                    item_tokens = set(item.name.lower().split())
                    meaningful = {
                        t for t in item_tokens if len(t) > 3
                    }  # skip short stop-words
                    if meaningful and meaningful & supply_name_tokens:
                        covered_ids.append(item.competence_id)
                    else:
                        missing.append(item)

            cluster = GapCluster(
                sector=sector,
                qmbd_axis=axis,
                demand_items=d_axis,
                supply_items=s_axis,
                missing_items=missing,
            )
            all_clusters.append(cluster)

    # Update overlap_status on demand items
    for cluster in all_clusters:
        missing_ids = {i.competence_id for i in cluster.missing_items}
        for item in cluster.demand_items:
            if item.competence_id in missing_ids:
                item.overlap_status = "demand_only"
            else:
                item.overlap_status = "covered"
        for item in cluster.supply_items:
            d_ids = {i.competence_id for i in cluster.demand_items}
            if item.competence_id not in d_ids:
                item.overlap_status = "supply_only"
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
