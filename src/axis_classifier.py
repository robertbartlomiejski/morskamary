"""Production module for TMBD axis classification."""

from __future__ import annotations

import re

from src.core import BlueDynamicsAxis
from src.dimension_mapping import map_dimension_to_axis


class AxisClassifier:
    """Classifier facade for assigning TMBD axis labels."""

    KEYWORD_AXIS_MAP = {
        BlueDynamicsAxis.MARINE: ("ecosystem", "biodiversity", "habitat", "species"),
        BlueDynamicsAxis.MARITIME: ("port", "shipping", "infrastructure", "logistics"),
        BlueDynamicsAxis.OCEANIC: ("governance", "policy", "cooperation", "justice"),
    }

    def classify_axis(self, text: str, dimension: str | None = None) -> BlueDynamicsAxis:
        """Classify axis using dimension-first logic and a text fallback."""
        if dimension:
            return map_dimension_to_axis(dimension)

        if not text or not text.strip():
            return BlueDynamicsAxis.OCEANIC

        normalized = re.sub(r"\s+", " ", text.lower())

        for axis, keywords in self.KEYWORD_AXIS_MAP.items():
            if any(keyword in normalized for keyword in keywords):
                return axis

        return BlueDynamicsAxis.OCEANIC
