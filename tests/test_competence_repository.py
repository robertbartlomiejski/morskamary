"""Tests for src.competence_repository."""

from dataclasses import dataclass
from typing import List

from src.core import BlueDynamicsAxis
from src.competence_repository import (
    ORIGIN_BASELINE,
    ORIGIN_LITERATURE,
    ORIGIN_UNKNOWN,
    LiteratureCompetenceRepository,
    classify_competence_origin,
)

SECTOR_BLUE_BIOTECH = "Blue Biotech"
SECTOR_BLUE_BIOTECH_LOWERCASE = "blue biotech"
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
            id="baseline_a1",
            axis=_StubAxis(AXIS_MARINE),
            sectors=[SECTOR_BLUE_BIOTECH],
        ),
        _StubCompetence(
            id="lit_test_0001",
            axis=_StubAxis(AXIS_OCEANIC),
            sectors=[SECTOR_BLUE_BIOTECH, SECTOR_PORTS],
        ),
        _StubCompetence(
            id="lit_test_0002", axis=_StubAxis(AXIS_MARITIME), sectors=[SECTOR_PORTS]
        ),
        _StubCompetence(
            id="other_0001", axis=_StubAxis(AXIS_MARITIME), sectors=[SECTOR_PORTS]
        ),
    ]


def test_iter_all_competences() -> None:
    repository = LiteratureCompetenceRepository(_extractor)
    all_competences = list(repository.iter_all_competences())
    ids = [competence.id for competence in all_competences]
    assert ids == ["baseline_a1", "lit_test_0001", "lit_test_0002", "other_0001"]
    assert all_competences[0].axis.name == AXIS_MARINE
    assert all_competences[1].sectors == [SECTOR_BLUE_BIOTECH, SECTOR_PORTS]


def test_get_competence_by_id() -> None:
    repository = LiteratureCompetenceRepository(_extractor)
    competence = repository.get_competence_by_id("lit_test_0001")
    assert competence is not None
    assert competence.id == "lit_test_0001"
    assert repository.get_competence_by_id("missing") is None


def test_iter_competences_for_sector_and_axis() -> None:
    repository = LiteratureCompetenceRepository(_extractor)
    sector_ids = [
        c.id
        for c in repository.iter_competences_for_sector(SECTOR_BLUE_BIOTECH_LOWERCASE)
    ]
    axis_ids = [c.id for c in repository.iter_competences_for_axis(AXIS_MARITIME)]
    empty_sector = list(repository.iter_competences_for_sector("Nonexistent Sector"))
    empty_axis = list(repository.iter_competences_for_axis("NONEXISTENT"))
    assert sector_ids == ["baseline_a1", "lit_test_0001"]
    assert axis_ids == ["lit_test_0002", "other_0001"]
    assert empty_sector == []
    assert empty_axis == []


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
    repository.get_competence_by_id("baseline_a1")
    list(repository.iter_competences_for_sector(SECTOR_BLUE_BIOTECH))

    assert calls["count"] == 1


def test_classify_competence_origin() -> None:
    assert classify_competence_origin("baselinea1") == ORIGIN_BASELINE
    assert classify_competence_origin("baseline_a1") == ORIGIN_BASELINE
    assert classify_competence_origin("lit_labor_justice_0001") == ORIGIN_LITERATURE
    assert classify_competence_origin("other_0001") == ORIGIN_UNKNOWN


def test_origin_specific_iterators() -> None:
    repository = LiteratureCompetenceRepository(_extractor)
    baseline_ids = [c.id for c in repository.iter_baseline_competences()]
    literature_ids = [c.id for c in repository.iter_literature_competences()]
    literature_sector_ids = [
        c.id for c in repository.iter_literature_competences_for_sector(SECTOR_PORTS)
    ]
    assert baseline_ids == ["baseline_a1"]
    assert literature_ids == ["lit_test_0001", "lit_test_0002"]
    assert literature_sector_ids == ["lit_test_0001", "lit_test_0002"]
