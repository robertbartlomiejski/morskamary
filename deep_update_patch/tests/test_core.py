"""
Updated test suite for the shared morskamary model.
"""

from deep_update_patch.src.core import (
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
from deep_update_patch.src.competence_mapper import CompetenceMapper


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


def test_add_sector_requirement_normalizes_sector_on_insert() -> None:
    """Regression: requirements inserted with non-normalized sector slugs must be
    retrievable via normalized lookups (e.g. 'Renewable Energy' → 'renewable-energy')."""
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
    # Insert with a non-normalized label — should still be retrievable.
    mapper.add_sector_requirement(
        SectorRequirement(
            competence_id="blue_comp_a_1",
            sector="Renewable Energy",          # non-normalized input
            sector_label="Renewable Energy",
            sector_text="Green energy advocacy",
            requirement_kind=RequirementKind.COMPETENCE,
            axis=BlueDynamicsAxis.OCEANIC,
            dimension="A",
        )
    )
    # Lookup with a different alias must resolve to the same record.
    records = mapper.get_sector_requirement_records("offshore-energy")
    assert len(records) == 1, (
        "Sector requirement inserted as 'Renewable Energy' must be retrievable as "
        "'offshore-energy' (both normalize to 'renewable-energy')."
    )
    assert records[0].sector == "renewable-energy"


def test_add_sector_requirement_does_not_mutate_input() -> None:
    """add_sector_requirement must not mutate the caller's SectorRequirement."""
    requirement = SectorRequirement(
        competence_id="blue_comp_a_1",
        sector="Renewable Energy",
        sector_label="Renewable Energy",
        sector_text="Green energy advocacy",
        requirement_kind=RequirementKind.COMPETENCE,
        axis=BlueDynamicsAxis.OCEANIC,
        dimension="A",
    )
    original_sector = requirement.sector
    mapper = CompetenceMapper()
    mapper.add_sector_requirement(requirement)
    assert requirement.sector == original_sector, (
        "add_sector_requirement must not mutate the caller's SectorRequirement."
    )
    stored = mapper.sector_requirements[0]
    assert stored.sector == "renewable-energy", (
        "Stored sector requirement must have a normalized sector slug."
    )


def test_add_credential_does_not_mutate_input() -> None:
    """add_credential must not mutate the passed-in MicroCredential object."""
    cred = MicroCredential(
        id="cred_001",
        title="Test",
        competences=["blue_comp_a_1"],
        description="desc",
        sector="Renewable Energy",
    )
    original_sector = cred.sector
    mapper = CompetenceMapper()
    mapper.add_credential(cred)
    assert cred.sector == original_sector, (
        "add_credential must not mutate the caller's MicroCredential object."
    )
    stored = mapper.credentials["cred_001"]
    assert stored.sector == "renewable-energy", (
        "Stored credential must have a normalized sector slug."
    )


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
