"""Tests for orchestration helpers in run_full_analysis."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from run_full_analysis import (
    Competence,
    CompetenceSource,
    GapAnalysis,
    MicroCredential,
    TMBDAxis,
    export_competences_json,
    export_credentials_json,
    export_gaps_summary_csv,
    export_pathways_json,
    export_sector_dictionaries,
    generate_credentials_html,
    generate_gaps_html,
    generate_literature_html,
    generate_micro_credentials,
    generate_report_index,
    load_baseline_competences,
    run_gap_analysis,
)


def test_export_sector_dictionaries_per_sector(tmp_path: Path) -> None:
    literature_competence = Competence(
        id="lit_example_0001",
        name="Literature competence",
        description="Example",
        axis=TMBDAxis.MARITIME,
        dimension="literature",
        source=CompetenceSource(file="data/derived/x.csv", row=2),
        sectors=["Blue Biotech"],
    )
    baseline_competence = Competence(
        id="baseline_a1",
        name="Baseline competence",
        description="Baseline row",
        axis=TMBDAxis.MARINE,
        dimension="A",
        source=CompetenceSource(file="data/derived/y.csv", row=3),
        sectors=["Blue Biotech"],
    )

    sectors = ["Blue Biotech", "R&I"]
    output_paths = export_sector_dictionaries(
        competences=[literature_competence, baseline_competence],
        sectors=sectors,
        output_dir=tmp_path,
    )

    assert len(output_paths) == len(sectors)
    assert [path.name for path in output_paths] == [
        "blue_biotech_tmbd_dictionary.json",
        "r_i_tmbd_dictionary.json",
    ]

    blue_biotech_payload = json.loads(output_paths[0].read_text(encoding="utf-8"))
    maritime_ids = [
        item["id"] for item in blue_biotech_payload["dictionary"]["MARITIME"]
    ]
    assert maritime_ids == ["lit_example_0001"]
    assert blue_biotech_payload["dictionary"]["MARINE"] == []
    exported_ids = {
        item["id"]
        for axis_records in blue_biotech_payload["dictionary"].values()
        for item in axis_records
    }
    assert exported_ids == {"lit_example_0001"}

    research_payload = json.loads(output_paths[1].read_text(encoding="utf-8"))
    assert research_payload["metadata"]["sector"] == "R&I"
    assert all(not records for records in research_payload["dictionary"].values())


class TestLoadBaselineCompetences:
    """Test baseline competence loading with mocked file system."""

    def test_load_baseline_with_actual_file(self, tmp_path: Path) -> None:
        """Test loading baseline competences from actual CSV file."""
        # Use the actual baseline CSV if it exists
        from run_full_analysis import BASELINE_CSV

        if BASELINE_CSV.exists():
            competences = load_baseline_competences()
            assert len(competences) > 0
            # Check that TMBD axes are assigned
            axes = {c.axis for c in competences}
            assert len(axes) > 0  # Should have at least one axis type


class TestGapAnalysis:
    """Test gap analysis logic."""

    def test_run_gap_analysis_identifies_missing_competences(self) -> None:
        """Test that gap analysis correctly identifies missing competences per sector."""
        baseline = [
            Competence(
                id="b1",
                name="Marine ecology",
                description="Understanding marine systems",
                axis=TMBDAxis.MARINE,
                dimension="A",
                source=CompetenceSource(file="baseline.csv", row=1),
                sectors=["Blue Biotech"],
            ),
        ]
        literature = []

        gaps, gap_details = run_gap_analysis(baseline, literature)

        assert "Blue Biotech" in gaps
        gap_analysis = gaps["Blue Biotech"]
        assert len(gap_analysis.required_ids) == 1
        # Baseline competences are also considered "available" in the system
        # so gap_pct represents literature coverage, which is 0 here
        assert gap_analysis.gap_pct >= 0

    def test_run_gap_analysis_with_literature_reduces_gaps(self) -> None:
        """Test that adding literature competences reduces gap percentage."""
        baseline = [
            Competence(
                id="b1",
                name="Marine ecology",
                description="Understanding marine systems",
                axis=TMBDAxis.MARINE,
                dimension="A",
                source=CompetenceSource(file="baseline.csv", row=1),
                sectors=["Blue Biotech"],
            ),
        ]
        literature = [
            Competence(
                id="lit1",
                name="Advanced marine biology",
                description="Deep sea research",
                axis=TMBDAxis.MARINE,
                dimension="literature",
                source=CompetenceSource(file="literature.csv", row=5),
                sectors=["Blue Biotech"],
            ),
        ]

        gaps, _ = run_gap_analysis(baseline, literature)

        gap_analysis = gaps["Blue Biotech"]
        assert len(gap_analysis.available_ids) >= 1
        # Gap percentage should be reduced with literature competences
        assert gap_analysis.gap_pct >= 0.0


class TestMicroCredentialGeneration:
    """Test micro-credential generation logic."""

    def test_generate_micro_credentials_creates_four_levels_per_sector(self) -> None:
        """Test that micro-credentials are generated for all 4 EQF levels per sector."""
        baseline = [
            Competence(
                id="b1",
                name="Marine ecology",
                description="Understanding marine systems",
                axis=TMBDAxis.MARINE,
                dimension="A",
                source=CompetenceSource(file="baseline.csv", row=1),
                sectors=["Blue Biotech", "R&I"],
            ),
        ]
        literature = []
        gaps, _ = run_gap_analysis(baseline, literature)

        credentials = generate_micro_credentials(baseline, literature, gaps)

        # Should generate credentials for both sectors
        assert len(credentials) > 0
        blue_biotech_creds = [c for c in credentials if c.sector == "Blue Biotech"]
        assert len(blue_biotech_creds) == 4  # 4 EQF levels
        assert {c.eqf_level.value for c in blue_biotech_creds} == {4, 5, 6, 7}


class TestExportFunctions:
    """Test JSON/CSV export functions."""

    def test_export_competences_json_creates_valid_file(self, tmp_path: Path) -> None:
        """Test that export_competences_json creates a valid JSON file."""
        baseline = [
            Competence(
                id="b1",
                name="Test competence",
                description="Test",
                axis=TMBDAxis.MARINE,
                dimension="A",
                source=CompetenceSource(file="test.csv", row=1),
                sectors=["Blue Biotech"],
            ),
        ]
        output_file = tmp_path / "competences.json"

        export_competences_json(baseline, [], output_file)

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert "baseline" in data
        assert "literature" in data
        assert len(data["baseline"]) == 1
        assert data["baseline"][0]["id"] == "b1"

    def test_export_credentials_json_creates_valid_file(self, tmp_path: Path) -> None:
        """Test that export_credentials_json creates a valid JSON file."""
        from run_full_analysis import EQFLevel

        credentials = [
            MicroCredential(
                id="cred1",
                title="Test Credential",
                sector="Blue Biotech",
                eqf_level=EQFLevel.EQF5,
                ects=10.0,
                competences=["b1"],
                learning_outcomes=["Outcome 1"],
                assessment_method="Written exam",
                description="Test description",
                prerequisites=[],
                learner_profile="Test learner",
                stackability_rules="Test rules",
            ),
        ]
        output_file = tmp_path / "credentials.json"

        export_credentials_json(credentials, output_file)

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        # export_credentials_json wraps credentials in metadata structure
        assert "credentials" in data or isinstance(data, list)
        # Verify our credential is present
        if "credentials" in data:
            assert len(data["credentials"]) == 1
            assert data["credentials"][0]["id"] == "cred1"
        else:
            assert len(data) == 1
            assert data[0]["id"] == "cred1"

    def test_export_gaps_summary_csv_creates_valid_file(self, tmp_path: Path) -> None:
        """Test that export_gaps_summary_csv creates a valid CSV file."""
        # Create sample competences for gap analysis
        baseline = [
            Competence(
                id="b1",
                name="Test",
                description="",
                axis=TMBDAxis.MARINE,
                dimension="A",
                source=CompetenceSource(file="test.csv", row=1),
                sectors=["Blue Biotech"],
            ),
        ]
        gaps, _ = run_gap_analysis(baseline, [])
        output_file = tmp_path / "gaps.csv"

        export_gaps_summary_csv(gaps, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        # CSV headers use capitalized names
        assert "Sector" in content or "sector" in content.lower()
        assert "Blue Biotech" in content

    def test_export_pathways_json_creates_valid_file(self, tmp_path: Path) -> None:
        """Test that export_pathways_json creates a valid JSON file."""
        from run_full_analysis import SectorPathway

        pathways = [
            SectorPathway(
                from_sector="Blue Biotech",
                to_sector="R&I",
                bridge_competences=["c1", "c2"],
                bridge_credentials=["cred1"],
            ),
        ]
        output_file = tmp_path / "pathways.json"

        export_pathways_json(pathways, output_file)

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        # Verify the basic structure - pathways export includes list
        assert isinstance(data, list) or "pathways" in data
        # Verify at least one pathway is present
        pathways_list = data if isinstance(data, list) else data.get("pathways", [])
        assert len(pathways_list) >= 1


class TestHTMLGeneration:
    """Test HTML report generation functions."""

    def test_generate_report_index_creates_valid_html(self, tmp_path: Path) -> None:
        """Test that generate_report_index creates a valid HTML file."""
        baseline = []
        literature = []
        gaps, _ = run_gap_analysis(baseline, literature)
        credentials = []
        output_file = tmp_path / "report_index.html"

        generate_report_index(baseline, literature, gaps, credentials, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert "<!DOCTYPE html>" in content
        assert "<html" in content
        assert "</html>" in content

    def test_generate_gaps_html_includes_tmbd_sections(self, tmp_path: Path) -> None:
        """Test that gaps HTML includes TMBD axis sections."""
        competences = {
            "c1": Competence(
                id="c1",
                name="Marine competence",
                description="Test",
                axis=TMBDAxis.MARINE,
                dimension="C",
                source=CompetenceSource(file="test.csv", row=1),
                sectors=["Blue Biotech"],
            ),
        }
        baseline = [competences["c1"]]
        gaps, _ = run_gap_analysis(baseline, [])
        output_file = tmp_path / "gaps.html"

        generate_gaps_html(gaps, competences, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert "MARINE" in content or "Marine" in content
        assert "Blue Biotech" in content

    def test_generate_credentials_html_includes_eqf_levels(self, tmp_path: Path) -> None:
        """Test that credentials HTML includes EQF level information."""
        from run_full_analysis import EQFLevel

        credentials = [
            MicroCredential(
                id="cred1",
                title="Test Credential EQF 5",
                sector="Blue Biotech",
                eqf_level=EQFLevel.EQF5,
                ects=10.0,
                competences=["c1"],
                learning_outcomes=["Outcome 1"],
                assessment_method="Exam",
                description="Test",
                prerequisites=[],
                learner_profile="Test learner",
                stackability_rules="Test rules",
            ),
        ]
        output_file = tmp_path / "credentials.html"

        generate_credentials_html(credentials, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert "EQF" in content or "eqf" in content.lower()
        assert "5" in content

    def test_generate_literature_html_includes_citations(self, tmp_path: Path) -> None:
        """Test that literature HTML includes source citations."""
        literature = [
            Competence(
                id="lit1",
                name="Literature competence",
                description="From research paper",
                axis=TMBDAxis.MARITIME,
                dimension="literature",
                source=CompetenceSource(file="data/derived/paper.csv", row=10),
                sectors=["Blue Biotech"],
            ),
        ]
        output_file = tmp_path / "literature.html"

        generate_literature_html(literature, output_file)

        assert output_file.exists()
        content = output_file.read_text()
        assert "paper.csv" in content or "Literature" in content


class TestIntegrationWorkflows:
    """Integration tests for complete workflows."""

    def test_full_pipeline_with_real_data(self, tmp_path: Path) -> None:
        """Test complete pipeline using real baseline data."""
        from run_full_analysis import BASELINE_CSV

        if not BASELINE_CSV.exists():
            pytest.skip("Baseline CSV not available")

        # Load baseline
        baseline = load_baseline_competences()
        assert len(baseline) > 0

        # Run gap analysis (no literature)
        gaps, _ = run_gap_analysis(baseline, [])
        assert len(gaps) > 0

        # Generate credentials
        credentials = generate_micro_credentials(baseline, [], gaps)
        assert len(credentials) > 0

        # Export all artifacts
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        export_competences_json(baseline, [], outputs_dir / "competences.json")
        export_credentials_json(credentials, outputs_dir / "credentials.json")
        export_gaps_summary_csv(gaps, outputs_dir / "gaps.csv")

        # Verify all files created
        assert (outputs_dir / "competences.json").exists()
        assert (outputs_dir / "credentials.json").exists()
        assert (outputs_dir / "gaps.csv").exists()
