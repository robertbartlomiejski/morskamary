"""
Test suite for morskamary Blue Sociology module
"""

import pytest
from pathlib import Path
from src.core import (
    Competence,
    MicroCredential,
    BlueDynamicsAxis,
    CompetenceLevel,
    create_sample_competences,
    load_competence_matrix,
)
from src.competence_mapper import CompetenceMapper


FIXTURES_DIR = Path(__file__).parent / "fixtures"


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


class TestLoadCompetenceMatrix:
    """Tests for load_competence_matrix function"""

    def test_load_csv_success(self):
        """Test loading competences from CSV file"""
        csv_path = FIXTURES_DIR / "sample_competences.csv"
        competences = load_competence_matrix(csv_path)
        assert len(competences) == 3
        assert competences[0].id == "comp_001"
        assert competences[0].axis == BlueDynamicsAxis.OCEANIC

    def test_load_excel_success(self):
        """Test loading competences from Excel file"""
        xlsx_path = FIXTURES_DIR / "sample_competences.xlsx"
        competences = load_competence_matrix(xlsx_path)
        assert len(competences) == 2
        assert competences[0].id == "comp_001"
        assert competences[1].axis == BlueDynamicsAxis.MARITIME

    def test_load_empty_csv(self):
        """Test loading empty CSV file"""
        csv_path = FIXTURES_DIR / "empty_competences.csv"
        competences = load_competence_matrix(csv_path)
        assert len(competences) == 0

    def test_unsupported_file_format(self):
        """Test error on unsupported file format"""
        with pytest.raises(ValueError, match="Unsupported file format"):
            load_competence_matrix("test.txt")

    def test_nonexistent_file(self):
        """Test error on non-existent file"""
        with pytest.raises(FileNotFoundError):
            load_competence_matrix(FIXTURES_DIR / "nonexistent.csv")

    def test_invalid_enum_value(self):
        """Test handling of invalid enum values in CSV"""
        csv_path = FIXTURES_DIR / "invalid_competences.csv"
        with pytest.raises(KeyError):
            load_competence_matrix(csv_path)


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

    def test_get_sector_competences(self, mapper):
        """Test retrieving competences for a specific sector"""
        from src.core import MicroCredential

        cred = MicroCredential(
            id="cred_test",
            title="Test Credential",
            competences=["comp_marine_001", "comp_maritime_001"],
            description="Test",
            sector="test-sector"
        )
        mapper.add_credentials(cred)

        sector_comps = mapper.get_sector_competences("test-sector")
        assert len(sector_comps) == 2
        assert "comp_marine_001" in sector_comps

    def test_get_sector_competences_case_insensitive(self, mapper):
        """Test sector matching is case-insensitive"""
        from src.core import MicroCredential

        cred = MicroCredential(
            id="cred_test",
            title="Test Credential",
            competences=["comp_marine_001"],
            description="Test",
            sector="Test-Sector"
        )
        mapper.add_credentials(cred)

        sector_comps = mapper.get_sector_competences("test-sector")
        assert len(sector_comps) == 1

    def test_get_sector_competences_empty(self, mapper):
        """Test retrieving competences for non-existent sector"""
        sector_comps = mapper.get_sector_competences("nonexistent-sector")
        assert len(sector_comps) == 0

    def test_gap_analysis_basic(self, mapper):
        """Test basic gap analysis"""
        from src.core import MicroCredential

        cred = MicroCredential(
            id="cred_test",
            title="Test Credential",
            competences=["comp_marine_001", "comp_maritime_001", "comp_oceanic_001"],
            description="Test",
            sector="test-sector"
        )
        mapper.add_credentials(cred)

        gaps = mapper.analyze_competence_gaps(
            available=["comp_marine_001"],
            required_sector="test-sector"
        )

        assert len(gaps["available"]) == 1
        assert len(gaps["missing"]) == 2
        assert "comp_maritime_001" in gaps["missing"]

    def test_gap_analysis_all_available(self, mapper):
        """Test gap analysis when all competences are available"""
        from src.core import MicroCredential

        cred = MicroCredential(
            id="cred_test",
            title="Test Credential",
            competences=["comp_marine_001"],
            description="Test",
            sector="test-sector"
        )
        mapper.add_credentials(cred)

        gaps = mapper.analyze_competence_gaps(
            available=["comp_marine_001"],
            required_sector="test-sector"
        )

        assert len(gaps["missing"]) == 0

    def test_gap_analysis_none_available(self, mapper):
        """Test gap analysis when no competences are available"""
        from src.core import MicroCredential

        cred = MicroCredential(
            id="cred_test",
            title="Test Credential",
            competences=["comp_marine_001", "comp_maritime_001"],
            description="Test",
            sector="test-sector"
        )
        mapper.add_credentials(cred)

        gaps = mapper.analyze_competence_gaps(
            available=[],
            required_sector="test-sector"
        )

        assert len(gaps["available"]) == 0
        assert len(gaps["missing"]) == 2

    def test_gap_analysis_by_level(self, mapper):
        """Test gap analysis includes breakdown by level"""
        from src.core import MicroCredential

        cred = MicroCredential(
            id="cred_test",
            title="Test Credential",
            competences=["comp_marine_001", "comp_maritime_001", "comp_oceanic_001"],
            description="Test",
            sector="test-sector"
        )
        mapper.add_credentials(cred)

        gaps = mapper.analyze_competence_gaps(
            available=[],
            required_sector="test-sector"
        )

        assert "INTERMEDIATE" in gaps["by_level"]
        assert "ADVANCED" in gaps["by_level"]

    def test_suggest_credential_pathway_empty(self, mapper):
        """Test credential pathway suggestion with no credentials"""
        pathway = mapper.suggest_credential_pathway()
        assert len(pathway) == 0

    def test_suggest_credential_pathway_single(self, mapper):
        """Test credential pathway suggestion with single credential"""
        from src.core import MicroCredential

        cred = MicroCredential(
            id="cred_test",
            title="Test Credential",
            competences=["comp_marine_001"],
            description="Test",
            sector="test-sector"
        )
        mapper.add_credentials(cred)

        pathway = mapper.suggest_credential_pathway()
        assert len(pathway) == 1

    def test_suggest_credential_pathway_with_starting_level(self, mapper):
        """Test credential pathway suggestion with starting level"""
        from src.core import MicroCredential

        cred1 = MicroCredential(
            id="cred_basic",
            title="Basic Credential",
            competences=["comp_marine_001"],
            description="Basic",
            sector="test-sector"
        )
        cred2 = MicroCredential(
            id="cred_advanced",
            title="Advanced Credential",
            competences=["comp_maritime_001", "comp_oceanic_001"],
            description="Advanced",
            sector="test-sector"
        )
        mapper.add_credentials(cred1)
        mapper.add_credentials(cred2)

        pathway = mapper.suggest_credential_pathway(CompetenceLevel.FOUNDATIONAL)
        assert len(pathway) == 2
        # Should be ordered by average level
        assert pathway[0].id == "cred_basic"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
