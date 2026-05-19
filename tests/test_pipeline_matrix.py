"""
tests/test_pipeline_matrix.py — Unified QMBD Matrix Smoke Test

End-to-end methodological verification of the Quadripartite Model of Blue
Dynamics (QMBD) pipeline.  Covers the full path from mocked live API
ingestion through sentence-level QMBD classification, static-fixture
triangulation, and structural schema validation.

Directive 4: Implement the Unified Matrix Smoke Test.
"""

from __future__ import annotations

import csv
import json
import urllib.request
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from run_full_analysis import (
    TMBDAxis,
    _classify_sentence_contexts,
)
from scripts.export_live_research_records import (
    LiveContextClassificationRepository,
    _DEFAULT_PROVIDER_POLICY,
    triangulate_identity_loop,
)
from src.axis_classifier import AxisClassifier
from src.cumulative_analysis.triangulator import ClaimOrigin, CumulativeTriangulator
from src.literature_extraction import extract_sentences
from src.scientific_sources.crossref import CrossrefProvider
from src.scientific_sources.models import LiteratureRecord

# ---------------------------------------------------------------------------
# Mock Crossref HTTP response payload
# ---------------------------------------------------------------------------
# Three test items designed to exercise distinct QMBD classification paths.

_CROSSREF_MOCK_PAYLOAD: Dict[str, Any] = {
    "message": {
        "items": [
            {
                # Record 1 — Marine + Hydronization terms (multi-axis)
                "title": [
                    "Marine ecosystem biodiversity and hydrosocial territory networks"
                ],
                "author": [{"given": "Alice", "family": "Marine"}],
                "URL": "https://doi.org/10.9999/marine001",
                "DOI": "10.9999/marine001",
                "published": {"date-parts": [[2024, 1, 1]]},
                "container-title": ["Marine Ecology Quarterly"],
                "subject": ["ecosystem", "hydronization", "biodiversity", "habitat"],
            },
            {
                # Record 2 — "blue economy" + "resilience" only; NO axis keywords
                # → UNCLASSIFIED_REVIEW_REQUIRED and is_blue_planetaryism=True
                "title": ["Blue economy resilience pathways for coastal transition"],
                "author": [{"given": "Bob", "family": "Blue"}],
                "URL": "https://doi.org/10.9999/blue002",
                "DOI": "10.9999/blue002",
                "published": {"date-parts": [[2024, 2, 1]]},
                "container-title": ["Ocean Policy"],
                "subject": ["blue economy", "resilience", "coastal adaptation"],
            },
            {
                # Record 3 — pure Maritime terms
                "title": ["Port 4.0 and maritime supply chain acceleration"],
                "author": [{"given": "Carol", "family": "Maritime"}],
                "URL": "https://doi.org/10.9999/maritime003",
                "DOI": "10.9999/maritime003",
                "published": {"date-parts": [[2024, 3, 1]]},
                "container-title": ["Maritime Research"],
                "subject": ["port", "shipping", "logistics", "infrastructure"],
            },
        ]
    }
}


class _DummyHTTPResponse:
    """Minimal file-like object that satisfies urllib.request.urlopen usage."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_DummyHTTPResponse":
        return self

    def __exit__(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_records() -> List[LiteratureRecord]:
    """Return three LiteratureRecord objects from a mocked Crossref API call."""

    def _fake_urlopen(req: urllib.request.Request, timeout: int = 10) -> _DummyHTTPResponse:
        return _DummyHTTPResponse(_CROSSREF_MOCK_PAYLOAD)

    with patch.object(urllib.request, "urlopen", _fake_urlopen):
        provider = CrossrefProvider()
        result = provider.search("blue economy marine hydronization", max_results=3)

    assert not result.is_empty, "Mocked Crossref call must return non-empty results"
    assert len(result.records) == 3, "Exactly 3 mocked records expected"
    return result.records


@pytest.fixture
def static_fixtures(tmp_path: Path) -> List[LiteratureRecord]:
    """Two static offline LiteratureRecord fixtures (simulating baseline CSV)."""
    return [
        LiteratureRecord(
            title="Coastal governance and ocean policy cooperation framework",
            authors="Smith, J.",
            year="2022",
            doi="10.8888/oceanic001",
            source_id="static:oceanic001",
            provider="static",
            journal="Blue Governance Journal",
            subject_terms=["governance", "policy", "cooperation"],
        ),
        LiteratureRecord(
            title="Benthic agency and pelagic metabolism in marine systems",
            authors="Jones, K.",
            year="2021",
            doi="10.8888/marine002",
            source_id="static:marine002",
            provider="static",
            journal="Marine Biology Reports",
            subject_terms=["benthic agency", "pelagic metabolism", "habitat"],
        ),
    ]


@pytest.fixture
def static_baseline_csv(tmp_path: Path, static_fixtures: List[LiteratureRecord]) -> Path:
    """Write static fixtures to a temporary CSV for CumulativeTriangulator ingestion."""
    csv_path = tmp_path / "static_baseline.csv"
    fieldnames = [
        "title", "authors", "year", "doi", "provider",
        "source_id", "journal", "url", "subject_terms",
        "source_query", "retrieval_timestamp", "licence_note",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for rec in static_fixtures:
            writer.writerow({
                "title": rec.title,
                "authors": rec.authors,
                "year": rec.year,
                "doi": rec.doi,
                "provider": rec.provider,
                "source_id": rec.source_id,
                "journal": rec.journal,
                "url": rec.url,
                "subject_terms": ";".join(rec.subject_terms),
                "source_query": rec.source_query,
                "retrieval_timestamp": rec.retrieval_timestamp,
                "licence_note": rec.licence_note,
            })
    return csv_path


# ---------------------------------------------------------------------------
# Helper: classify combined title + subjects for a LiteratureRecord
# ---------------------------------------------------------------------------


def _combined_text(rec: LiteratureRecord) -> str:
    parts = [rec.title] + [str(t) for t in rec.subject_terms if str(t).strip()]
    return " ".join(parts)


def _classify_record(rec: LiteratureRecord) -> List[Dict[str, Any]]:
    combined = _combined_text(rec)
    sentences = extract_sentences(combined) or [combined]
    return _classify_sentence_contexts(sentences, rec.source_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestQMBDPipelineMatrix:
    """End-to-end smoke tests for the unified QMBD methodological pipeline."""

    # ------------------------------------------------------------------
    # Abstract 1: Marine + Hydronization (multi-axis)
    # ------------------------------------------------------------------

    def test_abstract_1_crossref_record_ingested_correctly(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Mocked Crossref record 1 must be ingested with correct bibliographic fields."""
        rec = live_records[0]
        assert rec.provider == "Crossref"
        assert rec.doi == "10.9999/marine001"
        assert "Marine" in rec.title or "marine" in rec.title.lower()
        # Abstract must be empty (CrossrefProvider never stores abstracts)
        assert rec.abstract == ""
        assert rec.abstract_available is False

    def test_abstract_1_classifies_with_marine_keyword_evidence(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Record 1 must produce at least one MARINE classification with keyword evidence."""
        rec = live_records[0]
        analysis = _classify_record(rec)

        marine_items = [
            item for item in analysis if item.get("axis") == "MARINE"
        ]
        assert marine_items, "Expected at least one MARINE classification for record 1"
        for item in marine_items:
            assert item["matched_keywords"], (
                "MARINE classification must be backed by keyword evidence, not a fallback"
            )

    def test_abstract_1_text_contains_hydronization_keywords(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Record 1 combined text must contain Hydronization-axis keywords (multi-axis)."""
        rec = live_records[0]
        combined = _combined_text(rec)
        classifier = AxisClassifier()
        # Verify that Hydronization keywords are present by classifying the
        # hydronization portion of the subject terms directly
        hydro_text = "hydronization hydrosocial"
        result = classifier.classify_context(hydro_text, text_scope="full_sentence")
        assert result["axis"] == "HYDRONIZATION"
        assert result["matched_keywords"]

        # The combined text must also contain explicit hydronization vocabulary
        hydro_terms_in_combined = any(
            kw in combined.lower()
            for kw in ("hydronization", "hydrosocial", "wet ontology")
        )
        assert hydro_terms_in_combined, (
            f"Record 1 combined text must contain Hydronization terms for multi-axis; "
            f"got: {combined!r}"
        )

    # ------------------------------------------------------------------
    # Abstract 2: Blue Planetaryism (no axis keywords → UNCLASSIFIED)
    # ------------------------------------------------------------------

    def test_abstract_2_crossref_record_ingested_correctly(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Mocked Crossref record 2 must carry blue economy framing but no axis terms."""
        rec = live_records[1]
        assert rec.doi == "10.9999/blue002"
        combined = _combined_text(rec)
        # Must contain "blue" and "resilience" / "economy"
        assert "blue" in combined.lower()
        assert "resilience" in combined.lower() or "economy" in combined.lower()

    def test_abstract_2_routes_to_unclassified_review_required(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Record 2 with blue-economy framing only must route to UNCLASSIFIED_REVIEW_REQUIRED."""
        rec = live_records[1]
        analysis = _classify_record(rec)

        assert analysis, "Classification must produce at least one item for record 2"
        for item in analysis:
            assert item["classification"] == "UNCLASSIFIED_REVIEW_REQUIRED", (
                f"Expected UNCLASSIFIED_REVIEW_REQUIRED for blue-economy-only record, "
                f"got {item['classification']!r} (sentence: {item.get('sentence', '')!r})"
            )
            assert item["matched_keywords"] == [], (
                f"No axis keywords should match for record 2, "
                f"got {item['matched_keywords']!r}"
            )

    def test_abstract_2_is_blue_planetaryism_true(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Record 2 combined text must carry is_blue_planetaryism=True flag."""
        rec = live_records[1]
        combined = _combined_text(rec)
        classifier = AxisClassifier()
        result = classifier.classify_context(combined, text_scope="full_sentence")

        assert result["is_blue_planetaryism"] is True, (
            f"Expected is_blue_planetaryism=True for text {combined!r}, "
            f"got {result['is_blue_planetaryism']!r}"
        )
        assert result["matched_keywords"] == [], (
            "is_blue_planetaryism must coexist with empty matched_keywords"
        )

    # ------------------------------------------------------------------
    # Abstract 3: Maritime
    # ------------------------------------------------------------------

    def test_abstract_3_classifies_as_maritime(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Record 3 with port/shipping/logistics terms must classify as MARITIME."""
        rec = live_records[2]
        analysis = _classify_record(rec)

        maritime_items = [
            item for item in analysis if item.get("axis") == "MARITIME"
        ]
        assert maritime_items, (
            "Expected at least one MARITIME classification for record 3"
        )
        for item in maritime_items:
            assert item["matched_keywords"], (
                "MARITIME classification must be backed by keyword evidence"
            )

    def test_abstract_3_is_not_blue_planetaryism(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Record 3 with axis keywords must NOT be flagged as Blue Planetaryism."""
        rec = live_records[2]
        combined = _combined_text(rec)
        classifier = AxisClassifier()
        result = classifier.classify_context(combined, text_scope="full_sentence")

        assert result["is_blue_planetaryism"] is False, (
            "Record with axis keyword evidence must not be flagged as Blue Planetaryism"
        )

    # ------------------------------------------------------------------
    # Pipeline invariant: no fallback OCEANIC label
    # ------------------------------------------------------------------

    def test_no_record_falls_back_to_default_oceanic_label(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """No live record must receive a plain OCEANIC classification label.

        A no-keyword OCEANIC default must be routed to UNCLASSIFIED_REVIEW_REQUIRED
        by _classify_sentence_contexts.  With our three test records (Marine+Hydro,
        Blue-economy-only, Maritime), none should surface as classification='OCEANIC'.
        """
        for rec in live_records:
            analysis = _classify_record(rec)
            for item in analysis:
                assert item["classification"] != "OCEANIC", (
                    f"Fallback OCEANIC label must not appear as primary classification. "
                    f"Record DOI={rec.doi!r}, item={item!r}"
                )

    # ------------------------------------------------------------------
    # Schema integrity: provenance + text_scope keys
    # ------------------------------------------------------------------

    def test_output_schema_contains_provenance_key(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Every classification item must contain a top-level 'provenance' dict."""
        for rec in live_records:
            analysis = _classify_record(rec)
            assert analysis, f"Classification must not be empty for record {rec.doi!r}"
            for item in analysis:
                assert "provenance" in item, (
                    f"Missing 'provenance' key in classification item: {item!r}"
                )
                assert isinstance(item["provenance"], dict), (
                    f"'provenance' must be a dict, got {type(item['provenance']).__name__}"
                )
                assert "source_id" in item["provenance"], (
                    "'provenance' dict must contain 'source_id'"
                )
                assert "classifier_version" in item["provenance"], (
                    "'provenance' dict must contain 'classifier_version'"
                )

    def test_output_schema_contains_text_scope_key(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Every classification item must contain a top-level 'text_scope' key."""
        for rec in live_records:
            analysis = _classify_record(rec)
            for item in analysis:
                assert "text_scope" in item, (
                    f"Missing 'text_scope' key in classification item: {item!r}"
                )
                assert isinstance(item["text_scope"], str) and item["text_scope"], (
                    f"'text_scope' must be a non-empty string in item: {item!r}"
                )

    def test_classify_context_schema_always_includes_is_blue_planetaryism(self) -> None:
        """classify_context must always include is_blue_planetaryism in its return dict."""
        classifier = AxisClassifier()
        for text in [
            "ecosystem biodiversity habitat",
            "blue economy resilience",
            "port shipping logistics",
            "governance policy cooperation",
            "",
        ]:
            result = classifier.classify_context(text, text_scope="test_scope")
            assert "is_blue_planetaryism" in result, (
                f"is_blue_planetaryism missing from classify_context output for text={text!r}"
            )
            assert isinstance(result["is_blue_planetaryism"], bool)

    # ------------------------------------------------------------------
    # Triangulation: merge live + static fixtures
    # ------------------------------------------------------------------

    def test_triangulation_merges_live_and_static_fixtures(
        self,
        live_records: List[LiteratureRecord],
        static_baseline_csv: Path,
    ) -> None:
        """CumulativeTriangulator must merge 2 static + 3 live records correctly."""
        triangulator = CumulativeTriangulator()
        static_count = triangulator.ingest_static_baseline(static_baseline_csv)
        live_count = triangulator.ingest_dynamic_records(live_records)

        assert static_count == 2, f"Expected 2 static records ingested, got {static_count}"
        assert live_count == 3, f"Expected 3 live records ingested, got {live_count}"

        merged = triangulator.triangulate()

        # All 5 records have unique DOIs → no deduplication → 5 in output
        assert len(merged) == 5, (
            f"Expected 5 merged records (2 static + 3 live), got {len(merged)}"
        )

        # Every merged record must carry a ClaimOrigin provenance label
        for rec in merged:
            assert isinstance(rec.source, ClaimOrigin), (
                f"Record {rec.title!r} missing ClaimOrigin provenance"
            )
            assert rec.title, "Every merged record must have a non-empty title"

    def test_triangulation_live_records_supersede_static_on_doi_match(
        self,
        static_baseline_csv: Path,
    ) -> None:
        """A live record with a matching DOI must replace the static record (DOI-wins policy)."""
        # Create a live record that shares a DOI with a static fixture
        duplicate_doi_record = LiteratureRecord(
            title="Coastal governance and ocean policy cooperation framework",
            authors="Smith, J. (updated via API)",
            year="2023",
            doi="10.8888/oceanic001",  # same DOI as the static fixture
            source_id="crossref:10.8888/oceanic001",
            provider="Crossref",
            journal="Blue Governance Journal",
            subject_terms=["governance", "policy"],
        )

        triangulator = CumulativeTriangulator()
        triangulator.ingest_static_baseline(static_baseline_csv)
        triangulator.ingest_dynamic_records([duplicate_doi_record])
        merged = triangulator.triangulate()

        # The duplicate DOI replaces the static slot, so still 2 records total
        assert len(merged) == 2, (
            f"DOI-wins policy: duplicate DOI must replace static slot; got {len(merged)}"
        )
        # The winner must be the dynamic (Crossref) record
        doi_winners = [r for r in merged if r.doi == "10.8888/oceanic001"]
        assert len(doi_winners) == 1
        assert doi_winners[0].source is ClaimOrigin.DYNAMIC_API_CROSSREF, (
            "DOI-matching live record must carry DYNAMIC_API_CROSSREF ClaimOrigin"
        )

    def test_triangulation_identity_loop_respects_provider_priority(
        self, live_records: List[LiteratureRecord]
    ) -> None:
        """Identity-loop triangulation must apply the provider precedence policy."""
        merged_records, _, audit, stats, support_by_identity = triangulate_identity_loop(
            live_records, _DEFAULT_PROVIDER_POLICY
        )

        # All 3 live records have unique DOIs → no collisions, all accepted
        assert len(merged_records) == 3, (
            f"All 3 distinct live records must survive identity triangulation; "
            f"got {len(merged_records)}"
        )
        assert "policy_precedence" in audit, "'policy_precedence' must be in audit dict"
        assert "collision_events" in audit, "'collision_events' must be in audit dict"
        assert "crossref" in audit["policy_precedence"], (
            "Crossref must appear in provider precedence list"
        )
        # No DOI collisions expected for 3 distinct DOIs
        assert stats["doi_duplicates"] == 0, (
            f"Expected 0 DOI duplicates for 3 distinct records; got {stats['doi_duplicates']}"
        )
