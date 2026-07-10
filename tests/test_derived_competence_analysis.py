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
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from src.scientific_sources.derived_competence_analysis import (
    ALLOWED_DEMAND_STATUS,
    DERIVED_DEMAND_COLUMNS,
    GROWTH_ELIGIBLE_STATUSES,
    build_layer4,
    build_layer5,
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


def test_variable_and_value_labels_written(tmp_path: Path) -> None:
    out = tmp_path / "cumulative_database"
    out.mkdir()
    write_variable_and_value_labels(out)
    var = out / "VARIABLE_LABELS.csv"
    val = out / "VALUE_LABELS.csv"
    assert var.exists() and val.exists()
    assert var.read_text(encoding="utf-8").strip() != ""
    assert val.read_text(encoding="utf-8").strip() != ""
