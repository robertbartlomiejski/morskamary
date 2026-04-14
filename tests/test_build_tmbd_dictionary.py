"""Tests for scripts.build_tmbd_dictionary."""

from dataclasses import dataclass
from pathlib import Path

from scripts.build_tmbd_dictionary import (
    build_sector_dictionary,
    build_sector_dictionary_from_repository,
    export_sector_dictionary,
    slugify,
)
from src.competence_repository import LiteratureCompetenceRepository


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
    ]
    repository = LiteratureCompetenceRepository(lambda: competences)

    grouped = build_sector_dictionary_from_repository(repository, sector="Blue Biotech")

    assert len(grouped["MARINE"]) == 0
    assert len(grouped["MARITIME"]) == 1
    assert len(grouped["OCEANIC"]) == 0


def test_export_sector_dictionary(tmp_path: Path) -> None:
    grouped = {"MARINE": [{"id": "c1"}], "MARITIME": [], "OCEANIC": []}

    output_path = export_sector_dictionary(
        sector="Blue Biotech", grouped=grouped, output_dir=tmp_path
    )

    assert output_path.name == "blue_biotech_tmbd_dictionary.json"
    content = output_path.read_text(encoding="utf-8")
    assert '"sector": "Blue Biotech"' in content
