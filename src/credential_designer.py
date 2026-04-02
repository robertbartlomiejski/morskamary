"""
Credential designer: auto-generate stackable micro-credentials for each
Blue Economy sector based on competence profiles.

Generates both *foundation* and *advanced* credentials per sector, as well
as cross-sector *bridge* credentials to support workforce transitions.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from src.core import BlueDynamicsAxis, Competence, CompetenceLevel, MicroCredential

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LEVEL_VALUE: Dict[CompetenceLevel, int] = {
    CompetenceLevel.FOUNDATIONAL: 1,
    CompetenceLevel.INTERMEDIATE: 2,
    CompetenceLevel.ADVANCED: 3,
    CompetenceLevel.EXPERT: 4,
}


def _sector_slug(sector: str) -> str:
    """Convert a sector name to a URL-safe slug."""
    s = sector.lower()
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def _axis_counts(competences: List[Competence]) -> Dict[str, int]:
    """Count competences per TMBD axis name."""
    counts: Dict[str, int] = {ax.name: 0 for ax in BlueDynamicsAxis}
    for comp in competences:
        counts[comp.axis.name] += 1
    return counts


def _dominant_axis(axis_counts: Dict[str, int]) -> str:
    """Return the axis name with the highest count (ties → MARITIME)."""
    return max(axis_counts, key=lambda k: (axis_counts[k], k == "MARITIME"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calculate_ects(competences: List[Competence]) -> int:
    """Calculate ECTS credits based on competence levels.

    Base: 10 ECTS.  +1 per ADVANCED competence (max +3); +1 per EXPERT (max +2).
    Capped at 15.

    Args:
        competences: Competences included in the credential.

    Returns:
        ECTS credit value between 10 and 15.
    """
    base = 10
    advanced_bonus = min(
        3,
        sum(1 for c in competences if c.level == CompetenceLevel.ADVANCED),
    )
    expert_bonus = min(
        2,
        sum(1 for c in competences if c.level == CompetenceLevel.EXPERT),
    )
    return min(15, base + advanced_bonus + expert_bonus)


def assign_eqf_level(competences: List[Competence]) -> int:
    """Assign an EQF level from 4–7 based on the average competence level.

    Args:
        competences: Competences included in the credential.

    Returns:
        EQF level integer (4, 5, 6, or 7).
    """
    if not competences:
        return 4
    avg = sum(_LEVEL_VALUE[c.level] for c in competences) / len(competences)
    if avg > 3.5:
        return 7
    if avg > 2.5:
        return 6
    if avg > 1.5:
        return 5
    return 4


def define_assessment(sector: str, axis_counts: Dict[str, int]) -> str:
    """Return an appropriate assessment method string for a credential.

    Args:
        sector: Sector name (used as context hint).
        axis_counts: Mapping of axis name → competence count.

    Returns:
        Human-readable assessment method description.
    """
    dominant = _dominant_axis(axis_counts)

    marine_count = axis_counts.get("MARINE", 0)
    oceanic_count = axis_counts.get("OCEANIC", 0)
    maritime_count = axis_counts.get("MARITIME", 0)

    # Determine if clearly dominant or mixed
    total = max(1, marine_count + oceanic_count + maritime_count)
    dominant_pct = axis_counts.get(dominant, 0) / total

    if dominant_pct < 0.5:
        return "Portfolio of evidence + practical demonstration + reflective journal"

    if dominant == "MARINE":
        return "Fieldwork report + species identification portfolio + oral examination"
    if dominant == "OCEANIC":
        return "Policy brief + stakeholder engagement simulation + written examination"
    # MARITIME
    return "Technical project + digital skills assessment + industry case study"


def design_sector_credential(
    sector: str,
    competences: List[Competence],
    level_suffix: str = "foundation",
) -> MicroCredential:
    """Create a primary micro-credential for a given sector.

    Args:
        sector: Blue Economy sector name.
        competences: Competences included in this credential.
        level_suffix: ``"foundation"`` or ``"advanced"``.

    Returns:
        Populated :class:`MicroCredential` object.
    """
    slug = _sector_slug(sector)
    cred_id = f"microcred_{slug}_{level_suffix}"
    title = f"Blue Economy {sector} - {level_suffix.title()} Micro-Credential"

    ects = calculate_ects(competences)
    eqf = assign_eqf_level(competences)
    counts = _axis_counts(competences)
    assessment = define_assessment(sector, counts)

    comp_ids = [c.id for c in competences]

    # Provenance sources
    sources: List[Dict[str, Any]] = []
    for comp in competences:
        if comp.source_metadata:
            sources.append(
                {
                    "file": comp.source_metadata.get("file", ""),
                    "row": comp.source_metadata.get("row", ""),
                    "competence_id": comp.id,
                }
            )

    # Prerequisites
    if level_suffix == "foundation":
        prerequisites: List[str] = []
    else:
        prerequisites = [f"microcred_{slug}_foundation"]

    stackability = (
        f"Stackable with {sector} Advanced micro-credential. "
        "Can be combined with cross-sector bridge credentials."
    )

    dominant = _dominant_axis(counts)
    description = (
        f"Competence credential for {sector} professionals. "
        f"Primary TMBD axis: {dominant}. "
        f"Covers {len(comp_ids)} competences at {level_suffix} level."
    )

    return MicroCredential(
        id=cred_id,
        title=title,
        competences=comp_ids,
        description=description,
        sector=sector,
        ects=ects,
        eqf_level=eqf,
        assessment_method=assessment,
        prerequisites=prerequisites,
        stackability_rules=stackability,
        sources=sources,
    )


def design_bridge_credential(
    sector_a: str,
    sector_b: str,
    bridge_competences: List[Competence],
) -> MicroCredential:
    """Create a transition credential enabling movement from *sector_a* to *sector_b*.

    Args:
        sector_a: Source sector.
        sector_b: Target sector.
        bridge_competences: Competences that bridge the gap.

    Returns:
        Populated :class:`MicroCredential` object.
    """
    slug_a = _sector_slug(sector_a)
    slug_b = _sector_slug(sector_b)
    cred_id = f"microcred_bridge_{slug_a}_{slug_b}"
    title = f"Blue Economy Transition: {sector_a} → {sector_b}"

    ects = calculate_ects(bridge_competences)
    eqf = assign_eqf_level(bridge_competences)
    counts = _axis_counts(bridge_competences)
    assessment = define_assessment(f"{sector_a}→{sector_b}", counts)

    comp_ids = [c.id for c in bridge_competences]

    sources: List[Dict[str, Any]] = []
    for comp in bridge_competences:
        if comp.source_metadata:
            sources.append(
                {
                    "file": comp.source_metadata.get("file", ""),
                    "row": comp.source_metadata.get("row", ""),
                    "competence_id": comp.id,
                }
            )

    stackability = (
        f"Bridge credential enabling transition from {sector_a} to {sector_b}."
    )

    description = (
        f"Cross-sector transition credential from {sector_a} to {sector_b}. "
        f"Covers {len(comp_ids)} bridge competences."
    )

    return MicroCredential(
        id=cred_id,
        title=title,
        competences=comp_ids,
        description=description,
        sector=f"{sector_a} → {sector_b}",
        ects=ects,
        eqf_level=eqf,
        assessment_method=assessment,
        prerequisites=[f"microcred_{slug_a}_foundation"],
        stackability_rules=stackability,
        sources=sources,
    )


def design_credentials_all_sectors(
    sector_competences: Dict[str, List[Competence]],
) -> Dict[str, List[MicroCredential]]:
    """Generate foundation and advanced credentials for every sector.

    Args:
        sector_competences: Mapping of sector name → list of :class:`Competence`.

    Returns:
        Mapping of sector name → ``[foundation_cred, advanced_cred]``.
    """
    result: Dict[str, List[MicroCredential]] = {}
    for sector, comps in sector_competences.items():
        if not comps:
            continue
        foundation = design_sector_credential(sector, comps, "foundation")
        advanced = design_sector_credential(sector, comps, "advanced")
        result[sector] = [foundation, advanced]
    return result


def calculate_pathways(
    credentials: Dict[str, List[MicroCredential]],
) -> Dict[str, Any]:
    """Build a pathway graph of credential nodes and prerequisite edges.

    Args:
        credentials: Output of :func:`design_credentials_all_sectors`.

    Returns:
        Dict with ``"nodes"`` and ``"edges"`` lists for graph rendering.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []

    for sector, cred_list in credentials.items():
        for cred in cred_list:
            nodes.append(
                {
                    "id": cred.id,
                    "title": cred.title,
                    "sector": cred.sector,
                    "eqf": cred.eqf_level,
                    "ects": cred.ects,
                }
            )
            for prereq in cred.prerequisites:
                edges.append({"from": prereq, "to": cred.id})

    return {"nodes": nodes, "edges": edges}
