"""Tests for orchestration helpers in run_full_analysis."""

import json
from pathlib import Path

from run_full_analysis import (
    Competence,
    CompetenceSource,
    TMBDAxis,
    export_sector_dictionaries,
)


def test_export_sector_dictionaries_writes_one_file_per_sector(tmp_path: Path) -> None:
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
        description="Should be excluded",
        axis=TMBDAxis.MARINE,
        dimension="A",
        source=CompetenceSource(file="data/derived/y.csv", row=3),
        sectors=["Blue Biotech"],
    )

    output_paths = export_sector_dictionaries(
        literature=[literature_competence, baseline_competence],
        sectors=["Blue Biotech", "R&I"],
        output_dir=tmp_path,
    )

    assert [path.name for path in output_paths] == [
        "blue_biotech_tmbd_dictionary.json",
        "r_i_tmbd_dictionary.json",
    ]

    blue_biotech_payload = json.loads(output_paths[0].read_text(encoding="utf-8"))
    maritime_ids = [
        item["id"] for item in blue_biotech_payload["dictionary"]["MARITIME"]
    ]
    assert maritime_ids == ["lit_example_0001"]

    research_payload = json.loads(output_paths[1].read_text(encoding="utf-8"))
    assert research_payload["metadata"]["sector"] == "R&I"
    assert all(not records for records in research_payload["dictionary"].values())
