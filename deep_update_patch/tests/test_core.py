"""
Updated test suite for the shared morskamary model.
"""

from src.core import (
    Competence,
    MicroCredential,
    BlueDynamicsAxis,
    CompetenceLevel,
    RequirementKind,
    SectorRequirement,
    SourceRef,
    create_sample_competences,
    normalize_sector_name,
)
from src.competence_mapper import CompetenceMapper


def test_normalize_sector_name_aliases() -> None:
    assert normalize_sector_name("Renewable Energy") == "renewable-energy"
    assert normalize_sector_name("offshore-energy") == "renewable-energy"
    assert normalize_sector_name("R&I") == "research-innovation"


def test_competence_creation_and_to_dict() -> None:
    comp = Competence(
        id="test_001",
        name="Test Competence",
        description="A test competence",
        axis=BlueDynamicsAxis.MARINE,
        level=CompetenceLevel.FOUNDATIONAL,
        keywords=["test"],
        dimension="A",
        requirement_kind=RequirementKind.COMPETENCE,
        source=SourceRef(file="sample.csv", row=2),
    )
    data = comp.to_dict()
    assert data["id"] == "test_001"
    assert data["axis"] == "M"
    assert data["level"] == "FOUNDATIONAL"
    assert data["requirement_kind"] == "competence"


def test_microcredential_backward_compatible_fields() -> None:
    cred = MicroCredential(
        id="cred_001",
        title="Test Credential",
        competences=["comp_001"],
        description="Test",
        sector="renewable-energy",
    )
    data = cred.to_dict()
    assert data["id"] == "cred_001"
    assert data["sector"] == "renewable-energy"
    assert data["eqf_level"] is None


def test_mapper_axis_filters() -> None:
    mapper = CompetenceMapper()
    for comp in create_sample_competences():
        mapper.add_competence(comp)

    marine = mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)
    advanced = mapper.get_competences_by_level(CompetenceLevel.ADVANCED)

    assert len(marine) == 1
    assert len(advanced) == 2


def test_real_sector_requirements_override_credential_inference() -> None:
    mapper = CompetenceMapper()
    mapper.add_competence(
        Competence(
            id="blue_comp_a_1",
            name="Ocean literacy",
            description="desc",
            axis=BlueDynamicsAxis.OCEANIC,
            level=CompetenceLevel.INTERMEDIATE,
            keywords=["ocean"],
            dimension="A",
        )
    )
    mapper.add_competence(
        Competence(
            id="blue_skill_b",
            name="Software & Cyber Defense",
            description="desc",
            axis=BlueDynamicsAxis.MARITIME,
            level=CompetenceLevel.FOUNDATIONAL,
            keywords=["digital"],
            dimension="B",
            requirement_kind=RequirementKind.SKILL,
        )
    )

    mapper.add_sector_requirement(
        SectorRequirement(
            competence_id="blue_comp_a_1",
            sector="renewable-energy",
            sector_label="Renewable Energy",
            sector_text="Green energy advocacy",
            requirement_kind=RequirementKind.COMPETENCE,
            axis=BlueDynamicsAxis.OCEANIC,
            dimension="A",
            source=SourceRef(file="sector.csv", row=3, column="Renewable Energy"),
        )
    )
    mapper.add_sector_requirement(
        SectorRequirement(
            competence_id="blue_skill_b",
            sector="renewable-energy",
            sector_label="Renewable Energy",
            sector_text="Load analytics / SCADA",
            requirement_kind=RequirementKind.SKILL,
            axis=BlueDynamicsAxis.MARITIME,
            dimension="B",
            source=SourceRef(file="sector.csv", row=7, column="Renewable Energy"),
        )
    )

    gaps = mapper.analyze_competence_gaps(
        available=["blue_comp_a_1"],
        required_sector="offshore-energy",
    )
    assert gaps["sector"] == "renewable-energy"
    assert "blue_comp_a_1" in gaps["available"]
    assert "blue_skill_b" in gaps["missing"]


def test_mapper_summary_counts_sectors_and_requirements() -> None:
    mapper = CompetenceMapper()
    mapper.add_competence(
        Competence(
            id="blue_comp_d_4",
            name="Ethical governance",
            description="desc",
            axis=BlueDynamicsAxis.MARITIME,
            level=CompetenceLevel.INTERMEDIATE,
            keywords=["governance"],
            dimension="D",
        )
    )
    mapper.add_sector_requirement(
        SectorRequirement(
            competence_id="blue_comp_d_4",
            sector="port-activities",
            sector_label="Port Activities",
            sector_text="Port Commissions",
            requirement_kind=RequirementKind.COMPETENCE,
            axis=BlueDynamicsAxis.MARITIME,
            dimension="D",
        )
    )
    summary = mapper.get_summary()
    assert summary["total_competences"] == 1
    assert summary["total_sector_requirements"] == 1
    assert "port-activities" in summary["sectors"]
