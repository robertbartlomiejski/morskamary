"""
Core utilities and data structures for Blue Sociology analysis
"""

from pathlib import Path
from typing import Dict, List, Any, Union
from dataclasses import dataclass
from enum import Enum


class BlueDynamicsAxis(Enum):
    """Tripartite Model of Blue Dynamics (TMBD) axes"""
    MARINE = "M"       # Marine (biophysical agency)
    MARITIME = "T"     # Maritime (techno-economic and institutional mediation)
    OCEANIC = "O"      # Oceanic (planetary governance and hydrosocial subjectivity)


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
        axis: TMBD axis (Marine, Maritime, or Oceanic)
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
        import pandas as pd

        path = Path(file_path)
        if path.suffix.lower() == '.csv':
            df = pd.read_csv(path)
        elif path.suffix.lower() in ('.xlsx', '.xls'):
            df = pd.read_excel(path)
        else:
            raise ValueError(f"Unsupported file format: {path}")

        competences = []
        ids = (df["id"].astype(str) if "id" in df.columns else pd.Series("", index=df.index)).tolist()
        names = (df["name"].fillna("") if "name" in df.columns else pd.Series("", index=df.index)).tolist()
        descriptions = (df["description"].fillna("") if "description" in df.columns else pd.Series("", index=df.index)).tolist()
        axes = (df["axis"].fillna("MARINE") if "axis" in df.columns else pd.Series("MARINE", index=df.index)).tolist()
        levels = (df["level"].fillna("FOUNDATIONAL") if "level" in df.columns else pd.Series("FOUNDATIONAL", index=df.index)).tolist()
        keywords_col = (df["keywords"].fillna("").astype(str) if "keywords" in df.columns else pd.Series("", index=df.index)).tolist()
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
        raise ImportError("pandas is required to load competence matrices. Install with: pip install pandas openpyxl")


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
