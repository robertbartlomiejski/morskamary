"""Tests for literature abstraction extraction API."""

from src.literature_extraction import LiteratureExtractor, extract_from_abstracts


def test_extracts_excerpt_with_competence_phrase() -> None:
    text = "This abstract discusses blue economy competence development in ports."

    records = extract_from_abstracts(text)

    assert len(records) == 1
    assert "competence" in records[0]["abstract_excerpt"].lower()


def test_records_include_required_fields() -> None:
    text = "Capacity building and maritime skills are central to adaptation."

    records = extract_from_abstracts(text)

    assert records
    required_fields = {"abstract_excerpt", "extraction_method", "confidence_score"}
    assert required_fields.issubset(records[0].keys())


def test_empty_input_returns_no_records() -> None:
    extractor = LiteratureExtractor()

    assert extractor.detect_competence_phrases("") == []
    assert extractor.detect_competence_phrases("   ") == []
