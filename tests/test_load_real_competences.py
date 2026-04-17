"""Tests for load_real_competences module."""

import pytest
from pathlib import Path
from load_real_competences import map_dimension_to_axis, load_blue_competences
from src.core import BlueDynamicsAxis, CompetenceLevel


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestMapDimensionToAxis:
    """Tests for map_dimension_to_axis function"""

    def test_dimension_a_maps_to_oceanic(self):
        """Test dimension A maps to OCEANIC axis"""
        assert map_dimension_to_axis("A.1") == BlueDynamicsAxis.OCEANIC
        assert map_dimension_to_axis("A.2") == BlueDynamicsAxis.OCEANIC

    def test_dimension_b_maps_to_maritime(self):
        """Test dimension B maps to MARITIME axis"""
        assert map_dimension_to_axis("B.1") == BlueDynamicsAxis.MARITIME
        assert map_dimension_to_axis("B.2") == BlueDynamicsAxis.MARITIME

    def test_dimension_c_maps_to_marine(self):
        """Test dimension C maps to MARINE axis"""
        assert map_dimension_to_axis("C.1") == BlueDynamicsAxis.MARINE
        assert map_dimension_to_axis("C.2") == BlueDynamicsAxis.MARINE

    def test_dimension_d_maps_to_maritime(self):
        """Test dimension D maps to MARITIME axis"""
        assert map_dimension_to_axis("D.1") == BlueDynamicsAxis.MARITIME
        assert map_dimension_to_axis("D.2") == BlueDynamicsAxis.MARITIME

    def test_dimension_without_dot(self):
        """Test dimension without dot separator"""
        assert map_dimension_to_axis("A") == BlueDynamicsAxis.OCEANIC
        assert map_dimension_to_axis("B") == BlueDynamicsAxis.MARITIME
        assert map_dimension_to_axis("C") == BlueDynamicsAxis.MARINE

    def test_unknown_dimension_defaults_to_oceanic(self):
        """Test unknown dimension defaults to OCEANIC"""
        assert map_dimension_to_axis("X.1") == BlueDynamicsAxis.OCEANIC
        assert map_dimension_to_axis("Z") == BlueDynamicsAxis.OCEANIC


class TestLoadBlueCompetences:
    """Tests for load_blue_competences function"""

    def test_load_sample_csv(self):
        """Test loading sample Blue Social Competences CSV"""
        csv_path = FIXTURES_DIR / "blue_social_competences_sample.csv"
        mapper = load_blue_competences(csv_path)

        assert mapper is not None
        assert len(mapper.competences) == 4

    def test_axis_mapping(self):
        """Test that competences are mapped to correct axes"""
        csv_path = FIXTURES_DIR / "blue_social_competences_sample.csv"
        mapper = load_blue_competences(csv_path)

        # Check axis distribution
        oceanic_comps = mapper.get_competences_by_axis(BlueDynamicsAxis.OCEANIC)
        maritime_comps = mapper.get_competences_by_axis(BlueDynamicsAxis.MARITIME)
        marine_comps = mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)

        assert len(oceanic_comps) == 1  # A.1
        assert len(maritime_comps) == 2  # B.1, D.1
        assert len(marine_comps) == 1  # C.1

    def test_level_assignment(self):
        """Test that all competences are assigned INTERMEDIATE level"""
        csv_path = FIXTURES_DIR / "blue_social_competences_sample.csv"
        mapper = load_blue_competences(csv_path)

        for comp in mapper.competences.values():
            assert comp.level == CompetenceLevel.INTERMEDIATE

    def test_name_extraction(self):
        """Test that competence names are correctly extracted"""
        csv_path = FIXTURES_DIR / "blue_social_competences_sample.csv"
        mapper = load_blue_competences(csv_path)

        comp_a1 = mapper.competences["blue_comp_a_1"]
        assert comp_a1.name == "Ocean literacy and ecosystems"

    def test_keywords_assignment(self):
        """Test that keywords are assigned to competences"""
        csv_path = FIXTURES_DIR / "blue_social_competences_sample.csv"
        mapper = load_blue_competences(csv_path)

        for comp in mapper.competences.values():
            assert "blue-economy" in comp.keywords
            assert "sustainability" in comp.keywords
            assert "ocean" in comp.keywords

    def test_axis_distribution_summary(self):
        """Test axis distribution in summary"""
        csv_path = FIXTURES_DIR / "blue_social_competences_sample.csv"
        mapper = load_blue_competences(csv_path)

        summary = mapper.get_summary()
        assert summary["competences_by_axis"]["OCEANIC"] == 1
        assert summary["competences_by_axis"]["MARITIME"] == 2
        assert summary["competences_by_axis"]["MARINE"] == 1

    def test_missing_file_handling(self):
        """Test handling of missing CSV file"""
        with pytest.raises(FileNotFoundError):
            load_blue_competences(FIXTURES_DIR / "nonexistent.csv")

    def test_empty_row_skipping(self):
        """Test that empty rows are skipped"""
        # Create temporary CSV with empty rows
        import tempfile
        import csv

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Competence Name", "Key Simplified Focus (Applied to all 12 Sectors)"])
            writer.writerow(["A.1", "Test Competence", "Description"])
            writer.writerow(["", "", ""])  # Empty row
            writer.writerow(["B.1", "Another Competence", "Description"])
            temp_path = Path(f.name)

        try:
            mapper = load_blue_competences(temp_path)
            # Should only load 2 competences, skipping the empty row
            assert len(mapper.competences) == 2
        finally:
            temp_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
