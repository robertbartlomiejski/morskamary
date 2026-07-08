"""Tests for the explicit dynamic gap model (src/gap_model.py).

Test scope:
  - GapEvidence, GapCluster, GapModelResult dataclasses
  - compute_priority_score
  - compute_gap_model on small in-memory fixtures
  - run_gap_model integration tests (live-enriched changes demand_evidence)
  - supply_evidence is not only hard-coded baseline when supply files exist
  - gaps_summary.csv is still produced after adding gap-model outputs
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List

import pytest

from src.gap_model import (
    GapCluster,
    GapEvidence,
    GapModelResult,
    compute_gap_model,
    compute_priority_score,
)
from run_full_analysis import (
    Competence,
    CompetenceSource,
    GapAnalysis,
    TMBDAxis,
    export_gap_priority_ranking_csv,
    export_gaps_by_sector_axis_csv,
    export_gaps_detailed_json,
    export_gaps_summary_csv,
    run_gap_model,
    SECTORS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(
    competence_id: str,
    sector: str,
    axis: str,
    origin: str = "static_literature",
    provider: str = "crossref",
    year: str = "2022",
    confidence_score: float = 0.8,
    supporting_providers: List[str] | None = None,
) -> GapEvidence:
    return GapEvidence(
        competence_id=competence_id,
        name=f"Competence {competence_id}",
        description="Test description",
        sector=sector,
        qmbd_axis=axis,
        origin=origin,
        source_file="data/derived/test.csv",
        source_row=1,
        provider=provider,
        doi="10.1234/test",
        title=f"Paper about {competence_id}",
        year=year,
        confidence_score=confidence_score,
        overlap_status="demand_only",
        supporting_providers=supporting_providers or [],
    )


def _make_competence(
    comp_id: str,
    axis: TMBDAxis,
    sectors: List[str],
    dimension: str = "literature",
) -> Competence:
    return Competence(
        id=comp_id,
        name=f"Competence {comp_id}",
        description="Test",
        axis=axis,
        dimension=dimension,
        source=CompetenceSource(file="data/derived/x.csv", row=1, year="2022"),
        keywords=["test"],
        sectors=sectors,
    )


# ---------------------------------------------------------------------------
# Unit tests: GapEvidence
# ---------------------------------------------------------------------------


class TestGapEvidence:
    def test_to_dict_round_trip(self) -> None:
        ev = _make_evidence("comp_001", "Blue Biotech", "MARINE")
        d = ev.to_dict()
        assert d["competence_id"] == "comp_001"
        assert d["sector"] == "Blue Biotech"
        assert d["qmbd_axis"] == "MARINE"
        assert d["origin"] == "static_literature"
        assert d["confidence_score"] == 0.8

    def test_to_dict_all_fields_present(self) -> None:
        ev = _make_evidence("c2", "Coastal Tourism", "OCEANIC", year="2023")
        d = ev.to_dict()
        expected_keys = {
            "competence_id",
            "name",
            "description",
            "sector",
            "qmbd_axis",
            "origin",
            "source_file",
            "source_row",
            "provider",
            "doi",
            "title",
            "year",
            "confidence_score",
            "overlap_status",
            "supporting_providers",
            "matched_supply_id",
            "matched_supply_origin",
            "match_method",
            "match_score",
        }
        assert expected_keys == set(d.keys())


# ---------------------------------------------------------------------------
# Unit tests: GapCluster
# ---------------------------------------------------------------------------


class TestGapCluster:
    def test_gap_ratio_zero_demand(self) -> None:
        cluster = GapCluster(sector="Blue Biotech", qmbd_axis="MARINE")
        assert cluster.gap_ratio == 0.0

    def test_gap_ratio_all_missing(self) -> None:
        ev = _make_evidence("c1", "Blue Biotech", "MARINE")
        cluster = GapCluster(
            sector="Blue Biotech",
            qmbd_axis="MARINE",
            demand_items=[ev],
            supply_items=[],
            missing_items=[ev],
        )
        assert cluster.gap_ratio == 1.0

    def test_gap_ratio_partial(self) -> None:
        ev1 = _make_evidence("c1", "Blue Biotech", "MARINE")
        ev2 = _make_evidence("c2", "Blue Biotech", "MARINE")
        cluster = GapCluster(
            sector="Blue Biotech",
            qmbd_axis="MARINE",
            demand_items=[ev1, ev2],
            supply_items=[ev1],
            missing_items=[ev2],
        )
        assert cluster.gap_ratio == 0.5

    def test_to_dict_keys(self) -> None:
        cluster = GapCluster(sector="Port Activities", qmbd_axis="MARITIME")
        d = cluster.to_dict()
        assert "sector" in d
        assert "qmbd_axis" in d
        assert "demand_count" in d
        assert "priority_score" in d
        assert "missing_items" in d


# ---------------------------------------------------------------------------
# Unit tests: compute_priority_score
# ---------------------------------------------------------------------------


class TestComputePriorityScore:
    def _single_cluster(
        self,
        demand_count: int = 3,
        year: str = "2022",
        confidence: float = 0.8,
        supporting: bool = False,
    ) -> GapCluster:
        items = [
            _make_evidence(
                f"c{i}",
                "Blue Biotech",
                "MARINE",
                year=year,
                confidence_score=confidence,
                supporting_providers=["scopus"] if supporting else [],
            )
            for i in range(demand_count)
        ]
        return GapCluster(
            sector="Blue Biotech",
            qmbd_axis="MARINE",
            demand_items=items,
            supply_items=[],
            missing_items=items,
        )

    def test_score_in_range(self) -> None:
        cluster = self._single_cluster()
        score = compute_priority_score(cluster, [cluster])
        assert 0.0 <= score <= 1.0

    def test_higher_confidence_raises_score(self) -> None:
        low = self._single_cluster(confidence=0.2)
        high = self._single_cluster(confidence=0.9)
        s_low = compute_priority_score(low, [low])
        s_high = compute_priority_score(high, [high])
        assert s_high > s_low

    def test_more_demand_items_raises_score_relative(self) -> None:
        small = self._single_cluster(demand_count=1)
        large = self._single_cluster(demand_count=5)
        all_clusters = [small, large]
        s_small = compute_priority_score(small, all_clusters)
        s_large = compute_priority_score(large, all_clusters)
        assert s_large > s_small

    def test_multi_source_raises_score(self) -> None:
        no_support = self._single_cluster(supporting=False)
        with_support = self._single_cluster(supporting=True)
        s_no = compute_priority_score(no_support, [no_support])
        s_with = compute_priority_score(with_support, [with_support])
        assert s_with > s_no


# ---------------------------------------------------------------------------
# Unit tests: compute_gap_model
# ---------------------------------------------------------------------------


class TestComputeGapModel:
    def _build_inputs(
        self,
    ) -> tuple[Dict[str, List[GapEvidence]], Dict[str, List[GapEvidence]]]:
        demand: Dict[str, List[GapEvidence]] = {
            "Blue Biotech": [
                _make_evidence("comp_marine_001", "Blue Biotech", "MARINE"),
                _make_evidence("comp_oceanic_001", "Blue Biotech", "OCEANIC"),
            ],
            "Coastal Tourism": [
                _make_evidence("comp_maritime_001", "Coastal Tourism", "MARITIME"),
            ],
        }
        supply: Dict[str, List[GapEvidence]] = {
            "Blue Biotech": [
                _make_evidence(
                    "comp_marine_001",
                    "Blue Biotech",
                    "MARINE",
                    origin="static_baseline",
                ),
            ],
        }
        return demand, supply

    def test_result_type(self) -> None:
        demand, supply = self._build_inputs()
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech", "Coastal Tourism"])
        assert isinstance(result, GapModelResult)

    def test_missing_clusters_not_empty(self) -> None:
        demand, supply = self._build_inputs()
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech", "Coastal Tourism"])
        # comp_oceanic_001 and comp_maritime_001 are not covered
        assert len(result.missing_clusters) > 0

    def test_covered_item_not_in_missing(self) -> None:
        demand, supply = self._build_inputs()
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        # comp_marine_001 should be covered
        marine_cluster = next(
            (
                c
                for c in result.all_clusters
                if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
            ),
            None,
        )
        assert marine_cluster is not None
        missing_ids = {e.competence_id for e in marine_cluster.missing_items}
        assert "comp_marine_001" not in missing_ids

    def test_uncovered_item_in_missing(self) -> None:
        demand, supply = self._build_inputs()
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        oceanic_cluster = next(
            (
                c
                for c in result.all_clusters
                if c.sector == "Blue Biotech" and c.qmbd_axis == "OCEANIC"
            ),
            None,
        )
        assert oceanic_cluster is not None
        missing_ids = {e.competence_id for e in oceanic_cluster.missing_items}
        assert "comp_oceanic_001" in missing_ids

    def test_all_clusters_have_priority_scores(self) -> None:
        demand, supply = self._build_inputs()
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        for cluster in result.all_clusters:
            assert 0.0 <= cluster.priority_score <= 1.0

    def test_demand_evidence_passed_through(self) -> None:
        demand, supply = self._build_inputs()
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        assert "Blue Biotech" in result.demand_evidence
        assert len(result.demand_evidence["Blue Biotech"]) == 2

    def test_supply_evidence_passed_through(self) -> None:
        demand, supply = self._build_inputs()
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        assert "Blue Biotech" in result.supply_evidence
        assert len(result.supply_evidence["Blue Biotech"]) == 1

    def test_overlap_status_updated(self) -> None:
        demand, supply = self._build_inputs()
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        marine_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
        )
        covered = [e for e in marine_cluster.demand_items if e.competence_id == "comp_marine_001"]
        assert covered
        assert covered[0].overlap_status == "covered"

    def test_to_dict_serializable(self) -> None:
        demand, supply = self._build_inputs()
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        # Should not raise
        d = result.to_dict()
        json.dumps(d)


# ---------------------------------------------------------------------------
# Integration tests: run_gap_model
# ---------------------------------------------------------------------------


class TestRunGapModel:
    def _make_baseline(self) -> List[Competence]:
        return [
            _make_competence("baseline_a1", TMBDAxis.OCEANIC, ["Blue Biotech", "R&I"], "A"),
            _make_competence("baseline_c1", TMBDAxis.MARINE, ["Blue Biotech", "Living Res."], "C"),
        ]

    def _make_literature(self) -> List[Competence]:
        return [
            _make_competence("lit_bb_001", TMBDAxis.MARINE, ["Blue Biotech"], "literature"),
            _make_competence("lit_ct_001", TMBDAxis.OCEANIC, ["Coastal Tourism"], "literature"),
        ]

    def test_returns_gap_model_result(self) -> None:
        baseline = self._make_baseline()
        literature = self._make_literature()
        result = run_gap_model(baseline, literature)
        assert isinstance(result, GapModelResult)

    def test_all_sectors_represented_in_demand_or_supply(self) -> None:
        baseline = self._make_baseline()
        literature = self._make_literature()
        result = run_gap_model(baseline, literature)
        # All 12 sectors should be keys in both dicts
        assert set(result.demand_evidence.keys()) == set(SECTORS)
        assert set(result.supply_evidence.keys()) == set(SECTORS)

    def test_live_enriched_records_change_demand_evidence(self) -> None:
        """Live-enriched records must increase demand_evidence for covered sectors."""
        baseline = self._make_baseline()
        literature = self._make_literature()
        live = [
            _make_competence("lit_live_crossref_00001", TMBDAxis.MARITIME, ["Port Activities"], "literature"),
        ]

        result_static = run_gap_model(baseline, literature)
        result_live = run_gap_model(baseline, literature, live_competences=live)

        static_port_demand = len(result_static.demand_evidence.get("Port Activities", []))
        live_port_demand = len(result_live.demand_evidence.get("Port Activities", []))
        assert live_port_demand > static_port_demand, (
            "Adding live competences for Port Activities should increase demand evidence"
        )

    def test_supply_evidence_includes_baseline(self) -> None:
        baseline = self._make_baseline()
        literature = self._make_literature()
        result = run_gap_model(baseline, literature)
        supply_bb = result.supply_evidence.get("Blue Biotech", [])
        supply_origins = {e.origin for e in supply_bb}
        assert "static_baseline" in supply_origins

    def test_supply_evidence_augmented_when_credentials_db_exists(
        self, tmp_path: Path
    ) -> None:
        """credentials_database.json items must be tagged generated_credential_previous_run."""
        cred_db = {
            "metadata": {"total": 1},
            "credentials": [
                {
                    "id": "mc_test_eqf4",
                    "title": "Test credential",
                    "sector": "Blue Biotech",
                    "competences": ["baseline_a1"],
                    "eqf_level": 4,
                }
            ],
        }
        db_path = tmp_path / "credentials_database.json"
        db_path.write_text(json.dumps(cred_db), encoding="utf-8")

        baseline = self._make_baseline()
        literature = self._make_literature()

        import run_full_analysis as rfa

        original_specs = rfa._SUPPLY_FILE_SPECS
        rfa._SUPPLY_FILE_SPECS = [
            {
                "path": str(db_path),
                "origin": "generated_credential_previous_run",
                "provider": "credentials_database",
            }
        ]
        try:
            result = run_gap_model(baseline, literature)
            generated_bb = result.generated_supply_evidence.get("Blue Biotech", [])
            generated_origins = {e.origin for e in generated_bb}
            assert "generated_credential_previous_run" in generated_origins, (
                "credentials_database.json items must be tagged "
                "generated_credential_previous_run, not static supply"
            )
            # Must NOT appear in verified supply_evidence
            supply_bb = result.supply_evidence.get("Blue Biotech", [])
            assert "generated_credential_previous_run" not in {
                e.origin for e in supply_bb
            }, "Generated credentials must not appear in verified supply_evidence"
        finally:
            rfa._SUPPLY_FILE_SPECS = original_specs

    def test_generated_credentials_distinct_from_verified_baseline(self) -> None:
        """generated_credential_previous_run and static_baseline must be distinguishable."""
        baseline = self._make_baseline()
        literature = self._make_literature()
        result = run_gap_model(baseline, literature)
        for sector_items in result.supply_evidence.values():
            for item in sector_items:
                if item.provider == "baseline":
                    assert item.origin == "static_baseline"
                if item.origin == "generated_credential_previous_run":
                    assert item.provider != "baseline"

    def test_missing_clusters_only_when_gap_present(self) -> None:
        baseline = self._make_baseline()
        literature = self._make_literature()
        result = run_gap_model(baseline, literature)
        for cluster in result.missing_clusters:
            assert cluster.gap_ratio > 0.0


# ---------------------------------------------------------------------------
# Export function tests
# ---------------------------------------------------------------------------


class TestExportFunctions:
    def _make_result(self) -> GapModelResult:
        ev_demand = _make_evidence("d1", "Blue Biotech", "MARINE", year="2023")
        ev_supply = _make_evidence(
            "s1", "Blue Biotech", "MARINE", origin="static_baseline", year="2020"
        )
        cluster = GapCluster(
            sector="Blue Biotech",
            qmbd_axis="MARINE",
            demand_items=[ev_demand],
            supply_items=[ev_supply],
            missing_items=[ev_demand],
            priority_score=0.65,
        )
        return GapModelResult(
            demand_evidence={"Blue Biotech": [ev_demand]},
            supply_evidence={"Blue Biotech": [ev_supply]},
            generated_supply_evidence={},
            all_clusters=[cluster],
            missing_clusters=[cluster],
        )

    def test_export_gaps_detailed_json(self, tmp_path: Path) -> None:
        result = self._make_result()
        out = tmp_path / "gaps_detailed.json"
        export_gaps_detailed_json(result, out)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "metadata" in data
        assert "all_clusters" in data
        assert "missing_clusters" in data
        assert data["metadata"]["total_clusters"] == 1

    def test_export_gaps_by_sector_axis_csv(self, tmp_path: Path) -> None:
        result = self._make_result()
        out = tmp_path / "gaps_by_sector_axis.csv"
        export_gaps_by_sector_axis_csv(result, out)
        assert out.exists()
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 1
        assert rows[0]["Sector"] == "Blue Biotech"
        assert rows[0]["QMBD_Axis"] == "MARINE"
        assert rows[0]["Missing_Count"] == "1"

    def test_export_gap_priority_ranking_csv(self, tmp_path: Path) -> None:
        result = self._make_result()
        out = tmp_path / "gap_priority_ranking.csv"
        export_gap_priority_ranking_csv(result, out)
        assert out.exists()
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 1
        assert rows[0]["Rank"] == "1"
        assert rows[0]["Sector"] == "Blue Biotech"

    def test_export_gaps_summary_csv_still_produced(self, tmp_path: Path) -> None:
        """gaps_summary.csv must remain produced by export_gaps_summary_csv."""
        gaps = {
            s: GapAnalysis(
                sector=s,
                required_ids=["a", "b"],
                available_ids=["a"],
                missing_ids=["b"],
                gap_pct=50.0,
                by_axis={"MARINE": [], "MARITIME": ["b"], "OCEANIC": [], "HYDRONIZATION": []},
            )
            for s in SECTORS
        }
        out = tmp_path / "gaps_summary.csv"
        export_gaps_summary_csv(gaps, out)
        assert out.exists()
        rows = list(csv.reader(out.open(encoding="utf-8")))
        assert rows[0][0] == "Sector"
        assert len(rows) == len(SECTORS) + 1  # header + 12 sectors

    def test_export_gaps_detailed_json_is_valid_json(self, tmp_path: Path) -> None:
        result = self._make_result()
        out = tmp_path / "gaps_detailed.json"
        export_gaps_detailed_json(result, out)
        # Should not raise
        json.loads(out.read_text(encoding="utf-8"))

    def test_export_gap_priority_ranking_csv_audit_fields(self, tmp_path: Path) -> None:
        """gap_priority_ranking.csv must include the audit columns."""
        result = self._make_result()
        out = tmp_path / "gap_priority_ranking.csv"
        export_gap_priority_ranking_csv(result, out)
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 1
        row = rows[0]
        required_audit_cols = {
            "Top_Origins",
            "Top_Providers",
            "Top_DOIs",
            "Top_Titles",
            "Year_Range",
            "Average_Confidence",
            "Coverage_Method",
            "Supporting_Providers",
        }
        assert required_audit_cols.issubset(set(row.keys()))
        # Coverage_Method must be a meaningful value (not empty)
        assert row["Coverage_Method"]  # non-empty string

    def _make_result_multi_item(self) -> GapModelResult:
        """Build a GapModelResult with multiple missing items having varying confidence scores.

        Items are provided in reverse competence_id order to verify that sorting
        (not insertion order) drives deterministic aggregation.
        """
        items = [
            _make_evidence("z_comp", "Blue Biotech", "MARINE", confidence_score=0.90),
            _make_evidence("a_comp", "Blue Biotech", "MARINE", confidence_score=0.70),
            _make_evidence("m_comp", "Blue Biotech", "MARINE", confidence_score=0.80),
        ]
        cluster = GapCluster(
            sector="Blue Biotech",
            qmbd_axis="MARINE",
            demand_items=items,
            supply_items=[],
            missing_items=items,
            priority_score=0.75,
        )
        return GapModelResult(
            demand_evidence={"Blue Biotech": items},
            supply_evidence={},
            generated_supply_evidence={},
            all_clusters=[cluster],
            missing_clusters=[cluster],
        )

    def test_gap_priority_ranking_csv_is_deterministic_across_runs(
        self, tmp_path: Path
    ) -> None:
        """Calling export_gap_priority_ranking_csv twice must produce identical CSV output.

        This is a regression test for nondeterministic floating-point summation and
        _top_values tie-breaking that caused Average_Confidence to drift between runs.
        """
        result = self._make_result_multi_item()
        out1 = tmp_path / "run1.csv"
        out2 = tmp_path / "run2.csv"
        export_gap_priority_ranking_csv(result, out1)
        export_gap_priority_ranking_csv(result, out2)
        text1 = out1.read_text(encoding="utf-8")
        text2 = out2.read_text(encoding="utf-8")
        assert text1 == text2, (
            "gap_priority_ranking.csv produced different content on two consecutive runs; "
            "the generator is nondeterministic."
        )
        rows = list(csv.DictReader(out1.open(encoding="utf-8")))
        assert len(rows) == 1
        # Average_Confidence must equal the mean of 0.90, 0.70, 0.80 = 0.800
        assert rows[0]["Average_Confidence"] == "0.800"

    def test_gap_priority_ranking_avg_confidence_midpoint_rounds_up(
        self, tmp_path: Path
    ) -> None:
        """Average_Confidence must round correctly when the exact average is 0.8375.

        Regression test for a Python 3.11 vs 3.12 float accumulation difference: the
        naive sum() built-in could undercount and yield 0.8374... → "0.837", while
        math.fsum() correctly yields 0.8375... → "0.838".

        Cluster: 20 items at cs=0.75 (static_literature) + 28 items at cs=0.90 (live)
        True sum = 20×0.75 + 28×0.90 = 40.2; avg = 40.2/48 = 0.8375; rounds to 0.838.
        """
        items = [
            _make_evidence(
                f"lit_labor_justice_{i:04d}",
                "Infra & Robotics",
                "MARITIME",
                confidence_score=0.75,
            )
            for i in range(20)
        ] + [
            _make_evidence(
                f"lit_live_crossref_{i:05d}",
                "Infra & Robotics",
                "MARITIME",
                confidence_score=0.90,
            )
            for i in range(28)
        ]
        cluster = GapCluster(
            sector="Infra & Robotics",
            qmbd_axis="MARITIME",
            demand_items=items,
            supply_items=[],
            missing_items=items,
            priority_score=0.5814,
        )
        result = GapModelResult(
            demand_evidence={"Infra & Robotics": items},
            supply_evidence={},
            generated_supply_evidence={},
            all_clusters=[cluster],
            missing_clusters=[cluster],
        )
        out = tmp_path / "ranking.csv"
        export_gap_priority_ranking_csv(result, out)
        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 1
        assert rows[0]["Average_Confidence"] == "0.838", (
            f"Expected '0.838' (math.fsum of 20×0.75 + 28×0.90 / 48), "
            f"got '{rows[0]['Average_Confidence']}'. "
            "This may indicate that sum() is being used instead of math.fsum(), "
            "causing Python-version-dependent float accumulation drift."
        )


# ---------------------------------------------------------------------------
# Tests: axis-sensitive coverage (Fix 3)
# ---------------------------------------------------------------------------


class TestAxisSensitiveCoverage:
    """The coverage rule must be axis-scoped — no cross-axis leakage."""

    def test_cross_axis_supply_does_not_cover_demand(self) -> None:
        """A MARITIME supply item must NOT cover a MARINE demand item."""
        demand_item = _make_evidence("comp_001", "Blue Biotech", "MARINE")
        # Supply is MARITIME, not MARINE — must not cover the MARINE demand item
        supply_item = _make_evidence(
            "comp_001",  # same competence_id, but different axis
            "Blue Biotech",
            "MARITIME",
            origin="static_baseline",
        )
        demand = {"Blue Biotech": [demand_item]}
        supply = {"Blue Biotech": [supply_item]}
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        marine_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
        )
        missing_ids = {e.competence_id for e in marine_cluster.missing_items}
        assert "comp_001" in missing_ids, (
            "comp_001 on MARITIME supply must NOT cover MARINE demand"
        )

    def test_same_axis_supply_covers_demand_by_exact_id(self) -> None:
        """Same sector × axis exact ID match must cover the demand item."""
        demand_item = _make_evidence("comp_exact", "Blue Biotech", "MARINE")
        supply_item = _make_evidence(
            "comp_exact", "Blue Biotech", "MARINE", origin="static_baseline"
        )
        demand = {"Blue Biotech": [demand_item]}
        supply = {"Blue Biotech": [supply_item]}
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        marine_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
        )
        missing_ids = {e.competence_id for e in marine_cluster.missing_items}
        assert "comp_exact" not in missing_ids

    def test_coverage_method_exact_id(self) -> None:
        demand_item = _make_evidence("comp_exact", "Blue Biotech", "MARINE")
        supply_item = _make_evidence(
            "comp_exact", "Blue Biotech", "MARINE", origin="static_baseline"
        )
        demand = {"Blue Biotech": [demand_item]}
        supply = {"Blue Biotech": [supply_item]}
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        marine_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
        )
        assert marine_cluster.coverage_method == "exact_id"

    def test_coverage_method_uncovered(self) -> None:
        demand_item = _make_evidence("comp_only_demand", "Blue Biotech", "MARINE")
        demand = {"Blue Biotech": [demand_item]}
        supply: Dict[str, List[GapEvidence]] = {"Blue Biotech": []}
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        marine_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
        )
        assert marine_cluster.coverage_method == "uncovered"


# ---------------------------------------------------------------------------
# Tests: false-positive token overlap prevention (Fix 3)
# ---------------------------------------------------------------------------


class TestFalsePositiveOverlapPrevention:
    """The strengthened coverage rule must not cover unrelated items."""

    def test_stopword_only_names_not_covered(self) -> None:
        """Items whose names consist only of stopwords must not be covered by similarity."""
        # "blue ocean" — all tokens are in _COVERAGE_STOPWORDS
        demand_item = _make_evidence("d_stopword", "Blue Biotech", "MARINE")
        demand_item.name = "blue ocean"
        supply_item = _make_evidence(
            "s_other", "Blue Biotech", "MARINE", origin="static_baseline"
        )
        supply_item.name = "marine water"
        demand = {"Blue Biotech": [demand_item]}
        supply = {"Blue Biotech": [supply_item]}
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        marine_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
        )
        missing_ids = {e.competence_id for e in marine_cluster.missing_items}
        assert "d_stopword" in missing_ids, (
            "Stopword-only names must not produce false coverage"
        )

    def test_low_jaccard_similarity_not_covered(self) -> None:
        """Items with low name similarity (< threshold) must NOT be covered."""
        demand_item = _make_evidence("d_unrelated", "Blue Biotech", "MARINE")
        demand_item.name = "coastal erosion monitoring sediment transport"
        supply_item = _make_evidence(
            "s_unrelated", "Blue Biotech", "MARINE", origin="static_baseline"
        )
        supply_item.name = "digital twin vessel navigation autopilot control"
        demand = {"Blue Biotech": [demand_item]}
        supply = {"Blue Biotech": [supply_item]}
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        marine_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
        )
        missing_ids = {e.competence_id for e in marine_cluster.missing_items}
        assert "d_unrelated" in missing_ids, (
            "Low-similarity names must not produce false coverage"
        )

    def test_high_jaccard_similarity_covered(self) -> None:
        """Items with high name similarity (> threshold) SHOULD be covered."""
        demand_item = _make_evidence("d_similar", "Blue Biotech", "MARINE")
        demand_item.name = "bioprospecting marine organisms pharmaceutical applications"
        supply_item = _make_evidence(
            "s_similar", "Blue Biotech", "MARINE", origin="static_baseline"
        )
        supply_item.name = "bioprospecting organisms pharmaceutical marine applications"
        demand = {"Blue Biotech": [demand_item]}
        supply = {"Blue Biotech": [supply_item]}
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        marine_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
        )
        missing_ids = {e.competence_id for e in marine_cluster.missing_items}
        assert "d_similar" not in missing_ids, (
            "High-similarity names must be marked as covered"
        )


# ---------------------------------------------------------------------------
# Tests: gap-aware priority score (Fix 4)
# ---------------------------------------------------------------------------


class TestGapAwarePriorityScore:
    """Priority score must increase with gap_ratio and missing_count."""

    def _cluster_with_gap(
        self, demand: int, missing: int, year: str = "2022", conf: float = 0.8
    ) -> GapCluster:
        d_items = [
            _make_evidence(f"d{i}", "Blue Biotech", "MARINE", year=year, confidence_score=conf)
            for i in range(demand)
        ]
        m_items = d_items[:missing]
        return GapCluster(
            sector="Blue Biotech",
            qmbd_axis="MARINE",
            demand_items=d_items,
            supply_items=[],
            missing_items=m_items,
        )

    def test_higher_gap_ratio_raises_score(self) -> None:
        """A cluster with 100% gap must score higher than one with 0% gap."""
        full_gap = self._cluster_with_gap(demand=4, missing=4)
        no_gap = self._cluster_with_gap(demand=4, missing=0)
        all_clusters = [full_gap, no_gap]
        s_full = compute_priority_score(full_gap, all_clusters)
        s_none = compute_priority_score(no_gap, all_clusters)
        assert s_full > s_none, "Higher gap_ratio must yield higher priority score"

    def test_higher_missing_count_raises_score(self) -> None:
        """A cluster with more missing items must score higher (all else equal)."""
        many_missing = self._cluster_with_gap(demand=6, missing=6)
        few_missing = self._cluster_with_gap(demand=6, missing=1)
        all_clusters = [many_missing, few_missing]
        s_many = compute_priority_score(many_missing, all_clusters)
        s_few = compute_priority_score(few_missing, all_clusters)
        assert s_many > s_few, "Higher missing_count must yield higher priority score"

    def test_zero_gap_cluster_gets_low_score(self) -> None:
        """A fully-covered cluster must have lower score than a full-gap cluster."""
        full_gap = self._cluster_with_gap(demand=4, missing=4)
        zero_gap = self._cluster_with_gap(demand=4, missing=0)
        score_gap = compute_priority_score(full_gap, [full_gap, zero_gap])
        score_zero = compute_priority_score(zero_gap, [full_gap, zero_gap])
        assert score_gap > score_zero


# ---------------------------------------------------------------------------
# Tests: CSV supply parsing (Fix 2)
# ---------------------------------------------------------------------------


class TestMicrocredentialsCsvParsing:
    def _csv_path(self) -> Path:
        return Path(
            "data/derived/"
            "Blue Social Competences Univ Szczecin - Blue Clusters for Microcredentials.csv"
        )

    def test_csv_parsed_when_file_exists(self) -> None:
        """Blue Clusters CSV must produce supply evidence when file is present."""
        from run_full_analysis import (
            REPO_ROOT,
            _collect_supply_from_microcredentials_csv,
        )

        csv_path = REPO_ROOT / self._csv_path()
        if not csv_path.exists():
            pytest.skip("Blue Clusters CSV not present in this checkout")

        supply = _collect_supply_from_microcredentials_csv(csv_path)
        assert supply, "CSV parsing must produce at least one sector of supply evidence"
        # Each item must be tagged as existing_microcredential
        for sector_items in supply.values():
            for item in sector_items:
                assert item.origin == "existing_microcredential"
                assert item.provider == "microcredentials_clusters_csv"

    def test_csv_parsed_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        from run_full_analysis import _collect_supply_from_microcredentials_csv

        supply = _collect_supply_from_microcredentials_csv(tmp_path / "nonexistent.csv")
        assert supply == {}

    def test_csv_parsed_covers_known_sectors(self) -> None:
        """Parsed CSV must contain items for canonical SECTORS."""
        from run_full_analysis import (
            REPO_ROOT,
            SECTORS,
            _collect_supply_from_microcredentials_csv,
        )

        csv_path = REPO_ROOT / self._csv_path()
        if not csv_path.exists():
            pytest.skip("Blue Clusters CSV not present in this checkout")

        supply = _collect_supply_from_microcredentials_csv(csv_path)
        known = set(SECTORS) & set(supply.keys())
        assert known, "CSV parsing must map to at least one canonical SECTORS entry"

    def test_csv_run_gap_model_includes_microcredential_origin(self) -> None:
        """run_gap_model with real CSV must include existing_microcredential in supply."""
        from run_full_analysis import REPO_ROOT

        csv_path = (
            REPO_ROOT
            / "data/derived"
            / "Blue Social Competences Univ Szczecin - Blue Clusters for Microcredentials.csv"
        )
        if not csv_path.exists():
            pytest.skip("Blue Clusters CSV not present in this checkout")

        baseline = [
            _make_competence("bl_a1", TMBDAxis.OCEANIC, ["Blue Biotech"], "A"),
        ]
        literature = [
            _make_competence("lit_bb_001", TMBDAxis.MARINE, ["Blue Biotech"], "literature"),
        ]
        result = run_gap_model(baseline, literature)
        all_origins = {
            item.origin
            for sector_items in result.supply_evidence.values()
            for item in sector_items
        }
        assert "existing_microcredential" in all_origins


# ---------------------------------------------------------------------------
# Tests: provider provenance extraction (Fix 6)
# ---------------------------------------------------------------------------


class TestProviderProvenanceExtraction:
    def _make_comp_with_authors(self, authors: str) -> "Competence":
        return Competence(
            id="lit_live_crossref_00001",
            name="Test competence",
            description="Test",
            axis=TMBDAxis.MARINE,
            dimension="literature",
            source=CompetenceSource(
                file="data/derived/x.csv",
                row=1,
                authors=authors,
                year="2023",
                paper_title="Some paper",
                doi="10.1234/test",
            ),
            keywords=["crossref", "blue-economy"],
            sectors=["Blue Biotech"],
        )

    def test_authors_not_used_as_provider(self) -> None:
        """Authors must NOT be used as provider; ID slug takes priority instead."""
        from run_full_analysis import _extract_provider_from_comp

        # comp has both authors and a lit_live_ ID; provider must come from ID slug
        comp = self._make_comp_with_authors("Smith, J.; Jones, K.")
        comp.id = "lit_live_crossref_00001"
        provider = _extract_provider_from_comp(comp)
        assert provider == "crossref", (
            f"Authors must not be used as provider; expected ID slug 'crossref', got {provider!r}"
        )
        assert provider != "Smith, J.; Jones, K.", (
            "Bibliographic authorship must never be returned as provider"
        )

    def test_id_slug_used_when_no_authors(self) -> None:
        """Provider must be extracted from lit_live_<provider>_ID when authors absent."""
        from run_full_analysis import _extract_provider_from_comp

        comp = self._make_comp_with_authors("")
        comp.id = "lit_live_scopus_00042"
        provider = _extract_provider_from_comp(comp)
        assert provider == "scopus"

    def test_arbitrary_keyword_returns_unknown(self) -> None:
        """Arbitrary thematic keywords must not be returned as provider; return 'unknown'."""
        from run_full_analysis import _extract_provider_from_comp

        comp = _make_competence("baseline_x", TMBDAxis.MARINE, ["Blue Biotech"])
        comp.keywords = ["special-provider-kw"]
        provider = _extract_provider_from_comp(comp)
        assert provider == "unknown", (
            f"Arbitrary keyword must not be used as provider; expected 'unknown', got: {provider!r}"
        )

    def test_support_prefix_keyword_not_used_as_provider(self) -> None:
        """'support:wos' keyword must not become the provider; only provider: prefixes count."""
        from run_full_analysis import _extract_provider_from_comp

        comp = _make_competence("baseline_z", TMBDAxis.MARINE, ["Blue Biotech"])
        comp.keywords = ["support:wos"]
        provider = _extract_provider_from_comp(comp)
        assert provider == "unknown", (
            f"'support:' prefix must not map to provider; expected 'unknown', got: {provider!r}"
        )

    def test_thematic_keyword_labor_justice_not_provider(self) -> None:
        """'labor_justice' keyword must not become provider."""
        from run_full_analysis import _extract_provider_from_comp

        comp = _make_competence("baseline_lj", TMBDAxis.MARITIME, ["Blue Biotech"])
        comp.keywords = ["labor_justice", "oceanic", "sustainability"]
        provider = _extract_provider_from_comp(comp)
        assert provider == "unknown", (
            f"Thematic keyword 'labor_justice' must not be provider; got: {provider!r}"
        )

    def test_thematic_keyword_research_gaps_not_provider(self) -> None:
        """'research_gaps' keyword must not become provider."""
        from run_full_analysis import _extract_provider_from_comp

        comp = _make_competence("baseline_rg", TMBDAxis.OCEANIC, ["Blue Biotech"])
        comp.keywords = ["research_gaps", "blue_sociology"]
        provider = _extract_provider_from_comp(comp)
        assert provider == "unknown", (
            f"Thematic keyword 'research_gaps' must not be provider; got: {provider!r}"
        )

    def test_explicit_provider_prefix_keyword_resolved(self) -> None:
        """'provider:crossref' keyword must resolve to 'crossref'."""
        from run_full_analysis import _extract_provider_from_comp

        comp = _make_competence("baseline_cr", TMBDAxis.MARINE, ["Blue Biotech"])
        comp.keywords = ["provider:crossref", "blue-economy"]
        provider = _extract_provider_from_comp(comp)
        assert provider == "crossref", (
            f"'provider:crossref' keyword must resolve to 'crossref'; got: {provider!r}"
        )

    def test_source_provider_prefix_keyword_resolved(self) -> None:
        """'source_provider:scopus' keyword must resolve to 'scopus'."""
        from run_full_analysis import _extract_provider_from_comp

        comp = _make_competence("baseline_sp", TMBDAxis.MARINE, ["Blue Biotech"])
        comp.keywords = ["source_provider:scopus"]
        provider = _extract_provider_from_comp(comp)
        assert provider == "scopus", (
            f"'source_provider:scopus' must resolve to 'scopus'; got: {provider!r}"
        )

    def test_unknown_returned_when_no_info(self) -> None:
        from run_full_analysis import _extract_provider_from_comp

        comp = _make_competence("baseline_y", TMBDAxis.MARINE, ["Blue Biotech"])
        comp.keywords = []
        provider = _extract_provider_from_comp(comp)
        assert provider == "unknown"

    def test_multiword_provider_slug_preserved(self) -> None:
        """Multiword live-provider slugs must not be truncated to a single token."""
        from run_full_analysis import _extract_provider_from_comp

        comp = self._make_comp_with_authors("")
        comp.id = "lit_live_web_of_science_clarivate_00002"
        provider = _extract_provider_from_comp(comp)
        assert provider == "web_of_science_clarivate", (
            f"Full provider slug must be preserved; got {provider!r}"
        )

    def test_single_token_provider_slug_preserved(self) -> None:
        """Single-word provider slugs must still resolve correctly."""
        from run_full_analysis import _extract_provider_from_comp

        comp = self._make_comp_with_authors("")
        comp.id = "lit_live_crossref_00099"
        provider = _extract_provider_from_comp(comp)
        assert provider == "crossref"


# ---------------------------------------------------------------------------
# Regression tests: methodological edge cases
# ---------------------------------------------------------------------------


class TestGeneratedCredentialsNotUsedForCoverage:
    """P1: generated_credential_previous_run items must NOT affect gap ratios."""

    def _make_baseline(self) -> "List[Competence]":
        return [_make_competence("bl_a1", TMBDAxis.MARINE, ["Blue Biotech"], "A")]

    def _make_literature(self) -> "List[Competence]":
        return [_make_competence("lit_001", TMBDAxis.MARINE, ["Blue Biotech"], "literature")]

    def test_gap_ratios_unchanged_by_credentials_db(self, tmp_path: Path) -> None:
        """Presence of credentials_database.json must not change per-cluster gap ratios."""
        import run_full_analysis as rfa

        baseline = self._make_baseline()
        literature = self._make_literature()

        # Run without any credentials database
        result_without = run_gap_model(baseline, literature)

        # Create a credentials database with a matching competence ID
        cred_db = {
            "metadata": {"total": 1},
            "credentials": [
                {
                    "id": "mc_generated_001",
                    "title": "Generated credential",
                    "sector": "Blue Biotech",
                    "competences": ["lit_001"],  # matches demand item ID
                    "eqf_level": 4,
                }
            ],
        }
        db_path = tmp_path / "credentials_database.json"
        db_path.write_text(json.dumps(cred_db), encoding="utf-8")

        original_specs = rfa._SUPPLY_FILE_SPECS
        rfa._SUPPLY_FILE_SPECS = [
            {
                "path": str(db_path),
                "origin": "generated_credential_previous_run",
                "provider": "credentials_database",
            }
        ]
        try:
            result_with = run_gap_model(baseline, literature)
        finally:
            rfa._SUPPLY_FILE_SPECS = original_specs

        # Gap ratios must be identical regardless of the credentials database
        clusters_without = {
            (c.sector, c.qmbd_axis): c.gap_ratio for c in result_without.all_clusters
        }
        clusters_with = {
            (c.sector, c.qmbd_axis): c.gap_ratio for c in result_with.all_clusters
        }
        assert clusters_without == clusters_with, (
            "Gap ratios must not change when credentials_database.json is present; "
            "generated credentials must NOT be used for coverage"
        )

    def test_generated_credentials_visible_in_generated_supply_evidence_for_audit(
        self, tmp_path: Path
    ) -> None:
        """generated_credential_previous_run items must appear in generated_supply_evidence."""
        import run_full_analysis as rfa

        baseline = self._make_baseline()
        literature = self._make_literature()

        cred_db = {
            "metadata": {"total": 1},
            "credentials": [
                {
                    "id": "mc_audit_001",
                    "title": "Audit credential",
                    "sector": "Blue Biotech",
                    "competences": ["bl_a1"],
                    "eqf_level": 4,
                }
            ],
        }
        db_path = tmp_path / "credentials_database.json"
        db_path.write_text(json.dumps(cred_db), encoding="utf-8")

        original_specs = rfa._SUPPLY_FILE_SPECS
        rfa._SUPPLY_FILE_SPECS = [
            {
                "path": str(db_path),
                "origin": "generated_credential_previous_run",
                "provider": "credentials_database",
            }
        ]
        try:
            result = run_gap_model(baseline, literature)
        finally:
            rfa._SUPPLY_FILE_SPECS = original_specs

        # Generated credentials must be in generated_supply_evidence, not supply_evidence
        all_generated_origins = {
            item.origin
            for sector_items in result.generated_supply_evidence.values()
            for item in sector_items
        }
        assert "generated_credential_previous_run" in all_generated_origins, (
            "Generated credentials must be in generated_supply_evidence for audit visibility"
        )
        # Verified supply_evidence must NOT contain generated credentials
        all_supply_origins = {
            item.origin
            for sector_items in result.supply_evidence.values()
            for item in sector_items
        }
        assert "generated_credential_previous_run" not in all_supply_origins, (
            "Generated credentials must not pollute verified supply_evidence"
        )


class TestThematicKeywordsNotUsedAsProviders:
    """Thematic keyword tags must not appear as supporting_providers."""

    def test_thematic_keywords_not_in_supporting_providers(self) -> None:
        """Keywords like 'labor_justice', 'oceanic', axis labels must not pollute providers."""
        from run_full_analysis import _competence_to_gap_evidence

        comp = _make_competence("lit_x", TMBDAxis.OCEANIC, ["Blue Biotech"], "literature")
        comp.keywords = ["labor_justice", "oceanic", "maritime", "literature", "live-api"]
        evidence = _competence_to_gap_evidence(
            comp, sector="Blue Biotech", origin="static_literature", provider="crossref"
        )
        assert evidence.supporting_providers == [], (
            "Thematic/control keywords must not be added to supporting_providers"
        )

    def test_support_prefix_keyword_becomes_provider(self) -> None:
        """Only keywords with 'support:' prefix must populate supporting_providers."""
        from run_full_analysis import _competence_to_gap_evidence

        comp = _make_competence("lit_y", TMBDAxis.MARITIME, ["Port Activities"], "literature")
        comp.keywords = ["support:wos", "support:scopus", "labor_justice", "maritime"]
        evidence = _competence_to_gap_evidence(
            comp, sector="Port Activities", origin="static_literature", provider="crossref"
        )
        assert set(evidence.supporting_providers) == {"wos", "scopus"}, (
            "Only 'support:' prefixed keywords must populate supporting_providers"
        )


class TestSimilarityMatchedSupplyOverlapStatus:
    """Supply items that cover demand via name similarity must be marked 'covered'."""

    def test_similarity_matched_supply_gets_covered_status(self) -> None:
        """A supply item that name-similarity-covers a demand item must not be 'supply_only'."""
        demand_item = _make_evidence("d_biodiversity", "Blue Biotech", "MARINE")
        demand_item.name = "biodiversity assessment coastal habitats monitoring"
        supply_item = _make_evidence(
            "s_biodiversity_monitor", "Blue Biotech", "MARINE", origin="static_baseline"
        )
        supply_item.name = "coastal habitats biodiversity monitoring assessment"
        demand = {"Blue Biotech": [demand_item]}
        supply = {"Blue Biotech": [supply_item]}
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        marine_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARINE"
        )
        # demand must be covered
        assert marine_cluster.missing_items == [], "High-similarity demand must be covered"
        # supply item must NOT be 'supply_only'
        assert marine_cluster.supply_items[0].overlap_status == "covered", (
            "Supply item that covers via name similarity must have overlap_status='covered'"
        )


class TestNameTokenNormalization:
    """_name_tokens must normalize punctuation and use expanded stopwords."""

    def test_hyphenated_token_split(self) -> None:
        """Hyphenated compound words must be split into separate tokens."""
        from src.gap_model import _name_tokens

        tokens = _name_tokens("eco-tourism coastal")
        assert "eco" in tokens or "tourism" in tokens, (
            "Hyphenated words must be split on punctuation"
        )

    def test_slash_separated_tokens_split(self) -> None:
        """Slash-separated terms must be split into separate tokens."""
        from src.gap_model import _name_tokens

        tokens = _name_tokens("water/waste resource management")
        assert "water" in tokens or "waste" in tokens

    def test_generic_stopwords_excluded(self) -> None:
        """Extended stopwords (skills, management, etc.) must be excluded."""
        from src.gap_model import _name_tokens

        tokens = _name_tokens("digital skills management competence awareness")
        assert "skills" not in tokens
        assert "management" not in tokens
        assert "competence" not in tokens
        assert "awareness" not in tokens

    def test_only_one_shared_generic_token_not_covered(self) -> None:
        """Names sharing only one non-stopword token must NOT be covered (min_shared=2)."""
        demand_item = _make_evidence("d_single", "Blue Biotech", "MARITIME")
        demand_item.name = "digital literacy coastal communities"
        supply_item = _make_evidence(
            "s_single", "Blue Biotech", "MARITIME", origin="static_baseline"
        )
        # Shares "digital" but not "literacy" with demand — only 1 shared meaningful token
        supply_item.name = "digital navigation instruments vessel"
        demand = {"Blue Biotech": [demand_item]}
        supply = {"Blue Biotech": [supply_item]}
        result = compute_gap_model(demand, supply, sectors=["Blue Biotech"])
        maritime_cluster = next(
            c for c in result.all_clusters
            if c.sector == "Blue Biotech" and c.qmbd_axis == "MARITIME"
        )
        missing_ids = {e.competence_id for e in maritime_cluster.missing_items}
        assert "d_single" in missing_ids, (
            "One shared token must not satisfy the minimum-shared-token guard"
        )


class TestCsvSourceRowProvenance:
    """source_row in CSV-parsed supply evidence must use 1-based file line numbers."""

    def test_first_data_row_has_source_row_four(self, tmp_path: Path) -> None:
        """First data row (rows[3]) is physical line 4; source_row must be 4 not 3."""
        from run_full_analysis import _collect_supply_from_microcredentials_csv

        csv_content = (
            "# Comment row\n"
            "# Another comment\n"
            "Dimension,Blue Biotech,Coastal Tourism\n"
            "A,Bioprospecting techniques,Coastal ecosystem interpretation\n"
        )
        csv_file = tmp_path / "test_clusters.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        # Patch the sector map to recognise test headers
        import run_full_analysis as rfa

        orig_map = dict(rfa._CSV_SECTOR_MAP)
        orig_axis = dict(rfa._CSV_DIMENSION_AXIS)
        rfa._CSV_SECTOR_MAP = {"Blue Biotech": "Blue Biotech", "Coastal Tourism": "Coastal Tourism"}
        rfa._CSV_DIMENSION_AXIS = {"A": "OCEANIC"}
        try:
            supply = _collect_supply_from_microcredentials_csv(csv_file)
        finally:
            rfa._CSV_SECTOR_MAP = orig_map
            rfa._CSV_DIMENSION_AXIS = orig_axis

        items = supply.get("Blue Biotech", [])
        assert items, "CSV must produce at least one supply item"
        assert items[0].source_row == 4, (
            f"First data row is physical line 4; got source_row={items[0].source_row}"
        )


class TestCsvCodeBoundarySplitting:
    """Concatenated competence codes in CSV cells must be split into separate items."""

    def test_concatenated_codes_split_into_multiple_items(self, tmp_path: Path) -> None:
        """Cell with 'A.1: desc A.3: other' must produce two evidence items."""
        from run_full_analysis import _collect_supply_from_microcredentials_csv
        import run_full_analysis as rfa

        # Cell contains two coded items concatenated without a line break
        csv_content = (
            "# Row 1\n"
            "# Row 2\n"
            "Dimension,Blue Biotech\n"
            "A,A.1: Bioprospecting coastal A.3: Environmental impact assessment\n"
        )
        csv_file = tmp_path / "test_concat.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        orig_map = dict(rfa._CSV_SECTOR_MAP)
        orig_axis = dict(rfa._CSV_DIMENSION_AXIS)
        rfa._CSV_SECTOR_MAP = {"Blue Biotech": "Blue Biotech"}
        rfa._CSV_DIMENSION_AXIS = {"A": "OCEANIC"}
        try:
            supply = _collect_supply_from_microcredentials_csv(csv_file)
        finally:
            rfa._CSV_SECTOR_MAP = orig_map
            rfa._CSV_DIMENSION_AXIS = orig_axis

        items = supply.get("Blue Biotech", [])
        assert len(items) == 2, (
            f"Concatenated codes must produce 2 items; got {len(items)}: {[i.name for i in items]}"
        )

    def test_glued_codes_without_space_split_into_three_items(self, tmp_path: Path) -> None:
        """Cell with codes glued directly to preceding word must produce three items.

        'A.1: Visa governance outreachA.2: Stakeholder consultation outreachA.3: Monitoring practice'
        must yield three separate GapEvidence items (no space before A.2: and A.3:).
        """
        from run_full_analysis import _collect_supply_from_microcredentials_csv
        import run_full_analysis as rfa

        # No space before A.2: or A.3: — the word boundary \b regex would fail here
        glued_cell = (
            "A.1: Visa governance outreachA.2: "
            "Stakeholder consultation outreachA.3: Monitoring practice"
        )
        csv_content = (
            "# Row 1\n"
            "# Row 2\n"
            f"Dimension,Blue Biotech\n"
            f"A,{glued_cell}\n"
        )
        csv_file = tmp_path / "test_glued.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        orig_map = dict(rfa._CSV_SECTOR_MAP)
        orig_axis = dict(rfa._CSV_DIMENSION_AXIS)
        rfa._CSV_SECTOR_MAP = {"Blue Biotech": "Blue Biotech"}
        rfa._CSV_DIMENSION_AXIS = {"A": "OCEANIC"}
        try:
            supply = _collect_supply_from_microcredentials_csv(csv_file)
        finally:
            rfa._CSV_SECTOR_MAP = orig_map
            rfa._CSV_DIMENSION_AXIS = orig_axis

        items = supply.get("Blue Biotech", [])
        assert len(items) == 3, (
            f"Glued codes must produce 3 items; got {len(items)}: {[i.name for i in items]}"
        )
        names = [i.name for i in items]
        assert any("Visa governance" in n for n in names), (
            f"First item must contain 'Visa governance'; got {names}"
        )
        assert any("Stakeholder consultation" in n for n in names), (
            f"Second item must contain 'Stakeholder consultation'; got {names}"
        )
        assert any("Monitoring practice" in n for n in names), (
            f"Third item must contain 'Monitoring practice'; got {names}"
        )


class TestCsvDynamicHeaderDetection:
    """Header row must be located dynamically, not assumed to be at a fixed index."""

    def test_header_at_index_zero_is_found(self, tmp_path: Path) -> None:
        """CSV with no preamble rows must still parse correctly."""
        from run_full_analysis import _collect_supply_from_microcredentials_csv
        import run_full_analysis as rfa

        csv_content = (
            "Dimension,Blue Biotech\n"
            "A,Bioprospecting techniques\n"
        )
        csv_file = tmp_path / "test_no_preamble.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        orig_map = dict(rfa._CSV_SECTOR_MAP)
        orig_axis = dict(rfa._CSV_DIMENSION_AXIS)
        rfa._CSV_SECTOR_MAP = {"Blue Biotech": "Blue Biotech"}
        rfa._CSV_DIMENSION_AXIS = {"A": "OCEANIC"}
        try:
            supply = _collect_supply_from_microcredentials_csv(csv_file)
        finally:
            rfa._CSV_SECTOR_MAP = orig_map
            rfa._CSV_DIMENSION_AXIS = orig_axis

        items = supply.get("Blue Biotech", [])
        assert items, "CSV with header at row 0 must produce supply items"
        assert items[0].source_row == 2, (
            f"Data row is physical line 2; got source_row={items[0].source_row}"
        )

    def test_header_shifted_by_extra_intro_row(self, tmp_path: Path) -> None:
        """CSV with an extra introductory row must still detect the header."""
        from run_full_analysis import _collect_supply_from_microcredentials_csv
        import run_full_analysis as rfa

        # Three intro rows before the header (shifted by one vs the real CSV)
        csv_content = (
            "# Row 1\n"
            "# Row 2\n"
            "# Extra intro row\n"
            "Dimension,Blue Biotech\n"
            "A,Bioprospecting techniques\n"
        )
        csv_file = tmp_path / "test_shifted.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        orig_map = dict(rfa._CSV_SECTOR_MAP)
        orig_axis = dict(rfa._CSV_DIMENSION_AXIS)
        rfa._CSV_SECTOR_MAP = {"Blue Biotech": "Blue Biotech"}
        rfa._CSV_DIMENSION_AXIS = {"A": "OCEANIC"}
        try:
            supply = _collect_supply_from_microcredentials_csv(csv_file)
        finally:
            rfa._CSV_SECTOR_MAP = orig_map
            rfa._CSV_DIMENSION_AXIS = orig_axis

        items = supply.get("Blue Biotech", [])
        assert items, "CSV with shifted header must still produce supply items"
        assert items[0].source_row == 5, (
            f"Data row is physical line 5; got source_row={items[0].source_row}"
        )

    def test_no_dimension_header_returns_empty(self, tmp_path: Path) -> None:
        """CSV without a 'Dimension' header row must return empty supply."""
        from run_full_analysis import _collect_supply_from_microcredentials_csv
        import run_full_analysis as rfa

        csv_content = (
            "Category,Blue Biotech\n"
            "A,Bioprospecting techniques\n"
        )
        csv_file = tmp_path / "test_no_dim_header.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        orig_map = dict(rfa._CSV_SECTOR_MAP)
        rfa._CSV_SECTOR_MAP = {"Blue Biotech": "Blue Biotech"}
        try:
            supply = _collect_supply_from_microcredentials_csv(csv_file)
        finally:
            rfa._CSV_SECTOR_MAP = orig_map

        assert supply == {}, "CSV without 'Dimension' header must return empty dict"

    def test_bom_header_is_detected(self, tmp_path: Path) -> None:
        """CSV whose first cell carries a UTF-8 BOM must still detect the header."""
        from run_full_analysis import _collect_supply_from_microcredentials_csv
        import run_full_analysis as rfa

        # Write file with a UTF-8 BOM prefix so the first cell becomes
        # "\ufeffDimension" when read with plain encoding="utf-8".
        # Using encoding="utf-8-sig" (our fix) strips the BOM automatically.
        csv_content = "\ufeffDimension,Blue Biotech\nA,Bioprospecting techniques\n"
        csv_file = tmp_path / "test_bom.csv"
        csv_file.write_bytes(csv_content.encode("utf-8"))

        orig_map = dict(rfa._CSV_SECTOR_MAP)
        orig_axis = dict(rfa._CSV_DIMENSION_AXIS)
        rfa._CSV_SECTOR_MAP = {"Blue Biotech": "Blue Biotech"}
        rfa._CSV_DIMENSION_AXIS = {"A": "OCEANIC"}
        try:
            supply = _collect_supply_from_microcredentials_csv(csv_file)
        finally:
            rfa._CSV_SECTOR_MAP = orig_map
            rfa._CSV_DIMENSION_AXIS = orig_axis

        items = supply.get("Blue Biotech", [])
        assert items, "CSV with BOM header must produce supply items"
        assert items[0].source_row == 2, (
            f"Data row is physical line 2; got source_row={items[0].source_row}"
        )


class TestItemLevelMatchProvenance:
    """GapEvidence match provenance fields must be populated when items are covered."""

    def _make_demand(self, comp_id: str, name: str, axis: str = "MARINE") -> GapEvidence:
        return GapEvidence(
            competence_id=comp_id,
            name=name,
            description="demand",
            sector="Blue Biotech",
            qmbd_axis=axis,
            origin="static_literature",
            source_file="f.csv",
            source_row=1,
            provider="crossref",
            doi="",
            title=name,
            year="2023",
            confidence_score=0.9,
            overlap_status="demand_only",
        )

    def _make_supply(self, comp_id: str, name: str, axis: str = "MARINE") -> GapEvidence:
        return GapEvidence(
            competence_id=comp_id,
            name=name,
            description="supply",
            sector="Blue Biotech",
            qmbd_axis=axis,
            origin="static_baseline",
            source_file="g.csv",
            source_row=2,
            provider="baseline",
            doi="",
            title=name,
            year="2022",
            confidence_score=0.95,
            overlap_status="supply_only",
        )

    def test_exact_id_match_provenance_set(self) -> None:
        """Exact-ID covered demand items must have match_method='exact_id' and score 1.0."""
        demand = self._make_demand("shared_id", "Marine ecology monitoring")
        supply = self._make_supply("shared_id", "Marine ecology monitoring")
        result = compute_gap_model(
            {"Blue Biotech": [demand]},
            {"Blue Biotech": [supply]},
            qmbd_axes=["MARINE"],
        )
        covered = [
            i for i in result.all_clusters[0].demand_items
            if i.overlap_status == "covered"
        ]
        assert len(covered) == 1
        item = covered[0]
        assert item.match_method == "exact_id"
        assert item.match_score == 1.0
        assert item.matched_supply_id == "shared_id"
        assert item.matched_supply_origin == "static_baseline"

    def test_name_similarity_match_provenance_set(self) -> None:
        """Name-similarity covered items must store match_method, score, and supply ID."""
        demand = self._make_demand("d1", "underwater acoustic sensing monitoring techniques")
        supply = self._make_supply("s1", "acoustic underwater monitoring sensing systems")
        result = compute_gap_model(
            {"Blue Biotech": [demand]},
            {"Blue Biotech": [supply]},
            qmbd_axes=["MARINE"],
        )
        covered = [
            i for i in result.all_clusters[0].demand_items
            if i.overlap_status == "covered"
        ]
        assert len(covered) == 1
        item = covered[0]
        assert item.match_method == "name_similarity"
        assert item.match_score is not None and 0.0 < item.match_score <= 1.0
        assert item.matched_supply_id == "s1"
        assert item.matched_supply_origin == "static_baseline"

    def test_unmatched_demand_has_no_provenance(self) -> None:
        """Demand items with no supply coverage must have None provenance fields."""
        demand = self._make_demand("d_only", "Unique niche competence with no overlap")
        result = compute_gap_model(
            {"Blue Biotech": [demand]},
            {},
            qmbd_axes=["MARINE"],
        )
        missing = result.all_clusters[0].missing_items
        assert len(missing) == 1
        item = missing[0]
        assert item.match_method is None
        assert item.match_score is None
        assert item.matched_supply_id is None
        assert item.matched_supply_origin is None

    def test_stale_match_provenance_cleared_on_second_pass(self) -> None:
        """Reused demand GapEvidence must not retain match fields from a prior pass."""
        demand = self._make_demand("d_reuse", "Marine ecology monitoring")
        supply = self._make_supply("d_reuse", "Marine ecology monitoring")

        # First call: demand is covered; match fields must be populated.
        compute_gap_model(
            {"Blue Biotech": [demand]},
            {"Blue Biotech": [supply]},
            qmbd_axes=["MARINE"],
        )
        assert demand.overlap_status == "covered"
        assert demand.match_method == "exact_id"

        # Second call: no supply provided; demand must become 'demand_only' and
        # all match-provenance fields must be cleared (not retain stale values).
        compute_gap_model(
            {"Blue Biotech": [demand]},
            {},
            qmbd_axes=["MARINE"],
        )
        assert demand.overlap_status == "demand_only"
        assert demand.matched_supply_id is None
        assert demand.matched_supply_origin is None
        assert demand.match_method is None
        assert demand.match_score is None


# ---------------------------------------------------------------------------
# Tests: _stem_token / _name_tokens morphological normalisation
# ---------------------------------------------------------------------------


class TestStemToken:
    """Unit tests for the lightweight suffix-stripping stemmer."""

    def test_digitalisation_stems_to_digital(self) -> None:
        from src.gap_model import _stem_token
        # "digitalisation" → strip "-isation" → "digital" (≥4 chars)
        assert _stem_token("digitalisation") == "digital"

    def test_digitalization_stems_to_digital(self) -> None:
        from src.gap_model import _stem_token
        # "digitalization" → strip "-ization" → "digital" (≥4 chars)
        assert _stem_token("digitalization") == "digital"

    def test_fisheries_stems_to_fish(self) -> None:
        from src.gap_model import _stem_token
        # "fisheries" → strip "-eries" → "fish" (≥4 chars)
        assert _stem_token("fisheries") == "fish"

    def test_governance_strips_nothing_useful(self) -> None:
        from src.gap_model import _stem_token
        # "governance" has no matching suffix; returned unchanged
        result = _stem_token("governance")
        # The word doesn't match any suffix long enough to yield ≥4 stem chars
        # that would still be accepted; check it returns a non-empty string.
        assert isinstance(result, str) and len(result) >= 4

    def test_monitoring_stems_to_monitor(self) -> None:
        from src.gap_model import _stem_token
        # "monitoring" → strip "-ing" → "monitor" (≥4 chars)
        assert _stem_token("monitoring") == "monitor"

    def test_short_stem_guard_prevents_over_stripping(self) -> None:
        from src.gap_model import _stem_token
        # "ring" → strip "-ing" → "r" (< 4 chars) → no strip
        assert _stem_token("ring") == "ring"

    def test_ecological_stems_to_ecolog(self) -> None:
        from src.gap_model import _stem_token
        # "ecological" → strip "-ical" → "ecolog" (≥4 chars)
        assert _stem_token("ecological") == "ecolog"


class TestNameTokensStemming:
    """Tests that _name_tokens applies stemming to improve coverage matching."""

    def test_digitalization_and_digitalisation_share_stem(self) -> None:
        from src.gap_model import _name_tokens
        tokens_us = _name_tokens("digitalization of maritime transport")
        tokens_uk = _name_tokens("digitalisation of maritime transport")
        # Both should collapse to the same stem ("digital") for the key word
        assert tokens_us == tokens_uk, (
            f"Expected same stem set; got {tokens_us!r} vs {tokens_uk!r}"
        )

    def test_fisheries_and_fishery_stem_overlap(self) -> None:
        from src.gap_model import _name_tokens
        # "fisheries" stems to "fish"; "fishery" doesn't match a suffix cleanly
        # but the two token sets should share at least the "fish" stem from "fisheries"
        tokens_plural = _name_tokens("fisheries monitoring governance")
        assert "fish" in tokens_plural, (
            f"Expected 'fish' stem in {tokens_plural!r}"
        )

    def test_monitoring_and_monitored_overlap(self) -> None:
        from src.gap_model import _name_tokens
        tokens_a = _name_tokens("environmental monitoring systems")
        tokens_b = _name_tokens("environmental monitored approach")
        # Both should include the "monitor" stem
        assert "monitor" in tokens_a
        # "monitored" → strip "-ed" only if stem ≥4: "monitore" — but actually
        # "monitored" ends with "ed", stem = "monitor" (7 chars ≥ 4) → "monitor"
        assert "monitor" in tokens_b


class TestJaccardMorphologicalCoverage:
    """Integration tests for morphological Jaccard matching via compute_gap_model."""

    def _make_evidence(
        self,
        competence_id: str,
        name: str,
        sector: str = "Blue Biotech",
        axis: str = "MARINE",
        origin: str = "static_literature",
    ) -> GapEvidence:
        return GapEvidence(
            competence_id=competence_id,
            name=name,
            description="Test",
            sector=sector,
            qmbd_axis=axis,
            origin=origin,
            source_file="data/derived/test.csv",
            source_row=1,
            provider="crossref",
            doi="10.1234/test",
            title="Test paper",
            year="2023",
            confidence_score=0.8,
            overlap_status="demand_only",
        )

    def test_digitalization_covers_digitalisation(self) -> None:
        """Stemming must allow "digitalization" supply to cover "digitalisation" demand."""
        demand = self._make_evidence("d1", "digitalisation of maritime transport competences")
        supply = self._make_evidence("s1", "digitalization maritime transport competences")
        result = compute_gap_model(
            {"Blue Biotech": [demand]},
            {"Blue Biotech": [supply]},
            qmbd_axes=["MARINE"],
        )
        cluster = result.all_clusters[0]
        covered = [i for i in cluster.demand_items if i.overlap_status == "covered"]
        assert len(covered) == 1, (
            "digitalization (supply) should cover digitalisation (demand) after stemming"
        )

    def test_fisheries_monitoring_coverage(self) -> None:
        """Stemming must allow "fisheries" to match "fishery" context tokens."""
        demand = self._make_evidence("d2", "fisheries monitoring ecological assessment")
        supply = self._make_evidence("s2", "fisheries ecological monitoring evaluation")
        result = compute_gap_model(
            {"Blue Biotech": [demand]},
            {"Blue Biotech": [supply]},
            qmbd_axes=["MARINE"],
        )
        cluster = result.all_clusters[0]
        covered = [i for i in cluster.demand_items if i.overlap_status == "covered"]
        assert len(covered) == 1


# ---------------------------------------------------------------------------
# Tests: compute_priority_score with configurable weights
# ---------------------------------------------------------------------------


class TestConfigurableWeights:
    """Tests for the weights parameter in compute_priority_score."""

    def _make_cluster(
        self,
        *,
        gap_ratio: float = 0.5,
        missing_count: int = 1,
        demand_count: int = 2,
        axis: str = "MARINE",
        sector: str = "Blue Biotech",
        confidence: float = 0.8,
    ) -> GapCluster:
        demand_items = [
            GapEvidence(
                competence_id=f"d{i}",
                name=f"Demand {i}",
                description="Test",
                sector=sector,
                qmbd_axis=axis,
                origin="static_literature",
                source_file="data/derived/test.csv",
                source_row=i,
                provider="crossref",
                doi=f"10.1234/d{i}",
                title=f"Paper {i}",
                year="2023",
                confidence_score=confidence,
                overlap_status="demand_only",
            )
            for i in range(demand_count)
        ]
        missing_items = demand_items[:missing_count]
        return GapCluster(
            sector=sector,
            qmbd_axis=axis,
            demand_items=demand_items,
            supply_items=[],
            missing_items=missing_items,
            coverage_method="uncovered" if missing_count == demand_count else "mixed",
        )

    def test_default_weights_produce_same_result_as_original(self) -> None:
        """Calling with weights=None must be equivalent to calling with 7 equal weights."""
        cluster = self._make_cluster()
        all_clusters = [cluster]
        score_default = compute_priority_score(cluster, all_clusters)
        score_equal = compute_priority_score(
            cluster,
            all_clusters,
            weights={
                "gap_ratio": 1.0,
                "missing_count_normalized": 1.0,
                "evidence_frequency": 1.0,
                "recency": 1.0,
                "provider_confidence": 1.0,
                "multi_source_support": 1.0,
                "qmbd_axis_undercoverage": 1.0,
            },
        )
        assert abs(score_default - score_equal) < 1e-9

    def test_zero_weight_factor_excluded_from_score(self) -> None:
        """A factor with weight=0 must have no effect on the score."""
        cluster_a = self._make_cluster(confidence=0.9)
        cluster_b = self._make_cluster(confidence=0.1)
        all_clusters = [cluster_a, cluster_b]

        # With provider_confidence weight=0, the confidence difference should vanish
        w = {k: 1.0 for k in (
            "gap_ratio", "missing_count_normalized", "evidence_frequency",
            "recency", "multi_source_support", "qmbd_axis_undercoverage"
        )}
        w["provider_confidence"] = 0.0
        score_a = compute_priority_score(cluster_a, all_clusters, weights=w)
        score_b = compute_priority_score(cluster_b, all_clusters, weights=w)
        assert abs(score_a - score_b) < 1e-9, (
            "Zeroing provider_confidence weight should make scores equal when only confidence differs"
        )

    def test_high_gap_ratio_weight_amplifies_score(self) -> None:
        """Doubling gap_ratio weight must raise score for a high-gap cluster relative to equal weights."""
        full_gap = self._make_cluster(gap_ratio=1.0, missing_count=2, demand_count=2)
        no_gap = self._make_cluster(gap_ratio=0.0, missing_count=0, demand_count=2)
        all_clusters = [full_gap, no_gap]

        score_full_default = compute_priority_score(full_gap, all_clusters)
        score_full_boosted = compute_priority_score(
            full_gap, all_clusters, weights={"gap_ratio": 10.0}
        )
        score_no_default = compute_priority_score(no_gap, all_clusters)
        score_no_boosted = compute_priority_score(
            no_gap, all_clusters, weights={"gap_ratio": 10.0}
        )

        # Boosting gap_ratio weight must widen the gap between full-gap and no-gap clusters
        diff_default = score_full_default - score_no_default
        diff_boosted = score_full_boosted - score_no_boosted
        assert diff_boosted > diff_default, (
            "Boosting gap_ratio weight must increase the score differential"
        )

    def test_weights_normalised_regardless_of_magnitude(self) -> None:
        """Scaling all weights by the same constant must not change the score."""
        cluster = self._make_cluster()
        all_clusters = [cluster]
        equal = {k: 1.0 for k in (
            "gap_ratio", "missing_count_normalized", "evidence_frequency",
            "recency", "provider_confidence", "multi_source_support", "qmbd_axis_undercoverage"
        )}
        scaled = {k: 100.0 for k in equal}
        score_equal = compute_priority_score(cluster, all_clusters, weights=equal)
        score_scaled = compute_priority_score(cluster, all_clusters, weights=scaled)
        assert abs(score_equal - score_scaled) < 1e-9

    def test_unknown_weight_keys_ignored(self) -> None:
        """Unknown weight keys must be silently ignored; known keys work normally."""
        cluster = self._make_cluster()
        all_clusters = [cluster]
        score_default = compute_priority_score(cluster, all_clusters)
        score_with_unknown = compute_priority_score(
            cluster, all_clusters, weights={"gap_ratio": 1.0, "nonexistent_factor": 99.0}
        )
        # "nonexistent_factor" is ignored; "gap_ratio"=1.0 and remaining keys
        # each default to 1.0, so the result should equal the default score.
        assert abs(score_default - score_with_unknown) < 1e-9
