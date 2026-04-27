"""Dimension → TMBD axis mapping helpers."""

from __future__ import annotations

from src.core import BlueDynamicsAxis

DIMENSION_TO_AXIS_MAPPING = {
    "A": BlueDynamicsAxis.OCEANIC,
    "B": BlueDynamicsAxis.MARITIME,
    "C": BlueDynamicsAxis.MARINE,
    "D": BlueDynamicsAxis.MARITIME,
}


def map_dimension_to_axis(dimension: str) -> BlueDynamicsAxis:
    """
    Map a competence dimension code to a TMBD axis.

    Empty or unknown values default to ``OCEANIC``.
    """
    normalized_dimension = dimension.strip()
    if not normalized_dimension:
        return BlueDynamicsAxis.OCEANIC
    dimension_letter = (
        normalized_dimension.split(".")[0]
        if "." in normalized_dimension
        else normalized_dimension[0]
    )
    return DIMENSION_TO_AXIS_MAPPING.get(dimension_letter, BlueDynamicsAxis.OCEANIC)
