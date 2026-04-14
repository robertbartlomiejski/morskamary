"""
Test suite for morskamary Blue Sociology module
"""

import pandas as pd
import pytest
from src.core import (
    Competence,
    MicroCredential,
    BlueDynamicsAxis,
    CompetenceLevel,
    create_sample_competences,
    load_competence_matrix,
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

    @pytest.fixture
    def mapper_with_credentials(self):
        """Create a mapper with competences and credentials"""
        mapper = CompetenceMapper()
        competences = [
            Competence(
                id="comp_a",
                name="Foundational Marine Basics",
                description="Foundational marine literacy",
                axis=BlueDynamicsAxis.MARINE,
                level=CompetenceLevel.FOUNDATIONAL,
                keywords=["basics"],
            ),
            Competence(
                id="comp_b",
                name="Intermediate Maritime Operations",
                description="Intermediate maritime operations",
                axis=BlueDynamicsAxis.MARITIME,
                level=CompetenceLevel.INTERMEDIATE,
                keywords=["operations"],
            ),
            Competence(
                id="comp_c",
                name="Advanced Ocean Governance",
                description="Advanced ocean governance",
                axis=BlueDynamicsAxis.OCEANIC,
                level=CompetenceLevel.ADVANCED,
                keywords=["governance"],
            ),
        ]
        for comp in competences:
            mapper.add_competence(comp)

        mapper.add_credentials(
            MicroCredential(
                id="cred_ports_1",
                title="Ports Foundations",
                competences=["comp_a", "comp_b"],
                description="Ports basics",
                sector="Ports",
            )
        )
        mapper.add_credentials(
            MicroCredential(
                id="cred_ports_2",
                title="Ports Governance",
                competences=["comp_c", "comp_b"],
                description="Ports governance",
                sector="Ports",
            )
        )
        mapper.add_credentials(
            MicroCredential(
                id="cred_tourism",
                title="Tourism Basics",
                competences=["comp_a"],
                description="Tourism basics",
                sector="Tourism",
            )
        )
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

    def test_add_credentials(self, mapper_with_credentials):
        """Test adding credentials"""
        assert len(mapper_with_credentials.credentials) == 3

    def test_get_sector_competences_case_insensitive(self, mapper_with_credentials):
        """Test sector competence retrieval ignores case and duplicates"""
        mapper_with_credentials.add_credentials(
            MicroCredential(
                id="cred_ports_lower",
                title="Ports Lowercase",
                competences=["comp_a"],
                description="Ports lowercase sector",
                sector="ports",
            )
        )
        competences = mapper_with_credentials.get_sector_competences("PORTS")
        assert set(competences) == {"comp_a", "comp_b", "comp_c"}

    def test_analyze_competence_gaps(self, mapper_with_credentials):
        """Test gap analysis returns missing competences with level breakdown"""
        result = mapper_with_credentials.analyze_competence_gaps(
            available=["comp_a"], required_sector="Ports"
        )
        assert set(result["available"]) == {"comp_a"}
        assert set(result["missing"]) == {"comp_b", "comp_c"}
        assert set(result["by_level"]["INTERMEDIATE"]) == {"comp_b"}
        assert set(result["by_level"]["ADVANCED"]) == {"comp_c"}

    def test_suggest_credential_pathway_orders_by_level(self, mapper_with_credentials):
        """Test pathway suggestion orders credentials by average level"""
        pathway = mapper_with_credentials.suggest_credential_pathway()
        assert [cred.id for cred in pathway][:2] == ["cred_tourism", "cred_ports_1"]


class TestLoadCompetenceMatrix:
    """Tests for load_competence_matrix"""

    def test_load_competence_matrix_csv(self, tmp_path):
        """Test loading competences from CSV"""
        df = pd.DataFrame(
            [
                {
                    "id": 1,
                    "name": "Sample Marine",
                    "description": "Marine description",
                    "axis": "MARINE",
                    "level": "INTERMEDIATE",
                    "keywords": "a;b;c",
                },
                {
                    "id": "comp_2",
                    "name": "Sample Maritime",
                    "description": "Maritime description",
                    "axis": "MARITIME",
                    "level": "ADVANCED",
                    "keywords": "ports;logistics",
                },
            ]
        )
        csv_path = tmp_path / "competences.csv"
        df.to_csv(csv_path, index=False)

        competences = load_competence_matrix(csv_path)

        assert len(competences) == 2
        assert competences[0].id == "1"
        assert competences[0].axis == BlueDynamicsAxis.MARINE
        assert competences[0].level == CompetenceLevel.INTERMEDIATE
        assert competences[0].keywords == ["a", "b", "c"]

    def test_load_competence_matrix_xlsx(self, tmp_path):
        """Test loading competences from Excel"""
        df = pd.DataFrame(
            [
                {
                    "id": "comp_xlsx",
                    "name": "Sample Oceanic",
                    "description": "Oceanic description",
                    "axis": "OCEANIC",
                    "level": "FOUNDATIONAL",
                    "keywords": "governance",
                }
            ]
        )
        excel_path = tmp_path / "competences.xlsx"
        df.to_excel(excel_path, index=False)

        competences = load_competence_matrix(excel_path)

        assert len(competences) == 1
        assert competences[0].axis == BlueDynamicsAxis.OCEANIC
        assert competences[0].level == CompetenceLevel.FOUNDATIONAL

    def test_load_competence_matrix_unsupported_format(self, tmp_path):
        """Test unsupported file formats raise ValueError"""
        bad_path = tmp_path / "competences.txt"
        bad_path.write_text("id,name")

        with pytest.raises(ValueError, match="Unsupported file format"):
            load_competence_matrix(bad_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
