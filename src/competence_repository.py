"""Data access repository for literature-derived competences."""

from __future__ import annotations

import re
from typing import Callable, Dict, Iterator, List, Optional, Protocol, Sequence, Set

ORIGIN_BASELINE = "baseline"
ORIGIN_LITERATURE = "literature"
ORIGIN_UNKNOWN = "unknown"


class AxisLike(Protocol):
    """Structural type for axis objects."""

    name: str


class CompetenceLike(Protocol):
    """Structural type for competence objects exposed by repositories."""

    id: str
    axis: AxisLike
    sectors: Sequence[str]


def classify_competence_origin(competence_id: str) -> str:
    """
    Classify competence provenance using stable ID prefixes.

    Case-insensitive rules:
    - IDs matching `^baseline(?:_|$)` -> `baseline`
    - IDs starting with `lit_` -> `literature`
    - Any other prefix -> `unknown`
    """
    id_lower = competence_id.lower().strip()
    if re.match(r"^baseline(?:_|$)", id_lower):
        return ORIGIN_BASELINE
    if re.match(r"^lit_", id_lower):
        return ORIGIN_LITERATURE
    return ORIGIN_UNKNOWN


def normalize_sector_name(sector: str) -> str:
    """
    Normalize sector labels.

    This function keeps only alphanumeric content and spaces to maximize
    lookup robustness across punctuation/style variants.

    Examples:
    - ``Blue-Biotech`` -> ``blue biotech``
    - ``Blue--Biotech!!`` -> ``blue biotech``
    """
    return re.sub(r"[^a-z0-9]+", " ", sector.lower()).strip()


class LiteratureCompetenceRepository:
    """Repository abstraction exposing semantic access to competences."""

    def __init__(self, extractor: Callable[[], Sequence[CompetenceLike]]) -> None:
        """
        Initialize repository.

        Args:
            extractor: Callable that returns literature-derived competences.
                Each competence object must expose at least: `id`, `axis.name`,
                and `sectors`.
        """
        self._extractor = extractor
        self._cache: Optional[List[CompetenceLike]] = None
        self._id_index: Optional[Dict[str, CompetenceLike]] = None
        self._normalized_sector_index: Optional[Dict[str, Set[str]]] = None

    def _load(self) -> List[CompetenceLike]:
        """Load once, cache for reuse, and return the cached competence list."""
        if self._cache is None:
            self._cache = list(self._extractor())
            self._id_index = {competence.id: competence for competence in self._cache}
            self._normalized_sector_index = self._build_normalized_sector_index(
                self._cache
            )
        return self._cache

    def _build_normalized_sector_index(
        self, competences: Sequence[CompetenceLike]
    ) -> Dict[str, Set[str]]:
        """Build normalized sector lookup index keyed by competence id."""
        sector_normalization_cache: Dict[str, str] = {}

        def _normalize_cached(raw_sector: str) -> str:
            if raw_sector not in sector_normalization_cache:
                sector_normalization_cache[raw_sector] = normalize_sector_name(
                    raw_sector
                )
            return sector_normalization_cache[raw_sector]

        return {
            competence.id: {
                _normalize_cached(current_sector)
                for current_sector in competence.sectors
            }
            for competence in competences
        }

    def iter_all_competences(self) -> Iterator[CompetenceLike]:
        """Iterate all literature competences."""
        for competence in self._load():
            yield competence

    def get_competence_by_id(self, competence_id: str) -> Optional[CompetenceLike]:
        """Get one competence by id, if present."""
        self._load()
        return (self._id_index or {}).get(competence_id)

    def iter_competences_for_sector(self, sector: str) -> Iterator[CompetenceLike]:
        """Iterate competences associated with a specific sector."""
        normalized_sector = normalize_sector_name(sector)
        competences = self._load()
        sector_index = self._normalized_sector_index or {}
        for competence in competences:
            if normalized_sector in sector_index.get(competence.id, set()):
                yield competence

    def iter_literature_competences(self) -> Iterator[CompetenceLike]:
        """Iterate only literature-derived competences."""
        for competence in self._load():
            if classify_competence_origin(competence.id) == ORIGIN_LITERATURE:
                yield competence

    def iter_baseline_competences(self) -> Iterator[CompetenceLike]:
        """Iterate only baseline competences."""
        for competence in self._load():
            if classify_competence_origin(competence.id) == ORIGIN_BASELINE:
                yield competence

    def iter_literature_competences_for_sector(
        self, sector: str
    ) -> Iterator[CompetenceLike]:
        """Iterate only literature-derived competences for a specific sector."""
        for competence in self.iter_competences_for_sector(sector):
            if classify_competence_origin(competence.id) == ORIGIN_LITERATURE:
                yield competence

    def iter_competences_for_axis(self, axis: str) -> Iterator[CompetenceLike]:
        """Iterate competences associated with a specific TMBD axis."""
        for competence in self._load():
            if competence.axis.name == axis:
                yield competence
