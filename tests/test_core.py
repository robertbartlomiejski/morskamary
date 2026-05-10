"""
Test suite for morskamary Blue Sociology module
"""

import pytest
import json
from pathlib import Path
from src.core import (
    Competence,
    MicroCredential,
    BlueDynamicsAxis,
    CompetenceLevel,
    detect_all_themes,
    create_sample_competences,
    load_competence_matrix,
)
from src.competence_mapper import CompetenceMapper
from src.scientific_sources.models import LiteratureRecord

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


class TestBlueDynamicsAxis:
    """Tests for TMBD/QMBD axis enum values."""

    def test_hydronization_axis_exists(self):
        """HYDRONIZATION must exist as the fourth axis."""
        assert BlueDynamicsAxis.HYDRONIZATION.value == "H"
        assert len(list(BlueDynamicsAxis)) == 4


class TestDetectAllThemes:
    """Tests for structured all-theme detection from literature records."""

    @staticmethod
    def _record(**overrides):
        defaults = {
            "title": "Hydrosocial justice and ocean governance in port logistics",
            "authors": "A. Author",
            "year": "2026",
            "doi": "10.1234/example",
            "source_id": "id-1",
            "provider": "crossref",
            "journal": "Marine policy and ecosystem studies",
            "source_query": "shipping biodiversity cooperation hydronization",
            "subject_terms": ["fisheries", "water-energy", "port"],
        }
        defaults.update(overrides)
        return LiteratureRecord(**defaults)

    def test_detect_all_themes_returns_axis_mapping(self):
        """Detection must return a mapping with all axes as keys."""
        themes = detect_all_themes(self._record())
        assert set(themes.keys()) == {axis.name for axis in BlueDynamicsAxis}
        assert "ecosystem" in themes["MARINE"]
        assert "port" in themes["MARITIME"]
        assert "cooperation" in themes["OCEANIC"]
        assert "hydronization" in themes["HYDRONIZATION"]

    def test_detect_all_themes_uses_citation_required_when_empty(self):
        """Records with no matching keywords should mark citation requirement."""
        empty = self._record(
            title="Generic competence framing",
            journal="",
            source_query="",
            subject_terms=[],
        )
        themes = detect_all_themes(empty)
        assert themes["OCEANIC"] == ["[citation needed]"]

    def test_detect_all_themes_is_case_insensitive(self):
        """Keyword matching should remain case-insensitive."""
        mixed_case = self._record(
            title="HyDrOsOcIaL Transition for WATER-SOCIETY Governance"
        )
        themes = detect_all_themes(mixed_case)
        assert "hydrosocial" in themes["HYDRONIZATION"]

    def test_detect_all_themes_parses_pipe_delimited_subject_terms(self):
        """Pipe-delimited subject_terms strings should be detected safely."""
        record = self._record(
            title="Generic title",
            journal="",
            source_query="",
            subject_terms="hydrosocial|water-energy",
        )
        themes = detect_all_themes(record)
        assert "hydrosocial" in themes["HYDRONIZATION"]
        assert "water-energy" in themes["HYDRONIZATION"]

    def test_detect_all_themes_uses_boundary_aware_matching(self):
        """Single-word keywords should not match inside larger words."""
        record = self._record(
            title="Important transport systems",
            journal="",
            source_query="",
            subject_terms=[],
        )
        themes = detect_all_themes(record)
        assert "port" not in themes["MARITIME"]
        assert themes["OCEANIC"] == ["[citation needed]"]

    def test_detect_all_themes_output_is_json_serializable(self):
        """Public contract should serialize without key-type errors."""
        payload = detect_all_themes(self._record())
        assert isinstance(json.dumps(payload), str)


class TestLoadCompetenceMatrix:
    """Tests for load_competence_matrix function"""

    def test_load_csv_success(self):
        """Test successful loading of CSV file"""
        csv_path = FIXTURES_DIR / "sample_competences.csv"
        competences = load_competence_matrix(csv_path)

        assert len(competences) == 3
        assert competences[0].id == "comp_001"
        assert competences[0].name == "Marine Biology"
        assert competences[0].axis == BlueDynamicsAxis.MARINE
        assert competences[0].level == CompetenceLevel.FOUNDATIONAL
        assert "biology" in competences[0].keywords

    def test_load_excel_success(self):
        """Test successful loading of Excel file"""
        xlsx_path = FIXTURES_DIR / "sample_competences.xlsx"
        competences = load_competence_matrix(xlsx_path)

        assert len(competences) == 2
        assert competences[0].id == "comp_xl_001"
        assert competences[0].axis == BlueDynamicsAxis.MARINE
        assert competences[1].level == CompetenceLevel.ADVANCED

    def test_load_empty_csv(self):
        """Test loading CSV with only headers"""
        empty_path = FIXTURES_DIR / "empty_competences.csv"
        competences = load_competence_matrix(empty_path)
        assert len(competences) == 0

    def test_load_unsupported_format(self):
        """Test error on unsupported file format"""
        with pytest.raises(ValueError, match="Unsupported file format"):
            load_competence_matrix(FIXTURES_DIR / "sample.txt")

    def test_load_nonexistent_file(self):
        """Test error on non-existent file"""
        with pytest.raises(FileNotFoundError):
            load_competence_matrix(FIXTURES_DIR / "nonexistent.csv")

    def test_load_invalid_axis(self):
        """Test handling of invalid axis values"""
        invalid_path = FIXTURES_DIR / "invalid_competences.csv"
        with pytest.raises(KeyError):
            load_competence_matrix(invalid_path)


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
        competences = create_sample_competences()
        for comp in competences:
            mapper.add_competence(comp)

        # Add some credentials
        cred1 = MicroCredential(
            id="cred_001",
            title="Marine Specialist",
            competences=["comp_marine_001"],
            description="Basic marine competence",
            sector="fisheries",
        )
        cred2 = MicroCredential(
            id="cred_002",
            title="Maritime Professional",
            competences=["comp_maritime_001", "comp_oceanic_001"],
            description="Advanced maritime and governance",
            sector="fisheries",
        )
        mapper.add_credentials(cred1)
        mapper.add_credentials(cred2)
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

    def test_get_sector_competences(self, mapper_with_credentials):
        """Test getting competences for a sector"""
        sector_comps = mapper_with_credentials.get_sector_competences("fisheries")
        assert len(sector_comps) == 3
        assert "comp_marine_001" in sector_comps
        assert "comp_maritime_001" in sector_comps
        assert "comp_oceanic_001" in sector_comps

    def test_get_sector_competences_case_insensitive(self, mapper_with_credentials):
        """Test sector matching is case-insensitive"""
        sector_comps = mapper_with_credentials.get_sector_competences("FISHERIES")
        assert len(sector_comps) == 3

    def test_get_sector_competences_empty(self, mapper_with_credentials):
        """Test getting competences for non-existent sector"""
        sector_comps = mapper_with_credentials.get_sector_competences("nonexistent")
        assert len(sector_comps) == 0

    def test_analyze_competence_gaps_basic(self, mapper_with_credentials):
        """Test basic gap analysis"""
        gaps = mapper_with_credentials.analyze_competence_gaps(
            available=["comp_marine_001"], required_sector="fisheries"
        )
        assert len(gaps["available"]) == 1
        assert len(gaps["missing"]) == 2
        assert "comp_marine_001" in gaps["available"]
        assert "comp_maritime_001" in gaps["missing"]
        assert "comp_oceanic_001" in gaps["missing"]

    def test_analyze_competence_gaps_all_available(self, mapper_with_credentials):
        """Test gap analysis when all competences are available"""
        gaps = mapper_with_credentials.analyze_competence_gaps(
            available=["comp_marine_001", "comp_maritime_001", "comp_oceanic_001"],
            required_sector="fisheries",
        )
        assert len(gaps["available"]) == 3
        assert len(gaps["missing"]) == 0

    def test_analyze_competence_gaps_none_available(self, mapper_with_credentials):
        """Test gap analysis when no competences are available"""
        gaps = mapper_with_credentials.analyze_competence_gaps(
            available=[], required_sector="fisheries"
        )
        assert len(gaps["available"]) == 0
        assert len(gaps["missing"]) == 3

    def test_analyze_competence_gaps_by_level(self, mapper_with_credentials):
        """Test gap analysis includes level breakdown"""
        gaps = mapper_with_credentials.analyze_competence_gaps(
            available=["comp_marine_001"], required_sector="fisheries"
        )
        assert "by_level" in gaps
        assert "ADVANCED" in gaps["by_level"]
        assert len(gaps["by_level"]["ADVANCED"]) == 2

    def test_suggest_credential_pathway_empty(self):
        """Test pathway suggestion with no credentials"""
        mapper = CompetenceMapper()
        pathway = mapper.suggest_credential_pathway()
        assert len(pathway) == 0

    def test_suggest_credential_pathway_single(self, mapper_with_credentials):
        """Test pathway suggestion with credentials"""
        pathway = mapper_with_credentials.suggest_credential_pathway()
        assert len(pathway) == 2
        # First credential should be lower level (Marine Specialist)
        assert pathway[0].id == "cred_001"
        # Second should be higher level (Maritime Professional with advanced comps)
        assert pathway[1].id == "cred_002"

    def test_suggest_credential_pathway_starting_level(self, mapper_with_credentials):
        """Test pathway suggestion with custom starting level"""
        pathway = mapper_with_credentials.suggest_credential_pathway(
            starting_level=CompetenceLevel.ADVANCED
        )
        assert len(pathway) == 2


class TestLoadCompetenceMatrixImportError:
    """Test ImportError handling in load_competence_matrix"""

    def test_load_competence_matrix_without_pandas(self, monkeypatch, tmp_path):
        """Test that load_competence_matrix raises helpful ImportError when pandas is missing"""
        import sys
        import builtins

        # Create a simple CSV file
        csv_content = """ID,Competence Name,Description
A.1,Test Competence,Test description
"""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text(csv_content)

        # Mock pandas import to fail
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pandas" or name.startswith("pandas."):
                raise ImportError("No module named 'pandas'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        # Should raise ImportError with helpful message
        with pytest.raises(ImportError) as exc_info:
            load_competence_matrix(csv_path)

        assert "pandas is required" in str(exc_info.value)
        assert "pip install pandas openpyxl" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
