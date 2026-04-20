"""Edge case and error handling tests for morskamary."""

import pytest
from pathlib import Path
from src.core import (
    Competence,
    MicroCredential,
    BlueDynamicsAxis,
    CompetenceLevel,
)
from src.competence_mapper import CompetenceMapper
from src.competence_repository import (
    normalize_sector_name,
    classify_competence_origin,
    ORIGIN_BASELINE,
    ORIGIN_LITERATURE,
    ORIGIN_UNKNOWN,
)


class TestBlueDynamicsAxisEnum:
    """Tests for BlueDynamicsAxis enum edge cases"""

    def test_enum_values(self):
        """Test that enum values are correct"""
        assert BlueDynamicsAxis.MARINE.value == "M"
        assert BlueDynamicsAxis.MARITIME.value == "T"
        assert BlueDynamicsAxis.OCEANIC.value == "O"

    def test_enum_names(self):
        """Test that enum names are correct"""
        assert BlueDynamicsAxis.MARINE.name == "MARINE"
        assert BlueDynamicsAxis.MARITIME.name == "MARITIME"
        assert BlueDynamicsAxis.OCEANIC.name == "OCEANIC"

    def test_enum_iteration(self):
        """Test that all axes can be iterated"""
        axes = list(BlueDynamicsAxis)
        assert len(axes) == 3
        assert BlueDynamicsAxis.MARINE in axes
        assert BlueDynamicsAxis.MARITIME in axes
        assert BlueDynamicsAxis.OCEANIC in axes


class TestCompetenceLevelEnum:
    """Tests for CompetenceLevel enum edge cases"""

    def test_enum_values(self):
        """Test that enum values represent progression"""
        assert CompetenceLevel.FOUNDATIONAL.value == 1
        assert CompetenceLevel.INTERMEDIATE.value == 2
        assert CompetenceLevel.ADVANCED.value == 3
        assert CompetenceLevel.EXPERT.value == 4

    def test_enum_ordering(self):
        """Test that levels can be compared"""
        assert CompetenceLevel.FOUNDATIONAL.value < CompetenceLevel.INTERMEDIATE.value
        assert CompetenceLevel.INTERMEDIATE.value < CompetenceLevel.ADVANCED.value
        assert CompetenceLevel.ADVANCED.value < CompetenceLevel.EXPERT.value


class TestNormalizeSectorName:
    """Tests for sector name normalization"""

    def test_basic_normalization(self):
        """Test basic lowercase and space handling"""
        assert normalize_sector_name("Blue Biotech") == "blue biotech"
        assert normalize_sector_name("BLUE BIOTECH") == "blue biotech"
        assert normalize_sector_name("blue biotech") == "blue biotech"

    def test_punctuation_removal(self):
        """Test that punctuation is removed"""
        assert normalize_sector_name("Blue-Biotech") == "blue biotech"
        assert normalize_sector_name("R&I") == "r i"
        assert normalize_sector_name("Blue--Biotech!!") == "blue biotech"

    def test_multiple_spaces(self):
        """Test that multiple spaces are collapsed"""
        assert normalize_sector_name("Blue   Biotech") == "blue biotech"
        assert normalize_sector_name("  Blue  Biotech  ") == "blue biotech"

    def test_special_characters(self):
        """Test handling of special characters"""
        assert normalize_sector_name("Ports & Harbors") == "ports harbors"
        assert normalize_sector_name("R&I (Research)") == "r i research"

    def test_unicode_handling(self):
        """Test handling of unicode characters"""
        # Non-ASCII characters outside [a-z0-9], such as "é", are treated as
        # separators and removed/split rather than transliterated.
        result = normalize_sector_name("Océan Bleu")
        # Only ASCII alphanumeric tokens that remain after normalization are kept.
        assert "bleu" in result

    def test_empty_string(self):
        """Test handling of empty string"""
        assert normalize_sector_name("") == ""
        assert normalize_sector_name("   ") == ""

    def test_numbers_preserved(self):
        """Test that numbers are preserved"""
        assert normalize_sector_name("Sector123") == "sector123"
        assert normalize_sector_name("R&I 2030") == "r i 2030"


class TestClassifyCompetenceOrigin:
    """Tests for competence origin classification"""

    def test_baseline_identification(self):
        """Test baseline competence identification"""
        assert classify_competence_origin("baseline_a1") == ORIGIN_BASELINE
        assert classify_competence_origin("baseline_b2") == ORIGIN_BASELINE
        assert classify_competence_origin("baseline_") == ORIGIN_BASELINE

    def test_baseline_case_insensitive(self):
        """Test that baseline matching is case-insensitive"""
        assert classify_competence_origin("BASELINE_a1") == ORIGIN_BASELINE
        assert classify_competence_origin("Baseline_a1") == ORIGIN_BASELINE
        assert classify_competence_origin("BaSeLiNe_a1") == ORIGIN_BASELINE

    def test_literature_identification(self):
        """Test literature competence identification"""
        assert classify_competence_origin("lit_labor_justice_0001") == ORIGIN_LITERATURE
        assert classify_competence_origin("lit_test_0002") == ORIGIN_LITERATURE

    def test_literature_case_insensitive(self):
        """Test that literature matching is case-insensitive"""
        assert classify_competence_origin("LIT_test_0001") == ORIGIN_LITERATURE
        assert classify_competence_origin("Lit_test_0001") == ORIGIN_LITERATURE

    def test_unknown_identification(self):
        """Test unknown competence identification"""
        assert classify_competence_origin("comp_001") == ORIGIN_UNKNOWN
        assert classify_competence_origin("other_001") == ORIGIN_UNKNOWN
        assert classify_competence_origin("baselinea1") == ORIGIN_UNKNOWN  # no underscore
        assert classify_competence_origin("my_baseline_data") == ORIGIN_UNKNOWN  # not at start

    def test_edge_cases(self):
        """Test edge cases for origin classification"""
        assert classify_competence_origin("baseline") == ORIGIN_BASELINE  # just "baseline"
        assert classify_competence_origin("lit_") == ORIGIN_LITERATURE  # just "lit_"
        assert classify_competence_origin("baseline2_test") == ORIGIN_UNKNOWN  # baseline not at boundary
        assert classify_competence_origin("  baseline_a1  ") == ORIGIN_BASELINE  # with whitespace


class TestCompetenceEdgeCases:
    """Edge case tests for Competence dataclass"""

    def test_empty_keywords(self):
        """Test competence with empty keywords list"""
        comp = Competence(
            id="test_001",
            name="Test",
            description="Test",
            axis=BlueDynamicsAxis.MARINE,
            level=CompetenceLevel.FOUNDATIONAL,
            keywords=[],
        )
        assert comp.keywords == []
        comp_dict = comp.to_dict()
        assert comp_dict["keywords"] == []

    def test_long_description(self):
        """Test competence with very long description"""
        long_desc = "A" * 10000
        comp = Competence(
            id="test_001",
            name="Test",
            description=long_desc,
            axis=BlueDynamicsAxis.MARINE,
            level=CompetenceLevel.FOUNDATIONAL,
            keywords=["test"],
        )
        assert len(comp.description) == 10000

    def test_special_characters_in_fields(self):
        """Test competence with special characters"""
        comp = Competence(
            id="test_001",
            name="Test & Development",
            description="Testing <special> characters: @#$%",
            axis=BlueDynamicsAxis.MARINE,
            level=CompetenceLevel.FOUNDATIONAL,
            keywords=["test", "special-chars", "utf8:é"],
        )
        assert "&" in comp.name
        assert "<special>" in comp.description


class TestMicroCredentialEdgeCases:
    """Edge case tests for MicroCredential dataclass"""

    def test_empty_competences_list(self):
        """Test credential with no competences"""
        cred = MicroCredential(
            id="cred_001",
            title="Empty Credential",
            competences=[],
            description="No competences",
            sector="test",
        )
        assert len(cred.competences) == 0

    def test_many_competences(self):
        """Test credential with many competences"""
        many_comps = [f"comp_{i:03d}" for i in range(100)]
        cred = MicroCredential(
            id="cred_001",
            title="Large Credential",
            competences=many_comps,
            description="Many competences",
            sector="test",
        )
        assert len(cred.competences) == 100

    def test_duplicate_competences(self):
        """Test credential with duplicate competences"""
        cred = MicroCredential(
            id="cred_001",
            title="Duplicate Credential",
            competences=["comp_001", "comp_001", "comp_002"],
            description="Has duplicates",
            sector="test",
        )
        # Should preserve duplicates (business logic may dedupe later)
        assert len(cred.competences) == 3


class TestCompetenceMapperEdgeCases:
    """Edge case tests for CompetenceMapper"""

    def test_empty_mapper_operations(self):
        """Test operations on empty mapper"""
        mapper = CompetenceMapper()

        assert len(mapper.competences) == 0
        assert len(mapper.credentials) == 0

        # Operations on empty mapper should not fail
        marine = mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)
        assert len(marine) == 0

        summary = mapper.get_summary()
        assert summary["total_competences"] == 0
        assert summary["total_credentials"] == 0

    def test_duplicate_competence_ids(self):
        """Test adding competence with duplicate ID (should overwrite)"""
        mapper = CompetenceMapper()

        comp1 = Competence(
            id="comp_001",
            name="First",
            description="First version",
            axis=BlueDynamicsAxis.MARINE,
            level=CompetenceLevel.FOUNDATIONAL,
            keywords=["first"],
        )
        comp2 = Competence(
            id="comp_001",
            name="Second",
            description="Second version",
            axis=BlueDynamicsAxis.MARITIME,
            level=CompetenceLevel.ADVANCED,
            keywords=["second"],
        )

        mapper.add_competence(comp1)
        mapper.add_competence(comp2)

        # Should only have one competence (overwritten)
        assert len(mapper.competences) == 1
        # Should be the second one
        assert mapper.competences["comp_001"].name == "Second"

    def test_analyze_gaps_with_extra_competences(self):
        """Test gap analysis when user has more than required"""
        mapper = CompetenceMapper()

        comp = Competence(
            id="comp_001",
            name="Test",
            description="Test",
            axis=BlueDynamicsAxis.MARINE,
            level=CompetenceLevel.FOUNDATIONAL,
            keywords=["test"],
        )
        mapper.add_competence(comp)

        cred = MicroCredential(
            id="cred_001",
            title="Test Cred",
            competences=["comp_001"],
            description="Test",
            sector="test-sector",
        )
        mapper.add_credentials(cred)

        # User has more competences than required
        gaps = mapper.analyze_competence_gaps(
            available=["comp_001", "comp_002", "comp_003"],
            required_sector="test-sector"
        )

        assert len(gaps["available"]) == 1  # Only comp_001 is required
        assert len(gaps["missing"]) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
