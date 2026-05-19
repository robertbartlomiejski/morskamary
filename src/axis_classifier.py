"""Production module for TMBD/QMBD axis classification."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from src.core import BlueDynamicsAxis
from src.dimension_mapping import map_dimension_to_axis


class AxisClassifier:
    """Classifier implementing strict QMBD 4D context evaluation."""

    def __init__(self) -> None:
        # 1. Core QMBD Vocabularies (Deep trans-disciplinary semantic scopes)
        self.qmbd_vocabularies = {
            "MARINE": [
                r"\bmarine\b",
                r"\bmarinization\b",
                r"\bczynnik morski\b",
                r"\bmetabolic rift\b",
                r"\boceanography\b",
                r"\bacidification\b",
                r"\bbiophysical\b",
                r"\btrophic webs\b",
                r"\bmarine protected areas\b",
                r"\bbenthic\b",
                r"\bhydrothermal\b",
                r"\bde marinisation\b",
                r"\bbiodiversity collapse\b",
                r"\bplanetary boundaries\b",
            ],
            "MARITIME": [
                r"\bmaritime\b",
                r"\bmaritimization\b",
                r"\bterraforming\b",
                r"\bport cityness\b",
                r"\bshipping\b",
                r"\bseafarers\b",
                r"\blogistics\b",
                r"\bmaritime spatial planning\b",
                r"\boffshore infrastructure\b",
                r"\bexclusive economic zone\b",
                r"\bmaritime labour\b",
                r"\bde maritimisation\b",
                r"\baquaculture\b",
                r"\bchoke points\b",
            ],
            "OCEANIC": [
                r"\boceanic\b",
                r"\boceanization\b",
                r"\bplanetary governance\b",
                r"\bblue justice\b",
                r"\btransboundary\b",
                r"\bhigh seas treaty\b",
                r"\bbbnj\b",
                r"\bglobal commons\b",
                r"\bvolumetric sovereignty\b",
                r"\bmulti level governance\b",
                r"\bocean grabbing\b",
            ],
            "HYDRONIZATION": [
                r"\bhydronization\b",
                r"\bhydroization\b",
                r"\bporosity\b",
                r"\bporocity\b",
                r"\bwater cycle\b",
                r"\bwet ontologies\b",
                r"\bhydro social\b",
                r"\btranscorporeality\b",
                r"\bliquid life\b",
                r"\bwater personhood\b",
                r"\briverhood\b",
                r"\bamphibious\b",
                r"\baquapelagic assemblages\b",
                r"\bvirtual water\b",
            ],
        }

        # 2. Blue Planetaryism (Cross-cutting policy, economic, and systemic signals)
        self.planetaryism_vocab = [
            r"\bblue economy\b",
            r"\bblue growth\b",
            r"\bgreenwashing\b",
            r"\bblue washing\b",
            r"\bresilience\b",
            r"\bdegrowth\b",
            r"\bocean literacy\b",
            r"\becosystem services\b",
            r"\bsustainable development\b",
            r"\bblue finance\b",
            r"\bblue bonds\b",
        ]

        # Compile cached regex patterns
        self.compiled_qmbd = {
            axis: re.compile("|".join(patterns), re.IGNORECASE)
            for axis, patterns in self.qmbd_vocabularies.items()
        }
        self.compiled_planetaryism = re.compile(
            "|".join(self.planetaryism_vocab), re.IGNORECASE
        )
        self.legacy_keyword_axis_map = {
            BlueDynamicsAxis.MARINE: (
                "ecosystem",
                "biodiversity",
                "habitat",
                "species",
                "benthic",
            ),
            BlueDynamicsAxis.MARITIME: (
                "port",
                "shipping",
                "infrastructure",
                "logistics",
                "maritimization",
            ),
            BlueDynamicsAxis.HYDRONIZATION: (
                "hydronization",
                "hydrosocial",
                "wet ontology",
                "porosity",
                "porocity",
                "hydro social territory",
            ),
            BlueDynamicsAxis.OCEANIC: (
                "governance",
                "policy",
                "cooperation",
                "justice",
                "ocean literacy",
            ),
        }
        self.compiled_legacy_keyword_map = {
            axis: tuple(
                re.compile(
                    rf"\b{'\\s+'.join(re.escape(t) for t in self._normalize_text(keyword).split())}\b",
                    re.IGNORECASE,
                )
                for keyword in keywords
            )
            for axis, keywords in self.legacy_keyword_axis_map.items()
        }

    def _normalize_text(self, text: str) -> str:
        """Deterministic text normalization ensuring canonical matching."""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r"[-_]", " ", text)  # hyphen/underscore -> space
        text = re.sub(r"\s+", " ", text).strip()  # whitespace collapse
        return text

    def classify_context(
        self, text_context: str, source_id: str, scope_type: str
    ) -> Dict[str, Any]:
        """
        Evaluate full sentence/paragraph contexts against the strict QMBD matrix.
        """
        normalized_text = self._normalize_text(text_context)
        matched_axes: List[str] = []

        for axis, pattern in self.compiled_qmbd.items():
            if pattern.search(normalized_text):
                matched_axes.append(axis)

        has_planetaryism = bool(self.compiled_planetaryism.search(normalized_text))

        if not matched_axes:
            primary_classification = "UNCLASSIFIED_REVIEW_REQUIRED"
        elif len(matched_axes) == 1:
            primary_classification = matched_axes[0]
        else:
            primary_classification = "MULTI_AXIS_INTERSECTION"

        return {
            "classification": primary_classification,
            "is_blue_planetaryism": has_planetaryism,
            "matched_qmbd_axes": matched_axes,
            "provenance": {
                "source_id": source_id,
                "text_scope": scope_type,  # e.g., "full_sentence", "abstract_fragment"
                "classification_text": text_context,
                "classifier_version": "QMBD-4.0-strict",
            },
        }

    def classify_axis(
        self, text: str, dimension: str | None = None
    ) -> BlueDynamicsAxis:
        """Compatibility helper returning a single axis for existing call sites."""
        if dimension:
            return map_dimension_to_axis(dimension)

        normalized_text = self._normalize_text(text)
        if not normalized_text:
            return BlueDynamicsAxis.OCEANIC

        for axis, patterns in self.compiled_legacy_keyword_map.items():
            if any(pattern.search(normalized_text) for pattern in patterns):
                return axis

        result = self.classify_context(
            text_context=text,
            source_id="compat",
            scope_type="full_text",
        )
        if result["classification"] in BlueDynamicsAxis.__members__:
            return BlueDynamicsAxis[result["classification"]]
        return BlueDynamicsAxis.OCEANIC
