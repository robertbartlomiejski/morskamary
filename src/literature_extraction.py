"""Utilities for extracting competence-related signals from literature abstracts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List


@dataclass(frozen=True)
class ExtractionRecord:
    """Structured extraction output for a single competence phrase hit."""

    abstract_excerpt: str
    extraction_method: str
    confidence_score: float


class LiteratureExtractor:
    """Extract competence-focused snippets from scientific abstract text."""

    DEFAULT_COMPETENCE_PATTERNS = (
        r"\bcompetenc(?:e|ies)\b",
        r"\bskill(?:s)?\b",
        r"\bliteracy\b",
        r"\bcapacity\s+building\b",
        r"\bgovernance\b",
    )

    def __init__(self, competence_patterns: Iterable[str] | None = None) -> None:
        patterns = tuple(competence_patterns or self.DEFAULT_COMPETENCE_PATTERNS)
        self._pattern_sources = patterns
        self._compiled_patterns = tuple(
            re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns
        )

    def parse_abstracts(self, text: str) -> List[str]:
        """Parse one raw text blob into cleaned abstract fragments/sentences."""
        if not text or not text.strip():
            return []

        normalized = re.sub(r"\s+", " ", text.strip())
        return [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", normalized) if chunk.strip()]

    def detect_competence_phrases(self, text: str) -> List[ExtractionRecord]:
        """Detect competence phrases and return records with confidence metadata."""
        sentences = self.parse_abstracts(text)
        if not sentences:
            return []

        records: List[ExtractionRecord] = []
        for sentence in sentences:
            for pattern_source, pattern in zip(
                self._pattern_sources, self._compiled_patterns
            ):
                if pattern.search(sentence):
                    records.append(
                        ExtractionRecord(
                            abstract_excerpt=sentence,
                            extraction_method=f"regex:{pattern_source}",
                            confidence_score=0.75,
                        )
                    )
                    break

        return records


def extract_from_abstracts(text: str) -> List[dict]:
    """Convenience API returning serializable extraction records."""
    extractor = LiteratureExtractor()
    return [record.__dict__ for record in extractor.detect_competence_phrases(text)]
