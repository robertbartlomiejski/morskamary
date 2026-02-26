"""
Test suite for morskamary Blue Sociology module
"""

import pytest
from src.core import (
    Competence,
    MicroCredential,
    BlueDynamicsAxis,
    CompetenceLevel,
    create_sample_competences,
)
from src.competence_mapper import CompetenceMapper


class TestCompetence:
    """Tests for Competence model"""

    def test_competence_creation(self):
        """Test creating a competence"""
        comp = Competence(
            id="test_001",
            name="Test Competence",
            description="A test competence",
            axis=BlueDynamicsAxis.MARINE,
            level=CompetenceLevel.FOUNDATIONAL,
            keywords=["test", "sample"],
        )
        assert comp.id == "test_001"
        assert comp.name == "Test Competence"
        assert comp.axis == BlueDynamicsAxis.MARINE

    def test_competence_to_dict(self):
        """Test converting competence to dictionary"""
        comp = Competence(
            id="test_001",
            name="Test Competence",
            description="A test competence",
            axis=BlueDynamicsAxis.MARITIME,
            level=CompetenceLevel.ADVANCED,
            keywords=["test"],
        )
        comp_dict = comp.to_dict()
        assert comp_dict["id"] == "test_001"
        assert comp_dict["axis"] == "T"
        assert comp_dict["level"] == "ADVANCED"


class TestMicroCredential:
    """Tests for MicroCredential model"""

    def test_credential_creation(self):
        """Test creating a credential"""
        cred = MicroCredential(
            id="cred_001",
            title="Test Credential",
            competences=["comp_001"],
            description="Test description",
            sector="test-sector",
        )
        assert cred.id == "cred_001"
        assert len(cred.competences) == 1

    def test_credential_to_dict(self):
        """Test converting credential to dictionary"""
        cred = MicroCredential(
            id="cred_001",
            title="Test Credential",
            competences=["comp_001", "comp_002"],
            description="Test description",
            sector="test-sector",
        )
        cred_dict = cred.to_dict()
        assert cred_dict["title"] == "Test Credential"
        assert len(cred_dict["competences"]) == 2


class TestCompetenceMapper:
    """Tests for CompetenceMapper"""

    @pytest.fixture
    def mapper(self):
        """Create a mapper with sample data"""
        mapper = CompetenceMapper()
        competences = create_sample_competences()
        for comp in competences:
            mapper.add_competence(comp)
        return mapper

    def test_add_competence(self, mapper):
        """Test adding competences"""
        assert len(mapper.competences) == 3

    def test_get_competences_by_axis(self, mapper):
        """Test filtering by TMBD axis"""
        marine = mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)
        assert len(marine) == 1
        assert marine[0].name == "Marine Ecosystem Understanding"

    def test_get_competences_by_level(self, mapper):
        """Test filtering by competence level"""
        advanced = mapper.get_competences_by_level(CompetenceLevel.ADVANCED)
        assert len(advanced) == 2

    def test_get_summary(self, mapper):
        """Test summary generation"""
        summary = mapper.get_summary()
        assert summary["total_competences"] == 3
        assert summary["competences_by_axis"]["MARINE"] == 1
        assert summary["competences_by_axis"]["MARITIME"] == 1
        assert summary["competences_by_axis"]["OCEANIC"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
