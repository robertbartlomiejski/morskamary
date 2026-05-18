"""Production module for TMBD/QMBD axis classification."""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.core import BlueDynamicsAxis
from src.dimension_mapping import map_dimension_to_axis


class AxisClassifier:
    """Classifier facade for assigning QMBD axis labels.

    Supports all four axes of the Quadripartite Model of Blue Dynamics (QMBD):
    Marine, Maritime, Oceanic, and Hydronization.  The TMBD three-axis logic
    (Marine/Maritime/Oceanic) is preserved unchanged; the Hydronization axis is
    an additive extension inserted *before* the OCEANIC fallback so that
    Hydronization-specific keywords are matched in preference to the generic
    governance-first default.

    Fallback order when no dimension is supplied:
      1. Keyword scan in KEYWORD_AXIS_MAP order (MARINE → MARITIME →
         HYDRONIZATION → OCEANIC).
      2. Default → OCEANIC (governance-first bias, as per TMBD/QMBD spec).
    """

    KEYWORD_AXIS_MAP = {
        BlueDynamicsAxis.MARINE: (
            "ecosystem",
            "biodiversity",
            "habitat",
            "species",
            "bio-cycles",
            "deep-time rhythms",
            "cofka",
            "thermohaline circulation",
            "stewardship",
            "habitus of seafarers",
            "marine ecotone",
            "vibrant materialism",
            "weather-based risk",
            "intra-action",
            "pelagic metabolism",
            "benthic agency",
        ),
        BlueDynamicsAxis.MARITIME: (
            "port",
            "shipping",
            "infrastructure",
            "logistics",
            "maritimization",
            "port 4.0",
            "growth machine",
            "blue-washing",
            "ocean grabbing",
            "rigid superinfrastructure",
            "ten-t corridors",
            "flag of convenience",
            "throughput tonnage",
            "logistics algorithms",
            "supply chain acceleration",
            "maritime mindset",
            "cyber-physical port systems",
        ),
        BlueDynamicsAxis.HYDRONIZATION: (
            "hydronization",
            "hydrosocial",
            "wet ontology",
            "hydrofeminism",
            "transcorporeality",
            "porocity",
            "porosity",
            "sponge city",
            "liquid materiality",
            "estuarial hydrofeminism",
            "bodies of water",
            "hydrobiography",
            "metabolism of flows",
            "porous infrastructure",
            "hydro-social territory",
        ),
        BlueDynamicsAxis.OCEANIC: (
            "governance",
            "policy",
            "cooperation",
            "justice",
            "hyperobject",
            "hydrocommons",
            "blue degrowth",
            "high sea treaties",
            "volumetric sovereignty",
            "tidalectics",
            "rights of nature",
            "blue justice",
            "planetary water",
            "hydro-solidarity",
            "ocean literacy",
            "blue citizenship",
            "multispecies justice",
        ),
    }
    _SEPARATOR_RE = re.compile(r"[-_]+")
    _WHITESPACE_RE = re.compile(r"\s+")
    _compiled_keyword_map: (
        dict[BlueDynamicsAxis, tuple[re.Pattern[str], ...]] | None
    ) = None

    @classmethod
    def _normalize_text(cls, text: str) -> str:
        """Normalize text for deterministic keyword matching."""
        lowered = text.lower()
        separator_normalized = cls._SEPARATOR_RE.sub(" ", lowered)
        return cls._WHITESPACE_RE.sub(" ", separator_normalized).strip()

    @classmethod
    def _compile_keyword_pattern(cls, keyword: str) -> re.Pattern[str]:
        """Compile a regex that matches a keyword/phrase at word boundaries."""
        normalized_keyword = cls._normalize_text(keyword)
        keyword_tokens = normalized_keyword.split()
        escaped_phrase = r"\s+".join(re.escape(token) for token in keyword_tokens)
        return re.compile(rf"\b{escaped_phrase}\b")

    @classmethod
    def _get_compiled_keyword_map(
        cls,
    ) -> dict[BlueDynamicsAxis, tuple[re.Pattern[str], ...]]:
        """Compile and cache keyword regexes while preserving scan order."""
        if cls._compiled_keyword_map is None:
            cls._compiled_keyword_map = {
                axis: tuple(
                    cls._compile_keyword_pattern(keyword) for keyword in keywords
                )
                for axis, keywords in cls.KEYWORD_AXIS_MAP.items()
            }
        return cls._compiled_keyword_map

    @staticmethod
    def _matches_any_keyword(
        normalized_text: str, keyword_patterns: Iterable[re.Pattern[str]]
    ) -> bool:
        """Return True when any compiled keyword pattern appears in the text."""
        return any(pattern.search(normalized_text) for pattern in keyword_patterns)

    def classify_axis(
        self, text: str, dimension: str | None = None
    ) -> BlueDynamicsAxis:
        """Classify axis using dimension-first logic and a text fallback.

        When a dimension code is provided (e.g. 'A.1', 'B', 'C.3', 'D'),
        ``map_dimension_to_axis`` is used directly — the dimension mapping
        covers only the original TMBD axes (A→OCEANIC, B→MARITIME,
        C→MARINE, D→MARITIME).  Hydronization is reached via the keyword
        path only.

        When no dimension is provided, the KEYWORD_AXIS_MAP is scanned in
        declaration order (MARINE → MARITIME → HYDRONIZATION → OCEANIC).
        If no keywords match, the default is OCEANIC (governance-first bias).
        """
        if dimension:
            return map_dimension_to_axis(dimension)

        if not text or not text.strip():
            return BlueDynamicsAxis.OCEANIC

        normalized = self._normalize_text(text)

        for axis, keyword_patterns in self._get_compiled_keyword_map().items():
            if self._matches_any_keyword(normalized, keyword_patterns):
                return axis

        return BlueDynamicsAxis.OCEANIC
