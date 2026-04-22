"""Tests for orchestration helpers in run_full_analysis."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from run_full_analysis import (
    Competence,
    CompetenceSource,
    EQFLevel,
    GapAnalysis,
    MicroCredential,
    TMBDAxis,
    export_sector_dictionaries,
    generate_micro_credentials,
    main,
    parse_cli_args,
    SECTORS,
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


def test_main_orchestration_success(tmp_path: Path) -> None:
    baseline_csv = tmp_path / "baseline.csv"
    baseline_csv.write_text("placeholder", encoding="utf-8")
    output_dir = tmp_path / "outputs"

    baseline = [
        Competence(
            id="baseline_a1",
            name="Baseline competence",
            description="Baseline row",
            axis=TMBDAxis.MARINE,
            dimension="A",
            source=CompetenceSource(file="data/derived/y.csv", row=3),
            sectors=["Blue Biotech"],
        )
    ]
    literature = [
        Competence(
            id="lit_example_0001",
            name="Literature competence",
            description="Example",
            axis=TMBDAxis.MARITIME,
            dimension="literature",
            source=CompetenceSource(file="data/derived/x.csv", row=2),
            sectors=["Blue Biotech"],
        )
    ]
    fake_gaps = {
        sector: GapAnalysis(
            sector=sector,
            required_ids=["baseline_a1", "lit_example_0001"],
            available_ids=["baseline_a1"],
            missing_ids=["lit_example_0001"],
            gap_pct=50.0,
            by_axis={"MARINE": [], "MARITIME": ["lit_example_0001"], "OCEANIC": []},
        )
        for sector in SECTORS
    }
    fake_credentials = [MagicMock()]
    fake_pathways = [MagicMock()]

    with (
        patch("run_full_analysis.BASELINE_CSV", baseline_csv),
        patch("run_full_analysis.OUTPUTS_DIR", output_dir),
        patch("run_full_analysis.load_baseline_competences", return_value=baseline) as m_load,
        patch(
            "run_full_analysis.extract_literature_competences", return_value=literature
        ) as m_extract,
        patch("run_full_analysis.run_gap_analysis", return_value=(fake_gaps, {})) as m_gaps,
        patch(
            "run_full_analysis.generate_micro_credentials",
            return_value=fake_credentials,
        ) as m_generate,
        patch(
            "run_full_analysis.compute_sector_pathways", return_value=fake_pathways
        ) as m_pathways,
        patch("run_full_analysis.export_competences_json"),
        patch("run_full_analysis.export_credentials_json"),
        patch("run_full_analysis.export_pathways_json"),
        patch("run_full_analysis.export_gaps_summary_csv"),
        patch("run_full_analysis.generate_report_index"),
        patch("run_full_analysis.generate_gaps_html"),
        patch("run_full_analysis.generate_credentials_html"),
        patch("run_full_analysis.generate_literature_html"),
        patch("run_full_analysis.LiteratureCompetenceRepository") as m_repo_cls,
        patch(
            "run_full_analysis.build_sector_dictionary_from_repository",
            return_value={"MARINE": [], "MARITIME": [], "OCEANIC": []},
        ) as m_build_dict,
        patch(
            "run_full_analysis.export_sector_dictionary",
            side_effect=lambda sector, grouped, output_dir: output_dir
            / f"{sector.lower().replace(' ', '_')}.json",
        ) as m_export_dict,
    ):
        exit_code = main()

    assert exit_code == 0
    m_load.assert_called_once_with()
    m_extract.assert_called_once_with()
    m_gaps.assert_called_once_with(baseline, literature)
    m_generate.assert_called_once_with(baseline, literature, fake_gaps)
    m_pathways.assert_called_once_with(fake_credentials, baseline)
    m_repo_cls.assert_called_once()
    assert m_build_dict.call_count == len(SECTORS)
    assert m_export_dict.call_count == len(SECTORS)


def test_generate_micro_credentials_missing_gaps_error() -> None:
    baseline = [
        Competence(
            id="baseline_a1",
            name="Baseline competence",
            description="Baseline row",
            axis=TMBDAxis.MARINE,
            dimension="A",
            source=CompetenceSource(file="data/derived/y.csv", row=3),
            sectors=["Blue Biotech"],
        )
    ]
    literature = [
        Competence(
            id="lit_example_0001",
            name="Literature competence",
            description="Example",
            axis=TMBDAxis.MARITIME,
            dimension="literature",
            source=CompetenceSource(file="data/derived/x.csv", row=2),
            sectors=["Blue Biotech"],
        )
    ]
    incomplete_gaps = {
        "Blue Biotech": GapAnalysis(
            sector="Blue Biotech",
            required_ids=["baseline_a1", "lit_example_0001"],
            available_ids=["baseline_a1"],
            missing_ids=["lit_example_0001"],
            gap_pct=50.0,
            by_axis={"MARINE": [], "MARITIME": ["lit_example_0001"], "OCEANIC": []},
        )
    }

    with pytest.raises(
        ValueError,
        match="Gap analysis missing sectors needed for credential generation",
    ) as exc_info:
        generate_micro_credentials(baseline, literature, incomplete_gaps)
    assert "Coastal Tourism" in str(exc_info.value)


def test_main_uses_selected_sectors_for_dictionary_export(tmp_path: Path) -> None:
    baseline_csv = tmp_path / "baseline.csv"
    baseline_csv.write_text("placeholder", encoding="utf-8")
    output_dir = tmp_path / "outputs"
    selected = ["Desalination"]
    baseline = [
        Competence(
            id="baseline_a1",
            name="Baseline competence",
            description="Baseline row",
            axis=TMBDAxis.MARINE,
            dimension="A",
            source=CompetenceSource(file="data/derived/y.csv", row=3),
            sectors=["Blue Biotech"],
        )
    ]
    literature = [
        Competence(
            id="lit_example_0001",
            name="Literature competence",
            description="Example",
            axis=TMBDAxis.MARITIME,
            dimension="literature",
            source=CompetenceSource(file="data/derived/x.csv", row=2),
            sectors=["Blue Biotech"],
        )
    ]

    with (
        patch("run_full_analysis.BASELINE_CSV", baseline_csv),
        patch("run_full_analysis.OUTPUTS_DIR", output_dir),
        patch("run_full_analysis.load_baseline_competences", return_value=baseline),
        patch("run_full_analysis.extract_literature_competences", return_value=literature),
        patch("run_full_analysis.run_gap_analysis", return_value=({}, {})),
        patch("run_full_analysis.generate_micro_credentials", return_value=[]),
        patch("run_full_analysis.compute_sector_pathways", return_value=[]),
        patch("run_full_analysis.export_competences_json"),
        patch("run_full_analysis.export_credentials_json"),
        patch("run_full_analysis.export_pathways_json"),
        patch("run_full_analysis.export_gaps_summary_csv"),
        patch("run_full_analysis.generate_report_index"),
        patch("run_full_analysis.generate_gaps_html"),
        patch("run_full_analysis.generate_credentials_html"),
        patch("run_full_analysis.generate_literature_html"),
        patch("run_full_analysis.export_sector_dictionaries", return_value=[]) as m_export,
    ):
        exit_code = main(selected_sectors=selected)

    assert exit_code == 0
    m_export.assert_called_once()
    assert m_export.call_args.kwargs["sectors"] == selected


def test_cli_argument_parsing() -> None:
    with patch("sys.argv", ["run_full_analysis.py", "--sector", "Desalination"]):
        args = parse_cli_args()
    with patch(
        "sys.argv",
        [
            "run_full_analysis.py",
            "--sector",
            "Desalination",
            "--sector",
            "Blue Biotech",
        ],
    ):
        multi_args = parse_cli_args()
    with patch("sys.argv", ["run_full_analysis.py"]):
        default_args = parse_cli_args()

    assert args.sectors == ["Desalination"]
    assert multi_args.sectors == ["Desalination", "Blue Biotech"]
    assert default_args.sectors == []


def test_cli_argument_parsing_rejects_invalid_sector() -> None:
    with patch("sys.argv", ["run_full_analysis.py", "--sector", "Invalid Sector"]):
        with pytest.raises(SystemExit):
            parse_cli_args()


# ============================================================================
# Additional comprehensive tests for uncovered functions
# ============================================================================


def test_detect_axis_marine_keywords() -> None:
    """Test _detect_axis with MARINE keywords."""
    from run_full_analysis import _detect_axis

    text = "This research focuses on ecosystem biodiversity and coral reef restoration"
    result = _detect_axis(text)
    assert result.name == "MARINE"


def test_detect_axis_maritime_keywords() -> None:
    """Test _detect_axis with MARITIME keywords."""
    from run_full_analysis import _detect_axis

    text = "Labour rights for seafarers in port logistics and maritime transport"
    result = _detect_axis(text)
    assert result.name == "MARITIME"


def test_detect_axis_oceanic_keywords() -> None:
    """Test _detect_axis with OCEANIC keywords."""
    from run_full_analysis import _detect_axis

    text = "Planetary ocean governance and hydrosocial systems thinking"
    result = _detect_axis(text)
    assert result.name == "OCEANIC"


def test_detect_axis_no_keywords_uses_default() -> None:
    """Test _detect_axis with no matching keywords uses default."""
    from run_full_analysis import _detect_axis

    text = "General notes about scheduling, document review, and meeting agendas"
    result = _detect_axis(text, default="MARINE")
    assert result.name == "MARINE"


def test_slugify_converts_text_to_slug() -> None:
    """Test _slugify converts text to safe identifier."""
    from run_full_analysis import _slugify

    assert _slugify("Blue Economy Expert") == "blue_economy_expert"
    assert _slugify("Maritime Transport!!!") == "maritime_transport"
    assert _slugify("R&I — Research") == "r_i_research"
    # Test truncation at 60 chars
    long_text = "a" * 100
    assert len(_slugify(long_text)) <= 60


def test_load_baseline_competences_with_real_data(tmp_path: Path) -> None:
    """Test load_baseline_competences with realistic CSV data."""
    from run_full_analysis import load_baseline_competences, TMBDAxis

    csv_content = """Dimension,Competence,Blue competence name,Focus,Blue Biotech,Coastal Tourism,Desalination
A,A.1,Understanding Ocean Systems,Marine literacy basics,X,X,
B,B.2,Digital Data Tools,Data management,X,,X
C,C.1,Ecosystem Sustainability,Marine conservation,X,X,X
D,D.3,Business Governance,Economic frameworks,,,X"""

    csv_file = tmp_path / "baseline.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    with (
        patch("run_full_analysis.BASELINE_CSV", csv_file),
        patch("run_full_analysis.REPO_ROOT", tmp_path),
    ):
        competences = load_baseline_competences()

    assert len(competences) == 4
    assert competences[0].id == "baseline_a_1"
    assert competences[0].axis == TMBDAxis.OCEANIC  # Dimension A → OCEANIC
    assert competences[1].axis == TMBDAxis.MARITIME  # Dimension B → MARITIME
    assert competences[2].axis == TMBDAxis.MARINE  # Dimension C → MARINE
    assert "Blue Biotech" in competences[0].sectors
    assert "Coastal Tourism" in competences[0].sectors


def test_load_baseline_competences_skips_invalid_rows(tmp_path: Path) -> None:
    """Test load_baseline_competences skips rows with missing data."""
    from run_full_analysis import load_baseline_competences

    csv_content = """Dimension,Competence,Blue competence name,Focus,Sector1
A,A.1,Valid Competence,Description,X
,,,,
,—,Empty Competence,,
B,,Missing Name,Desc,X"""

    csv_file = tmp_path / "baseline.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    with (
        patch("run_full_analysis.BASELINE_CSV", csv_file),
        patch("run_full_analysis.REPO_ROOT", tmp_path),
    ):
        competences = load_baseline_competences()

    # Only one valid competence should be loaded
    assert len(competences) == 1
    assert competences[0].id == "baseline_a_1"


def test_extract_literature_competences_with_sample_data(tmp_path: Path) -> None:
    """Test extract_literature_competences with sample CSV."""
    from run_full_analysis import extract_literature_competences, SECTORS

    csv_content = """"Paper Title","Abstract","Author Names","Publication Year","DOI"
"Marine Labour Justice","Study on seafarer rights and port labour conditions","Smith, J.","2023","10.1234/test1"
"Ocean Governance Systems","Planetary boundaries and ocean policy","Jones, A.","2022","10.1234/test2"
"Coral Reef Restoration","Biodiversity restoration in tropical ecosystems","Brown, B.","2024","10.1234/test3"
"""

    csv_file = tmp_path / "test_literature.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    lit_files = [
        {
            "filename": csv_file.name,
            "theme": "test_theme",
            "description": "Test papers",
            "primary_axis": "MARITIME",
        }
    ]

    # Mock theme pool
    mock_themes = {
        "test_theme": {
            "MARITIME": ["Test maritime theme", "Another maritime theme"],
            "MARINE": ["Test marine theme"],
            "OCEANIC": ["Test oceanic theme"],
        }
    }

    with (
        patch("run_full_analysis.LITERATURE_FILES", lit_files),
        patch("run_full_analysis.DATA_DERIVED", tmp_path),
        patch("run_full_analysis.DATA_RAW", tmp_path),
        patch("run_full_analysis.REPO_ROOT", tmp_path),
        patch("run_full_analysis._LIT_THEMES", mock_themes),
    ):
        competences = extract_literature_competences()

    assert len(competences) == 3
    assert all(c.dimension == "literature" for c in competences)
    assert all(c.sectors == SECTORS for c in competences)  # Cross-sector
    assert competences[0].source.authors == "Smith, J."
    assert competences[0].source.year == "2023"


def test_extract_literature_competences_deduplicates_titles(tmp_path: Path) -> None:
    """Test that duplicate paper titles are filtered out."""
    from run_full_analysis import extract_literature_competences

    csv_content = """"Paper Title","Abstract","Author Names","Publication Year","DOI"
"Duplicate Paper","Abstract 1","Author A","2023","10.1234/dup1"
"Duplicate Paper","Abstract 2","Author B","2024","10.1234/dup2"
"Unique Paper","Abstract 3","Author C","2023","10.1234/unique"
"""

    csv_file = tmp_path / "lit.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    lit_files = [
        {
            "filename": csv_file.name,
            "theme": "test",
            "description": "Test",
            "primary_axis": "OCEANIC",
        }
    ]

    # Mock theme pool
    mock_themes = {
        "test": {
            "MARITIME": ["Test maritime"],
            "MARINE": ["Test marine"],
            "OCEANIC": ["Test oceanic"],
        }
    }

    with (
        patch("run_full_analysis.LITERATURE_FILES", lit_files),
        patch("run_full_analysis.DATA_DERIVED", tmp_path),
        patch("run_full_analysis.REPO_ROOT", tmp_path),
        patch("run_full_analysis._LIT_THEMES", mock_themes),
    ):
        competences = extract_literature_competences()

    # Only 2 papers (duplicate removed)
    assert len(competences) == 2
    titles = [c.source.paper_title for c in competences]
    assert titles.count("Duplicate Paper") == 1


def test_run_gap_analysis_calculates_correctly() -> None:
    """Test run_gap_analysis computes gaps correctly."""
    from run_full_analysis import run_gap_analysis

    baseline = [
        Competence(
            id="baseline_a1",
            name="Baseline A1",
            description="Description",
            axis=TMBDAxis.MARINE,
            dimension="A",
            source=CompetenceSource(file="test.csv", row=1),
            sectors=["Blue Biotech", "Coastal Tourism"],
        ),
        Competence(
            id="baseline_b1",
            name="Baseline B1",
            description="Description",
            axis=TMBDAxis.MARITIME,
            dimension="B",
            source=CompetenceSource(file="test.csv", row=2),
            sectors=["Blue Biotech"],
        ),
    ]

    literature = [
        Competence(
            id="lit_001",
            name="Literature 1",
            description="Description",
            axis=TMBDAxis.OCEANIC,
            dimension="literature",
            source=CompetenceSource(file="lit.csv", row=1),
            sectors=SECTORS,
        ),
    ]

    gaps, sector_comps = run_gap_analysis(baseline, literature)

    # Blue Biotech has 2 baseline + 1 literature = 3 required
    # Blue Biotech has 2 baseline available
    # Blue Biotech has 1 missing (the literature one)
    biotech_gap = gaps["Blue Biotech"]
    assert len(biotech_gap.required_ids) == 3
    assert len(biotech_gap.available_ids) == 2
    assert len(biotech_gap.missing_ids) == 1
    assert biotech_gap.gap_pct == pytest.approx(33.33, rel=0.1)

    # Check axis breakdown
    assert "lit_001" in biotech_gap.by_axis["OCEANIC"]


def test_compute_sector_pathways_finds_bridges() -> None:
    """Test compute_sector_pathways identifies bridge competences."""
    from run_full_analysis import compute_sector_pathways

    baseline = [
        Competence(
            id="shared_comp",
            name="Shared",
            description="Desc",
            axis=TMBDAxis.MARINE,
            dimension="A",
            source=CompetenceSource(file="test.csv", row=1),
            sectors=["Blue Biotech", "Coastal Tourism"],
        ),
        Competence(
            id="biotech_only",
            name="Biotech Only",
            description="Desc",
            axis=TMBDAxis.MARITIME,
            dimension="B",
            source=CompetenceSource(file="test.csv", row=2),
            sectors=["Blue Biotech"],
        ),
    ]

    credentials = [
        MicroCredential(
            id="mc_blue_biotech_eqf5",
            title="Blue Biotech EQF5",
            competences=["shared_comp"],
            description="Test",
            sector="Blue Biotech",
            ects=6.0,
            eqf_level=EQFLevel.EQF5,
            assessment_method="Test",
            prerequisites=[],
            learner_profile="Test",
            learning_outcomes=["Test"],
            stackability_rules="Test",
        ),
    ]

    pathways = compute_sector_pathways(credentials, baseline)

    # Find pathway from Blue Biotech to Coastal Tourism
    biotech_to_tourism = next(
        p for p in pathways
        if p.from_sector == "Blue Biotech" and p.to_sector == "Coastal Tourism"
    )
    assert "shared_comp" in biotech_to_tourism.bridge_competences
    assert "mc_blue_biotech_eqf5" in biotech_to_tourism.bridge_credentials


def test_export_gaps_summary_csv_creates_file(tmp_path: Path) -> None:
    """Test export_gaps_summary_csv creates valid CSV."""
    from run_full_analysis import export_gaps_summary_csv

    gaps = {
        "Blue Biotech": GapAnalysis(
            sector="Blue Biotech",
            required_ids=["a", "b", "c"],
            available_ids=["a"],
            missing_ids=["b", "c"],
            gap_pct=66.7,
            by_axis={"MARINE": ["b"], "MARITIME": [], "OCEANIC": ["c"]},
        ),
    }

    output_file = tmp_path / "gaps.csv"

    with patch("run_full_analysis.SECTORS", ["Blue Biotech"]):
        export_gaps_summary_csv(gaps, output_file)

    assert output_file.exists()
    content = output_file.read_text()
    assert "Blue Biotech" in content
    assert "66.7" in content


def test_export_competences_json_creates_file(tmp_path: Path) -> None:
    """Test export_competences_json creates valid JSON."""
    from run_full_analysis import export_competences_json

    baseline = [
        Competence(
            id="base_1",
            name="Baseline",
            description="Test",
            axis=TMBDAxis.MARINE,
            dimension="A",
            source=CompetenceSource(file="test.csv", row=1),
            sectors=["Blue Biotech"],
        ),
    ]

    literature = [
        Competence(
            id="lit_1",
            name="Literature",
            description="Test",
            axis=TMBDAxis.OCEANIC,
            dimension="literature",
            source=CompetenceSource(file="lit.csv", row=1),
            sectors=SECTORS,
        ),
    ]

    output_file = tmp_path / "comps.json"
    export_competences_json(baseline, literature, output_file)

    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["metadata"]["total"] == 2
    assert data["metadata"]["baseline_count"] == 1
    assert data["metadata"]["literature_count"] == 1
    assert len(data["baseline"]) == 1
    assert len(data["literature"]) == 1


def test_export_credentials_json_creates_file(tmp_path: Path) -> None:
    """Test export_credentials_json creates valid JSON."""
    from run_full_analysis import export_credentials_json

    credentials = [
        MicroCredential(
            id="mc_test",
            title="Test Credential",
            competences=["comp1"],
            description="Test",
            sector="Blue Biotech",
            ects=3.0,
            eqf_level=EQFLevel.EQF4,
            assessment_method="Test",
            prerequisites=[],
            learner_profile="Test",
            learning_outcomes=["Test"],
            stackability_rules="Test",
        ),
    ]

    output_file = tmp_path / "creds.json"
    export_credentials_json(credentials, output_file)

    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["metadata"]["total"] == 1
    assert len(data["credentials"]) == 1
    assert data["credentials"][0]["id"] == "mc_test"


def test_export_pathways_json_creates_file(tmp_path: Path) -> None:
    """Test export_pathways_json creates valid JSON."""
    from run_full_analysis import export_pathways_json, SectorPathway

    pathways = [
        SectorPathway(
            from_sector="Blue Biotech",
            to_sector="Coastal Tourism",
            bridge_competences=["comp1"],
            bridge_credentials=["cred1"],
        ),
    ]

    output_file = tmp_path / "pathways.json"
    export_pathways_json(pathways, output_file)

    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["metadata"]["total_pathways"] == 1
    assert len(data["pathways"]) == 1
    assert data["pathways"][0]["from_sector"] == "Blue Biotech"


def test_axis_badge_generates_html() -> None:
    """Test _axis_badge generates correct HTML."""
    from run_full_analysis import _axis_badge

    marine_badge = _axis_badge(TMBDAxis.MARINE)
    assert 'class="badge-M"' in marine_badge
    assert "M MARINE" in marine_badge

    maritime_badge = _axis_badge(TMBDAxis.MARITIME)
    assert 'class="badge-T"' in maritime_badge

    oceanic_badge = _axis_badge(TMBDAxis.OCEANIC)
    assert 'class="badge-O"' in oceanic_badge


def test_generate_report_index_creates_html(tmp_path: Path) -> None:
    """Test generate_report_index creates HTML file."""
    from run_full_analysis import generate_report_index

    baseline = [
        Competence(
            id="base_1",
            name="Baseline",
            description="Test",
            axis=TMBDAxis.MARINE,
            dimension="A",
            source=CompetenceSource(file="test.csv", row=1),
            sectors=["Blue Biotech"],
        ),
    ]

    literature = []

    gaps = {
        sector: GapAnalysis(
            sector=sector,
            required_ids=["a"],
            available_ids=[],
            missing_ids=["a"],
            gap_pct=100.0,
            by_axis={"MARINE": ["a"], "MARITIME": [], "OCEANIC": []},
        )
        for sector in SECTORS
    }

    credentials = []

    output_file = tmp_path / "index.html"
    generate_report_index(baseline, literature, gaps, credentials, output_file)

    assert output_file.exists()
    content = output_file.read_text()
    assert "Blue Economy Analysis" in content
    assert "Summary Dashboard" in content


def test_generate_gaps_html_creates_file(tmp_path: Path) -> None:
    """Test generate_gaps_html creates HTML file."""
    from run_full_analysis import generate_gaps_html

    comp = Competence(
        id="missing_comp",
        name="Missing Competence",
        description="Test",
        axis=TMBDAxis.MARINE,
        dimension="A",
        source=CompetenceSource(file="test.csv", row=1),
        sectors=["Blue Biotech"],
    )

    gaps = {
        "Blue Biotech": GapAnalysis(
            sector="Blue Biotech",
            required_ids=["missing_comp"],
            available_ids=[],
            missing_ids=["missing_comp"],
            gap_pct=100.0,
            by_axis={"MARINE": ["missing_comp"], "MARITIME": [], "OCEANIC": []},
        ),
    }

    all_comps = {"missing_comp": comp}

    output_file = tmp_path / "gaps.html"

    with patch("run_full_analysis.SECTORS", ["Blue Biotech"]):
        generate_gaps_html(gaps, all_comps, output_file)

    assert output_file.exists()
    content = output_file.read_text()
    assert "Blue Biotech" in content
    assert "100.0%" in content


def test_generate_credentials_html_creates_file(tmp_path: Path) -> None:
    """Test generate_credentials_html creates HTML file."""
    from run_full_analysis import generate_credentials_html

    credentials = [
        MicroCredential(
            id="mc_test",
            title="Test Credential",
            competences=["comp1"],
            description="Test credential description",
            sector="Blue Biotech",
            ects=3.0,
            eqf_level=EQFLevel.EQF4,
            assessment_method="Written test",
            prerequisites=[],
            learner_profile="Test learners",
            learning_outcomes=["Outcome 1", "Outcome 2"],
            stackability_rules="Test stacking",
        ),
    ]

    output_file = tmp_path / "creds.html"
    generate_credentials_html(credentials, output_file)

    assert output_file.exists()
    content = output_file.read_text()
    assert "Test Credential" in content
    assert "Blue Biotech" in content


def test_generate_literature_html_creates_file(tmp_path: Path) -> None:
    """Test generate_literature_html creates HTML file with per-theme table rows."""
    from run_full_analysis import generate_literature_html

    # Use an id containing the "labor_justice" theme so the theme-specific
    # table is rendered with this competence's data.
    literature = [
        Competence(
            id="labor_justice_0001",
            name="Blue Labour Justice Competence",
            description="Test",
            axis=TMBDAxis.OCEANIC,
            dimension="literature",
            source=CompetenceSource(
                file="lit.csv", row=1, authors="Smith, J.", year="2023",
                paper_title="Test Paper", doi="10.1234/test"
            ),
            sectors=SECTORS,
        ),
    ]

    output_file = tmp_path / "lit.html"
    generate_literature_html(literature, output_file)

    assert output_file.exists()
    content = output_file.read_text()
    # The theme-specific table must include the competence name and authors
    assert "Blue Labour Justice Competence" in content
    assert "Smith, J." in content


def test_main_handles_missing_baseline_csv(tmp_path: Path) -> None:
    """Test main returns error code when baseline CSV is missing."""
    from run_full_analysis import main

    missing_csv = tmp_path / "nonexistent.csv"

    with patch("run_full_analysis.BASELINE_CSV", missing_csv):
        exit_code = main()

    assert exit_code == 1


def test_main_handles_no_literature_files(tmp_path: Path) -> None:
    """Test main continues when no literature files are found."""
    from run_full_analysis import main

    baseline_csv = tmp_path / "baseline.csv"
    baseline_csv.write_text(
        "Dimension,Competence,Blue competence name,Focus,Sector1\n"
        "A,A.1,Test,Description,X\n",
        encoding="utf-8"
    )

    output_dir = tmp_path / "outputs"

    with (
        patch("run_full_analysis.BASELINE_CSV", baseline_csv),
        patch("run_full_analysis.OUTPUTS_DIR", output_dir),
        patch("run_full_analysis.LITERATURE_FILES", []),
        patch("run_full_analysis.REPO_ROOT", tmp_path),
    ):
        exit_code = main()

    # Should succeed even with no literature files
    assert exit_code == 0


class TestCLIAndEdgeCases:
    """Tests for CLI arguments and edge case branches"""

    def test_parse_cli_args_defaults(self):
        """Test CLI argument parsing returns correct default structure"""
        import sys

        # Test with no arguments (default)
        with patch.object(sys, 'argv', ['run_full_analysis.py']):
            args = parse_cli_args()
            assert hasattr(args, 'sectors')
            # Default value is an empty list, not None
            assert args.sectors == [] or args.sectors is None

    def test_main_with_cli_sector_selection(self, tmp_path):
        """Test main() with CLI sector selection"""
        baseline_csv = tmp_path / "baseline.csv"
        baseline_csv.write_text(
            "Dimension,Competence,Blue competence name,Focus,Blue Biotech,Ports\n"
            "A,A.1,Test,Description,X,X\n",
            encoding="utf-8"
        )

        output_dir = tmp_path / "outputs"

        with (
            patch("run_full_analysis.BASELINE_CSV", baseline_csv),
            patch("run_full_analysis.OUTPUTS_DIR", output_dir),
            patch("run_full_analysis.LITERATURE_FILES", []),
            patch("run_full_analysis.REPO_ROOT", tmp_path),
        ):
            exit_code = main(selected_sectors=["Blue Biotech"])

        assert exit_code == 0

    def test_main_if_name_main_block(self):
        """Test the if __name__ == '__main__' execution path"""
        # This test verifies the CLI entry point structure
        # The actual block calls parse_cli_args() and main(selected_sectors=...)
        # We verify parse_cli_args works and returns expected structure
        import sys

        with patch.object(sys, 'argv', ['run_full_analysis.py']):
            args = parse_cli_args()
            assert hasattr(args, 'sectors')

