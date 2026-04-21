"""Tests for orchestration helpers in run_full_analysis."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from run_full_analysis import (
    Competence,
    CompetenceSource,
    GapAnalysis,
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
