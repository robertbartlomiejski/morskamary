"""
Core utilities and data structures for Blue Sociology analysis.
Authoritative shared domain model for morskamary.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
from enum import Enum


class BlueDynamicsAxis(Enum):
    """Tripartite Model of Blue Dynamics (TMBD) axes."""
    MARINE = "M"
    MARITIME = "T"
    OCEANIC = "O"


class CompetenceLevel(Enum):
    """Competence proficiency levels."""
    FOUNDATIONAL = 1
    INTERMEDIATE = 2
    ADVANCED = 3
    EXPERT = 4


class RequirementKind(Enum):
    """Whether a row is treated as a skill or a competence."""
    SKILL = "skill"
    COMPETENCE = "competence"


CANONICAL_SECTOR_ORDER: List[str] = [
    "blue-biotech",
    "coastal-tourism",
    "desalination",
    "infra-robotics",
    "living-resources",
    "non-living-resources",
    "renewable-energy",
    "maritime-defence",
    "maritime-transport",
    "port-activities",
    "research-innovation",
    "ship-repair",
]

SECTOR_LABELS_BY_SLUG: Dict[str, str] = {
    "blue-biotech": "Blue Biotech",
    "coastal-tourism": "Coastal Tourism",
    "desalination": "Desalination",
    "infra-robotics": "Infra & Robotics",
    "living-resources": "Living Res.",
    "non-living-resources": "Non-living Res.",
    "renewable-energy": "Renewable Energy",
    "maritime-defence": "Maritime Defence",
    "maritime-transport": "Maritime Transport",
    "port-activities": "Port Activities",
    "research-innovation": "R&I",
    "ship-repair": "Ship Repair",
}

SECTOR_ALIASES: Dict[str, str] = {
    "blue biotech": "blue-biotech",
    "blue-biotech": "blue-biotech",
    "coastal tourism": "coastal-tourism",
    "coastal-tourism": "coastal-tourism",
    "desalination": "desalination",
    "infra & robotics": "infra-robotics",
    "infrastructure & robotics": "infra-robotics",
    "infra-robotics": "infra-robotics",
    "renewable energy (wind-ocean)": "renewable-energy",
    "renewable energy (wind/ocean)": "renewable-energy",
    "non-living resources (mining)": "non-living-resources",
    "ship repair & shipbuilding": "ship-repair",
    "living resources (fisheries-aqua)": "living-resources",
    "living resources (fisheries/aqua)": "living-resources",
    "r&i (research & innovation)": "research-innovation",
    "r & i (research & innovation)": "research-innovation",
    "living res.": "living-resources",
    "living resources": "living-resources",
    "living-resources": "living-resources",
    "non-living res.": "non-living-resources",
    "non-living resources": "non-living-resources",
    "non-living-resources": "non-living-resources",
    "renewable energy": "renewable-energy",
    "renewable-energy": "renewable-energy",
    "offshore energy": "renewable-energy",
    "offshore-energy": "renewable-energy",
    "maritime defence": "maritime-defence",
    "maritime-defence": "maritime-defence",
    "maritime transport": "maritime-transport",
    "maritime-transport": "maritime-transport",
    "port activities": "port-activities",
    "port-activities": "port-activities",
    "r&i": "research-innovation",
    "r & i": "research-innovation",
    "research & innovation": "research-innovation",
    "research-innovation": "research-innovation",
    "ship repair": "ship-repair",
    "ship-repair": "ship-repair",
}


def normalize_sector_name(sector: str) -> str:
    """Normalize sector strings to canonical slug form."""
    normalized = " ".join(str(sector).strip().lower().replace("&", " & ").split())
    if normalized in SECTOR_ALIASES:
        return SECTOR_ALIASES[normalized]
    slug = normalized.replace(" & ", "-").replace("/", "-").replace(".", "").replace(" ", "-")
    return SECTOR_ALIASES.get(slug, slug)


def sector_label(sector_slug: str) -> str:
    """Return human-readable sector label from slug."""
    normalized = normalize_sector_name(sector_slug)
    return SECTOR_LABELS_BY_SLUG.get(normalized, normalized.replace("-", " ").title())


@dataclass
class SourceRef:
    """Light provenance record."""
    file: str
    row: int
    column: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "row": self.row,
            "column": self.column,
            "note": self.note,
        }


@dataclass
class Competence:
    """
    A single Blue Social Competence drawn from the University of Szczecin baseline.

    Fields
    ------
    id          : Unique identifier (e.g. ``blue_comp_a_1``).
    name        : Human-readable competence name.
    description : Short description or key focus area.
    axis        : TMBD axis (MARINE / MARITIME / OCEANIC).
    level       : Proficiency level (FOUNDATIONAL … EXPERT).
    keywords    : Discovery keywords for search and filtering.
    dimension   : Single-letter dimension code (A / B / C / D).
    requirement_kind : Whether this row is a SKILL or a COMPETENCE.
    source      : Optional provenance record (CSV file, row, column).
    """
    id: str
    name: str
    description: str
    axis: BlueDynamicsAxis
    level: CompetenceLevel
    keywords: List[str]
    dimension: str = ""
    requirement_kind: RequirementKind = RequirementKind.COMPETENCE
    source: Optional[SourceRef] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "axis": self.axis.value,
            "axis_name": self.axis.name,
            "level": self.level.name,
            "keywords": self.keywords,
            "dimension": self.dimension,
            "requirement_kind": self.requirement_kind.value,
            "source": self.source.to_dict() if self.source else None,
        }


@dataclass
class SectorRequirement:
    """
    One sector-specific operationalisation of a baseline competence.

    A SectorRequirement record links a ``Competence`` to a particular blue
    economy sector and captures how that competence is expressed there.

    Fields
    ------
    competence_id    : FK to ``Competence.id``.
    sector           : Normalised sector slug (e.g. ``renewable-energy``).
    sector_label     : Human-readable sector label (e.g. ``Renewable Energy``).
    sector_text      : Sector-specific operationalisation text from the matrix.
    requirement_kind : SKILL or COMPETENCE.
    axis             : TMBD axis of the parent competence.
    dimension        : Single-letter dimension code.
    cluster_name     : Micro-credential cluster name, if applicable.
    source           : Optional provenance record.
    """
    competence_id: str
    sector: str
    sector_label: str
    sector_text: str
    requirement_kind: RequirementKind
    axis: BlueDynamicsAxis
    dimension: str = ""
    cluster_name: str = ""
    source: Optional[SourceRef] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "competence_id": self.competence_id,
            "sector": self.sector,
            "sector_label": self.sector_label,
            "sector_text": self.sector_text,
            "requirement_kind": self.requirement_kind.value,
            "axis": self.axis.value,
            "axis_name": self.axis.name,
            "dimension": self.dimension,
            "cluster_name": self.cluster_name,
            "source": self.source.to_dict() if self.source else None,
        }


@dataclass
class MicroCredential:
    """
    A stackable micro-credential aligned to one or more Blue Social Competences.

    Required fields
    ---------------
    id, title, competences, description, sector

    Optional but recommended for completeness
    -----------------------------------------
    learner_profile   : Who this credential is designed for.
    workload_hours    : Total learning hours.
    ects              : ECTS credit value (e.g. 2.0).
    eqf_level         : European Qualifications Framework level (1–8).
    assessment_method : How learners are assessed.
    prerequisites     : List of prerequisite credential IDs.
    learning_outcomes : List of learning outcome statements.
    stackability_rules: How this credential stacks with others.
    source_cluster    : Name of the micro-credential cluster, if applicable.
    """
    id: str
    title: str
    competences: List[str]
    description: str
    sector: str
    learner_profile: str = ""
    workload_hours: int = 0
    ects: Optional[float] = None
    eqf_level: Optional[int] = None
    assessment_method: str = ""
    prerequisites: List[str] = field(default_factory=list)
    learning_outcomes: List[str] = field(default_factory=list)
    stackability_rules: str = ""
    source_cluster: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "competences": self.competences,
            "description": self.description,
            "sector": normalize_sector_name(self.sector),
            "sector_label": sector_label(self.sector),
            "learner_profile": self.learner_profile,
            "workload_hours": self.workload_hours,
            "ects": self.ects,
            "eqf_level": self.eqf_level,
            "assessment_method": self.assessment_method,
            "prerequisites": self.prerequisites,
            "learning_outcomes": self.learning_outcomes,
            "stackability_rules": self.stackability_rules,
            "source_cluster": self.source_cluster,
        }


def load_competence_matrix(file_path: Union[str, Path]) -> List[Competence]:
    """Generic matrix loader kept for backward compatibility."""
    try:
        import pandas as pd  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "pandas is required to load competence matrices. Install with: pip install pandas openpyxl"
        ) from exc

    path = Path(file_path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    elif path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        raise ValueError(f"Unsupported file format: {path}")

    competences: List[Competence] = []
    for _, row in df.iterrows():
        axis_name = str(row.get("axis", "MARINE")).strip()
        level_name = str(row.get("level", "FOUNDATIONAL")).strip()
        competences.append(
            Competence(
                id=str(row.get("id", "")).strip(),
                name=str(row.get("name", "")).strip(),
                description=str(row.get("description", "")).strip(),
                axis=BlueDynamicsAxis[axis_name],
                level=CompetenceLevel[level_name],
                keywords=[part.strip() for part in str(row.get("keywords", "")).split(";") if part.strip()],
            )
        )
    return competences


def create_sample_competences() -> List[Competence]:
    """Create sample competences for demonstration and tests."""
    return [
        Competence(
            id="comp_marine_001",
            name="Marine Ecosystem Understanding",
            description="Comprehensive understanding of marine biophysical systems, species interactions, and ecosystem dynamics",
            axis=BlueDynamicsAxis.MARINE,
            level=CompetenceLevel.INTERMEDIATE,
            keywords=["marine biology", "ecology", "biodiversity", "fisheries"],
        ),
        Competence(
            id="comp_maritime_001",
            name="Maritime Infrastructure Management",
            description="Management of ports, fleets, grids, and maritime spatial planning infrastructure",
            axis=BlueDynamicsAxis.MARITIME,
            level=CompetenceLevel.ADVANCED,
            keywords=["ports", "maritime spatial planning", "infrastructure", "fleet management"],
        ),
        Competence(
            id="comp_oceanic_001",
            name="Ocean Governance and Cooperation",
            description="Cross-border ocean governance integration, hydrosocial literacy, and transcorporeal responsibility",
            axis=BlueDynamicsAxis.OCEANIC,
            level=CompetenceLevel.ADVANCED,
            keywords=["governance", "international cooperation", "policy", "sustainability"],
        ),
    ]
