"""Data access repository for literature-derived competences."""

from __future__ import annotations

from typing import Any, Callable, Iterator, List, Optional, Sequence


class LiteratureCompetenceRepository:
    """Repository abstraction exposing semantic access to competences."""

    def __init__(self, extractor: Callable[[], Sequence[Any]]) -> None:
        """
        Initialize repository.

        Args:
            extractor: Callable that returns literature-derived competences.
        """
        self._extractor = extractor
        self._cache: Optional[List[Any]] = None

    def _load(self) -> List[Any]:
        """Load once, cache for reuse, and return the cached competence list."""
        if self._cache is None:
            self._cache = list(self._extractor())
        return self._cache

    def iter_all_competences(self) -> Iterator[Any]:
        """Iterate all literature competences."""
        for competence in self._load():
            yield competence

    def get_competence_by_id(self, competence_id: str) -> Optional[Any]:
        """Get one competence by id, if present."""
        for competence in self._load():
            if competence.id == competence_id:
                return competence
        return None

    def iter_competences_for_sector(self, sector: str) -> Iterator[Any]:
        """Iterate competences associated with a specific sector."""
        for competence in self._load():
            if sector in competence.sectors:
                yield competence

    def iter_competences_for_axis(self, axis: str) -> Iterator[Any]:
        """Iterate competences associated with a specific TMBD axis."""
        for competence in self._load():
            if competence.axis.name == axis:
                yield competence
