"""
Competence mapping and analysis module for Blue Sociology
"""

from typing import Dict, List, Set, Tuple
from src.core import Competence, MicroCredential, BlueDynamicsAxis, CompetenceLevel


class CompetenceMapper:
    """Maps competences to sectors and creates micro-credentials"""

    def __init__(self):
        self.competences: Dict[str, Competence] = {}
        self.credentials: Dict[str, MicroCredential] = {}

    def add_competence(self, competence: Competence) -> None:
        """Add a competence to the mapper"""
        self.competences[competence.id] = competence

    def add_credentials(self, credential: MicroCredential) -> None:
        """Add a micro-credential to the mapper"""
        self.credentials[credential.id] = credential

    def get_competences_by_axis(self, axis: BlueDynamicsAxis) -> List[Competence]:
        """Get all competences for a specific TMBD axis"""
        return [c for c in self.competences.values() if c.axis == axis]

    def get_competences_by_level(self, level: CompetenceLevel) -> List[Competence]:
        """Get all competences at a specific proficiency level"""
        return [c for c in self.competences.values() if c.level == level]

    def get_sector_competences(self, sector: str) -> List[str]:
        """Get competence IDs required for a specific sector"""
        sector_credentials = [
            cred for cred in self.credentials.values()
            if cred.sector.lower() == sector.lower()
        ]

        all_competences: Set[str] = set()
        for cred in sector_credentials:
            all_competences.update(cred.competences)

        return list(all_competences)

    def analyze_competence_gaps(self,
                               available: List[str],
                               required_sector: str) -> Dict[str, List[str]]:
        """
        Analyze gaps between available and required competences for a sector

        Args:
            available: List of competence IDs the person already has
            required_sector: Target sector

        Returns:
            Dict with 'available', 'missing', and 'by_level' breakdown
        """
        required = set(self.get_sector_competences(required_sector))
        available_set = set(available)

        missing = required - available_set

        result = {
            "available": list(available_set & required),
            "missing": list(missing),
            "by_level": {}
        }

        for level in CompetenceLevel:
            level_missing = [
                cid for cid in missing
                if cid in self.competences
                and self.competences[cid].level == level
            ]
            if level_missing:
                result["by_level"][level.name] = level_missing

        return result

    def suggest_credential_pathway(self,
                                  starting_level: CompetenceLevel = CompetenceLevel.FOUNDATIONAL
                                  ) -> List[MicroCredential]:
        """
        Suggest a logical progression of micro-credentials

        Args:
            starting_level: Starting proficiency level

        Returns:
            List of credentials ordered by progression
        """
        # Group credentials by average competence level
        credential_levels: List[Tuple[MicroCredential, float]] = []

        for cred in self.credentials.values():
            avg_level = sum(
                self.competences[cid].level.value
                for cid in cred.competences
                if cid in self.competences
            ) / max(1, len(cred.competences))
            credential_levels.append((cred, avg_level))

        # Sort by level
        credential_levels.sort(key=lambda x: x[1])

        return [cred for cred, _ in credential_levels]

    def get_summary(self) -> Dict[str, any]:
        """Get a summary of all mapped competences and credentials"""
        axis_counts = {
            axis: len(self.get_competences_by_axis(axis))
            for axis in BlueDynamicsAxis
        }

        level_counts = {
            level.name: len(self.get_competences_by_level(level))
            for level in CompetenceLevel
        }

        sectors = set(cred.sector for cred in self.credentials.values())

        return {
            "total_competences": len(self.competences),
            "total_credentials": len(self.credentials),
            "competences_by_axis": {k.name: v for k, v in axis_counts.items()},
            "competences_by_level": level_counts,
            "sectors": list(sectors),
        }
