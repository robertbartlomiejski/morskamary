"""
Test suite for the full analysis pipeline (run_full_analysis.py)
and real-data integration (load_real_competences.py, main_real_data.py).

These tests validate end-to-end functionality with real data files.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

# Ensure repo root is on the path so imports work
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core import BlueDynamicsAxis, CompetenceLevel, MicroCredential  # noqa: E402
from src.competence_mapper import CompetenceMapper  # noqa: E402, F401
from load_real_competences import load_blue_competences, map_dimension_to_axis  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASELINE_CSV = (
    REPO_ROOT
    / "data"
    / "derived"
    / "Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv"
)


@pytest.fixture
def baseline_csv_path():
    """Return path to baseline CSV, skip if missing."""
    if not BASELINE_CSV.exists():
        pytest.skip("Baseline CSV not available")
    return BASELINE_CSV


@pytest.fixture
def loaded_mapper(baseline_csv_path):
    """Load real data into a CompetenceMapper."""
    return load_blue_competences(baseline_csv_path)


# ---------------------------------------------------------------------------
# 1. Dimension-to-axis mapping
# ---------------------------------------------------------------------------


class TestDimensionMapping:
    """Tests for dimension → TMBD axis mapping."""

    def test_dimension_a_maps_to_oceanic(self):
        assert map_dimension_to_axis("A") == BlueDynamicsAxis.OCEANIC

    def test_dimension_b_maps_to_maritime(self):
        assert map_dimension_to_axis("B") == BlueDynamicsAxis.MARITIME

    def test_dimension_c_maps_to_marine(self):
        assert map_dimension_to_axis("C") == BlueDynamicsAxis.MARINE

    def test_dimension_d_maps_to_maritime(self):
        assert map_dimension_to_axis("D") == BlueDynamicsAxis.MARITIME

    def test_dimension_id_format(self):
        """Test mapping with full ID format (e.g., 'A.1')."""
        assert map_dimension_to_axis("A.1") == BlueDynamicsAxis.OCEANIC
        assert map_dimension_to_axis("B.3") == BlueDynamicsAxis.MARITIME
        assert map_dimension_to_axis("C.2") == BlueDynamicsAxis.MARINE

    def test_unknown_dimension_defaults_to_oceanic(self):
        assert map_dimension_to_axis("Z") == BlueDynamicsAxis.OCEANIC


# ---------------------------------------------------------------------------
# 2. Real data loading
# ---------------------------------------------------------------------------


class TestRealDataLoading:
    """Tests for loading real CSV baseline data."""

    def test_loads_competences(self, loaded_mapper):
        """Baseline CSV should load at least 15 competences."""
        total = len(loaded_mapper.competences)
        assert total >= 15, f"Expected ≥15 competences, got {total}"

    def test_axis_distribution(self, loaded_mapper):
        """Check the TMBD axis distribution matches expected counts."""
        marine = len(loaded_mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE))
        maritime = len(loaded_mapper.get_competences_by_axis(BlueDynamicsAxis.MARITIME))
        oceanic = len(loaded_mapper.get_competences_by_axis(BlueDynamicsAxis.OCEANIC))
        assert marine >= 3, f"Expected ≥3 MARINE, got {marine}"
        assert maritime >= 4, f"Expected ≥4 MARITIME, got {maritime}"
        assert oceanic >= 3, f"Expected ≥3 OCEANIC, got {oceanic}"

    def test_competence_ids_are_unique(self, loaded_mapper):
        """All competence IDs must be unique."""
        ids = list(loaded_mapper.competences.keys())
        assert len(ids) == len(set(ids))

    def test_competence_has_required_fields(self, loaded_mapper):
        """Each competence must have non-empty id, name, description, axis."""
        for comp in loaded_mapper.competences.values():
            assert comp.id, "Competence missing id"
            assert comp.name, "Competence missing name"
            assert comp.description, "Competence missing description"
            assert isinstance(comp.axis, BlueDynamicsAxis)
            assert isinstance(comp.level, CompetenceLevel)

    def test_competence_serialization(self, loaded_mapper):
        """to_dict() should produce valid dictionaries."""
        for comp in loaded_mapper.competences.values():
            d = comp.to_dict()
            assert d["id"] == comp.id
            assert d["axis"] in ("M", "T", "O")
            assert d["level"] in ("FOUNDATIONAL", "INTERMEDIATE", "ADVANCED", "EXPERT")
            break  # one is enough

    def test_all_levels_are_intermediate(self, loaded_mapper):
        """Baseline data sets all competences to INTERMEDIATE level."""
        for comp in loaded_mapper.competences.values():
            assert comp.level == CompetenceLevel.INTERMEDIATE


# ---------------------------------------------------------------------------
# 3. Gap analysis with real data
# ---------------------------------------------------------------------------


class TestGapAnalysis:
    """Tests for gap analysis functionality with real data."""

    def test_gap_analysis_returns_correct_keys(self, loaded_mapper):
        """Gap analysis result must have 'available', 'missing', 'by_level'."""
        # Create a credential first
        marine_ids = [
            c.id
            for c in loaded_mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)[:2]
        ]
        cred = MicroCredential(
            id="test_cred",
            title="Test",
            competences=marine_ids,
            description="Test",
            sector="test-sector",
        )
        loaded_mapper.add_credentials(cred)

        gaps = loaded_mapper.analyze_competence_gaps(
            available=[marine_ids[0]] if marine_ids else [],
            required_sector="test-sector",
        )
        assert "available" in gaps
        assert "missing" in gaps
        assert "by_level" in gaps

    def test_gap_analysis_math(self, loaded_mapper):
        """Available + missing should equal total required."""
        marine_ids = [
            c.id for c in loaded_mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)
        ]
        maritime_ids = [
            c.id
            for c in loaded_mapper.get_competences_by_axis(BlueDynamicsAxis.MARITIME)[
                :2
            ]
        ]
        all_ids = marine_ids + maritime_ids

        cred = MicroCredential(
            id="test_cred2",
            title="Test2",
            competences=all_ids,
            description="Test",
            sector="gap-test-sector",
        )
        loaded_mapper.add_credentials(cred)

        gaps = loaded_mapper.analyze_competence_gaps(
            available=marine_ids,
            required_sector="gap-test-sector",
        )
        total_required = len(set(all_ids))
        total_result = len(gaps["available"]) + len(gaps["missing"])
        assert total_result == total_required


# ---------------------------------------------------------------------------
# 4. Credential pathway
# ---------------------------------------------------------------------------


class TestCredentialPathway:
    """Tests for credential pathway suggestions."""

    def test_pathway_returns_sorted_credentials(self, loaded_mapper):
        """Pathway should return credentials sorted by average level."""
        marine = [
            c.id
            for c in loaded_mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)[:2]
        ]
        oceanic = [
            c.id
            for c in loaded_mapper.get_competences_by_axis(BlueDynamicsAxis.OCEANIC)[:2]
        ]

        cred1 = MicroCredential(
            id="path_cred1",
            title="Foundation",
            competences=marine,
            description="Foundation credential",
            sector="pathway-test",
        )
        cred2 = MicroCredential(
            id="path_cred2",
            title="Advanced",
            competences=oceanic,
            description="Advanced credential",
            sector="pathway-test",
        )
        loaded_mapper.add_credentials(cred1)
        loaded_mapper.add_credentials(cred2)

        pathway = loaded_mapper.suggest_credential_pathway()
        assert len(pathway) >= 2
        assert all(isinstance(c, MicroCredential) for c in pathway)


# ---------------------------------------------------------------------------
# 5. Summary statistics
# ---------------------------------------------------------------------------


class TestSummary:
    """Tests for mapper summary with real data."""

    def test_summary_has_required_keys(self, loaded_mapper):
        summary = loaded_mapper.get_summary()
        assert "total_competences" in summary
        assert "total_credentials" in summary
        assert "competences_by_axis" in summary
        assert "competences_by_level" in summary
        assert "sectors" in summary

    def test_summary_axis_counts_sum_to_total(self, loaded_mapper):
        summary = loaded_mapper.get_summary()
        axis_sum = sum(summary["competences_by_axis"].values())
        assert axis_sum == summary["total_competences"]


# ---------------------------------------------------------------------------
# 6. run_full_analysis.py output validation
# ---------------------------------------------------------------------------

OUTPUTS_DIR = REPO_ROOT / "outputs"


class TestFullAnalysisOutputs:
    """Tests validating that run_full_analysis.py outputs are present and valid."""

    @pytest.fixture(autouse=True)
    def check_outputs_exist(self):
        """Skip if outputs haven't been generated."""
        if not (OUTPUTS_DIR / "competences_full_database.json").exists():
            pytest.skip("Output files not generated; run: python run_full_analysis.py")

    def test_competences_json_structure(self):
        path = OUTPUTS_DIR / "competences_full_database.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "metadata" in data
        assert "baseline" in data
        assert "literature" in data
        assert data["metadata"]["total"] > 0
        assert data["metadata"]["baseline_count"] >= 15
        assert data["metadata"]["literature_count"] > 0

    def test_competences_json_baseline_records(self):
        path = OUTPUTS_DIR / "competences_full_database.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for rec in data["baseline"]:
            assert "id" in rec
            assert "name" in rec
            assert "axis" in rec
            assert rec["axis"] in ("M", "T", "O")
            assert "source" in rec
            assert "github_url" in rec["source"]

    def test_credentials_json_structure(self):
        path = OUTPUTS_DIR / "credentials_database.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["metadata"]["total"] == 48  # 12 sectors × 4 EQF levels
        assert data["metadata"]["sectors"] == 12
        for cred in data["credentials"]:
            assert "id" in cred
            assert "title" in cred
            assert "eqf_level" in cred
            assert cred["eqf_level"] in (4, 5, 6, 7)
            assert "ects" in cred
            assert "learning_outcomes" in cred
            assert "stackability_rules" in cred

    def test_gaps_summary_csv(self):
        path = OUTPUTS_DIR / "gaps_summary.csv"
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 12  # 12 sectors
        for row in rows:
            assert "Sector" in row
            assert "Required" in row
            assert "Gap %" in row
            assert float(row["Gap %"]) >= 0

    def test_sector_pathways_json(self):
        path = OUTPUTS_DIR / "sector_pathways.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["metadata"]["total_pathways"] == 132  # 12×11
        assert len(data["pathways"]) == 132

    def test_html_reports_exist(self):
        for fname in [
            "report_index.html",
            "gaps_by_sector.html",
            "credentials_matrix.html",
            "literature_integration.html",
        ]:
            path = OUTPUTS_DIR / fname
            assert path.exists(), f"Missing HTML report: {fname}"
            content = path.read_text(encoding="utf-8")
            assert "<html" in content
            assert "Blue" in content

    def test_report_index_has_dashboard(self):
        path = OUTPUTS_DIR / "report_index.html"
        content = path.read_text(encoding="utf-8")
        assert "Competences" in content
        assert "Credentials" in content
        assert "Sectors" in content


# ---------------------------------------------------------------------------
# 7. CSV baseline file validation
# ---------------------------------------------------------------------------


class TestBaselineCSV:
    """Tests validating the baseline CSV file itself."""

    def test_csv_exists(self, baseline_csv_path):
        assert baseline_csv_path.exists()

    def test_csv_has_expected_columns(self, baseline_csv_path):
        with open(baseline_csv_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert len(header) >= 4
        # First 4 columns: Dimension, ID, Competence Name, Key Focus
        assert "ID" in header[1] or header[1].strip() == "ID"

    def test_csv_has_sector_columns(self, baseline_csv_path):
        with open(baseline_csv_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        # Expect 12 sector columns after the first 4
        sector_cols = header[4:]
        assert (
            len(sector_cols) >= 10
        ), f"Expected ≥10 sector columns, got {len(sector_cols)}"
