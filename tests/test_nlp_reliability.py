"""
Tests for the src/nlp_reliability module.

Covers deduplication, coverage, confidence scoring, and triangulation.
"""

from __future__ import annotations

from src.scientific_sources.models import LiteratureRecord, ProviderResult
from src.nlp_reliability.deduplication import deduplicate_records
from src.nlp_reliability.source_coverage import compute_coverage
from src.nlp_reliability.confidence import score_record_confidence, is_low_confidence
from src.nlp_reliability.triangulation import (
    build_provider_overlap_matrix,
    format_overlap_matrix_text,
)


def _rec(**kwargs) -> LiteratureRecord:
    defaults = dict(
        title="Blue Economy",
        authors="A. Smith",
        year="2023",
        doi="10.1/x",
        source_id="crossref:10.1/x",
        provider="Crossref",
    )
    defaults.update(kwargs)
    return LiteratureRecord(**defaults)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_doi_exact_dedup_removes_second_occurrence(self):
        r1 = _rec(doi="10.1/a", source_id="a1")
        r2 = _rec(doi="10.1/a", source_id="a2")
        unique, dups = deduplicate_records([r1, r2])
        assert len(unique) == 1
        assert len(dups) == 1

    def test_distinct_dois_are_kept(self):
        r1 = _rec(doi="10.1/a", source_id="a")
        r2 = _rec(doi="10.1/b", source_id="b", title="Different Title")
        unique, dups = deduplicate_records([r1, r2])
        assert len(unique) == 2
        assert len(dups) == 0

    def test_title_fuzzy_dedup_above_threshold(self):
        r1 = _rec(doi="", source_id="a", title="Blue Economy Governance in Europe")
        r2 = _rec(doi="", source_id="b", title="Blue Economy Governance in Europe")
        unique, dups = deduplicate_records([r1, r2])
        assert len(unique) == 1
        assert len(dups) == 1

    def test_title_fuzzy_dedup_below_threshold_keeps_both(self):
        r1 = _rec(doi="", source_id="a", title="Blue Economy in Poland")
        r2 = _rec(doi="", source_id="b", title="Maritime Sociology and Ocean Justice")
        unique, dups = deduplicate_records([r1, r2])
        assert len(unique) == 2
        assert len(dups) == 0

    def test_empty_input_returns_empty(self):
        unique, dups = deduplicate_records([])
        assert unique == []
        assert dups == []


# ---------------------------------------------------------------------------
# Source coverage
# ---------------------------------------------------------------------------


class TestSourceCoverage:
    def test_coverage_counts_providers(self):
        records = [
            _rec(doi="10.1/a", source_id="a", provider="Crossref"),
            _rec(doi="10.1/b", source_id="b", provider="Crossref"),
            _rec(doi="10.1/c", source_id="c", provider="Scopus"),
        ]
        cov = compute_coverage(records)
        assert cov["provider_counts"]["Crossref"] == 2
        assert cov["provider_counts"]["Scopus"] == 1
        assert cov["total_records"] == 3

    def test_coverage_flags_low_evidence_records(self):
        records = [
            _rec(doi="", source_id="a", journal=""),
            _rec(doi="10.1/b", source_id="b"),
        ]
        cov = compute_coverage(records)
        assert cov["low_confidence_count"] == 1
        assert "a" in cov["evidence_absent_flags"]

    def test_coverage_counts_doi_presence(self):
        records = [
            _rec(doi="10.1/a", source_id="a"),
            _rec(doi="", source_id="b"),
        ]
        cov = compute_coverage(records)
        assert cov["records_with_doi"] == 1
        assert cov["records_without_doi"] == 1

    def test_coverage_empty_list(self):
        cov = compute_coverage([])
        assert cov["total_records"] == 0


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_full_metadata_scores_high(self):
        rec = _rec(
            doi="10.1/x",
            authors="A. Smith",
            year="2024",
            journal="Ocean Studies",
            url="https://example.org",
            subject_terms=["blue economy"],
        )
        score = score_record_confidence(rec)
        assert score == 1.0

    def test_no_doi_scores_lower(self):
        rec = _rec(doi="", year="2024", journal="J", url="https://x.org")
        score = score_record_confidence(rec)
        assert score < 1.0
        assert score > 0.0

    def test_minimal_record_scores_low(self):
        rec = _rec(doi="", authors="Unknown", year="", journal="", url="")
        score = score_record_confidence(rec)
        assert score < 0.5

    def test_is_low_confidence_true_below_threshold(self):
        rec = _rec(doi="", authors="Unknown", year="", journal="", url="")
        assert is_low_confidence(rec) is True

    def test_is_low_confidence_false_above_threshold(self):
        rec = _rec(
            doi="10.1/x",
            authors="A. Smith",
            year="2024",
            journal="J",
            url="https://x.org",
        )
        assert is_low_confidence(rec) is False


# ---------------------------------------------------------------------------
# Triangulation
# ---------------------------------------------------------------------------


class TestTriangulation:
    def test_overlap_matrix_single_provider(self):
        results = [
            ProviderResult(
                records=[
                    _rec(doi="10.1/a", source_id="a", provider="Crossref"),
                    _rec(doi="10.1/b", source_id="b", provider="Crossref"),
                ]
            )
        ]
        matrix = build_provider_overlap_matrix(results)
        assert matrix["total_unique_dois"] == 2
        assert len(matrix["single_source_dois"]) == 2
        assert len(matrix["multi_source_dois"]) == 0

    def test_overlap_matrix_two_providers_sharing_doi(self):
        results = [
            ProviderResult(
                records=[_rec(doi="10.1/a", source_id="a", provider="Crossref")]
            ),
            ProviderResult(
                records=[_rec(doi="10.1/a", source_id="b", provider="Scopus")]
            ),
        ]
        matrix = build_provider_overlap_matrix(results)
        assert "10.1/a" in matrix["multi_source_dois"]
        assert len(matrix["overlap_pairs"]) == 1

    def test_overlap_matrix_skips_records_without_doi(self):
        results = [
            ProviderResult(records=[_rec(doi="", source_id="a", provider="Crossref")])
        ]
        matrix = build_provider_overlap_matrix(results)
        assert matrix["total_unique_dois"] == 0

    def test_format_overlap_text_contains_summary(self):
        results = [
            ProviderResult(
                records=[_rec(doi="10.1/a", source_id="a", provider="Crossref")]
            )
        ]
        text = format_overlap_matrix_text(results)
        assert "Provider Overlap Matrix" in text
        assert "Total unique DOIs" in text


# ---------------------------------------------------------------------------
# Jaccard similarity edge cases (covers deduplication.py lines 53, 55)
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:
    def test_both_empty_strings_return_one(self):
        from src.nlp_reliability.deduplication import _jaccard_similarity

        assert _jaccard_similarity("", "") == 1.0

    def test_one_empty_string_returns_zero(self):
        from src.nlp_reliability.deduplication import _jaccard_similarity

        assert _jaccard_similarity("", "blue economy") == 0.0
        assert _jaccard_similarity("ocean governance", "") == 0.0


# ---------------------------------------------------------------------------
# Subject term frequency (covers source_coverage.py line 68)
# ---------------------------------------------------------------------------


class TestSourceCoverageSubjectTerms:
    def test_subject_terms_are_counted(self):
        records = [
            _rec(
                doi="10.1/a",
                source_id="a",
                subject_terms=["blue economy", "ocean"],
            ),
            _rec(
                doi="10.1/b",
                source_id="b",
                subject_terms=["blue economy"],
            ),
        ]
        cov = compute_coverage(records)
        assert cov["subject_term_frequency"]["blue economy"] == 2
        assert cov["subject_term_frequency"]["ocean"] == 1


# ---------------------------------------------------------------------------
# format_overlap_matrix_text with pairwise overlap (covers triangulation.py
# lines 100-102)
# ---------------------------------------------------------------------------


class TestTriangulationPairwiseFormat:
    def test_format_overlap_text_shows_pairwise_overlap_section(self):
        results = [
            ProviderResult(
                records=[_rec(doi="10.1/a", source_id="a", provider="Crossref")]
            ),
            ProviderResult(
                records=[_rec(doi="10.1/a", source_id="b", provider="Scopus")]
            ),
        ]
        text = format_overlap_matrix_text(results)
        assert "Pairwise overlap:" in text
        assert "shared DOI" in text
