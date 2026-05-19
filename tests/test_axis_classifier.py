"""Tests for src/axis_classifier.py - TMBD axis classification logic."""

import pytest
from src.axis_classifier import AxisClassifier
from src.core import BlueDynamicsAxis
from src.dimension_mapping import map_dimension_to_axis


class TestAxisClassifier:
    """Test suite for AxisClassifier."""

    def test_classify_with_dimension_a_returns_oceanic(self):
        """Dimension A (Understanding) maps to OCEANIC axis."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("any text", dimension="A.1")
        assert result == BlueDynamicsAxis.OCEANIC

    def test_classify_with_dimension_b_returns_maritime(self):
        """Dimension B (Digital/Data) maps to MARITIME axis."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("any text", dimension="B.2")
        assert result == BlueDynamicsAxis.MARITIME

    def test_classify_with_dimension_c_returns_marine(self):
        """Dimension C (Sustainability) maps to MARINE axis."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("any text", dimension="C.3")
        assert result == BlueDynamicsAxis.MARINE

    def test_classify_with_dimension_d_returns_maritime(self):
        """Dimension D (Business/Governance) maps to MARITIME axis."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("any text", dimension="D.4")
        assert result == BlueDynamicsAxis.MARITIME

    def test_classify_no_dimension_with_ecosystem_keyword(self):
        """Text containing 'ecosystem' should map to MARINE."""
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "This competence involves ecosystem management"
        )
        assert result == BlueDynamicsAxis.MARINE

    def test_classify_no_dimension_with_biodiversity_keyword(self):
        """Text containing 'biodiversity' should map to MARINE."""
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "Understanding biodiversity in marine environments"
        )
        assert result == BlueDynamicsAxis.MARINE

    def test_classify_no_dimension_with_port_keyword(self):
        """Text containing 'port' should map to MARITIME."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("Port operations and logistics management")
        assert result == BlueDynamicsAxis.MARITIME

    def test_classify_no_dimension_with_shipping_keyword(self):
        """Text containing 'shipping' should map to MARITIME."""
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "Shipping industry regulations and compliance"
        )
        assert result == BlueDynamicsAxis.MARITIME

    def test_classify_no_dimension_with_infrastructure_keyword(self):
        """Text containing 'infrastructure' should map to MARITIME."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("Maritime infrastructure development")
        assert result == BlueDynamicsAxis.MARITIME

    def test_classify_no_dimension_with_governance_keyword(self):
        """Text containing 'governance' should map to OCEANIC."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("Ocean governance and international policy")
        assert result == BlueDynamicsAxis.OCEANIC

    def test_classify_no_dimension_with_policy_keyword(self):
        """Text containing 'policy' should map to OCEANIC."""
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "Policy frameworks for sustainable blue economy"
        )
        assert result == BlueDynamicsAxis.OCEANIC

    def test_classify_empty_text_returns_oceanic_default(self):
        """Empty text with no dimension should default to OCEANIC."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("")
        assert result == BlueDynamicsAxis.OCEANIC

    def test_classify_whitespace_only_text_returns_oceanic_default(self):
        """Whitespace-only text with no dimension should default to OCEANIC."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("   \n\t   ")
        assert result == BlueDynamicsAxis.OCEANIC

    def test_classify_no_dimension_no_keywords_returns_oceanic(self):
        """Text without dimension or keywords should default to OCEANIC."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("Generic blue economy competence")
        assert result == BlueDynamicsAxis.OCEANIC

    def test_dimension_takes_priority_over_keywords(self):
        """When both dimension and keywords present, dimension takes priority."""
        classifier = AxisClassifier()
        # Text suggests MARINE (ecosystem), but dimension B.1 should give MARITIME
        result = classifier.classify_axis(
            "Understanding ecosystem biodiversity", dimension="B.1"
        )
        assert result == BlueDynamicsAxis.MARITIME

    def test_classify_case_insensitive_keywords(self):
        """Keyword matching should be case-insensitive."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("GOVERNANCE and POLICY frameworks")
        assert result == BlueDynamicsAxis.OCEANIC

    def test_classify_multiple_spaces_normalized(self):
        """Multiple spaces in text should be normalized before keyword matching."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("port    operations   with    logistics")
        assert result == BlueDynamicsAxis.MARITIME

    def test_keyword_matching_uses_word_boundaries(self):
        """Partial-word matches must not trigger false-positive axis assignment."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("Important blue economy transitions")
        assert result == BlueDynamicsAxis.OCEANIC

    def test_classify_context_returns_sentence_level_metadata(self):
        """classify_context should emit axis metadata for one sentence."""
        classifier = AxisClassifier()
        result = classifier.classify_context(
            "Port logistics and shipping corridors are expanding.",
            text_scope="live_api_abstract_sentence",
        )
        assert result["axis"] == BlueDynamicsAxis.MARITIME.name
        assert result["axis_code"] == BlueDynamicsAxis.MARITIME.value
        assert result["text_scope"] == "live_api_abstract_sentence"
        assert (
            result["sentence"] == "Port logistics and shipping corridors are expanding."
        )

    def test_classify_context_collects_keyword_matches(self):
        """Matched keywords should be included in classify_context output."""
        classifier = AxisClassifier()
        result = classifier.classify_context("Hydrosocial governance transitions.")
        assert result["axis"] == BlueDynamicsAxis.HYDRONIZATION.name
        assert "hydrosocial" in result["matched_keywords"]


class TestMapDimensionToAxis:
    """Direct tests for map_dimension_to_axis edge cases."""

    def test_empty_string_returns_oceanic(self):
        """Empty dimension string defaults to OCEANIC."""
        assert map_dimension_to_axis("") == BlueDynamicsAxis.OCEANIC

    def test_whitespace_only_returns_oceanic(self):
        """Whitespace-only dimension string defaults to OCEANIC."""
        assert map_dimension_to_axis("   ") == BlueDynamicsAxis.OCEANIC


# ---------------------------------------------------------------------------
# QMBD 4D — Hydronization axis tests
# ---------------------------------------------------------------------------


class TestQMBDHydronizationAxis:
    """Tests proving the additive QMBD 4th axis (Hydronization) is correctly
    classified and does not break the legacy TMBD 3-axis logic.

    Keyword basis:
    - "hydronization": direct 4th-axis term (QMBD spec).
    - "hydrosocial": Linton & Budds (2014) "The hydrosocial cycle", Geoforum 57
      (docs/literature/Bartłomiejskie Cocco krytyka oceanocentryzmu.txt:912);
      also in scripts/cumulative_fragment_analysis.py:qmbd_label_from_text.
    - "wet ontology": Steinberg & Peters (2015) via Bartłomiejski Cocco
      Performatywność wody morza oceanu.txt:2064-2066; also in
      scripts/cumulative_fragment_analysis.py:qmbd_label_from_text.
    """

    def test_hydronization_keyword_maps_to_hydronization_axis(self):
        """Text containing 'hydronization' must map to HYDRONIZATION."""
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "The process of hydronization reshapes coastal society"
        )
        assert result == BlueDynamicsAxis.HYDRONIZATION

    def test_hydrosocial_keyword_maps_to_hydronization_axis(self):
        """Text containing 'hydrosocial' must map to HYDRONIZATION."""
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "Hydrosocial relations in Baltic coastal communities"
        )
        assert result == BlueDynamicsAxis.HYDRONIZATION

    def test_hydronization_keyword_matching_normalizes_hyphens(self):
        """Hyphen variants like 'hydro-social territory' should classify as HYDRONIZATION."""
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "Hydro-social territory in urban delta governance"
        )
        assert result == BlueDynamicsAxis.HYDRONIZATION

    def test_porosity_keyword_maps_to_hydronization_axis(self):
        """Text containing 'porosity' should map to HYDRONIZATION."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("Water porosity and sponge city planning")
        assert result == BlueDynamicsAxis.HYDRONIZATION

    def test_wet_ontology_maps_to_hydronization_axis(self):
        """Text containing 'wet ontology' must map to HYDRONIZATION."""
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "Wet ontology perspectives in maritime sociology"
        )
        assert result == BlueDynamicsAxis.HYDRONIZATION

    def test_hydronization_does_not_supersede_marine_when_marine_appears_first(self):
        """MARINE keywords appear before HYDRONIZATION in KEYWORD_AXIS_MAP.

        When both MARINE and HYDRONIZATION keywords are present in the same
        text, the first-match rule means MARINE wins.
        """
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "Ecosystem biodiversity and hydrosocial relations"
        )
        assert result == BlueDynamicsAxis.MARINE

    def test_hydronization_takes_precedence_over_oceanic(self):
        """HYDRONIZATION is checked before OCEANIC in the keyword scan order.

        A text with both 'hydrosocial' and 'governance' should yield
        HYDRONIZATION because HYDRONIZATION appears earlier in KEYWORD_AXIS_MAP.
        """
        classifier = AxisClassifier()
        result = classifier.classify_axis(
            "Hydrosocial governance and ocean policy frameworks"
        )
        assert result == BlueDynamicsAxis.HYDRONIZATION

    def test_hydronization_axis_value(self):
        """HYDRONIZATION axis value must be 'H' (QMBD 4th dimension code)."""
        assert BlueDynamicsAxis.HYDRONIZATION.value == "H"

    def test_four_axes_in_enum(self):
        """BlueDynamicsAxis must now have exactly four members (QMBD model)."""
        axes = list(BlueDynamicsAxis)
        assert len(axes) == 4
        names = {a.name for a in axes}
        assert names == {"MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION"}

    # --- Legacy TMBD axes unaffected ----------------------------------------

    def test_legacy_marine_axis_still_works(self):
        """TMBD MARINE axis must still classify correctly after QMBD extension."""
        classifier = AxisClassifier()
        assert (
            classifier.classify_axis("Ecosystem and habitat conservation")
            == BlueDynamicsAxis.MARINE
        )

    def test_legacy_maritime_axis_still_works(self):
        """TMBD MARITIME axis must still classify correctly after QMBD extension."""
        classifier = AxisClassifier()
        assert (
            classifier.classify_axis("Port operations and shipping logistics")
            == BlueDynamicsAxis.MARITIME
        )

    def test_legacy_oceanic_axis_still_works(self):
        """TMBD OCEANIC axis must still classify correctly after QMBD extension."""
        classifier = AxisClassifier()
        assert (
            classifier.classify_axis("Governance and international policy cooperation")
            == BlueDynamicsAxis.OCEANIC
        )

    def test_legacy_oceanic_fallback_unchanged(self):
        """Default fallback (no dimension, no keywords) must still be OCEANIC."""
        classifier = AxisClassifier()
        assert classifier.classify_axis("") == BlueDynamicsAxis.OCEANIC
        assert (
            classifier.classify_axis("Generic blue economy text")
            == BlueDynamicsAxis.OCEANIC
        )

    def test_dimension_path_does_not_route_to_hydronization(self):
        """Dimension-based classification (A/B/C/D) must not produce HYDRONIZATION.

        The dimension→axis mapping covers only the original TMBD axes.
        Hydronization is reachable via the keyword path only.
        """
        classifier = AxisClassifier()
        for dim in ("A", "B", "C", "D", "A.1", "B.2", "C.3", "D.4"):
            result = classifier.classify_axis(
                "hydronization hydrosocial wet ontology", dimension=dim
            )
            assert (
                result != BlueDynamicsAxis.HYDRONIZATION
            ), f"Dimension '{dim}' must not route to HYDRONIZATION"


# ---------------------------------------------------------------------------
# Negative / regression tests for input validation
# ---------------------------------------------------------------------------


class TestAxisClassifierInputValidation:
    """Regression tests that guard against invalid inputs reaching the classifier."""

    def test_classify_axis_raises_type_error_for_non_str_text(self):
        """Passing a non-str value for ``text`` must raise TypeError."""
        classifier = AxisClassifier()
        with pytest.raises(TypeError, match="Expected 'text' to be str"):
            classifier.classify_axis(text=None)  # type: ignore[arg-type]

    def test_classify_axis_raises_type_error_for_non_str_dimension(self):
        """Passing a non-str value for ``dimension`` must raise TypeError."""
        classifier = AxisClassifier()
        with pytest.raises(TypeError, match="Expected 'dimension' to be str"):
            classifier.classify_axis(text="Some text", dimension=123)  # type: ignore[arg-type]

    def test_classify_context_raises_type_error_for_non_str_text(self):
        """Passing a non-str value for ``text`` to classify_context must raise TypeError."""
        classifier = AxisClassifier()
        with pytest.raises(TypeError, match="Expected 'text' to be str"):
            classifier.classify_context(text=42)  # type: ignore[arg-type]

    def test_classify_context_raises_value_error_for_empty_text_scope(self):
        """Passing an empty string for ``text_scope`` must raise ValueError."""
        classifier = AxisClassifier()
        with pytest.raises(ValueError, match="'text_scope' must be a non-empty string"):
            classifier.classify_context(text="Some text", text_scope="")

    def test_classify_context_raises_value_error_for_none_text_scope(self):
        """Passing None for ``text_scope`` must raise ValueError."""
        classifier = AxisClassifier()
        with pytest.raises(ValueError, match="'text_scope' must be a non-empty string"):
            classifier.classify_context(text="Some text", text_scope=None)  # type: ignore[arg-type]

    def test_classify_context_raises_value_error_for_whitespace_text_scope(self):
        """Passing whitespace-only string for ``text_scope`` must raise ValueError."""
        classifier = AxisClassifier()
        with pytest.raises(ValueError, match="'text_scope' must be a non-empty string"):
            classifier.classify_context(text="Some text", text_scope="   ")

    def test_dimension_lowercase_normalized_to_uppercase(self):
        """Lowercase dimension code must produce the same axis as its uppercase equivalent.

        Dimension 'b.1' (lowercase) should yield MARITIME, identical to 'B.1'.
        """
        classifier = AxisClassifier()
        assert classifier.classify_axis("some text", dimension="b.1") == BlueDynamicsAxis.MARITIME
        assert classifier.classify_axis("some text", dimension="a") == BlueDynamicsAxis.OCEANIC
        assert classifier.classify_axis("some text", dimension="c") == BlueDynamicsAxis.MARINE

    def test_dimension_mixed_case_normalized(self):
        """Mixed-case dimension codes must be handled correctly after normalization."""
        classifier = AxisClassifier()
        assert classifier.classify_axis("some text", dimension="B.2") == classifier.classify_axis(
            "some text", dimension="b.2"
        )
