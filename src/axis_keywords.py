"""Shared QMBD keyword sets and boundary-aware keyword matching utilities."""

from __future__ import annotations

import re

CLASSIFIER_MARINE_KEYWORDS = (
    "ecosystem",
    "biodiversity",
    "habitat",
    "species",
)

CLASSIFIER_MARITIME_KEYWORDS = (
    "port",
    "shipping",
    "infrastructure",
    "logistics",
)

CLASSIFIER_HYDRONIZATION_KEYWORDS = (
    "hydronization",
    "hydrosocial",
    "wet ontology",
)

CLASSIFIER_OCEANIC_KEYWORDS = (
    "governance",
    "policy",
    "cooperation",
    "justice",
)

THEME_MARINE_KEYWORDS = CLASSIFIER_MARINE_KEYWORDS + (
    "fisheries",
    "aquaculture",
)

THEME_MARITIME_KEYWORDS = CLASSIFIER_MARITIME_KEYWORDS + (
    "maritime",
    "fleet",
)

THEME_HYDRONIZATION_KEYWORDS = CLASSIFIER_HYDRONIZATION_KEYWORDS + (
    "water-energy",
    "water society",
    "hydrological transition",
)

THEME_OCEANIC_KEYWORDS = CLASSIFIER_OCEANIC_KEYWORDS + (
    "ocean governance",
    "transboundary",
    "planetary",
)


def keyword_in_text(text: str, keyword: str) -> bool:
    """Return True when keyword matches text with word/phrase boundaries."""
    if not text or not keyword:
        return False
    normalized_text = re.sub(r"\s+", " ", text.lower())
    normalized_keyword = re.sub(r"\s+", " ", keyword.lower()).strip()
    pattern = rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)"
    return re.search(pattern, normalized_text) is not None
