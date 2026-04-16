"""
Competence mapping and analysis module for Blue Sociology.
Authoritative mapper that works from real sector requirements, not only from credentials.
"""

from typing import Any, Dict, List, Set, Tuple, TypedDict, Optional
from .core import (
    Competence,
    MicroCredential,
    BlueDynamicsAxis,
    CompetenceLevel,
    RequirementKind,
    SectorRequirement,
    normalize_sector_name,
    sector_label,
)


class GapAnalysisResult(TypedDict, total=False):
    available: List[str]
    missing: List[str]
    by_level: Dict[str, List[str]]
    required: List[str]
    sector: str
    sector_label: str


class CompetenceMapper:
    """Maps competences to sectors and creates micro-credentials."""

    def __init__(self) -> None:
        self.competences: Dict[str, Competence] = {}
        self.sector_requirements: List[SectorRequirement] = []
        self.credentials: Dict[str, MicroCredential] = {}
        self.sector_clusters: Dict[str, str] = {}

    def add_competence(self, competence: Competence) -> None:
        self.competences[competence.id] = competence

    def add_competences(self, competences: List[Competence]) -> None:
        for competence in competences:
            self.add_competence(competence)

    def add_sector_requirement(self, requirement: SectorRequirement) -> None:
        """Add a sector requirement, normalizing the sector slug on insert."""
        normalized = normalize_sector_name(requirement.sector)
        self.sector_requirements.append(
            SectorRequirement(
                competence_id=requirement.competence_id,
                sector=normalized,
                sector_label=requirement.sector_label,
                sector_text=requirement.sector_text,
                requirement_kind=requirement.requirement_kind,
                axis=requirement.axis,
                dimension=requirement.dimension,
                cluster_name=requirement.cluster_name,
                source=requirement.source,
            )
        )

    def add_sector_requirements(self, requirements: List[SectorRequirement]) -> None:
        for requirement in requirements:
            self.add_sector_requirement(requirement)

    def add_credential(self, credential: MicroCredential) -> None:
        """Add a micro-credential, normalizing its sector slug on insert."""
        normalized = normalize_sector_name(credential.sector)
        self.credentials[credential.id] = MicroCredential(
            id=credential.id,
            title=credential.title,
            competences=list(credential.competences),
            description=credential.description,
            sector=normalized,
            learner_profile=credential.learner_profile,
            workload_hours=credential.workload_hours,
            ects=credential.ects,
            eqf_level=credential.eqf_level,
            assessment_method=credential.assessment_method,
            prerequisites=list(credential.prerequisites),
            learning_outcomes=list(credential.learning_outcomes),
            stackability_rules=credential.stackability_rules,
            source_cluster=credential.source_cluster,
        )

    # Backward-compatible alias
    def add_credentials(self, credential: MicroCredential) -> None:
        """Deprecated alias for add_credential; accepts a single MicroCredential."""
        self.add_credential(credential)

    def register_sector_cluster(self, sector: str, cluster_name: str) -> None:
        self.sector_clusters[normalize_sector_name(sector)] = cluster_name.strip()

    def get_sector_cluster(self, sector: str) -> str:
        return self.sector_clusters.get(normalize_sector_name(sector), "")

    def get_competences_by_axis(self, axis: BlueDynamicsAxis) -> List[Competence]:
        return [c for c in self.competences.values() if c.axis == axis]

    def get_competences_by_level(self, level: CompetenceLevel) -> List[Competence]:
        return [c for c in self.competences.values() if c.level == level]

    def get_sector_requirement_records(self, sector: str) -> List[SectorRequirement]:
        normalized = normalize_sector_name(sector)
        records = [req for req in self.sector_requirements if req.sector == normalized]

        def sort_key(item: SectorRequirement) -> Tuple[str, str, str]:
            competence = self.competences.get(item.competence_id)
            dimension = competence.dimension if competence else item.dimension
            kind_rank = "0" if item.requirement_kind == RequirementKind.SKILL else "1"
            return (dimension, kind_rank, item.competence_id)

        return sorted(records, key=sort_key)

    def get_sector_competences(self, sector: str) -> List[str]:
        normalized = normalize_sector_name(sector)

        requirement_ids = [
            req.competence_id
            for req in self.get_sector_requirement_records(normalized)
            if req.competence_id in self.competences
        ]
        if requirement_ids:
            return sorted(set(requirement_ids))

        sector_credentials = [
            cred for cred in self.credentials.values()
            if normalize_sector_name(cred.sector) == normalized
        ]
        fallback: Set[str] = set()
        for cred in sector_credentials:
            fallback.update(cred.competences)
        return sorted(fallback)

    def analyze_competence_gaps(self, available: List[str], required_sector: str) -> GapAnalysisResult:
        normalized = normalize_sector_name(required_sector)
        required = set(self.get_sector_competences(normalized))
        available_set = set(available)
        missing = required - available_set

        result: GapAnalysisResult = {
            "available": sorted(list(available_set & required)),
            "missing": sorted(list(missing)),
            "required": sorted(list(required)),
            "sector": normalized,
            "sector_label": sector_label(normalized),
            "by_level": {},
        }

        for level in CompetenceLevel:
            level_missing = [
                cid for cid in sorted(missing)
                if cid in self.competences and self.competences[cid].level == level
            ]
            if level_missing:
                result["by_level"][level.name] = level_missing

        return result

    def suggest_credential_pathway(
        self,
        starting_level: CompetenceLevel = CompetenceLevel.FOUNDATIONAL,
        sector: Optional[str] = None,
    ) -> List[MicroCredential]:
        credentials = list(self.credentials.values())
        if sector:
            normalized = normalize_sector_name(sector)
            credentials = [cred for cred in credentials if normalize_sector_name(cred.sector) == normalized]

        def sort_key(credential: MicroCredential) -> Tuple[float, float, str]:
            if credential.eqf_level is not None:
                primary = float(credential.eqf_level)
            else:
                levels = [
                    self.competences[cid].level.value
                    for cid in credential.competences
                    if cid in self.competences
                ]
                primary = float(sum(levels) / max(1, len(levels)))
            workload = float(credential.workload_hours or 0)
            return (primary, workload, credential.title.lower())

        ordered = sorted(credentials, key=sort_key)
        if starting_level == CompetenceLevel.FOUNDATIONAL:
            return ordered

        return [
            cred for cred in ordered
            if cred.eqf_level is None or cred.eqf_level >= starting_level.value + 2
        ]

    def get_sector_profile(self, sector: str) -> Dict[str, Any]:
        normalized = normalize_sector_name(sector)
        records = self.get_sector_requirement_records(normalized)
        axis_counts = {axis.name: 0 for axis in BlueDynamicsAxis}
        kind_counts = {kind.value: 0 for kind in RequirementKind}

        for record in records:
            axis_counts[record.axis.name] += 1
            kind_counts[record.requirement_kind.value] += 1

        return {
            "sector": normalized,
            "sector_label": sector_label(normalized),
            "cluster_name": self.get_sector_cluster(normalized),
            "total_requirements": len(records),
            "requirements_by_axis": axis_counts,
            "requirements_by_kind": kind_counts,
            "competence_ids": [record.competence_id for record in records],
        }

    def get_summary(self) -> Dict[str, Any]:
        axis_counts = {
            axis.name: len(self.get_competences_by_axis(axis))
            for axis in BlueDynamicsAxis
        }
        level_counts = {
            level.name: len(self.get_competences_by_level(level))
            for level in CompetenceLevel
        }

        sectors_from_requirements = {req.sector for req in self.sector_requirements}
        sectors_from_credentials = {normalize_sector_name(cred.sector) for cred in self.credentials.values()}
        sectors = sorted(sectors_from_requirements | sectors_from_credentials)

        return {
            "total_competences": len(self.competences),
            "total_sector_requirements": len(self.sector_requirements),
            "total_credentials": len(self.credentials),
            "competences_by_axis": axis_counts,
            "competences_by_level": level_counts,
            "sectors": sectors,
            "sector_labels": {sector: sector_label(sector) for sector in sectors},
        }
