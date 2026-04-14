"""Tests for scripts.chunk_competence_db."""

import json
from pathlib import Path

import pytest

from scripts.chunk_competence_db import run_chunking


def _write_json(path: Path, payload: object) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def test_run_chunking_baseline_and_literature_payload(tmp_path: Path) -> None:
    input_path = tmp_path / "competences_full_database.json"
    payload = {
        "metadata": {"total": 3},
        "baseline": [
            {
                "id": "baseline_1",
                "name": "Ocean literacy",
                "description": "Understanding ocean systems",
                "axis": "O",
                "level": "FOUNDATIONAL",
                "source": {"file": "data/derived/a.csv"},
            },
            {
                "id": "baseline_2",
                "name": "Maritime tools",
                "description": "Apply digital tools",
                "axis_name": "MARITIME",
                "level": "INTERMEDIATE",
                "source": {"file": "data/derived/b.csv"},
            },
        ],
        "literature": [
            {
                "id": "lit_1",
                "name": "Biodiversity monitoring",
                "description": "Monitor marine biodiversity",
                "axis": "M",
                "level": "ADVANCED",
                "source": {"file": "data/raw/lit.csv"},
            }
        ],
    }
    _write_json(input_path, payload)

    output_dir = tmp_path / "chunks"
    result = run_chunking(
        input_path=input_path,
        output_dir=output_dir,
        chunk_size=2,
        strict_level=False,
        export_lightweight_csv=True,
    )

    assert result["total_records"] == 3
    assert len(result["chunk_files"]) == 2

    with (output_dir / "competences_part_1.json").open("r", encoding="utf-8") as handle:
        part_1 = json.load(handle)
    assert part_1["competences"][0]["axis"] == "OCEANIC"
    assert part_1["competences"][1]["axis"] == "MARITIME"

    with (output_dir / "competences_part_2.json").open("r", encoding="utf-8") as handle:
        part_2 = json.load(handle)
    assert part_2["competences"][0]["axis"] == "MARINE"

    csv_path = output_dir / "competences_export.csv"
    assert csv_path.exists()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "id,name,description,axis,level,source" in csv_text
    assert (
        "baseline_1,Ocean literacy,Understanding ocean systems,OCEANIC,FOUNDATIONAL,data/derived/a.csv"
        in csv_text
    )


def test_run_chunking_strict_level_rejects_missing_level(tmp_path: Path) -> None:
    input_path = tmp_path / "competences_full_database.json"
    payload = {
        "competences": [
            {
                "id": "comp_1",
                "name": "Ocean governance",
                "description": "Govern coupled systems",
                "axis": "O",
            }
        ]
    }
    _write_json(input_path, payload)

    with pytest.raises(ValueError, match="missing required field 'level'"):
        run_chunking(
            input_path=input_path,
            output_dir=tmp_path / "chunks",
            chunk_size=100,
            strict_level=True,
            export_lightweight_csv=False,
        )
