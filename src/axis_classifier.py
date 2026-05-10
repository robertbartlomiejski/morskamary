"""Production module for TMBD/QMBD axis classification."""

from __future__ import annotations

import re

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
        BlueDynamicsAxis.MARINE: ("ecosystem", "biodiversity", "habitat", "species"),
        BlueDynamicsAxis.MARITIME: ("port", "shipping", "infrastructure", "logistics"),
        # Hydronization keywords — water-society co-constitution (QMBD 4th
        # dimension, Manus methodological review).
        # "hydronization": direct term for the 4th axis.
        # "hydrosocial": established in blue-sociology literature; cf. Linton &
        #   Budds (2014) "The hydrosocial cycle", Geoforum 57, cited in
        #   docs/literature/Bartłomiejskie Cocco krytyka oceanocentryzmu.txt:912
        #   and scripts/cumulative_fragment_analysis.py:qmbd_label_from_text.
        # "wet ontology": Steinberg & Peters (2015) via Bartłomiejski Cocco
        #   Performatywność wody morza oceanu.txt:2064-2066; also in use in
        #   scripts/cumulative_fragment_analysis.py:qmbd_label_from_text.
        BlueDynamicsAxis.HYDRONIZATION: (
            "hydronization",
            "hydrosocial",
            "wet ontology",
        ),
        BlueDynamicsAxis.OCEANIC: ("governance", "policy", "cooperation", "justice"),
    }

    def classify_axis(self, text: str, dimension: str | None = None) -> BlueDynamicsAxis:
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

        normalized = re.sub(r"\s+", " ", text.lower())

        for axis, keywords in self.KEYWORD_AXIS_MAP.items():
            if any(keyword in normalized for keyword in keywords):
                return axis

        return BlueDynamicsAxis.OCEANIC
