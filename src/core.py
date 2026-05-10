"""
Core utilities and data structures for Blue Sociology analysis
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Union

if TYPE_CHECKING:
    from src.scientific_sources.models import LiteratureRecord


class BlueDynamicsAxis(Enum):
    """Quadripartite Model of Blue Dynamics (QMBD) axes.

    The original Tripartite Model (TMBD) comprised Marine/Maritime/Oceanic.
    The fourth dimension, Hydronization, extends the model following the Manus
    methodological review while remaining fully backward-compatible: all
    existing TMBD logic is preserved and the new axis is additive only.
    """

    MARINE = "M"  # Marine (biophysical agency)
    MARITIME = "T"  # Maritime (techno-economic and institutional mediation)
    OCEANIC = "O"  # Oceanic (planetary governance and hydrosocial subjectivity)
    HYDRONIZATION = "H"  # Hydronization (water-society co-constitution)


class CompetenceLevel(Enum):
    """Competence proficiency levels"""

    FOUNDATIONAL = 1
    INTERMEDIATE = 2
    ADVANCED = 3
    EXPERT = 4


@dataclass
class Competence:
    """
    Represents a single competence in Blue Sociology context

    Attributes:
        id: Unique identifier
        name: Competence name
        description: Detailed description
        axis: QMBD axis (Marine, Maritime, Oceanic, or Hydronization)
        level: Proficiency level
        keywords: Associated keywords for discovery
    """

    id: str
    name: str
    description: str
    axis: BlueDynamicsAxis
    level: CompetenceLevel
    keywords: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert competence to dictionary"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "axis": self.axis.value,
            "level": self.level.name,
            "keywords": self.keywords,
        }


@dataclass
class MicroCredential:
    """
    Represents a stackable micro-credential

    Attributes:
        id: Unique identifier
        title: Credential title
        competences: List of competence IDs
        description: Credential description
        sector: Blue economy sector (e.g., offshore energy, ports, tourism)
    """

    id: str
    title: str
    competences: List[str]
    description: str
    sector: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert credential to dictionary"""
        return {
            "id": self.id,
            "title": self.title,
            "competences": self.competences,
            "description": self.description,
            "sector": self.sector,
        }


_THEME_KEYWORDS: Dict[BlueDynamicsAxis, List[str]] = {
    BlueDynamicsAxis.MARINE: [
        "ecosystem",
        "biodiversity",
        "habitat",
        "species",
        "fisheries",
        "aquaculture",
    ],
    BlueDynamicsAxis.MARITIME: [
        "maritime",
        "shipping",
        "port",
        "logistics",
        "infrastructure",
        "fleet",
    ],
    BlueDynamicsAxis.OCEANIC: [
        "ocean governance",
        "policy",
        "cooperation",
        "transboundary",
        "justice",
        "planetary",
    ],
    BlueDynamicsAxis.HYDRONIZATION: [
        "hydronization",
        "hydrosocial",
        "water-energy",
        "water society",
        "hydrological transition",
    ],
}


def _detect_all_themes(record: "LiteratureRecord") -> Dict[BlueDynamicsAxis, List[str]]:
    """
    Detect axis themes from a literature record and return a structured mapping.

    If no axis keywords are found, a single ``[citation needed]`` marker is added
    under ``OCEANIC`` to keep downstream outputs explicit and non-empty.
    ``OCEANIC`` is used as fallback for unknown classifications in this project.

    Args:
        record: Normalized bibliographic record used for keyword theme detection.

    Returns:
        Mapping of each ``BlueDynamicsAxis`` to detected theme keywords.
    """
    raw_subject_terms = record.subject_terms
    if isinstance(raw_subject_terms, str):
        subject_terms = [t.strip() for t in raw_subject_terms.split("|") if t.strip()]
    elif raw_subject_terms:
        subject_terms = [str(t).strip() for t in raw_subject_terms if str(t).strip()]
    else:
        subject_terms = []

    themes: Dict[BlueDynamicsAxis, List[str]] = {axis: [] for axis in BlueDynamicsAxis}
    text = " ".join(
        part
        for part in [
            record.title,
            record.journal,
            record.source_query,
            " ".join(subject_terms),
        ]
        if part
    ).lower()

    for axis, keywords in _THEME_KEYWORDS.items():
        themes[axis] = [keyword for keyword in keywords if keyword in text]

    if not any(themes.values()):
        themes[BlueDynamicsAxis.OCEANIC].append("[citation needed]")

    return themes


def load_competence_matrix(file_path: Union[str, Path]) -> List[Competence]:
    """
    Load competence matrix from file (CSV or Excel)

    Args:
        file_path: Path to competence file (str or pathlib.Path)

    Returns:
        List of Competence objects
    """
    try:
        import pandas as pd  # type: ignore[import-untyped]

        path = Path(file_path)
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path)
        elif path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(path)
        else:
            raise ValueError(f"Unsupported file format: {path}")

        competences = []
        for _, row in df.iterrows():
            competence = Competence(
                id=str(row.get("id", "")),
                name=row.get("name", ""),
                description=row.get("description", ""),
                axis=BlueDynamicsAxis[row.get("axis", "MARINE")],
                level=CompetenceLevel[row.get("level", "FOUNDATIONAL")],
                keywords=str(row.get("keywords", "")).split(";"),
            )
            competences.append(competence)

        return competences
    except ImportError:
        raise ImportError(
            "pandas is required to load competence matrices. Install with: pip install pandas openpyxl"
        )


def create_sample_competences() -> List[Competence]:
    """Create sample competences for demonstration"""
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
            description="Management of ports, fleets, grids, and maritime spatial planning (MSP) infrastructure",
            axis=BlueDynamicsAxis.MARITIME,
            level=CompetenceLevel.ADVANCED,
            keywords=[
                "ports",
                "maritime spatial planning",
                "infrastructure",
                "fleet management",
            ],
        ),
        Competence(
            id="comp_oceanic_001",
            name="Ocean Governance and Cooperation",
            description="Cross-border ocean governance integration, hydrosocial literacy, and transcorporeal responsibility",
            axis=BlueDynamicsAxis.OCEANIC,
            level=CompetenceLevel.ADVANCED,
            keywords=[
                "governance",
                "international cooperation",
                "policy",
                "sustainability",
            ],
        ),
    ]
