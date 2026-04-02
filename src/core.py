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

    Raises:
        ValueError: If file_path is empty or has unsupported format
        FileNotFoundError: If the file does not exist
    """
    try:
        import pandas as pd  # type: ignore[import-untyped]

        if file_path is None:
            raise ValueError("file_path cannot be empty")

        if isinstance(file_path, str):
            if not file_path.strip():
                raise ValueError("file_path cannot be empty")
            path = Path(file_path)
        else:
            path = Path(file_path)
            if str(path) == ".":
                raise ValueError("file_path cannot be empty")

        if not path.is_file():
            raise FileNotFoundError(f"Competence file not found: {path}")

        if path.suffix.lower() == '.csv':
            df = pd.read_csv(path)
        elif path.suffix.lower() in ('.xlsx', '.xls'):
            df = pd.read_excel(path)
        else:
            raise ValueError(f"Unsupported file format: {path}")

        competences = []
        for _, row in df.iterrows():
            comp_id = str(row.get('id', '')).strip()
            comp_name = str(row.get('name', '')).strip()

            if not comp_id or not comp_name:
                continue

            raw_keywords = str(row.get('keywords', ''))
            keywords = [k.strip() for k in raw_keywords.split(';') if k.strip()]

            competence = Competence(
                id=comp_id,
                name=comp_name,
                description=str(row.get('description', '')).strip(),
                axis=BlueDynamicsAxis[row.get('axis', 'MARINE')],
                level=CompetenceLevel[row.get('level', 'FOUNDATIONAL')],
                keywords=keywords,
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
