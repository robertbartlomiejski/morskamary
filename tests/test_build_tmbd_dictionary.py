"""Tests for scripts.build_tmbd_dictionary."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from scripts.build_tmbd_dictionary import (
    build_sector_dictionary,
    build_sector_dictionary_from_repository,
    export_sector_dictionary,
    slugify,
)
from src.competence_repository import MixedProvenanceCompetenceRepository


@dataclass
class _DummyAxis:
    name: str


@dataclass
class _DummySource:
    file: str
    row: int
    paper_title: str
    authors: str
    year: str
    doi: str


@dataclass
class _DummyCompetence:
    id: str
    name: str
    description: str
    axis: _DummyAxis
    source: _DummySource
    sectors: list[str]


def test_slugify() -> None:
    assert slugify("Blue Biotech") == "blue_biotech"
    assert slugify("R&I") == "r_i"


def test_build_sector_dictionary_groups_by_axis() -> None:
    competences = [
        _DummyCompetence(
            id="c1",
            name="Marine",
            description="d1",
            axis=_DummyAxis("MARINE"),
            source=_DummySource("f.csv", 2, "p1", "a1", "2020", ""),
            sectors=["Blue Biotech"],
        ),
        _DummyCompetence(
            id="c2",
            name="Oceanic",
            description="d2",
            axis=_DummyAxis("OCEANIC"),
            source=_DummySource("f.csv", 3, "p2", "a2", "2021", ""),
            sectors=["Blue Biotech"],
        ),
        _DummyCompetence(
            id="c3",
            name="Other sector",
            description="d3",
            axis=_DummyAxis("MARITIME"),
            source=_DummySource("f.csv", 4, "p3", "a3", "2022", ""),
            sectors=["Coastal Tourism"],
        ),
    ]

    grouped = build_sector_dictionary(competences, sector="Blue Biotech")

    assert len(grouped["MARINE"]) == 1
    assert len(grouped["OCEANIC"]) == 1
    assert len(grouped["MARITIME"]) == 0
    maritime_ids = [record["id"] for record in grouped["MARITIME"]]
    assert "c3" not in maritime_ids


def test_build_sector_dictionary_normalizes_sector_labels() -> None:
    competences = [
        _DummyCompetence(
            id="c1",
            name="R&I competence",
            description="d1",
            axis=_DummyAxis("MARINE"),
            source=_DummySource("f.csv", 2, "p1", "a1", "2020", ""),
            sectors=[" R&I "],
        ),
        _DummyCompetence(
            id="c2",
            name="Different sector",
            description="d2",
            axis=_DummyAxis("OCEANIC"),
            source=_DummySource("f.csv", 3, "p2", "a2", "2021", ""),
            sectors=["Ports"],
        ),
    ]

    grouped = build_sector_dictionary(competences, sector="r&i")

    assert [record["id"] for record in grouped["MARINE"]] == ["c1"]
    assert grouped["MARITIME"] == []
    assert grouped["OCEANIC"] == []


def test_build_sector_dictionary_rejects_unknown_axis() -> None:
    competences = [
        _DummyCompetence(
            id="c1",
            name="Invalid axis competence",
            description="d1",
            axis=_DummyAxis("UNKNOWN"),
            source=_DummySource("f.csv", 2, "p1", "a1", "2020", ""),
            sectors=["Blue Biotech"],
        )
    ]

    with pytest.raises(ValueError, match="Unsupported TMBD axis"):
        build_sector_dictionary(competences, sector="Blue Biotech")


def test_build_sector_dictionary_from_repository() -> None:
    competences = [
        _DummyCompetence(
            id="baseline_a1",
            name="Marine",
            description="d1",
            axis=_DummyAxis("MARINE"),
            source=_DummySource("f.csv", 2, "p1", "a1", "2020", ""),
            sectors=["Blue Biotech"],
        ),
        _DummyCompetence(
            id="lit_example_0001",
            name="Maritime",
            description="d2",
            axis=_DummyAxis("MARITIME"),
            source=_DummySource("f.csv", 3, "p2", "a2", "2021", ""),
            sectors=["Blue Biotech"],
        ),
        _DummyCompetence(
            id="lit_example_0002",
            name="Ports only",
            description="d3",
            axis=_DummyAxis("OCEANIC"),
            source=_DummySource("f.csv", 4, "p3", "a3", "2022", ""),
            sectors=["Ports"],
        ),
    ]
    repository = MixedProvenanceCompetenceRepository(lambda: competences)

    grouped = build_sector_dictionary_from_repository(repository, sector="Blue Biotech")

    assert len(grouped["MARINE"]) == 0
    assert len(grouped["MARITIME"]) == 1
    assert len(grouped["OCEANIC"]) == 0
    dictionary_ids = {
        record["id"] for axis_records in grouped.values() for record in axis_records
    }
    assert "lit_example_0002" not in dictionary_ids
    assert "baseline_a1" not in dictionary_ids


def test_export_sector_dictionary(tmp_path: Path) -> None:
    grouped = {"MARINE": [{"id": "c1"}], "MARITIME": [], "OCEANIC": []}

    output_path = export_sector_dictionary(
        sector="Blue Biotech", grouped=grouped, output_dir=tmp_path
    )

    assert output_path.name == "blue_biotech_tmbd_dictionary.json"
    content = output_path.read_text(encoding="utf-8")
    assert '"sector": "Blue Biotech"' in content


class TestMainAndCLI:
    """Tests for main() function and CLI execution path"""

    def test_main_missing_module_spec(self, monkeypatch):
        """Test main() handles missing module spec gracefully"""
        import scripts.build_tmbd_dictionary as btd
        import importlib.util

        # Mock spec_from_file_location to return None
        monkeypatch.setattr(
            importlib.util,
            "spec_from_file_location",
            lambda name, path: None
        )

        # Should raise ImportError
        with pytest.raises(ImportError) as exc_info:
            btd.load_literature_competence_extractor()

        assert "Cannot load module spec" in str(exc_info.value)

    def test_main_missing_loader(self, monkeypatch):
        """Test main() handles missing spec.loader gracefully"""
        import scripts.build_tmbd_dictionary as btd
        import importlib.util

        # Create a mock spec without loader
        @dataclass
        class MockSpec:
            loader = None

        monkeypatch.setattr(
            importlib.util,
            "spec_from_file_location",
            lambda name, path: MockSpec()
        )

        # Should raise ImportError
        with pytest.raises(ImportError) as exc_info:
            btd.load_literature_competence_extractor()

        assert "Cannot load module spec" in str(exc_info.value)

    def test_main_cli_execution(self, tmp_path):
        """Test that __name__ == __main__ block can be tested"""
        from scripts.build_tmbd_dictionary import main
        from unittest.mock import patch
        import sys

        # Mock sys.argv to provide required arguments
        with patch.object(sys, 'argv', [
            'build_tmbd_dictionary.py',
            '--sector', 'Blue Biotech',
            '--output-dir', str(tmp_path)
        ]):
            # Test calling main() directly returns 0 on success
            result = main()
            assert result == 0

            # Verify output directory has dictionary file
            expected_file = tmp_path / "blue_biotech_tmbd_dictionary.json"
            assert expected_file.exists()
