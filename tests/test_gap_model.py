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
import re
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

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
        """Supply evidence should include credentials_database.json items when the file exists."""
        # Build a minimal credentials_database.json
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

        # Patch REPO_ROOT and supply spec to point to tmp_path
        import run_full_analysis as rfa

        original_specs = rfa._SUPPLY_FILE_SPECS
        rfa._SUPPLY_FILE_SPECS = [
            {
                "path": str(db_path),
                "origin": "supply_file",
                "provider": "credentials_database",
            }
        ]
        # Also patch REPO_ROOT to resolve relative_to correctly
        import src.gap_model  # noqa: F401

        try:
            result = run_gap_model(baseline, literature)
            supply_bb = result.supply_evidence.get("Blue Biotech", [])
            supply_origins = {e.origin for e in supply_bb}
            assert "supply_file" in supply_origins, (
                "Supply evidence should contain supply_file items from credentials_database.json"
            )
        finally:
            rfa._SUPPLY_FILE_SPECS = original_specs

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
        sector = SECTORS[0]
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
