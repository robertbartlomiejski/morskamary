"""Tests for src/axis_classifier.py - TMBD axis classification logic."""

from src.axis_classifier import AxisClassifier
from src.core import BlueDynamicsAxis


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
        result = classifier.classify_axis("This competence involves ecosystem management")
        assert result == BlueDynamicsAxis.MARINE

    def test_classify_no_dimension_with_biodiversity_keyword(self):
        """Text containing 'biodiversity' should map to MARINE."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("Understanding biodiversity in marine environments")
        assert result == BlueDynamicsAxis.MARINE

    def test_classify_no_dimension_with_port_keyword(self):
        """Text containing 'port' should map to MARITIME."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("Port operations and logistics management")
        assert result == BlueDynamicsAxis.MARITIME

    def test_classify_no_dimension_with_shipping_keyword(self):
        """Text containing 'shipping' should map to MARITIME."""
        classifier = AxisClassifier()
        result = classifier.classify_axis("Shipping industry regulations and compliance")
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
        result = classifier.classify_axis("Policy frameworks for sustainable blue economy")
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
        result = classifier.classify_axis("Understanding ecosystem biodiversity", dimension="B.1")
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
