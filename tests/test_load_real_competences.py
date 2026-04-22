"""Tests for load_real_competences module."""

import pytest
from pathlib import Path
from src.core import BlueDynamicsAxis, CompetenceLevel
from load_real_competences import map_dimension_to_axis, load_blue_competences


class TestMapDimensionToAxis:
    """Tests for dimension to TMBD axis mapping"""

    def test_dimension_a_maps_to_oceanic(self):
        """Dimension A (Understanding) should map to OCEANIC"""
        assert map_dimension_to_axis("A.1") == BlueDynamicsAxis.OCEANIC
        assert map_dimension_to_axis("A.2") == BlueDynamicsAxis.OCEANIC

    def test_dimension_b_maps_to_maritime(self):
        """Dimension B (Digital & Data) should map to MARITIME"""
        assert map_dimension_to_axis("B.1") == BlueDynamicsAxis.MARITIME
        assert map_dimension_to_axis("B.2") == BlueDynamicsAxis.MARITIME

    def test_dimension_c_maps_to_marine(self):
        """Dimension C (Sustainability) should map to MARINE"""
        assert map_dimension_to_axis("C.1") == BlueDynamicsAxis.MARINE
        assert map_dimension_to_axis("C.2") == BlueDynamicsAxis.MARINE

    def test_dimension_d_maps_to_maritime(self):
        """Dimension D (Business/Governance) should map to MARITIME"""
        assert map_dimension_to_axis("D.1") == BlueDynamicsAxis.MARITIME
        assert map_dimension_to_axis("D.2") == BlueDynamicsAxis.MARITIME

    def test_dimension_without_dot(self):
        """Test dimension without dot separator"""
        assert map_dimension_to_axis("A") == BlueDynamicsAxis.OCEANIC
        assert map_dimension_to_axis("B") == BlueDynamicsAxis.MARITIME
        assert map_dimension_to_axis("C") == BlueDynamicsAxis.MARINE
        assert map_dimension_to_axis("D") == BlueDynamicsAxis.MARITIME

    def test_unknown_dimension_defaults_to_oceanic(self):
        """Unknown dimensions should default to OCEANIC"""
        assert map_dimension_to_axis("X.1") == BlueDynamicsAxis.OCEANIC
        assert map_dimension_to_axis("Z") == BlueDynamicsAxis.OCEANIC


class TestLoadBlueCompetences:
    """Tests for loading Blue Social Competences from CSV"""

    def test_load_sample_competences(self):
        """Test loading from sample CSV file"""
        csv_path = Path("tests/fixtures/blue_social_competences_sample.csv")
        mapper = load_blue_competences(csv_path)

        # Should have loaded 5 competences
        assert len(mapper.competences) == 5

        # Check that competences were created with correct IDs
        comp_ids = list(mapper.competences.keys())
        assert "blue_comp_a_1" in comp_ids
        assert "blue_comp_b_1" in comp_ids
        assert "blue_comp_c_1" in comp_ids
        assert "blue_comp_d_1" in comp_ids

    def test_competence_axis_mapping(self):
        """Test that competences are mapped to correct axes"""
        csv_path = Path("tests/fixtures/blue_social_competences_sample.csv")
        mapper = load_blue_competences(csv_path)

        # A dimension → OCEANIC
        comp_a = mapper.competences.get("blue_comp_a_1")
        assert comp_a is not None
        assert comp_a.axis == BlueDynamicsAxis.OCEANIC

        # B dimension → MARITIME
        comp_b = mapper.competences.get("blue_comp_b_1")
        assert comp_b is not None
        assert comp_b.axis == BlueDynamicsAxis.MARITIME

        # C dimension → MARINE
        comp_c = mapper.competences.get("blue_comp_c_1")
        assert comp_c is not None
        assert comp_c.axis == BlueDynamicsAxis.MARINE

        # D dimension → MARITIME
        comp_d = mapper.competences.get("blue_comp_d_1")
        assert comp_d is not None
        assert comp_d.axis == BlueDynamicsAxis.MARITIME

    def test_competence_level(self):
        """Test that all competences are set to INTERMEDIATE level"""
        csv_path = Path("tests/fixtures/blue_social_competences_sample.csv")
        mapper = load_blue_competences(csv_path)

        for comp in mapper.competences.values():
            assert comp.level == CompetenceLevel.INTERMEDIATE

    def test_competence_names(self):
        """Test that competence names are loaded correctly"""
        csv_path = Path("tests/fixtures/blue_social_competences_sample.csv")
        mapper = load_blue_competences(csv_path)

        comp_a1 = mapper.competences.get("blue_comp_a_1")
        assert comp_a1 is not None
        assert comp_a1.name == "Understanding Blue Economy Sectors"

    def test_competence_keywords(self):
        """Test that competences have default keywords"""
        csv_path = Path("tests/fixtures/blue_social_competences_sample.csv")
        mapper = load_blue_competences(csv_path)

        comp = mapper.competences.get("blue_comp_a_1")
        assert comp is not None
        assert "blue-economy" in comp.keywords
        assert "sustainability" in comp.keywords
        assert "ocean" in comp.keywords

    def test_axis_distribution_in_summary(self):
        """Test that loaded competences are distributed across axes"""
        csv_path = Path("tests/fixtures/blue_social_competences_sample.csv")
        mapper = load_blue_competences(csv_path)

        summary = mapper.get_summary()

        # Should have competences on multiple axes
        assert summary["competences_by_axis"]["OCEANIC"] >= 1  # A dimensions
        assert summary["competences_by_axis"]["MARITIME"] >= 2  # B and D dimensions
        assert summary["competences_by_axis"]["MARINE"] >= 1  # C dimensions

    def test_missing_csv_file(self):
        """Test handling of non-existent CSV file"""
        csv_path = Path("tests/fixtures/nonexistent.csv")
        # The function should raise FileNotFoundError
        with pytest.raises(FileNotFoundError):
            load_blue_competences(csv_path)

    def test_empty_rows_are_skipped(self, tmp_path):
        """Test that rows without ID or name are skipped"""
        # Create a CSV with some empty rows in isolated temp directory
        csv_content = """ID,Competence Name,Key Simplified Focus (Applied to all 12 Sectors),imension (Aspect)
A.1,Valid Competence,Description,A. Understanding
,,Missing both,A. Understanding
B.1,,Missing name,B. Digital
,Missing ID,Description,C. Sustainability
"""
        csv_path = tmp_path / "temp_with_empty.csv"
        csv_path.write_text(csv_content)

        mapper = load_blue_competences(csv_path)
        # Should only load the valid row
        assert len(mapper.competences) == 1
        assert "blue_comp_a_1" in mapper.competences


class TestMainFunction:
    """Tests for main() CLI entry point"""

    def test_main_cli_execution(self):
        """Test that main() can be executed as CLI script"""
        import load_real_competences

        # Test the if __name__ == "__main__" block indirectly
        # by calling main() and checking it returns int
        result = load_real_competences.main()
        assert isinstance(result, int)
        assert result in (0, 1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
