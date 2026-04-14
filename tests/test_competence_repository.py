"""Tests for src.competence_repository."""

from dataclasses import dataclass
from typing import List

from src.competence_repository import LiteratureCompetenceRepository


@dataclass
class _DummyAxis:
    name: str


@dataclass
class _DummyCompetence:
    id: str
    axis: _DummyAxis
    sectors: List[str]


def _extractor() -> List[_DummyCompetence]:
    return [
        _DummyCompetence(id="c1", axis=_DummyAxis("MARINE"), sectors=["Blue Biotech"]),
        _DummyCompetence(
            id="c2", axis=_DummyAxis("OCEANIC"), sectors=["Blue Biotech", "Ports"]
        ),
        _DummyCompetence(id="c3", axis=_DummyAxis("MARITIME"), sectors=["Ports"]),
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
    sector_ids = [c.id for c in repository.iter_competences_for_sector("Blue Biotech")]
    axis_ids = [c.id for c in repository.iter_competences_for_axis("MARITIME")]
    assert sector_ids == ["c1", "c2"]
    assert axis_ids == ["c3"]
