"""
Core utilities and data structures for Blue Sociology analysis
"""

from pathlib import Path
from typing import Any, Dict, List, Union
from dataclasses import dataclass
from enum import Enum


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


_AXIS_THEME_KEYWORDS: Dict[BlueDynamicsAxis, List[str]] = {
    BlueDynamicsAxis.MARINE: [
        "marine",
        "ocean",
        "fisheries",
        "aquaculture",
        "ecosystem",
        "biodiversity",
        "bio-cycles",
        "deep-time rhythms",
        "cofka",
        "thermohaline circulation",
        "stewardship",
        "habitus of seafarers",
        "marine ecotone",
        "vibrant materialism",
        "weather-based risk",
        "intra-action",
        "pelagic metabolism",
        "benthic agency",
    ],
    BlueDynamicsAxis.MARITIME: [
        "maritime",
        "port",
        "shipping",
        "logistics",
        "infrastructure",
        "msp",
        "maritimization",
        "port 4.0",
        "growth machine",
        "blue-washing",
        "ocean grabbing",
        "rigid superinfrastructure",
        "ten-t corridors",
        "flag of convenience",
        "throughput tonnage",
        "logistics algorithms",
        "supply chain acceleration",
        "maritime mindset",
        "cyber-physical port systems",
    ],
    BlueDynamicsAxis.OCEANIC: [
        "governance",
        "policy",
        "cooperation",
        "justice",
        "sustainability",
        "hyperobject",
        "hydrocommons",
        "blue degrowth",
        "high sea treaties",
        "volumetric sovereignty",
        "tidalectics",
        "rights of nature",
        "blue justice",
        "planetary water",
        "hydro-solidarity",
        "ocean literacy",
        "blue citizenship",
        "multispecies justice",
    ],
    BlueDynamicsAxis.HYDRONIZATION: [
        "hydronization",
        "hydrosocial",
        "wet ontology",
        "hydrofeminism",
        "transcorporeality",
        "porocity",
        "sponge city",
        "liquid materiality",
        "estuarial hydrofeminism",
        "bodies of water",
        "hydrobiography",
        "metabolism of flows",
        "porous infrastructure",
        "hydro-social territory",
        "[citation needed]",
    ],
}


def _detect_all_themes(record: Dict[str, Any]) -> Dict[BlueDynamicsAxis, List[str]]:
    """Detect per-axis thematic keywords from record text.

    Returns a dictionary keyed by all QMBD axes. If no keywords are found,
    applies a deterministic governance fallback under OCEANIC.
    """
    text = " ".join(
        str(record.get(field, "")) for field in ("title", "abstract", "keywords")
    ).lower()

    themes: Dict[BlueDynamicsAxis, List[str]] = {
        axis: [] for axis in BlueDynamicsAxis
    }
    for axis, keywords in _AXIS_THEME_KEYWORDS.items():
        themes[axis] = [keyword for keyword in keywords if keyword in text]

    if not any(themes.values()):
        themes[BlueDynamicsAxis.OCEANIC] = ["[citation needed]"]

    return themes


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
        ids = (
            df["id"].astype(str)
            if "id" in df.columns
            else pd.Series("", index=df.index)
        ).tolist()
        names = (
            df["name"].fillna("")
            if "name" in df.columns
            else pd.Series("", index=df.index)
        ).tolist()
        descriptions = (
            df["description"].fillna("")
            if "description" in df.columns
            else pd.Series("", index=df.index)
        ).tolist()
        axes = (
            df["axis"].fillna("MARINE")
            if "axis" in df.columns
            else pd.Series("MARINE", index=df.index)
        ).tolist()
        levels = (
            df["level"].fillna("FOUNDATIONAL")
            if "level" in df.columns
            else pd.Series("FOUNDATIONAL", index=df.index)
        ).tolist()
        keywords_col = (
            df["keywords"].fillna("").astype(str)
            if "keywords" in df.columns
            else pd.Series("", index=df.index)
        ).tolist()

        for id_val, name, desc, axis, level, kw in zip(
            ids, names, descriptions, axes, levels, keywords_col
        ):
            competence = Competence(
                id=id_val,
                name=name,
                description=desc,
                axis=BlueDynamicsAxis[str(axis)],
                level=CompetenceLevel[str(level)],
                keywords=kw.split(";"),
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
