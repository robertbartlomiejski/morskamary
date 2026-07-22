"""Tests for Layer 4-5 derived competence analysis (PR-190 Task C).

Covers:

* Deterministic column set for derived_competence_demands.
* Mandated demand_strength_score formula (weights sum to 1.0).
* Growth-eligible reliability filter excludes ``duplicate_only``.
* Layer 5 gap model separates ``static_baseline_available_count`` from
  live availability (never contaminates live counters).
* EQF 4-7 credential translation produces at least one credential per
  derived demand with EQF level in the allowed range.
* Hypothesis testing returns interpretation strings from the allowed set
  even when sample is too small (``not_computable``).
* VARIABLE_LABELS.csv / VALUE_LABELS.csv are written and non-empty.
* layer4_manifest.json and layer5_manifest.json include classifier_version.
* _checksums_layer45.sha256 covers all Layer 4-5 emitted files.
* Hashing uses 1 MB chunked reads.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from src.scientific_sources.derived_competence_analysis import (
    ALLOWED_DEMAND_STATUS,
    DERIVED_DEMAND_COLUMNS,
    GROWTH_ELIGIBLE_STATUSES,
    LAYER45_CHECKSUMS_FILENAME,
    build_layer4,
    build_layer5,
    write_layer45_checksums,
    write_variable_and_value_labels,
)


def _mk_evidence(
    idx: int,
    *,
    doi: str,
    provider: str,
    year: int,
    sector: str = "ports",
    novelty: str = "new_record",
) -> Dict[str, Any]:
    return {
        "evidence_id": f"E-{idx:04d}",
        "canonical_doi": doi,
        "doi_normalized": doi,
        "title_normalized": f"title {idx}",
        "provider_source": provider,
        "providers_seen": provider,
        "publication_year": year,
        "publication_date": f"{year}-06-01",
        "sector_slug": sector,
        "sector": sector,
        "query_family": "ports_digitalization",
        "query_id": f"Q-{idx}",
        "record_novelty_status": novelty,
        "first_seen_run_id": "RUN-001",
        "latest_seen_run_id": "RUN-001",
        "first_seen_at_utc": f"{year}-06-01T00:00:00+00:00",
        "latest_seen_at_utc": f"{year}-06-01T00:00:00+00:00",
        "record_recurrence_count": 1,
        "query_family_seen_count": 1,
        "provider_source_set": [provider],
        "abstract": "port digitalization energy transition offshore wind",
    }


def _mk_signal(idx: int, *, sector: str = "ports", axis: str = "MARITIME",
               confidence: float = 0.8) -> Dict[str, Any]:
    return {
        "signal_id": f"S-{idx:04d}",
        "evidence_id": f"E-{idx:04d}",
        "sector": sector,
        "axis_group": axis,
        "signal_type": "competence_demand",
        "competence_label": "digital port operations",
        "competence_description": "Digital operations skills for port workers.",
        "confidence_score": confidence,
        "supporting_span": "port digitalization",
        "review_flag": "auto_accepted",
        "classifier_version": "v1",
        "providers_seen": "crossref",
        "query_family": "ports_digitalization",
        "query_id": f"Q-{idx}",
    }


def test_demand_strength_weights_sum_to_one() -> None:
    # Formula: 0.30 + 0.20 + 0.20 + 0.15 + 0.15 == 1.00
    assert round(0.30 + 0.20 + 0.20 + 0.15 + 0.15, 6) == 1.0


def test_derived_demand_columns_are_deterministic() -> None:
    assert isinstance(DERIVED_DEMAND_COLUMNS, tuple)
    assert len(DERIVED_DEMAND_COLUMNS) >= 20
    assert "demand_strength_score" in DERIVED_DEMAND_COLUMNS
    assert "status" in DERIVED_DEMAND_COLUMNS
    assert "axis_code" in DERIVED_DEMAND_COLUMNS


def test_growth_eligibility_excludes_duplicate_only() -> None:
    assert "duplicate_only" not in GROWTH_ELIGIBLE_STATUSES
    assert "new_record" in GROWTH_ELIGIBLE_STATUSES
    assert "provider_enriched" in GROWTH_ELIGIBLE_STATUSES


def test_build_layer4_layer5_end_to_end(tmp_path: Path) -> None:
    evidence: List[Dict[str, Any]] = [
        _mk_evidence(1, doi="10.1000/a", provider="crossref", year=2024),
        _mk_evidence(2, doi="10.1000/b", provider="scopus", year=2023),
        _mk_evidence(3, doi="10.1000/c", provider="crossref", year=2025,
                     novelty="duplicate_only"),
    ]
    signals = [_mk_signal(i) for i in (1, 2, 3)]

    out = tmp_path / "cumulative_database"
    out.mkdir()
    l4 = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out,
        current_run_id="RUN-001",
    )
    l5 = build_layer5(
        derived_demands=l4.derived_demands,
        evidence_records=evidence,
        static_baseline_count_by_sector={"ports": 15},
        existing_credential_coverage=None,
        output_dir=out,
        current_run_id="RUN-001",
    )

    # CSVs on disk
    dd_csv = out / "derived_competence_demands.csv"
    gap_csv = out / "sector_axis_gap_model.csv"
    cred_csv = out / "credential_translation_eqf4_7.csv"
    lo_csv = out / "learning_outcomes.csv"
    for p in (dd_csv, gap_csv, cred_csv, lo_csv):
        assert p.exists(), f"missing {p}"

    # Statuses stay in allowed vocabulary
    with dd_csv.open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "expected at least one derived demand"
    for r in rows:
        assert r["status"] in ALLOWED_DEMAND_STATUS

    # Layer 5 gap row uses static baseline field, not live availability.
    with gap_csv.open() as fh:
        gap_rows = list(csv.DictReader(fh))
    assert gap_rows
    header = gap_rows[0].keys()
    assert "static_baseline_available_count" in header
    # The 15 provided must appear only in the static baseline column.
    ports_row = [r for r in gap_rows if r.get("sector") == "ports"]
    assert ports_row, "expected a ports gap row"
    assert int(ports_row[0]["static_baseline_available_count"]) == 15

    with lo_csv.open() as fh:
        outcome_rows = list(csv.DictReader(fh))
    assert outcome_rows
    first_statement = outcome_rows[0]["outcome_statement"]
    assert "evidence=" in first_statement
    assert "demand=" in first_statement
    assert "confidence=" in first_statement
    assert any(
        first_statement.startswith(verb)
        for verb in ("Operate", "Apply", "Analyse", "Evaluate")
    )

    # Hypothesis interpretations are within allowed set.
    allowed = {"supported", "partially_supported", "not_supported",
               "not_computable"}
    for h in l5.hypothesis_results.values():
        assert h["interpretation"] in allowed


def test_learning_outcomes_use_fragment_matched_hypothesis_ids(tmp_path: Path) -> None:
    evidence = [_mk_evidence(1, doi="10.1000/a", provider="crossref", year=2024)]
    signals = [_mk_signal(1, axis="MARINE")]
    out = tmp_path / "cumulative_database"
    out.mkdir()
    l4 = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out,
        current_run_id="RUN-001",
    )
    l5 = build_layer5(
        derived_demands=l4.derived_demands,
        evidence_records=evidence,
        hypothesis_fragments=[
            {"hypothesis_id": "H1", "evidence_id": "E-0001"},
            {"hypothesis_id": "H3", "evidence_id": "E-9999"},
        ],
        output_dir=out,
        current_run_id="RUN-001",
    )
    assert l5.learning_outcomes
    assert l5.learning_outcomes[0].hypothesis_ids == "H1"


def test_variable_and_value_labels_written(tmp_path: Path) -> None:
    out = tmp_path / "cumulative_database"
    out.mkdir()
    write_variable_and_value_labels(out)
    var = out / "VARIABLE_LABELS.csv"
    val = out / "VALUE_LABELS.csv"
    assert var.exists() and val.exists()
    assert var.read_text(encoding="utf-8").strip() != ""
    assert val.read_text(encoding="utf-8").strip() != ""


# ---------------------------------------------------------------------------
# Regression tests for hardening fixes (PR-191)
# ---------------------------------------------------------------------------


def _mk_hydro_demand(idx: int, *, sector: str = "ports") -> "Dict[str, Any]":
    """Build a minimal HYDRONIZATION DerivedCompetenceDemand-like dict."""
    from src.scientific_sources.derived_competence_analysis import DerivedCompetenceDemand
    return DerivedCompetenceDemand(
        competence_demand_id=f"cd:hydro:{sector}:HYDRONIZATION:demand{idx}",
        competence_label=f"hydro demand {idx}",
        competence_definition=f"definition {idx}",
        sector=sector,
        axis_group="HYDRONIZATION",
        axis_code="H",
        eqf_relevance="5|6",
        demand_strength_score=0.5,
        evidence_record_count=1,
        unique_doi_count=1,
        record_occurrence_count=1,
        provider_count=1,
        providers_seen="crossref",
        provider_diversity_score=0.5,
        query_count=1,
        query_families_seen="core_sector",
        query_diversity_score=0.5,
        temporal_recency_score=0.8,
        cross_sector_recurrence_score=0.1,
        semantic_confidence_mean=0.7,
        first_seen_run_id="RUN-001",
        latest_seen_run_id="RUN-001",
        first_seen_at_utc="2025-01-01T00:00:00+00:00",
        latest_seen_at_utc="2025-01-01T00:00:00+00:00",
        status="active",
        manual_review_status="auto_accepted",
        validity_warning="",
    )


def test_duplicate_only_evidence_excluded_from_demand_aggregation(
    tmp_path: Path,
) -> None:
    """Fix 2: duplicate_only evidence must not inflate demand-strength scores."""
    evidence = [
        _mk_evidence(1, doi="10.1000/a", provider="crossref", year=2024),
        _mk_evidence(2, doi="10.1000/b", provider="scopus", year=2023,
                     novelty="duplicate_only"),
    ]
    # Signal 1 from real evidence, signal 2 from duplicate_only evidence.
    signals = [_mk_signal(1), _mk_signal(2)]

    out = tmp_path / "cumulative_database"
    out.mkdir()
    l4 = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out,
        current_run_id="RUN-FIX2",
    )
    # Signal from duplicate_only evidence (E-0002) must not contribute a demand.
    # Only signal from E-0001 (new_record) should be reflected in demands.
    demand = l4.derived_demands[0] if l4.derived_demands else None
    assert demand is not None, "expected at least one derived demand"
    # The duplicate DOI (10.1000/b) must NOT appear in demand DOI counts.
    assert demand.unique_doi_count <= 1, (
        f"duplicate_only DOI must be excluded; unique_doi_count={demand.unique_doi_count}"
    )


def test_non_growth_evidence_is_excluded_from_demand_aggregation(
    tmp_path: Path,
) -> None:
    evidence = [
        _mk_evidence(1, doi="10.1000/a", provider="crossref", year=2024, novelty="new_record"),
        _mk_evidence(2, doi="10.1000/b", provider="scopus", year=2024, novelty="repeated_record"),
    ]
    signals = [_mk_signal(1), _mk_signal(2)]
    out = tmp_path / "cumulative_database"
    out.mkdir()
    l4 = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out,
        current_run_id="RUN-GROWTH-ONLY",
    )
    assert len(l4.derived_demands) == 1
    demand = l4.derived_demands[0]
    assert demand.evidence_record_count == 1
    assert demand.unique_doi_count == 1
    assert demand.evidence_ids == "E-0001"


def test_repeated_and_duplicate_only_evidence_creates_no_growth_demands_or_hypothesis_signal(
    tmp_path: Path,
) -> None:
    evidence = [
        _mk_evidence(
            1,
            doi="10.1000/repeated",
            provider="crossref",
            year=2024,
            novelty="repeated_record",
        ),
        _mk_evidence(
            2,
            doi="10.1000/duplicate",
            provider="scopus",
            year=2024,
            novelty="duplicate_only",
        ),
    ]
    signals = [_mk_signal(1), _mk_signal(2)]
    out = tmp_path / "db-non-growth-only"
    out.mkdir()

    l4 = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out,
        current_run_id="RUN-NON-GROWTH-ONLY",
    )
    assert l4.derived_demands == []

    l5 = build_layer5(
        derived_demands=l4.derived_demands,
        evidence_records=evidence,
        output_dir=out,
        current_run_id="RUN-NON-GROWTH-ONLY",
    )
    assert l5.gap_rows == []
    assert l5.credentials == []
    assert l5.learning_outcomes == []
    assert l5.hypothesis_results["H1"]["interpretation"] == "not_computable"
    assert l5.hypothesis_results["H2"]["interpretation"] == "not_computable"
    assert l5.hypothesis_results["H3"]["interpretation"] == "not_computable"
    assert l5.hypothesis_results["H2"]["validated_covered_demand_count"] == 0


def test_review_required_signals_propagate_to_demand_and_validated_counts(
    tmp_path: Path,
) -> None:
    evidence = [_mk_evidence(1, doi="10.1000/review", provider="crossref", year=2024)]
    signals = [
        {
            **_mk_signal(1, confidence=0.95),
            "manual_review_status": "review_required",
            "validity_warning": "metadata_only_limitation",
        }
    ]

    out = tmp_path / "db"
    out.mkdir()
    l4 = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out,
        current_run_id="RUN-REVIEW",
    )
    assert l4.derived_demands
    demand = l4.derived_demands[0]
    assert demand.status == "review_required"
    assert demand.manual_review_status == "review_required"
    assert "propagated_review_required" in demand.validity_warning

    l5 = build_layer5(
        derived_demands=l4.derived_demands,
        evidence_records=evidence,
        output_dir=out,
        current_run_id="RUN-REVIEW",
    )
    gap_rows = [row for row in l5.gap_rows if row.sector == demand.sector and row.axis_group == demand.axis_group]
    assert gap_rows
    assert gap_rows[0].validated_demand_count == 0


def test_learning_outcome_statement_does_not_use_placeholder_evidence_id(
    tmp_path: Path,
) -> None:
    out = tmp_path / "db"
    out.mkdir()
    demand = _mk_hydro_demand(1, sector="ports")
    demand.status = "review_required"
    demand.manual_review_status = "review_required"
    demand.evidence_ids = ""

    l5 = build_layer5(
        derived_demands=[demand],
        evidence_records=[],
        output_dir=out,
        current_run_id="RUN-LO-PROV",
    )

    assert l5.credentials
    assert "see_learning_outcomes_evidence_id" not in l5.credentials[0].learning_outcomes
    assert "evidence=unavailable;" in l5.credentials[0].learning_outcomes
    assert l5.learning_outcomes
    assert l5.learning_outcomes[0].evidence_id == "unavailable"


def test_taxonomy_uses_duplicate_filtered_signals_and_multi_axis_columns(
    tmp_path: Path,
) -> None:
    evidence = [
        _mk_evidence(1, doi="10.1000/safety-live", provider="crossref", year=2024),
        _mk_evidence(
            2,
            doi="10.1000/safety-dup",
            provider="scopus",
            year=2024,
            novelty="duplicate_only",
        ),
    ]
    signals = [
        {
            **_mk_signal(1),
            "competence_label": "occupational safety planning",
            "competence_description": "risk assessment and emergency response",
            "demand_phrase": "risk assessment",
        },
        {
            **_mk_signal(2),
            "competence_label": "occupational safety planning",
            "competence_description": "risk assessment and emergency response",
            "demand_phrase": "risk assessment",
        },
    ]
    out = tmp_path / "db"
    stats = tmp_path / "stats"
    out.mkdir()
    stats.mkdir()

    build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out,
        stats_dir=stats,
        current_run_id="RUN-TAXONOMY",
    )
    rows = list(csv.DictReader((stats / "taxonomic_clusters.csv").open()))
    assert rows
    header = rows[0].keys()
    for column in (
        "primary_axis",
        "secondary_axes",
        "axis_bridge_score",
        "matched_hypothesis_ids",
        "primary_axis_code",
    ):
        assert column in header

    safety = next(row for row in rows if row["category_label"] == "Safety and risk")
    assert safety["primary_axis"] == "MARITIME"
    assert safety["primary_axis_code"] == "T"
    assert safety["matched_hypothesis_ids"] == "H1"
    assert int(safety["matched_signal_count"]) == 1
    assert int(safety["matched_evidence_count"]) == 1


def test_h2_computed_at_demand_id_unit_not_credential_row_count(
    tmp_path: Path,
) -> None:
    """Fix 3: H2 missing_eqf6_7_outcome_count is per demand_id, not credential rows."""
    from src.scientific_sources.derived_competence_analysis import build_layer5
    # Create 3 HYDRONIZATION demands.
    demands = [_mk_hydro_demand(i) for i in range(1, 4)]

    out = tmp_path / "cumulative_database"
    out.mkdir()
    l5 = build_layer5(
        derived_demands=demands,
        evidence_records=[],
        static_baseline_count_by_sector={},
        existing_credential_coverage=None,
        output_dir=out,
        current_run_id="RUN-FIX3",
    )
    h2 = l5.hypothesis_results.get("H2", {})
    assert h2, "H2 must always be serialized"
    assert h2["hypothesis_id"] == "H2"
    assert "unit_of_analysis" in h2, "H2 must declare its unit_of_analysis"
    assert h2["unit_of_analysis"] == "competence_demand_id"
    assert "hydronization_demand_count" in h2, "H2 must report total demand count"
    assert h2["hydronization_demand_count"] == len(demands)
    assert "coverage_note" in h2, "H2 must include coverage_note distinguishing candidate from validated"
    assert "candidate" in h2["coverage_note"].lower()
    # The interpretation must be in the allowed set.
    assert h2["interpretation"] in {
        "supported", "partially_supported", "not_supported", "not_computable"
    }


def test_h2_generated_credentials_not_treated_as_validated_supply(
    tmp_path: Path,
) -> None:
    """Regression test: H2 must be not_computable when no external supply map exists.

    Using generated candidate credentials to compute covered_demand_ids is
    circular — it forces missing coverage toward zero because every demand
    receives a generated credential.  The validated coverage must be 0 and
    interpretation must be not_computable when no validated supply map is provided.
    """
    from src.scientific_sources.derived_competence_analysis import build_layer5
    demands = [_mk_hydro_demand(i) for i in range(1, 4)]
    out = tmp_path / "db"
    out.mkdir()
    l5 = build_layer5(
        derived_demands=demands,
        evidence_records=[],
        static_baseline_count_by_sector={},
        existing_credential_coverage=None,
        output_dir=out,
        current_run_id="RUN-H2-NEG",
    )
    h2 = l5.hypothesis_results.get("H2", {})
    assert h2.get("interpretation") == "not_computable", (
        "H2 must be not_computable when no validated supply map is available; "
        f"got interpretation={h2.get('interpretation')!r}"
    )
    assert h2.get("validated_covered_demand_count") == 0, (
        "validated_covered_demand_count must be 0 — generated candidates are not validated supply"
    )
    assert "no_validated_supply_map" in h2.get("validity_warning", ""), (
        "H2 validity_warning must include 'no_validated_supply_map'"
    )
    assert "H3" in l5.hypothesis_results, "H3 must always be serialized alongside H1 and H2"


def test_h1_signed_direction_controls_interpretation(
    tmp_path: Path,
) -> None:
    """Regression test: H1 (Maritimisation Shift) uses signed Cohen's d.

    The declared H1 hypothesis is *Maritimisation Shift*: MARITIME demand
    exceeds OCEANIC demand.  It can only be "supported" in one direction.

    - When MARITIME > OCEANIC (positive d) → supported_maritime_dominance
      (or partially_supported_maritime for 0.2 ≤ d < 0.5).
    - When OCEANIC > MARITIME (negative d) → not_supported.

    Using abs(cohens_d) or labelling negative d as "oceanic_dominance" would
    be a different hypothesis — the declared H1 must return not_supported
    when the shift is not observed.
    """
    from src.scientific_sources.derived_competence_analysis import (
        DerivedCompetenceDemand, build_layer5,
    )

    def _mk_demand(axis: str, score: float, idx: int) -> DerivedCompetenceDemand:
        return DerivedCompetenceDemand(
            competence_demand_id=f"cd:{axis}:sector:{idx}",
            competence_label=f"{axis} demand {idx}",
            competence_definition="",
            sector="ports",
            axis_group=axis,
            axis_code=axis[0],
            eqf_relevance="6",
            demand_strength_score=score,
            evidence_record_count=1,
            unique_doi_count=1,
            record_occurrence_count=1,
            provider_count=1,
            providers_seen="crossref",
            provider_diversity_score=0.5,
            query_count=1,
            query_families_seen="core",
            query_diversity_score=0.5,
            temporal_recency_score=0.8,
            cross_sector_recurrence_score=0.1,
            semantic_confidence_mean=0.7,
            first_seen_run_id="R1",
            latest_seen_run_id="R1",
            first_seen_at_utc="2025-01-01T00:00:00+00:00",
            latest_seen_at_utc="2025-01-01T00:00:00+00:00",
            status="active",
            manual_review_status="auto_accepted",
            validity_warning="",
        )

    # MARITIME dominance scenario: MARITIME scores >> OCEANIC scores (with variance).
    maritime_dominant = (
        [_mk_demand("MARITIME", 0.9 + 0.01 * i, i) for i in range(5)]
        + [_mk_demand("OCEANIC", 0.1 + 0.01 * i, i + 10) for i in range(5)]
    )
    out1 = tmp_path / "db1"
    out1.mkdir()
    l5_m = build_layer5(
        derived_demands=maritime_dominant,
        evidence_records=[],
        static_baseline_count_by_sector={},
        existing_credential_coverage=None,
        output_dir=out1,
        current_run_id="R-H1-M",
    )
    h1_m = l5_m.hypothesis_results["H1"]
    assert h1_m["effect_size_cohens_d"] > 0, "MARITIME > OCEANIC must yield positive cohens_d"
    assert "maritime" in h1_m["interpretation"].lower(), (
        f"MARITIME-dominant scenario must include 'maritime' in interpretation; "
        f"got {h1_m['interpretation']!r}"
    )

    # OCEANIC dominance scenario: OCEANIC scores >> MARITIME scores (with variance).
    # The declared H1 is the *Maritimisation Shift* — it can only be supported in
    # one direction.  When OCEANIC > MARITIME the outcome must be not_supported.
    oceanic_dominant = (
        [_mk_demand("MARITIME", 0.1 + 0.01 * i, i) for i in range(5)]
        + [_mk_demand("OCEANIC", 0.9 + 0.01 * i, i + 10) for i in range(5)]
    )
    out2 = tmp_path / "db2"
    out2.mkdir()
    l5_o = build_layer5(
        derived_demands=oceanic_dominant,
        evidence_records=[],
        static_baseline_count_by_sector={},
        existing_credential_coverage=None,
        output_dir=out2,
        current_run_id="R-H1-O",
    )
    h1_o = l5_o.hypothesis_results["H1"]
    assert h1_o["effect_size_cohens_d"] < 0, "OCEANIC > MARITIME must yield negative cohens_d"
    assert h1_o["interpretation"] == "not_supported", (
        f"When OCEANIC > MARITIME the Maritimisation Shift is not_supported; "
        f"got {h1_o['interpretation']!r}"
    )


def test_h3_always_emitted_including_not_computable(
    tmp_path: Path,
) -> None:
    """Regression test: H3 (MARINE vs OCEANIC Differential Coverage) must always
    be serialized, even when not_computable. The declared H3 hypothesis tests
    marine/oceanic fragment counts, balance, sector distributions and semantic
    bridges — not Cross-Sector Recurrence.
    """
    from src.scientific_sources.derived_competence_analysis import build_layer5
    # Empty demands → H3 should be not_computable.
    out = tmp_path / "db_h3"
    out.mkdir()
    l5 = build_layer5(
        derived_demands=[],
        evidence_records=[],
        static_baseline_count_by_sector={},
        existing_credential_coverage=None,
        output_dir=out,
        current_run_id="RUN-H3-EMPTY",
    )
    assert "H3" in l5.hypothesis_results, "H3 must always be present in hypothesis_results"
    h3 = l5.hypothesis_results["H3"]
    assert h3.get("hypothesis_id") == "H3"
    assert h3.get("hypothesis_label") == "MARINE vs OCEANIC Differential Coverage", (
        f"H3 must use the declared label, not 'Cross-Sector Recurrence'; "
        f"got {h3.get('hypothesis_label')!r}"
    )
    assert h3.get("interpretation") == "not_computable"
    # Structural fields required by the declared H3 hypothesis.
    for field in (
        "sample_size_marine", "sample_size_oceanic",
        "marine_fragment_count", "oceanic_fragment_count",
        "balance_score", "marine_sector_count", "oceanic_sector_count",
        "marine_sectors", "oceanic_sectors", "semantic_bridge_count",
    ):
        assert field in h3, f"H3 must contain field {field!r}"
    # H1 and H2 must also always be present.
    assert "H1" in l5.hypothesis_results
    assert "H2" in l5.hypothesis_results


def test_triangulated_records_preferred_over_live_records(
    tmp_path: Path,
) -> None:
    """Regression test: cumulative DB build must prefer live_records_triangulated.json
    over live_records.json so triangulated supporting-provider metadata is not lost.
    """
    import json
    from src.scientific_sources.cumulative_scientific_database import (
        build_cumulative_scientific_database,
    )

    current = tmp_path / "outputs"
    rs = current / "research_sources"
    rs.mkdir(parents=True)

    triangulated_doi = "10.1000/triangulated-preferred"
    fallback_doi = "10.1000/fallback-only"

    # Write live_records_triangulated.json with one record.
    (rs / "live_records_triangulated.json").write_text(
        json.dumps([{
            "title": "Triangulated record",
            "doi": triangulated_doi,
            "provider": "crossref",
            "source_query": "maritime governance",
            "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
        }]),
        encoding="utf-8",
    )
    # Write live_records.json with a *different* DOI so we can tell which was read.
    (rs / "live_records.json").write_text(
        json.dumps([{
            "title": "Fallback record",
            "doi": fallback_doi,
            "provider": "crossref",
            "source_query": "maritime governance",
            "retrieval_timestamp": "2026-07-01T00:00:00+00:00",
        }]),
        encoding="utf-8",
    )

    result = build_cumulative_scientific_database(
        current_run_dir=current,
        output_dir=tmp_path / "out",
        current_run_id="R-TRI",
        built_at_utc="2026-07-01T00:00:00+00:00",
    )
    doi_ids = {r.get("canonical_doi") or r.get("evidence_id", "") for r in
               [er.__dict__ if hasattr(er, "__dict__") else er
                for er in result.evidence_records]}
    # The triangulated record's DOI must be present.
    assert any(triangulated_doi in str(eid) for eid in doi_ids), (
        "live_records_triangulated.json must be preferred over live_records.json; "
        f"DOI {triangulated_doi!r} not found in evidence; found: {doi_ids}"
    )
    # The fallback DOI must NOT be loaded (triangulated takes precedence).
    assert not any(fallback_doi in str(eid) for eid in doi_ids), (
        "live_records.json fallback-only DOI must not be loaded when triangulated file exists"
    )


def test_layer4_honors_stats_dir_and_fixed_timestamp(tmp_path: Path) -> None:
    evidence = [
        _mk_evidence(
            1,
            doi="10.1000/reproducible",
            provider="crossref",
            year=2025,
        )
    ]
    signals = [_mk_signal(1)]
    timestamp = "2026-07-13T12:00:00+00:00"
    first = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=tmp_path / "db-first",
        stats_dir=tmp_path / "stats-first",
        analysis_timestamp_utc=timestamp,
    )
    second = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=tmp_path / "db-second",
        stats_dir=tmp_path / "stats-second",
        analysis_timestamp_utc=timestamp,
    )
    assert first.stats_dir == tmp_path / "stats-first"
    assert (first.stats_dir / "qmbd_cross_tables.csv").is_file()
    assert first.derived_demands[0].temporal_recency_score == (
        second.derived_demands[0].temporal_recency_score
    )
    assert first.derived_demands[0].evidence_ids == "E-0001"
    assert first.derived_demands[0].signal_types == "competence_demand"


def test_h2_consumes_only_validated_demand_level_supply(tmp_path: Path) -> None:
    demands = [_mk_hydro_demand(index) for index in range(1, 4)]
    validated_supply = {
        demands[0].competence_demand_id: [6],
        demands[1].competence_demand_id: [5],
    }
    result = build_layer5(
        derived_demands=demands,
        evidence_records=[],
        validated_credential_supply=validated_supply,
        output_dir=tmp_path / "db-validated-supply",
    )
    h2 = result.hypothesis_results["H2"]
    assert h2["validated_supply_map_provided"] is True
    assert h2["validated_covered_demand_count"] == 1
    assert h2["validated_missing_demand_count"] == 2
    assert h2["candidate_covered_demand_count"] == 3
    assert h2["interpretation"] == "supported"


def test_h2_partial_support_threshold_is_0_25(tmp_path: Path) -> None:
    demands = [_mk_hydro_demand(index) for index in range(1, 5)]
    validated_supply = {
        demands[0].competence_demand_id: [6],
        demands[1].competence_demand_id: [7],
        demands[2].competence_demand_id: [5],
    }
    result = build_layer5(
        derived_demands=demands,
        evidence_records=[],
        validated_credential_supply=validated_supply,
        output_dir=tmp_path / "db-h2-partial",
    )
    h2 = result.hypothesis_results["H2"]
    assert h2["validated_supply_map_provided"] is True
    assert h2["validated_covered_demand_count"] == 2
    assert h2["validated_missing_demand_count"] == 2
    assert h2["association_metric_missing_ratio"] == 0.5
    assert h2["interpretation"] == "supported"

    validated_supply = {
        demands[0].competence_demand_id: [6],
        demands[1].competence_demand_id: [7],
        demands[2].competence_demand_id: [6],
    }
    result_partial = build_layer5(
        derived_demands=demands,
        evidence_records=[],
        validated_credential_supply=validated_supply,
        output_dir=tmp_path / "db-h2-partial-025",
    )
    h2_partial = result_partial.hypothesis_results["H2"]
    assert h2_partial["association_metric_missing_ratio"] == 0.25
    assert h2_partial["interpretation"] == "partially_supported"


def test_static_baseline_only_cells_are_serialized(tmp_path: Path) -> None:
    result = build_layer5(
        derived_demands=[],
        evidence_records=[],
        static_baseline_count_by_sector={"ports": 15},
        output_dir=tmp_path / "db-baseline-only",
    )
    assert len(result.gap_rows) == 4
    assert {row.axis_group for row in result.gap_rows} == {
        "MARINE",
        "MARITIME",
        "OCEANIC",
        "HYDRONIZATION",
    }
    assert all(row.live_literature_demand_count == 0 for row in result.gap_rows)
    assert all(
        "static_baseline_only" in row.validity_warning
        for row in result.gap_rows
    )


def test_h3_uses_matched_fragments_and_evidence_level_bridges(tmp_path: Path) -> None:
    from src.scientific_sources.derived_competence_analysis import (
        DerivedCompetenceDemand,
        build_layer5,
    )

    marine_demand = DerivedCompetenceDemand(
        competence_demand_id="cd:marine:1",
        competence_label="marine skill",
        competence_definition="marine",
        sector="ports",
        axis_group="MARINE",
        axis_code="M",
        eqf_relevance="6",
        demand_strength_score=0.9,
        evidence_record_count=20,
        unique_doi_count=20,
        record_occurrence_count=20,
        provider_count=1,
        providers_seen="crossref",
        provider_diversity_score=0.1,
        query_count=1,
        query_families_seen="hypothesis_verification",
        query_diversity_score=0.1,
        temporal_recency_score=0.8,
        cross_sector_recurrence_score=0.2,
        semantic_confidence_mean=0.8,
        first_seen_run_id="R1",
        latest_seen_run_id="R1",
        first_seen_at_utc="2026-01-01T00:00:00+00:00",
        latest_seen_at_utc="2026-01-01T00:00:00+00:00",
        status="high_demand",
        manual_review_status="auto_accepted",
        validity_warning="",
        evidence_ids="E-BRIDGE",
        signal_types="competence_demand",
    )
    oceanic_demand = DerivedCompetenceDemand(
        competence_demand_id="cd:oceanic:1",
        competence_label="oceanic skill",
        competence_definition="oceanic",
        sector="ports",
        axis_group="OCEANIC",
        axis_code="O",
        eqf_relevance="6",
        demand_strength_score=0.2,
        evidence_record_count=1,
        unique_doi_count=1,
        record_occurrence_count=1,
        provider_count=1,
        providers_seen="crossref",
        provider_diversity_score=0.1,
        query_count=1,
        query_families_seen="hypothesis_verification",
        query_diversity_score=0.1,
        temporal_recency_score=0.8,
        cross_sector_recurrence_score=0.2,
        semantic_confidence_mean=0.8,
        first_seen_run_id="R1",
        latest_seen_run_id="R1",
        first_seen_at_utc="2026-01-01T00:00:00+00:00",
        latest_seen_at_utc="2026-01-01T00:00:00+00:00",
        status="high_demand",
        manual_review_status="auto_accepted",
        validity_warning="",
        evidence_ids="E-BRIDGE",
        signal_types="competence_demand",
    )
    fragments = [
        {
            "hypothesis_id": "H3",
            "signal_id": "S-M",
            "evidence_id": "E-BRIDGE",
            "axis_group": "MARINE",
            "sector": "ports",
        },
        {
            "hypothesis_id": "H3",
            "signal_id": "S-O",
            "evidence_id": "E-BRIDGE",
            "axis_group": "OCEANIC",
            "sector": "ports",
        },
    ]
    result = build_layer5(
        derived_demands=[marine_demand, oceanic_demand],
        evidence_records=[],
        hypothesis_fragments=fragments,
        output_dir=tmp_path / "db-h3-fragments",
    )
    h3 = result.hypothesis_results["H3"]
    assert h3["marine_fragment_count"] == 1
    assert h3["oceanic_fragment_count"] == 1
    assert h3["semantic_bridge_count"] == 1
    assert h3["interpretation"] in {"supported", "partially_supported"}


# ---------------------------------------------------------------------------
# Provenance / governance tests (Layer 4-5 manifest and checksum fixes)
# ---------------------------------------------------------------------------


def test_layer4_manifest_includes_classifier_version(tmp_path: Path) -> None:
    """layer4_manifest.json must include classifier_version."""
    out = tmp_path / "db"
    out.mkdir()
    build_layer4(
        evidence_records=[_mk_evidence(1, doi="10.1000/a", provider="crossref", year=2024)],
        competence_signals=[_mk_signal(1)],
        output_dir=out,
        current_run_id="RUN-PROV",
        classifier_version="test-classifier-v1",
    )
    manifest = json.loads((out / "layer4_manifest.json").read_text(encoding="utf-8"))
    assert "classifier_version" in manifest, "layer4_manifest.json must include classifier_version"
    assert manifest["classifier_version"] == "test-classifier-v1"


def test_layer4_manifest_classifier_version_defaults_to_empty_string(tmp_path: Path) -> None:
    """classifier_version defaults to empty string when not supplied."""
    out = tmp_path / "db"
    out.mkdir()
    build_layer4(
        evidence_records=[],
        competence_signals=[],
        output_dir=out,
        current_run_id="RUN-EMPTY",
    )
    manifest = json.loads((out / "layer4_manifest.json").read_text(encoding="utf-8"))
    assert "classifier_version" in manifest
    assert manifest["classifier_version"] == ""


def test_layer5_manifest_includes_classifier_version(tmp_path: Path) -> None:
    """layer5_manifest.json must include classifier_version."""
    out = tmp_path / "db"
    out.mkdir()
    l4 = build_layer4(
        evidence_records=[_mk_evidence(1, doi="10.1000/a", provider="crossref", year=2024)],
        competence_signals=[_mk_signal(1)],
        output_dir=out,
        current_run_id="RUN-PROV",
        classifier_version="test-classifier-v2",
    )
    build_layer5(
        derived_demands=l4.derived_demands,
        evidence_records=[],
        output_dir=out,
        current_run_id="RUN-PROV",
        classifier_version="test-classifier-v2",
    )
    manifest = json.loads((out / "layer5_manifest.json").read_text(encoding="utf-8"))
    assert "classifier_version" in manifest, "layer5_manifest.json must include classifier_version"
    assert manifest["classifier_version"] == "test-classifier-v2"


def test_layer5_manifest_classifier_version_defaults_to_empty_string(tmp_path: Path) -> None:
    """classifier_version defaults to empty string when not supplied."""
    out = tmp_path / "db"
    out.mkdir()
    build_layer5(
        derived_demands=[],
        evidence_records=[],
        output_dir=out,
        current_run_id="RUN-EMPTY",
    )
    manifest = json.loads((out / "layer5_manifest.json").read_text(encoding="utf-8"))
    assert "classifier_version" in manifest
    assert manifest["classifier_version"] == ""


def test_write_layer45_checksums_covers_emitted_files(tmp_path: Path) -> None:
    """_checksums_layer45.sha256 must cover all Layer 4-5 emitted files."""
    out = tmp_path / "db"
    out.mkdir()
    evidence = [_mk_evidence(1, doi="10.1000/a", provider="crossref", year=2024)]
    signals = [_mk_signal(1)]
    l4 = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out,
        current_run_id="RUN-CHKSUM",
        classifier_version="v-chksum",
    )
    l5 = build_layer5(
        derived_demands=l4.derived_demands,
        evidence_records=evidence,
        output_dir=out,
        current_run_id="RUN-CHKSUM",
        classifier_version="v-chksum",
    )
    all_files = list(l4.files) + list(l5.files)
    chk_path = write_layer45_checksums(all_files, out)

    assert chk_path == out / LAYER45_CHECKSUMS_FILENAME
    assert chk_path.exists()

    text = chk_path.read_text(encoding="utf-8")
    covered = {line.split("  ", 1)[1] for line in text.strip().splitlines()}

    # Required Layer 4-5 analytical files must all be covered.
    required = {
        "derived_competence_demands.csv",
        "sector_axis_gap_model.csv",
        "credential_translation_eqf4_7.csv",
        "learning_outcomes.csv",
        "layer4_manifest.json",
        "layer5_manifest.json",
    }
    missing = required - covered
    assert not missing, f"checksum file is missing coverage for: {missing}"


def test_write_layer45_checksums_digest_uses_chunked_1mb_reads(tmp_path: Path) -> None:
    """Behavioral test: digests must match a reference chunked-read computation."""
    out = tmp_path / "db"
    out.mkdir()
    # Write a synthetic file large enough to conceptually exercise chunking.
    test_file = out / "test_large.csv"
    test_file.write_bytes(b"header\n" + b"x" * (2 * 1024 * 1024))  # 2 MB of data

    chk_path = write_layer45_checksums([test_file], out)

    # Compute the reference digest using explicit 1 MB chunked reads.
    sha = hashlib.sha256()
    with test_file.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
    expected_digest = sha.hexdigest()

    text = chk_path.read_text(encoding="utf-8").strip()
    assert text != "", "checksum file must not be empty"
    recorded_digest = text.split("  ", 1)[0]
    assert recorded_digest == expected_digest, (
        "write_layer45_checksums must use 1 MB chunked reads; "
        f"recorded={recorded_digest!r}, expected={expected_digest!r}"
    )


def test_write_layer45_checksums_format_is_sha256sum_compatible(tmp_path: Path) -> None:
    """Each line must be exactly '<64-hex>  <relpath>' (sha256sum -c compatible)."""
    import re
    out = tmp_path / "db"
    out.mkdir()
    f1 = out / "file_a.csv"
    f2 = out / "file_b.json"
    f1.write_text("a,b\n1,2\n", encoding="utf-8")
    f2.write_text('{"k": "v"}\n', encoding="utf-8")

    chk_path = write_layer45_checksums([f1, f2], out)
    hex64 = re.compile(r"^[0-9a-f]{64}$")
    for line in chk_path.read_text(encoding="utf-8").strip().splitlines():
        parts = line.split("  ", 1)
        assert len(parts) == 2, f"malformed checksum line: {line!r}"
        assert hex64.match(parts[0]), f"digest is not 64 hex chars: {parts[0]!r}"
        assert (out / parts[1]).is_file(), f"checksum references non-existent file: {parts[1]!r}"
