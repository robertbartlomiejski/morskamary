"""Tests for src.competence_repository."""

from dataclasses import dataclass
from typing import List

from src.core import BlueDynamicsAxis
from src.competence_repository import LiteratureCompetenceRepository

SECTOR_BLUE_BIOTECH = "Blue Biotech"
SECTOR_PORTS = "Ports"
AXIS_MARINE = "MARINE"
AXIS_MARITIME = "MARITIME"
AXIS_OCEANIC = "OCEANIC"


@dataclass
class _StubAxis:
    name: str


@dataclass
class _StubCompetence:
    id: str
    axis: _StubAxis
    sectors: List[str]


def _extractor() -> List[_StubCompetence]:
    return [
        _StubCompetence(
            id="c1", axis=_StubAxis(AXIS_MARINE), sectors=[SECTOR_BLUE_BIOTECH]
        ),
        _StubCompetence(
            id="c2",
            axis=_StubAxis(AXIS_OCEANIC),
            sectors=[SECTOR_BLUE_BIOTECH, SECTOR_PORTS],
        ),
        _StubCompetence(id="c3", axis=_StubAxis(AXIS_MARITIME), sectors=[SECTOR_PORTS]),
    ]


def test_iter_all_competences() -> None:
    repository = LiteratureCompetenceRepository(_extractor)
    ids = [competence.id for competence in repository.iter_all_competences()]
    assert ids == ["c1", "c2", "c3"]


def test_get_competence_by_id() -> None:
    repository = LiteratureCompetenceRepository(_extractor)
    competence = repository.get_competence_by_id("c2")
    assert competence is not None
    assert competence.id == "c2"
    assert repository.get_competence_by_id("missing") is None


def test_iter_competences_for_sector_and_axis() -> None:
    repository = LiteratureCompetenceRepository(_extractor)
    sector_ids = [
        c.id for c in repository.iter_competences_for_sector(SECTOR_BLUE_BIOTECH)
    ]
    axis_ids = [c.id for c in repository.iter_competences_for_axis(AXIS_MARITIME)]
    assert sector_ids == ["c1", "c2"]
    assert axis_ids == ["c3"]


def test_axis_names_align_with_canonical_enum() -> None:
    canonical_axis_names = {axis.name for axis in BlueDynamicsAxis}
    stub_axis_names = {AXIS_MARINE, AXIS_MARITIME, AXIS_OCEANIC}
    assert stub_axis_names == canonical_axis_names


def test_repository_caches_extractor_results() -> None:
    calls = {"count": 0}

    def counting_extractor() -> List[_StubCompetence]:
        calls["count"] += 1
        return _extractor()

    repository = LiteratureCompetenceRepository(counting_extractor)
    list(repository.iter_all_competences())
    repository.get_competence_by_id("c1")
    list(repository.iter_competences_for_sector(SECTOR_BLUE_BIOTECH))

    assert calls["count"] == 1
