"""Utilities for mapping competence dimensions to TMBD axes."""

from __future__ import annotations

from src.core import BlueDynamicsAxis


def map_dimension_to_axis(dimension: str) -> BlueDynamicsAxis:
    """Map a competence dimension code to a TMBD axis."""
    dimension_letter = dimension.split(".")[0] if "." in dimension else dimension[0]

    mapping = {
        "A": BlueDynamicsAxis.OCEANIC,  # Understanding/literacy → planetary
        "B": BlueDynamicsAxis.MARITIME,  # Digital/technical → infrastructure
        "C": BlueDynamicsAxis.MARINE,  # Sustainability → ecological
        "D": BlueDynamicsAxis.MARITIME,  # Governance → institutional
    }

    return mapping.get(dimension_letter, BlueDynamicsAxis.OCEANIC)
