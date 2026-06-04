#!/usr/bin/env python3
"""
run_full_analysis.py — Enhanced Master Script: Complete Gap Analysis &
Micro-Credential Design with Automation

Deliverables (generated in outputs/ directory):
  report_index.html           — Master report with navigation
  gaps_by_sector.html         — Interactive gap analysis tables
  credentials_matrix.html     — Micro-credential cards with stackability
  literature_integration.html — Papers → competences mapping
  competences_full_database.json — All competences with metadata
  credentials_database.json   — Auto-generated micro-credentials
  sector_pathways.json        — Sector transition graphs
  gaps_summary.csv            — Gap percentages by sector
  sector_dictionaries/*.json  — Sector-specific TMBD competence dictionaries

Usage:
    python run_full_analysis.py

Evidence discipline: All competences cite source files with row/file
references and GitHub hyperlinks.
"""

import csv
import argparse
import html as _html_module
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeAlias,
    cast,
)
from urllib.parse import quote

from scripts.build_tmbd_dictionary import (
    build_sector_dictionary_from_repository,
    export_sector_dictionary,
)
from src.axis_classifier import AxisClassifier
from src.core import BlueDynamicsAxis
from src.literature_extraction import extract_sentences
from src.utils import slugify
from src.competence_repository import (
    CompetenceLike,
    MixedProvenanceCompetenceRepository,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)
_TOKEN_PATTERN = re.compile(r"\w+")

# ---------------------------------------------------------------------------
# Repository constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
DATA_DERIVED = REPO_ROOT / "data" / "derived"
DATA_RAW = REPO_ROOT / "data" / "raw"
OUTPUTS_DIR = REPO_ROOT / "outputs"
DEFAULT_LIVE_RECORDS_JSON = (
    OUTPUTS_DIR / "research_sources" / "live_records_triangulated.json"
)
CUMULATIVE_QMBD_RECORDS_FILENAME = "cumulative_qmbd_records.json"
REPO_GITHUB_BASE = "https://github.com/robertbartlomiejski/morskamary/blob/main"
_AXIS_CLASSIFIER = AxisClassifier()

# 12 blue economy sectors (canonical names matching the CSV headers)
SECTORS: List[str] = [
    "Blue Biotech",
    "Coastal Tourism",
    "Desalination",
    "Infra & Robotics",
    "Living Res.",
    "Non-living Res.",
    "Renewable Energy",
    "Maritime Defence",
    "Maritime Transport",
    "Port Activities",
    "R&I",
    "Ship Repair",
]

# Canonical sector → short slug
SECTOR_SLUG: Dict[str, str] = {
    "Blue Biotech": "blue-biotech",
    "Coastal Tourism": "coastal-tourism",
    "Desalination": "desalination",
    "Infra & Robotics": "infra-robotics",
    "Living Res.": "living-resources",
    "Non-living Res.": "non-living-resources",
    "Renewable Energy": "renewable-energy",
    "Maritime Defence": "maritime-defence",
    "Maritime Transport": "maritime-transport",
    "Port Activities": "port-activities",
    "R&I": "research-innovation",
    "Ship Repair": "ship-repair",
}

# Literature CSV files (relative paths under data/derived)
LITERATURE_FILES: List[Dict[str, str]] = [
    {
        "filename": "combined_blue_economy_labor_justice.csv",
        "theme": "labor_justice",
        "description": "Blue economy labour justice & social equity papers",
        "primary_axis": "MARITIME",
    },
    {
        "filename": "combined_blue_economy_research_gaps.csv",
        "theme": "research_gaps",
        "description": "Blue economy research gaps & governance papers",
        "primary_axis": "OCEANIC",
    },
    {
        "filename": "combined_blue_sociology_results.csv",
        "theme": "blue_sociology",
        "description": "Blue sociology & maritime society papers",
        "primary_axis": "MARITIME",
    },
]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


TMBDAxis: TypeAlias = BlueDynamicsAxis


def _axis_from_name(
    axis_name: str, default_axis: TMBDAxis = TMBDAxis.OCEANIC
) -> TMBDAxis:
    """Safely convert axis name to enum value with default fallback."""
    return getattr(TMBDAxis, axis_name, default_axis)


class EQFLevel(Enum):
    """European Qualifications Framework levels relevant to micro-credentials"""

    EQF4 = 4  # Upper secondary / technician
    EQF5 = 5  # Short-cycle tertiary
    EQF6 = 6  # Bachelor level
    EQF7 = 7  # Master level


@dataclass
class CompetenceSource:
    """Provenance record for a competence"""

    file: str  # relative path in repo
    row: int  # 1-based row index
    authors: str = ""
    year: str = ""
    paper_title: str = ""
    doi: str = ""

    @property
    def github_url(self) -> str:
        """Return GitHub hyperlink to the source file/row"""
        encoded = self.file.replace(" ", "%20")
        return f"{REPO_GITHUB_BASE}/{encoded}#L{self.row}"


@dataclass
class Competence:
    """A single Blue Economy / Blue Sociology competence"""

    id: str
    name: str
    description: str
    axis: TMBDAxis
    dimension: str  # A / B / C / D or 'literature'
    source: CompetenceSource
    keywords: List[str] = field(default_factory=list)
    sectors: List[str] = field(default_factory=list)  # sectors it applies to

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "axis": self.axis.value,
            "axis_name": self.axis.name,
            "dimension": self.dimension,
            "keywords": self.keywords,
            "sectors": self.sectors,
            "source": {
                "file": self.source.file,
                "row": self.source.row,
                "authors": self.source.authors,
                "year": self.source.year,
                "paper_title": self.source.paper_title,
                "doi": self.source.doi,
                "github_url": self.source.github_url,
            },
        }


@dataclass
class MicroCredential:
    """A stackable micro-credential with all 9 required fields"""

    id: str
    title: str
    competences: List[str]  # competence IDs
    description: str
    sector: str
    ects: float
    eqf_level: EQFLevel
    assessment_method: str
    prerequisites: List[str]  # credential IDs
    learner_profile: str
    learning_outcomes: List[str]
    stackability_rules: str

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "competences": self.competences,
            "description": self.description,
            "sector": self.sector,
            "ects": self.ects,
            "eqf_level": self.eqf_level.value,
            "assessment_method": self.assessment_method,
            "prerequisites": self.prerequisites,
            "learner_profile": self.learner_profile,
            "learning_outcomes": self.learning_outcomes,
            "stackability_rules": self.stackability_rules,
        }


@dataclass
class GapAnalysis:
    """Gap analysis result for one sector"""

    sector: str
    required_ids: List[str]
    available_ids: List[str]
    missing_ids: List[str]
    gap_pct: float
    by_axis: Dict[str, List[str]]  # axis name → missing IDs


@dataclass
class SectorPathway:
    """Transition pathway between two sectors"""

    from_sector: str
    to_sector: str
    bridge_competences: List[str]  # competence IDs in common
    bridge_credentials: List[str]  # credential IDs that bridge the gap


# ---------------------------------------------------------------------------
# QMBD sentence-context classification helpers and localized record repository
# ---------------------------------------------------------------------------


def _classify_sentence_contexts(
    sentences: List[str], source_id: str
) -> List[Dict[str, Any]]:
    """Classify full-sentence contexts with strict QMBD output."""
    classifications: List[Dict[str, Any]] = []
    for sentence in sentences:
        axis_payload = _AXIS_CLASSIFIER.classify_context(
            sentence,
            text_scope="full_sentence",
        )
        axis_name = str(axis_payload.get("axis", "")).upper()
        matched_keywords = axis_payload.get("matched_keywords", [])
        has_supported_evidence = isinstance(matched_keywords, list) and any(
            isinstance(keyword, str) and keyword.strip() for keyword in matched_keywords
        )
        matched_axes = (
            [axis_name]
            if axis_name in TMBDAxis.__members__ and has_supported_evidence
            else []
        )
        classification_name = (
            axis_name
            if axis_name in TMBDAxis.__members__ and has_supported_evidence
            else "UNCLASSIFIED_REVIEW_REQUIRED"
        )
        classifications.append(
            {
                "classification": classification_name,
                "matched_qmbd_axes": matched_axes,
                "provenance": {
                    "source_id": source_id,
                    "text_scope": "full_sentence",
                    "classification_text": sentence,
                    "classifier_version": "QMBD-4.0-strict",
                },
                **axis_payload,
            }
        )
    return classifications


def _sentence_classification_counts_as_evidence(item: Dict[str, Any]) -> bool:
    """Return True when a sentence-level classification contains positive axis evidence."""
    matched_keywords = item.get("matched_keywords", [])
    if isinstance(matched_keywords, list) and any(
        isinstance(keyword, str) and keyword.strip() for keyword in matched_keywords
    ):
        return True

    confidence_score = item.get("confidence_score")
    if isinstance(confidence_score, (int, float)) and float(confidence_score) > 0.6:
        return True

    axis_name = (
        str(item.get("axis") or item.get("classification") or "").strip().upper()
    )
    if axis_name in {"MARINE", "MARITIME", "HYDRONIZATION"} and (
        "matched_keywords" not in item and "confidence_score" not in item
    ):
        return True

    return False


def _resolve_primary_axis_from_analysis(
    analysis: List[Dict[str, Any]], default_axis: str = "OCEANIC"
) -> TMBDAxis:
    """Resolve one axis for competence objects from strict sentence analysis."""
    axis_counts: Dict[str, int] = {
        "MARINE": 0,
        "MARITIME": 0,
        "OCEANIC": 0,
        "HYDRONIZATION": 0,
    }
    for item in analysis:
        if not _sentence_classification_counts_as_evidence(item):
            continue
        classification = str(item.get("classification", "")) or str(
            item.get("axis", "")
        )
        classification = classification.upper()
        if classification in axis_counts:
            axis_counts[classification] += 1

    ranked = sorted(axis_counts.items(), key=lambda kv: kv[1], reverse=True)
    if ranked and ranked[0][1] > 0:
        top_score = ranked[0][1]
        tied_axes = [axis for axis, score in ranked if score == top_score]
        if len(tied_axes) == 1:
            return _axis_from_name(tied_axes[0], default_axis=TMBDAxis.OCEANIC)
        precedence = ("MARINE", "MARITIME", "HYDRONIZATION", "OCEANIC")
        for axis_name in precedence:
            if axis_name in tied_axes:
                return _axis_from_name(axis_name, default_axis=TMBDAxis.OCEANIC)

    for item in analysis:
        for axis_name in item.get("matched_qmbd_axes", []):
            if axis_name in TMBDAxis.__members__:
                return _axis_from_name(axis_name, default_axis=TMBDAxis.OCEANIC)

    return _axis_from_name(default_axis, default_axis=TMBDAxis.OCEANIC)


@dataclass
class LocalizedQMBDRecordRepository:
    """Localized repository exposing baseline and live records as one iterator."""

    static_records: List[Dict[str, Any]]
    live_records_path: Path
    include_live_records: bool = True

    def _iter_live_records(self) -> Iterator[Dict[str, Any]]:
        if not self.include_live_records:
            return
        if not self.live_records_path.exists():
            log.info(
                "Live records file not found for QMBD enrichment: %s",
                self.live_records_path,
            )
            return
        try:
            payload = json.loads(self.live_records_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning(
                "Failed to parse live records for QMBD enrichment (%s): %s",
                self.live_records_path,
                exc,
            )
            return
        if not isinstance(payload, list):
            log.warning(
                "Live records JSON must be a list for QMBD enrichment: %s",
                self.live_records_path,
            )
            return
        for idx, record in enumerate(payload, start=2):
            if isinstance(record, dict):
                prepared = dict(record)
                prepared.setdefault("source_id", str(record.get("doi", "")).strip())
                if not prepared.get("source_id"):
                    prepared["source_id"] = f"live_record_{idx:05d}"
                prepared.setdefault("record_origin", "LIVE_API")
                yield prepared

    def iter_records(self) -> Iterator[Dict[str, Any]]:
        """Iterate static records followed by dynamic live records."""
        yield from self.static_records
        yield from self._iter_live_records()


def enrich_and_store_records(
    records_iterator: Iterable[Dict[str, Any]], output_filepath: Path
) -> List[Dict[str, Any]]:
    """
    Enrich records with full-sentence QMBD analysis and store cumulatively.
    """
    enriched_outputs: List[Dict[str, Any]] = []

    for record in records_iterator:
        serialized_subject_terms = _serialize_subject_terms(
            record.get("subject_terms", "")
        )
        full_text = (
            f"{record.get('title', '')}. "
            f"{record.get('description', '')}. "
            f"{serialized_subject_terms}"
        )
        sentences = extract_sentences(full_text)
        source_id = str(record.get("source_id", "unknown_doi"))
        record_classifications = _classify_sentence_contexts(sentences, source_id)
        enriched_record = dict(record)
        enriched_record["qmbd_analysis"] = record_classifications
        enriched_outputs.append(enriched_record)

    output_filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(output_filepath, "w", encoding="utf-8") as f:
        json.dump(enriched_outputs, f, indent=4, ensure_ascii=False)

    return enriched_outputs


def _serialize_subject_terms(subject_terms: Any) -> str:
    """Serialize subject terms into a deterministic string for sentence analysis."""
    if subject_terms is None:
        return ""
    if isinstance(subject_terms, list):
        return ", ".join(
            str(term).strip() for term in subject_terms if str(term).strip()
        )
    return str(subject_terms).strip()


def _build_static_qmbd_records(
    competences: List[Competence], record_origin: str
) -> List[Dict[str, Any]]:
    """Build static records from competences for the localized QMBD repository."""
    records: List[Dict[str, Any]] = []
    for competence in competences:
        source_identifier = competence.source.doi or competence.id
        records.append(
            {
                "source_id": source_identifier,
                "title": competence.name,
                "description": competence.description,
                "subject_terms": _serialize_subject_terms(competence.keywords),
                "axis_name": competence.axis.name,
                "sectors": competence.sectors,
                "record_origin": record_origin,
            }
        )
    return records


# ---------------------------------------------------------------------------
# Dimension → axis mapping for baseline competences
# ---------------------------------------------------------------------------
_DIM_TO_AXIS: Dict[str, TMBDAxis] = {
    "A": TMBDAxis.OCEANIC,  # Understanding / literacy → planetary
    "B": TMBDAxis.MARITIME,  # Digital / data → techno-economic
    "C": TMBDAxis.MARINE,  # Sustainability → ecological
    "D": TMBDAxis.MARITIME,  # Governance / business → institutional
}


# ---------------------------------------------------------------------------
# 1. Load baseline competences
# ---------------------------------------------------------------------------

BASELINE_CSV = (
    DATA_DERIVED
    / "Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv"
)
SECTOR_X_COMP_CSV = (
    DATA_DERIVED
    / "Blue Social Competences Univ Szczecin - Blue competences x blue economy sector.csv"
)


def load_baseline_competences() -> List[Competence]:
    """
    Load baseline Blue Social Competences from the University of Szczecin CSV.

    Source: data/derived/Blue Social Competences Univ Szczecin -
            Overall Blue Competences Dimension.csv

    Returns:
        List of Competence objects with TMBD axis assignments.
    """
    log.info("Loading baseline competences from University of Szczecin CSV…")
    competences: List[Competence] = []

    rel_path = BASELINE_CSV.relative_to(REPO_ROOT).as_posix()

    with open(BASELINE_CSV, encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        # Sector columns: index 4 onward
        sector_cols = header[4:]

        # row_num tracks the 1-based CSV row number; row 1 is the header.
        row_num = 1
        for row in reader:
            row_num += 1  # increment first so skipped rows still advance counter
            if len(row) < 4:
                continue
            comp_id = row[1].strip()
            comp_name = row[2].strip()
            focus = row[3].strip()
            if not comp_id or comp_id == "—" or not comp_name:
                continue

            dim_letter = comp_id.split(".")[0] if "." in comp_id else comp_id[0]
            axis = _DIM_TO_AXIS.get(dim_letter, TMBDAxis.OCEANIC)

            # Which sectors apply (marked with 'X')
            sectors: List[str] = []
            for i, sec in enumerate(sector_cols):
                cell = row[4 + i].strip().upper() if len(row) > 4 + i else ""
                if cell == "X":
                    sectors.append(sec)

            source = CompetenceSource(
                file=rel_path,
                row=row_num,
            )
            safe_id = re.sub(r"[^a-z0-9]", "_", comp_id.lower())
            competences.append(
                Competence(
                    id=f"baseline_{safe_id}",
                    name=comp_name,
                    description=focus,
                    axis=axis,
                    dimension=dim_letter,
                    source=source,
                    keywords=["blue-economy", "baseline", dim_letter.lower()],
                    sectors=sectors,
                )
            )

    log.info("  Loaded %d baseline competences.", len(competences))
    return competences


# ---------------------------------------------------------------------------
# 2. Extract literature-derived competences
# ---------------------------------------------------------------------------

# Competence themes derived from literature, grouped by axis
_LIT_THEMES: Dict[str, Dict[str, List[str]]] = {
    "labor_justice": {
        "MARITIME": [
            "Fair wage and labour rights in maritime sectors",
            "Seafarer welfare and social protection",
            "Gender equity and inclusion in blue workplaces",
            "Racial equity and anti-discrimination in blue economy",
            "Labour union organising and collective bargaining",
            "Occupational health and safety at sea",
            "Precarious work and informality in coastal fisheries",
            "Child labour and forced labour prevention in fisheries",
            "Decent work standards for aquaculture workers",
            "Migration and mobile labour in maritime industries",
        ],
        "OCEANIC": [
            "Blue justice frameworks and social sustainability",
            "Equitable benefit-sharing in ocean resource governance",
            "Community participation in marine spatial planning",
            "Indigenous and traditional fishing rights advocacy",
            "Social impact assessment for blue economy projects",
        ],
        "MARINE": [
            "Small-scale fisheries sustainability and livelihoods",
            "Artisanal fishing knowledge and ecological literacy",
        ],
    },
    "research_gaps": {
        "OCEANIC": [
            "Transdisciplinary ocean research co-production",
            "Knowledge transfer between science and ocean policy",
            "Integrated ocean observing and data governance",
            "Blue economy monitoring, evaluation and learning",
            "Ocean literacy and public engagement",
            "Science-policy interface in maritime governance",
            "Cross-border ocean research collaboration",
            "Open science and FAIR data in blue economy",
        ],
        "MARITIME": [
            "Blue economy innovation ecosystems and incubators",
            "Digital transformation of maritime industries",
            "Technology readiness for sustainable blue economy",
            "Maritime education and training gaps",
        ],
        "MARINE": [
            "Marine biodiversity monitoring and assessment",
            "Cumulative impacts on marine ecosystems",
            "Marine protected area design and effectiveness",
            "Blue carbon accounting and ecosystem services",
            "Coral reef and seagrass restoration science",
            "Deep-sea ecology and environmental safeguarding",
            "Marine noise pollution and acoustic ecology",
            "Plastic pollution monitoring in marine systems",
        ],
    },
    "blue_sociology": {
        "OCEANIC": [
            "Hydrosocial literacy and ocean citizenship",
            "Planetary boundary thinking in ocean governance",
            "Post-colonial perspectives in maritime sociology",
            "Oceanic subjectivity and cultural identities",
            "Cross-cultural maritime heritage management",
            "Sustainability transitions in coastal societies",
            "Social-ecological resilience of coastal communities",
        ],
        "MARITIME": [
            "Maritimisation processes and port-city relations",
            "Socio-technical transitions in shipping",
            "Labour geography of maritime transport",
            "Cultural dimensions of seafaring",
            "Coastal tourism and blue economy value chains",
        ],
        "MARINE": [
            "Marinisation of societies and biophysical coupling",
            "Ethnographic approaches to fishing communities",
            "Traditional ecological knowledge in fisheries governance",
        ],
    },
}


# ---------------------------------------------------------------------------
# Theme → sector mapping for literature competences
# ---------------------------------------------------------------------------
# Maps each theme cluster name to the blue economy sectors it primarily
# addresses. Themes absent from this dict fall back to SECTORS (cross-sector).
_THEME_SECTORS: Dict[str, List[str]] = {
    # labor_justice
    "Fair wage and labour rights in maritime sectors": [
        "Maritime Transport",
        "Port Activities",
        "Ship Repair",
        "Maritime Defence",
    ],
    "Seafarer welfare and social protection": [
        "Maritime Transport",
        "Maritime Defence",
        "Ship Repair",
    ],
    "Labour union organising and collective bargaining": [
        "Maritime Transport",
        "Port Activities",
        "Ship Repair",
    ],
    "Occupational health and safety at sea": [
        "Maritime Transport",
        "Maritime Defence",
        "Ship Repair",
        "Renewable Energy",
    ],
    "Precarious work and informality in coastal fisheries": [
        "Living Res.",
        "Coastal Tourism",
    ],
    "Child labour and forced labour prevention in fisheries": ["Living Res."],
    "Decent work standards for aquaculture workers": ["Living Res."],
    "Migration and mobile labour in maritime industries": [
        "Maritime Transport",
        "Port Activities",
        "Ship Repair",
    ],
    "Equitable benefit-sharing in ocean resource governance": [
        "Living Res.",
        "Non-living Res.",
        "Renewable Energy",
        "Blue Biotech",
    ],
    "Indigenous and traditional fishing rights advocacy": [
        "Living Res.",
        "Coastal Tourism",
    ],
    "Small-scale fisheries sustainability and livelihoods": [
        "Living Res.",
        "Coastal Tourism",
    ],
    "Artisanal fishing knowledge and ecological literacy": ["Living Res."],
    # research_gaps
    "Knowledge transfer between science and ocean policy": ["R&I"],
    "Integrated ocean observing and data governance": [
        "R&I",
        "Blue Biotech",
        "Non-living Res.",
    ],
    "Cross-border ocean research collaboration": ["R&I"],
    "Open science and FAIR data in blue economy": ["R&I", "Blue Biotech"],
    "Digital transformation of maritime industries": [
        "Maritime Transport",
        "Port Activities",
        "Ship Repair",
        "Infra & Robotics",
    ],
    "Technology readiness for sustainable blue economy": [
        "Infra & Robotics",
        "Renewable Energy",
        "Desalination",
    ],
    "Marine biodiversity monitoring and assessment": [
        "Blue Biotech",
        "Living Res.",
        "Non-living Res.",
        "R&I",
    ],
    "Cumulative impacts on marine ecosystems": [
        "Blue Biotech",
        "Living Res.",
        "Non-living Res.",
        "R&I",
        "Renewable Energy",
    ],
    "Marine protected area design and effectiveness": [
        "Living Res.",
        "Non-living Res.",
        "R&I",
        "Coastal Tourism",
    ],
    "Blue carbon accounting and ecosystem services": [
        "Blue Biotech",
        "Living Res.",
        "R&I",
        "Renewable Energy",
    ],
    "Coral reef and seagrass restoration science": [
        "Blue Biotech",
        "Living Res.",
        "R&I",
        "Coastal Tourism",
    ],
    "Deep-sea ecology and environmental safeguarding": [
        "Blue Biotech",
        "Non-living Res.",
        "R&I",
    ],
    "Marine noise pollution and acoustic ecology": [
        "Renewable Energy",
        "Living Res.",
        "R&I",
    ],
    "Plastic pollution monitoring in marine systems": [
        "Blue Biotech",
        "Living Res.",
        "R&I",
        "Coastal Tourism",
    ],
    # blue_sociology
    "Cross-cultural maritime heritage management": ["Coastal Tourism"],
    "Sustainability transitions in coastal societies": [
        "Coastal Tourism",
        "Living Res.",
        "Port Activities",
    ],
    "Social-ecological resilience of coastal communities": [
        "Coastal Tourism",
        "Living Res.",
        "Port Activities",
    ],
    "Maritimisation processes and port-city relations": [
        "Port Activities",
        "Maritime Transport",
    ],
    "Socio-technical transitions in shipping": ["Maritime Transport", "Ship Repair"],
    "Labour geography of maritime transport": ["Maritime Transport", "Port Activities"],
    "Cultural dimensions of seafaring": ["Maritime Transport", "Maritime Defence"],
    "Coastal tourism and blue economy value chains": [
        "Coastal Tourism",
        "Port Activities",
    ],
    "Ethnographic approaches to fishing communities": [
        "Living Res.",
        "Coastal Tourism",
    ],
    "Traditional ecological knowledge in fisheries governance": [
        "Living Res.",
        "Non-living Res.",
    ],
}


def _validate_theme_sectors() -> None:
    """Validate _THEME_SECTORS keys and values at import time.

    Raises:
        ValueError: if a key in _THEME_SECTORS does not match any theme in
            _LIT_THEMES, or if a sector value is not a canonical member of SECTORS.
    """
    all_themes: Set[str] = set()
    for axis_groups in _LIT_THEMES.values():
        for names in axis_groups.values():
            all_themes.update(names)

    bad_keys = [k for k in _THEME_SECTORS if k not in all_themes]
    if bad_keys:
        raise ValueError(
            "_THEME_SECTORS contains keys that do not match any theme in _LIT_THEMES: "
            + ", ".join(sorted(bad_keys))
        )

    sectors_set = set(SECTORS)
    bad_values: List[str] = []
    for theme, sector_list in _THEME_SECTORS.items():
        for sec in sector_list:
            if sec not in sectors_set:
                bad_values.append(f"{theme!r} → {sec!r}")
    if bad_values:
        raise ValueError(
            "_THEME_SECTORS contains sector names not in the canonical SECTORS list: "
            + "; ".join(bad_values)
        )


_validate_theme_sectors()


def _slugify(text: str) -> str:
    """Convert text to a safe identifier slug."""
    return cast(str, slugify(text, max_length=60))


def _normalize_title_for_dedup(title: str) -> str:
    """
    Normalize titles for cross-source deduplication.

    Rules:
      - convert to lowercase
      - replace non-word characters with spaces
      - collapse/strip surrounding whitespace
    """
    return re.sub(r"\W+", " ", title.lower()).strip()


def _infer_live_record_sectors(text: str, axis: TMBDAxis) -> List[str]:
    """Infer a narrow sector scope for a live record using existing theme maps.

    Strategy:
      1. Filter candidate themes to the detected TMBD axis only.
      2. Score each theme by token-overlap between record text and theme name.
      3. Select the highest-scoring theme; if all scores are zero, fall back to a
         deterministic axis-local theme (lexicographically first).
      4. Map the chosen theme to sectors via _THEME_SECTORS.
    """
    text_tokens = set(_TOKEN_PATTERN.findall(text.lower()))
    axis_theme_names: List[str] = []
    best_theme: Optional[str] = None
    best_score = 0

    for theme_pool in _LIT_THEMES.values():
        for axis_name, theme_names in theme_pool.items():
            if axis_name != axis.name:
                continue
            for theme_name in theme_names:
                axis_theme_names.append(theme_name)
                theme_tokens = set(_TOKEN_PATTERN.findall(theme_name.lower()))
                score = len(text_tokens & theme_tokens)
                if score > best_score:
                    best_score = score
                    best_theme = theme_name

    fallback_theme = sorted(axis_theme_names)[0] if len(axis_theme_names) > 0 else None
    chosen_theme = best_theme or fallback_theme
    if chosen_theme is None or chosen_theme not in _THEME_SECTORS:
        global_best_theme: Optional[str] = None
        global_best_score = 0
        for theme_name in _THEME_SECTORS:
            theme_tokens = set(_TOKEN_PATTERN.findall(theme_name.lower()))
            score = len(text_tokens & theme_tokens)
            if score > global_best_score:
                global_best_score = score
                global_best_theme = theme_name
        chosen_theme = global_best_theme if global_best_score > 0 else None
    selected_sectors = (
        _THEME_SECTORS.get(chosen_theme, SECTORS) if chosen_theme else SECTORS
    )
    return list(selected_sectors)


def _extract_live_sentence_classifications(
    row: Dict[str, object],
) -> List[Dict[str, object]]:
    """Return validated sentence-level live classifications from one payload row.

    Enforces the minimum FAIR/QMBD audit schema: each item must be a dict
    containing the axis metadata plus either a raw non-empty ``sentence`` or a
    persisted non-empty ``sentence_hash`` with positive ``sentence_length``.
    Incomplete or malformed items are silently dropped.
    """
    raw = row.get("sentence_classifications", [])
    if not isinstance(raw, list):
        return []
    _REQUIRED_KEYS: set[str] = {"axis", "axis_code", "text_scope"}
    valid: List[Dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict) or not _REQUIRED_KEYS.issubset(item.keys()):
            continue

        axis = item.get("axis")
        axis_code = item.get("axis_code")
        text_scope = item.get("text_scope")
        sentence = item.get("sentence")

        if not isinstance(axis, str):
            continue
        if not isinstance(axis_code, str):
            continue
        if not isinstance(text_scope, str):
            continue

        normalized_axis = axis.strip().upper()
        normalized_axis_code = axis_code.strip().upper()
        normalized_text_scope = text_scope.strip()

        if not normalized_text_scope:
            continue

        normalized_item = dict(item)
        normalized_item["axis"] = normalized_axis
        normalized_item["axis_code"] = normalized_axis_code
        normalized_item["text_scope"] = normalized_text_scope
        if isinstance(sentence, str) and sentence.strip():
            normalized_item["sentence"] = sentence.strip()
        else:
            sentence_hash = item.get("sentence_hash")
            sentence_length = item.get("sentence_length")
            if (
                not isinstance(sentence_hash, str)
                or not sentence_hash.strip()
                or not isinstance(sentence_length, int)
                or sentence_length <= 0
            ):
                continue
            normalized_item["sentence_hash"] = sentence_hash.strip()
            normalized_item["sentence_length"] = sentence_length
        valid.append(normalized_item)
    return valid


def _dominant_axis_from_live_sentence_classifications(
    sentence_classifications: List[Dict[str, object]],
) -> Optional[TMBDAxis]:
    """Resolve dominant axis from sentence-level live classifications."""
    axis_count: Dict[str, int] = {
        "MARINE": 0,
        "MARITIME": 0,
        "OCEANIC": 0,
        "HYDRONIZATION": 0,
    }
    for item in sentence_classifications:
        if not _sentence_classification_counts_as_evidence(dict(item)):
            continue
        axis_name = str(item.get("axis", "")).strip().upper()
        if axis_name in axis_count:
            axis_count[axis_name] += 1
    ranked = sorted(axis_count.items(), key=lambda pair: pair[1], reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return None
    top_score = ranked[0][1]
    tied_axes = [axis for axis, score in ranked if score == top_score]
    precedence = ("MARINE", "MARITIME", "HYDRONIZATION", "OCEANIC")
    for axis_name in precedence:
        if axis_name in tied_axes:
            return TMBDAxis.__members__.get(axis_name)
    return None


def extract_literature_competences() -> List[Competence]:
    """
    Extract competences from 3 literature CSV files:
      - combined_blue_economy_labor_justice.csv
      - combined_blue_economy_research_gaps.csv
      - combined_blue_sociology_results.csv

    Strategy:
      1. For each paper, detect TMBD axis via keyword matching on title + abstract.
      2. Map paper to the nearest theme cluster in _LIT_THEMES for that axis.
      3. Create a Competence object per unique paper, citing (file, row, authors, year).
         Competence name = "{theme_cluster}: {paper_title_excerpt}" to ensure
         each paper produces a uniquely-named and traceable competence.
      4. Deduplicate across files by normalised paper title (prevents counting
         the same paper twice if it appears in multiple CSVs).

    Returns:
        Deduplicated list of 200+ literature-derived Competence objects,
        each citing its source with a GitHub hyperlink to the CSV row.
    """
    log.info("Extracting literature-derived competences…")
    competences: List[Competence] = []
    # Deduplicate by normalised paper title across all three files
    seen_titles: Set[str] = set()

    for lit in LITERATURE_FILES:
        csv_path = DATA_DERIVED / lit["filename"]
        if not csv_path.exists():
            csv_path = DATA_RAW / lit["filename"]
        if not csv_path.exists():
            log.warning("  Literature file not found: %s — skipping.", lit["filename"])
            continue

        rel_path = csv_path.relative_to(REPO_ROOT).as_posix()
        theme_key = lit["theme"]
        default_axis = lit["primary_axis"]
        theme_pool = _LIT_THEMES.get(theme_key, {})

        # Build flattened list of (axis, theme_name) for round-robin assignment
        axis_themes: List[Tuple[str, str]] = []
        for ax, names in theme_pool.items():
            for n in names:
                axis_themes.append((ax, n))

        file_count = 0
        with open(csv_path, encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row_idx, row in enumerate(reader, start=2):
                title = row.get("Paper Title", "").strip()
                abstract = row.get("Abstract", "").strip()
                authors = row.get("Author Names", "").strip()
                year = row.get("Publication Year", "").strip()
                doi = row.get("DOI", "").strip()

                if not title:
                    continue

                # Deduplicate across files by normalised title
                norm_title = _normalize_title_for_dedup(title)
                if norm_title in seen_titles:
                    continue
                seen_titles.add(norm_title)

                # Detect axis from full-sentence context of title + abstract
                combined_text = f"{title}. {abstract}"
                source_identifier = doi or f"{theme_key}:{row_idx}"
                sentence_analysis = _classify_sentence_contexts(
                    extract_sentences(combined_text), source_identifier
                )
                detected_axis = _resolve_primary_axis_from_analysis(
                    sentence_analysis, default_axis=default_axis
                )

                # Pick the closest theme cluster from the pool for this axis
                candidate_themes = [
                    (ax, nm) for ax, nm in axis_themes if ax == detected_axis.name
                ]
                if not candidate_themes:
                    candidate_themes = axis_themes  # fallback: any theme

                # Assign theme deterministically using row index as cycle offset
                ax_name, theme_name = candidate_themes[row_idx % len(candidate_themes)]
                axis = _axis_from_name(ax_name, default_axis=detected_axis)

                # Competence name: theme cluster + paper title excerpt (unique per paper)
                title_short = title[:70].rstrip(",. ")
                comp_name = f"{theme_name}: {title_short}"

                source = CompetenceSource(
                    file=rel_path,
                    row=row_idx,
                    authors=authors[:120],
                    year=year,
                    paper_title=title[:120],
                    doi=doi,
                )

                # ID is unique per paper (theme_key + row index)
                comp_id = f"lit_{theme_key}_{row_idx:04d}"
                competences.append(
                    Competence(
                        id=comp_id,
                        name=comp_name,
                        description=(
                            f"Literature-derived competence (cluster: {theme_name}) "
                            f"from {lit['description']}. "
                            f"Source paper: {title[:120]} "
                            f"({authors[:60]}, {year})."
                        ),
                        axis=axis,
                        dimension="literature",
                        source=source,
                        keywords=[
                            theme_key,
                            ax_name.lower(),
                            "literature",
                            theme_name[:30],
                        ],
                        sectors=_THEME_SECTORS.get(theme_name, SECTORS),
                    )
                )
                file_count += 1

        log.info(
            "  [%s] %d competences (running total: %d).",
            lit["filename"],
            file_count,
            len(competences),
        )

    log.info("  Total literature competences: %d", len(competences))
    return competences


def extract_live_records_competences(
    live_records_path: Path,
    known_titles: Optional[Set[str]] = None,
) -> List[Competence]:
    """
    Convert Stage-1 live records JSON into literature-like competence objects.

    Args:
        live_records_path: Path to outputs/research_sources/live_records_triangulated.json.
        known_titles: Optional set of normalized titles to deduplicate against.

    Returns:
        List of competence objects derived from live API records.
    """
    if not live_records_path.exists():
        log.warning(
            "Live records file not found (%s) — skipping live enrichment.",
            live_records_path,
        )
        return []

    try:
        payload = json.loads(live_records_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(
            "Failed to parse live records JSON (%s): %s", live_records_path, exc
        )
        return []

    if not isinstance(payload, list):
        log.warning("Live records JSON must be a list: %s", live_records_path)
        return []

    seen_titles: Set[str] = set(known_titles or set())
    competences: List[Competence] = []
    try:
        rel_path = live_records_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        # Custom paths may live outside REPO_ROOT; keep source metadata usable.
        rel_path = live_records_path.resolve().as_posix()

    canonical_by_norm = {
        re.sub(r"[^a-z0-9]+", " ", sec.lower()).strip(): sec for sec in SECTORS
    }
    # start=2 aligns source row references with data-row indexing semantics.
    for idx, row in enumerate(payload, start=2):
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()
        if not title:
            continue
        norm_title = _normalize_title_for_dedup(title)
        if norm_title in seen_titles:
            continue
        seen_titles.add(norm_title)

        authors = str(row.get("authors", "")).strip()
        year = str(row.get("year", "")).strip()
        doi = str(row.get("doi", "")).strip()
        provider = str(row.get("provider", "")).strip() or "Unknown"
        claim_origin = str(row.get("source", "")).strip()
        overlap_status = str(row.get("overlap_status", "")).strip()
        confidence_score = row.get("confidence_score")
        journal = str(row.get("journal", "")).strip()
        abstract = str(row.get("abstract", "")).strip()
        subject_terms = row.get("subject_terms", [])
        if not isinstance(subject_terms, list):
            subject_terms = [str(subject_terms)] if subject_terms else []
        sentence_classifications = _extract_live_sentence_classifications(row)
        combined_text = " ".join(
            [title, abstract, journal] + [str(t).strip() for t in subject_terms]
        ).strip()
        axis = _dominant_axis_from_live_sentence_classifications(
            sentence_classifications
        )
        if axis is None:
            source_identifier = doi or f"{provider}:{idx}"
            sentence_analysis = _classify_sentence_contexts(
                extract_sentences(combined_text), source_identifier
            )
            axis = _resolve_primary_axis_from_analysis(
                sentence_analysis, default_axis="OCEANIC"
            )
        supplied_sectors: List[str] = []
        raw_sectors = row.get("sectors") or row.get("sector")
        candidates: List[str] = []
        if isinstance(raw_sectors, list):
            candidates = [
                str(item).strip() for item in raw_sectors if str(item).strip()
            ]
        elif isinstance(raw_sectors, str) and raw_sectors.strip():
            candidates = [raw_sectors.strip()]
        for candidate in candidates:
            norm = re.sub(r"[^a-z0-9]+", " ", candidate.lower()).strip()
            canonical = canonical_by_norm.get(norm)
            if canonical and canonical not in supplied_sectors:
                supplied_sectors.append(canonical)
        sectors = supplied_sectors or _infer_live_record_sectors(combined_text, axis)

        source = CompetenceSource(
            file=rel_path,
            row=idx,
            authors=authors[:120],
            year=year,
            paper_title=title[:120],
            doi=doi,
        )
        comp_id = f"lit_live_{_slugify(provider)}_{idx:05d}"
        confidence_text = (
            f" confidence={confidence_score:.2f}."
            if isinstance(confidence_score, (int, float))
            else ""
        )
        source_text = f" claim_origin={claim_origin}." if claim_origin else ""
        overlap_text = f" overlap={overlap_status}." if overlap_status else ""
        sentence_text = (
            f" sentence_classifications={len(sentence_classifications)}."
            if sentence_classifications
            else ""
        )
        competences.append(
            Competence(
                id=comp_id,
                name=f"Live API ({provider}): {title[:70].rstrip(',. ')}",
                description=(
                    "Live-API-derived literature competence from provider "
                    f"{provider}.{source_text}{overlap_text}{confidence_text}{sentence_text} "
                    f"Source paper: {title[:120]} ({authors[:60]}, {year})."
                ),
                axis=axis,
                dimension="literature",
                source=source,
                keywords=[
                    "live-api",
                    _slugify(provider),
                    _slugify(claim_origin) if claim_origin else "claim-origin-unknown",
                    _slugify(overlap_status) if overlap_status else "overlap-unknown",
                    axis.name.lower(),
                    "literature",
                ],
                sectors=sectors,
            )
        )

    log.info("  Live API competences: %d", len(competences))
    return competences


# ---------------------------------------------------------------------------
# 3. Gap analysis
# ---------------------------------------------------------------------------


def run_gap_analysis(
    baseline: List[Competence],
    literature: List[Competence],
) -> Tuple[Dict[str, GapAnalysis], Dict[str, List[Competence]]]:
    """
    Run competence gap analysis for all 12 blue economy sectors.

    For each sector:
      - required: baseline competences that list that sector + literature
                  competences whose sectors field includes that sector
      - available: baseline competences for that sector
      - missing: required − available

    Args:
        baseline: 15 University of Szczecin baseline competences
        literature: literature-derived competences (sector-specific via _THEME_SECTORS)

    Returns:
        Tuple of:
          - gaps dict: sector → GapAnalysis
          - sector_comps dict: sector → list of required Competence objects
    """
    log.info("Running gap analysis for %d sectors…", len(SECTORS))

    # Build lookup by ID
    all_comps: Dict[str, Competence] = {}
    for c in baseline + literature:
        all_comps[c.id] = c

    gaps: Dict[str, GapAnalysis] = {}
    sector_comps: Dict[str, List[Competence]] = {}

    for sector in SECTORS:
        # Required: baseline comps that include this sector + literature comps
        # that explicitly list this sector in their sectors field.
        required_ids: List[str] = []
        for c in baseline:
            if sector in c.sectors:
                required_ids.append(c.id)
        for c in literature:
            if sector in c.sectors:
                required_ids.append(c.id)

        # Available: baseline competences for this sector
        available_ids = [c.id for c in baseline if sector in c.sectors]

        missing_ids = [rid for rid in required_ids if rid not in set(available_ids)]

        gap_pct = 100.0 * len(missing_ids) / len(required_ids) if required_ids else 0.0

        # Break down missing by TMBD axis
        by_axis: Dict[str, List[str]] = {ax.name: [] for ax in TMBDAxis}
        for mid in missing_ids:
            if mid in all_comps:
                by_axis[all_comps[mid].axis.name].append(mid)

        gaps[sector] = GapAnalysis(
            sector=sector,
            required_ids=required_ids,
            available_ids=available_ids,
            missing_ids=missing_ids,
            gap_pct=gap_pct,
            by_axis=by_axis,
        )
        sector_comps[sector] = [
            all_comps[rid] for rid in required_ids if rid in all_comps
        ]

    log.info("  Gap analysis complete.")
    return gaps, sector_comps


# ---------------------------------------------------------------------------
# 4. Micro-credential generation
# ---------------------------------------------------------------------------

_SECTOR_LEARNER_PROFILES: Dict[str, str] = {
    "Blue Biotech": (
        "Early-career marine biologists, biochemists, and biotech graduates seeking "
        "competences in marine bioresource commercialisation."
    ),
    "Coastal Tourism": (
        "Tourism and hospitality professionals operating in coastal zones who wish to "
        "integrate blue sustainability and stakeholder engagement."
    ),
    "Desalination": (
        "Water engineers and environmental planners working on desalination projects "
        "in water-scarce coastal regions."
    ),
    "Infra & Robotics": (
        "Ocean engineers and robotics specialists involved in subsea infrastructure "
        "and autonomous systems deployment."
    ),
    "Living Res.": (
        "Fisheries managers, aquaculture operators, and coastal community leaders "
        "managing living marine resources."
    ),
    "Non-living Res.": (
        "Geologists, mining engineers, and environmental officers working on seabed "
        "mineral extraction projects."
    ),
    "Renewable Energy": (
        "Energy sector professionals, policy makers, and spatial planners working on "
        "offshore wind, wave, and tidal energy."
    ),
    "Maritime Defence": (
        "Naval officers and civil-maritime security professionals involved in coast "
        "guard, EUROSUR, and maritime domain awareness."
    ),
    "Maritime Transport": (
        "Shipping company officers, decarbonisation managers, and port logistics "
        "specialists transitioning to low-emission transport."
    ),
    "Port Activities": (
        "Port authority managers, logistics coordinators, and smart-port technology "
        "specialists."
    ),
    "R&I": (
        "Academic researchers, science-policy liaisons, and innovation officers in "
        "blue economy research institutions."
    ),
    "Ship Repair": (
        "Naval architects, shipyard engineers, and sustainable-ship-design specialists "
        "focused on green retrofitting."
    ),
}

_SECTOR_ASSESSMENT: Dict[str, str] = {
    "Blue Biotech": "Portfolio of bioprospecting case study + oral defence",
    "Coastal Tourism": "Sustainable tourism action plan + stakeholder workshop facilitation",
    "Desalination": "Technical feasibility report + environmental impact summary",
    "Infra & Robotics": "AUV/ROV simulation exercise + technical report",
    "Living Res.": "Fisheries stock assessment practical + governance essay",
    "Non-living Res.": "Seabed mining impact assessment + regulatory compliance plan",
    "Renewable Energy": "MSP spatial conflict analysis + offshore energy business case",
    "Maritime Defence": "Maritime security scenario exercise + policy brief",
    "Maritime Transport": "Decarbonisation pathway analysis + IMO compliance audit",
    "Port Activities": "Smart-port logistics simulation + sustainability report",
    "R&I": "Literature review + FAIR data management plan",
    "Ship Repair": "Green retrofit specification + lifecycle cost analysis",
}


def generate_micro_credentials(
    baseline: List[Competence],
    literature: List[Competence],
    gaps: Dict[str, GapAnalysis],
) -> List[MicroCredential]:
    """
    Auto-generate micro-credentials for each of the 12 sectors using
    baseline + literature competences.  Applies the 9-field template.

    Stackability rule: EQF4 credential is prerequisite for EQF5,
    EQF5 is prerequisite for EQF6, EQF6 for EQF7.

    Args:
        baseline: baseline competence objects
        literature: literature-derived competence objects
        gaps: gap analysis results per sector

    Returns:
        List of MicroCredential objects with full metadata.
    """
    log.info("Generating micro-credentials for %d sectors…", len(SECTORS))

    all_comps: Dict[str, Competence] = {}
    for c in baseline + literature:
        all_comps[c.id] = c

    credentials: List[MicroCredential] = []
    # Track EQF4 credential IDs per sector for stackability
    eqf4_ids: Dict[str, str] = {}
    eqf5_ids: Dict[str, str] = {}
    eqf6_ids: Dict[str, str] = {}

    missing_gaps = [sector for sector in SECTORS if sector not in gaps]
    if missing_gaps:
        raise ValueError(
            "Gap analysis missing sectors needed for credential generation: "
            + ", ".join(sorted(missing_gaps))
        )

    for sector in SECTORS:
        slug = SECTOR_SLUG[sector]
        gap = gaps[sector]

        # Select competences from the same sector-aware pool used by gap analysis:
        # available baseline competences + first 5 literature competences
        # required for this sector.
        base_ids = gap.available_ids[:8]
        sector_lit_ids = [
            cid
            for cid in gap.required_ids
            if cid in all_comps and all_comps[cid].dimension == "literature"
        ]
        lit_ids = sector_lit_ids[:5]
        # dict.fromkeys preserves order while deduplicating IDs
        comp_ids = list(dict.fromkeys(base_ids + lit_ids))

        learner_profile = _SECTOR_LEARNER_PROFILES.get(
            sector, "Blue economy practitioners"
        )
        assessment = _SECTOR_ASSESSMENT.get(sector, "Portfolio and oral examination")

        # --- EQF 4: Foundational credential ---
        eqf4_comp_ids = [cid for cid in comp_ids[:4] if cid in all_comps]
        eqf4_id = f"mc_{slug}_eqf4"
        eqf4_ids[sector] = eqf4_id
        credentials.append(
            MicroCredential(
                id=eqf4_id,
                title=f"Blue Economy Foundations — {sector}",
                competences=eqf4_comp_ids,
                description=(
                    f"Introductory credential covering foundational competences for "
                    f"the {sector} sector of the EU Blue Economy."
                ),
                sector=sector,
                ects=3.0,
                eqf_level=EQFLevel.EQF4,
                assessment_method=f"Written test + reflective journal ({assessment})",
                prerequisites=[],
                learner_profile=learner_profile,
                learning_outcomes=[
                    f"Identify key TMBD axes relevant to {sector}",
                    "Apply ocean literacy principles to professional context",
                    "Navigate basic blue economy regulatory framework",
                    "Use foundational digital tools for sector data management",
                ],
                stackability_rules=(
                    f"This EQF 4 credential is a prerequisite for "
                    f"'Blue Economy Professional — {sector}' (EQF 5). "
                    f"Stackable within the Blue Economy Competence Framework."
                ),
            )
        )

        # --- EQF 5: Professional credential ---
        eqf5_comp_ids = [cid for cid in comp_ids[:6] if cid in all_comps]
        eqf5_id = f"mc_{slug}_eqf5"
        eqf5_ids[sector] = eqf5_id
        credentials.append(
            MicroCredential(
                id=eqf5_id,
                title=f"Blue Economy Professional — {sector}",
                competences=eqf5_comp_ids,
                description=(
                    f"Professional-level credential developing applied competences "
                    f"for practitioners in the {sector} sector."
                ),
                sector=sector,
                ects=6.0,
                eqf_level=EQFLevel.EQF5,
                assessment_method=assessment,
                prerequisites=[eqf4_id],
                learner_profile=learner_profile,
                learning_outcomes=[
                    f"Apply systems thinking to {sector} challenges",
                    "Implement sustainable resource management in sector context",
                    "Design participatory stakeholder engagement processes",
                    "Analyse TMBD interactions in sector-specific case studies",
                    "Deploy digital and data tools for sector monitoring",
                ],
                stackability_rules=(
                    f"Requires EQF 4 credential '{eqf4_id}'. "
                    f"Is a prerequisite for 'Blue Economy Expert — {sector}' (EQF 6)."
                ),
            )
        )

        # --- EQF 6: Expert credential ---
        eqf6_comp_ids = [cid for cid in comp_ids if cid in all_comps]
        eqf6_id = f"mc_{slug}_eqf6"
        eqf6_ids[sector] = eqf6_id
        credentials.append(
            MicroCredential(
                id=eqf6_id,
                title=f"Blue Economy Expert — {sector}",
                competences=eqf6_comp_ids,
                description=(
                    f"Expert-level credential for senior practitioners leading "
                    f"innovation, governance, and sustainability in {sector}."
                ),
                sector=sector,
                ects=9.0,
                eqf_level=EQFLevel.EQF6,
                assessment_method=(f"Research project + policy brief + {assessment}"),
                prerequisites=[eqf5_id],
                learner_profile=(
                    f"Experienced {sector} professionals (≥3 years) seeking "
                    f"EQF 6 recognition for leadership and strategic roles."
                ),
                learning_outcomes=[
                    f"Lead strategic planning for {sector} organisations",
                    "Integrate blue justice and equity into governance frameworks",
                    "Design and evaluate marine spatial plans",
                    "Manage cross-sector blue economy partnerships",
                    "Apply advanced quantitative and qualitative research methods",
                    "Develop and pilot micro-credential learning pathways",
                ],
                stackability_rules=(
                    f"Requires EQF 5 credential '{eqf5_id}'. "
                    f"Is a prerequisite for 'Blue Economy Leadership — {sector}' (EQF 7)."
                ),
            )
        )

        # --- EQF 7: Leadership credential ---
        eqf7_id = f"mc_{slug}_eqf7"
        credentials.append(
            MicroCredential(
                id=eqf7_id,
                title=f"Blue Economy Leadership — {sector}",
                competences=eqf6_comp_ids,  # same pool, advanced application
                description=(
                    f"Master-level leadership credential for policy makers, "
                    f"researchers, and senior executives shaping the future of {sector}."
                ),
                sector=sector,
                ects=12.0,
                eqf_level=EQFLevel.EQF7,
                assessment_method=(
                    "Thesis (5,000 words) on a cross-sector blue economy challenge "
                    f"+ international conference presentation relating to {sector}"
                ),
                prerequisites=[eqf6_id],
                learner_profile=(
                    f"Senior {sector} leaders, researchers, and policy makers "
                    f"with EQF 6 qualification seeking master-level recognition."
                ),
                learning_outcomes=[
                    "Synthesise TMBD theory with empirical blue economy evidence",
                    f"Design transdisciplinary governance frameworks for {sector}",
                    "Lead international blue economy negotiations and partnerships",
                    "Publish evidence-based blue economy policy recommendations",
                    "Mentor the next generation of blue economy professionals",
                ],
                stackability_rules=(
                    f"Requires EQF 6 credential '{eqf6_id}'. "
                    "Top of the Blue Economy Competence Framework stackability ladder."
                ),
            )
        )

    log.info("  Generated %d micro-credentials.", len(credentials))
    return credentials


# ---------------------------------------------------------------------------
# 5. Sector transition pathways
# ---------------------------------------------------------------------------


def compute_sector_pathways(
    credentials: List[MicroCredential],
    baseline: List[Competence],
) -> List[SectorPathway]:
    """
    Compute sector-to-sector transition pathways by identifying
    'bridge' competences and credentials shared across sectors.

    Args:
        credentials: list of all generated micro-credentials
        baseline: baseline competence objects

    Returns:
        List of SectorPathway objects (N×N-1 directed pairs).
    """
    log.info("Computing sector transition pathways…")

    # Map sector → set of competence IDs (from baseline)
    sector_comp_sets: Dict[str, Set[str]] = {}
    for sector in SECTORS:
        sector_comp_sets[sector] = {c.id for c in baseline if sector in c.sectors}

    # Map sector → set of EQF5 credential IDs
    sector_cred_map: Dict[str, List[str]] = {s: [] for s in SECTORS}
    for cred in credentials:
        if cred.sector in sector_cred_map:
            sector_cred_map[cred.sector].append(cred.id)

    pathways: List[SectorPathway] = []

    for i, from_sec in enumerate(SECTORS):
        for j, to_sec in enumerate(SECTORS):
            if i == j:
                continue
            bridge_comps = sorted(sector_comp_sets[from_sec] & sector_comp_sets[to_sec])
            bridge_creds: List[str] = []
            # Include EQF5 credentials from the source sector as bridge
            for cid in sector_cred_map.get(from_sec, []):
                if "eqf5" in cid:
                    bridge_creds.append(cid)

            pathways.append(
                SectorPathway(
                    from_sector=from_sec,
                    to_sector=to_sec,
                    bridge_competences=bridge_comps,
                    bridge_credentials=bridge_creds,
                )
            )

    log.info("  Computed %d sector transition pathways.", len(pathways))
    return pathways


# ---------------------------------------------------------------------------
# 6. Export CSV and JSON databases
# ---------------------------------------------------------------------------


def export_gaps_summary_csv(
    gaps: Dict[str, GapAnalysis],
    output_path: Path,
) -> None:
    """Export gaps_summary.csv with gap percentages by sector."""
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "Sector",
                "Required",
                "Available",
                "Missing",
                "Gap %",
                "Missing MARINE",
                "Missing MARITIME",
                "Missing OCEANIC",
            ]
        )
        for sector in SECTORS:
            g = gaps[sector]
            writer.writerow(
                [
                    sector,
                    len(g.required_ids),
                    len(g.available_ids),
                    len(g.missing_ids),
                    f"{g.gap_pct:.1f}",
                    len(g.by_axis.get("MARINE", [])),
                    len(g.by_axis.get("MARITIME", [])),
                    len(g.by_axis.get("OCEANIC", [])),
                ]
            )
    log.info("  Exported: %s", output_path)


def export_competences_json(
    baseline: List[Competence],
    literature: List[Competence],
    output_path: Path,
) -> None:
    """Export full competences database as JSON."""
    total_count = len(baseline) + len(literature)
    data = {
        "metadata": {
            "total": total_count,
            "baseline_count": len(baseline),
            "literature_count": len(literature),
            "axes": {ax.name: ax.value for ax in TMBDAxis},
            "source": "University of Szczecin Blue Social Competences + literature review",
        },
        "baseline": [c.to_dict() for c in baseline],
        "literature": [c.to_dict() for c in literature],
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    log.info("  Exported: %s (%d competences)", output_path, total_count)


def export_credentials_json(
    credentials: List[MicroCredential],
    output_path: Path,
) -> None:
    """Export full credentials database as JSON."""
    data = {
        "metadata": {
            "total": len(credentials),
            "sectors": len(SECTORS),
            "eqf_levels": [4, 5, 6, 7],
        },
        "credentials": [c.to_dict() for c in credentials],
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    log.info("  Exported: %s (%d credentials)", output_path, len(credentials))


def export_pathways_json(
    pathways: List[SectorPathway],
    output_path: Path,
) -> None:
    """Export sector transition pathways as JSON."""
    data = {
        "metadata": {"total_pathways": len(pathways), "sectors": SECTORS},
        "pathways": [
            {
                "from_sector": p.from_sector,
                "to_sector": p.to_sector,
                "bridge_competences": p.bridge_competences,
                "bridge_credentials": p.bridge_credentials,
            }
            for p in pathways
        ],
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    log.info("  Exported: %s (%d pathways)", output_path, len(pathways))


def export_sector_dictionaries(
    competences: List[Competence], sectors: List[str], output_dir: Path
) -> List[Path]:
    """
    Export one sector TMBD dictionary JSON per requested sector.

    Input may include mixed provenance (baseline + literature). In this helper,
    ``MixedProvenanceCompetenceRepository`` wraps the provided extractor output, while
    literature-only selection is applied during sector-dictionary construction
    before grouping by TMBD axis (MARINE, MARITIME, OCEANIC). This helper is
    intended for single-use pipeline export in ``main()``. Files follow the
    ``<lowercase_underscore_sector>_tmbd_dictionary.json`` naming convention,
    and returned
    paths preserve the order of the input ``sectors`` list.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    def extractor() -> Sequence[CompetenceLike]:
        return cast(Sequence[CompetenceLike], competences)

    repository = MixedProvenanceCompetenceRepository(extractor)
    exported_paths: List[Path] = []

    for sector in sectors:
        grouped = build_sector_dictionary_from_repository(repository, sector=sector)
        output_path = export_sector_dictionary(
            sector=sector, grouped=grouped, output_dir=output_dir
        )
        exported_paths.append(output_path)

    return exported_paths


# ---------------------------------------------------------------------------
# 7. HTML report generation
# ---------------------------------------------------------------------------

_HTML_HEAD = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 0;
          background: #f0f4f8; color: #222; }}
  header {{ background: #003366; color: #fff; padding: 1.2rem 2rem; }}
  header h1 {{ margin: 0; font-size: 1.6rem; }}
  header p {{ margin: 0.3rem 0 0; opacity: 0.85; font-size: 0.95rem; }}
  nav {{ background: #005599; padding: 0.5rem 2rem; }}
  nav a {{ color: #cce; margin-right: 1.2rem; text-decoration: none;
            font-size: 0.9rem; }}
  nav a:hover {{ color: #fff; text-decoration: underline; }}
  main {{ padding: 1.5rem 2rem; }}
  h2 {{ color: #003366; border-bottom: 2px solid #cce; padding-bottom: 0.3rem; }}
  h3 {{ color: #005599; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem;
           font-size: 0.88rem; }}
  th {{ background: #003366; color: #fff; padding: 0.5rem 0.7rem;
        text-align: left; }}
  td {{ padding: 0.4rem 0.7rem; border-bottom: 1px solid #dde; }}
  tr:nth-child(even) {{ background: #eef3f8; }}
  .badge-M {{ background: #1a7a4a; color: #fff; border-radius: 4px;
               padding: 2px 6px; font-size: 0.78rem; }}
  .badge-T {{ background: #1a4a8a; color: #fff; border-radius: 4px;
               padding: 2px 6px; font-size: 0.78rem; }}
  .badge-O {{ background: #6a1a8a; color: #fff; border-radius: 4px;
               padding: 2px 6px; font-size: 0.78rem; }}
  .badge-H {{ background: #8a5a1a; color: #fff; border-radius: 4px;
               padding: 2px 6px; font-size: 0.78rem; }}
  .card {{ background: #fff; border: 1px solid #cce; border-radius: 6px;
           padding: 1rem 1.2rem; margin-bottom: 1rem;
           box-shadow: 0 1px 4px rgba(0,0,50,0.07); }}
  .card h3 {{ margin-top: 0; }}
  .gap-bar {{ height: 10px; border-radius: 5px;
              background: linear-gradient(to right, #c0392b, #f39c12); }}
  .bar-bg {{ background: #dde; border-radius: 5px; height: 10px;
             margin: 4px 0 8px; }}
  a {{ color: #005599; }}
  footer {{ text-align: center; font-size: 0.8rem; color: #888;
            padding: 1.5rem; border-top: 1px solid #cce; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <p>{subtitle}</p>
</header>
<nav>
  <a href="report_index.html">🏠 Index</a>
  <a href="gaps_by_sector.html">📊 Gap Analysis</a>
  <a href="credentials_matrix.html">🎓 Credentials</a>
  <a href="literature_integration.html">📚 Literature</a>
</nav>
<main>
"""

_HTML_FOOT = """\
</main>
<footer>
  Blue Sociology — morskamary evidence base &nbsp;|&nbsp;
  <a href="{repo_url}">GitHub Repository</a> &nbsp;|&nbsp;
  Generated by run_full_analysis.py
</footer>
</body>
</html>
"""


def _axis_badge(axis: TMBDAxis) -> str:
    cls = {
        "MARINE": "M",
        "MARITIME": "T",
        "OCEANIC": "O",
        "HYDRONIZATION": "H",
    }[axis.name]
    return f'<span class="badge-{cls}">{axis.value} {axis.name}</span>'


def generate_report_index(
    baseline: List[Competence],
    literature: List[Competence],
    gaps: Dict[str, GapAnalysis],
    credentials: List[MicroCredential],
    output_path: Path,
    *,
    analysis_input_mode: str = "static",
    static_literature_count: Optional[int] = None,
    live_enrichment_count: Optional[int] = None,
) -> None:
    """Generate master report index HTML."""
    total_comps = len(baseline) + len(literature)
    avg_gap = sum(g.gap_pct for g in gaps.values()) / max(1, len(gaps))
    static_count = (
        int(static_literature_count)
        if static_literature_count is not None
        else len(literature)
    )
    live_count = (
        int(live_enrichment_count)
        if live_enrichment_count is not None
        else max(0, len(literature) - static_count)
    )

    baseline_csv_url = (
        f"{REPO_GITHUB_BASE}/data/derived/"
        "Blue%20Social%20Competences%20Univ%20Szczecin%20"
        "-%20Overall%20Blue%20Competences%20Dimension.csv"
    )
    live_records_url = (
        f"{REPO_GITHUB_BASE}/outputs/research_sources/live_records_triangulated.json"
    )
    live_coverage_url = (
        f"{REPO_GITHUB_BASE}/outputs/research_sources/live_source_coverage.csv"
    )

    html = _HTML_HEAD.format(
        title="Blue Economy Analysis — Master Report Index",
        subtitle="Competence Gap Analysis & Micro-Credential Design | morskamary",
    )
    competence_breakdown = (
        f"{len(baseline)} baseline + {len(literature)} literature-derived"
    )
    if analysis_input_mode == "live-enriched":
        competence_breakdown = (
            f"{len(baseline)} baseline + {static_count} static literature + "
            f"{live_count} live-enriched"
        )
    html += f"""
<h2>Summary Dashboard</h2>
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-bottom:1.5rem">
  <div class="card"><h3>📋 Competences</h3><p style="font-size:2rem;margin:0">{total_comps}</p>
    <p>{competence_breakdown}</p></div>
  <div class="card"><h3>🎓 Credentials</h3><p style="font-size:2rem;margin:0">{len(credentials)}</p>
    <p>{len(SECTORS)} sectors × 4 EQF levels</p></div>
  <div class="card"><h3>🏭 Sectors</h3><p style="font-size:2rem;margin:0">{len(SECTORS)}</p>
    <p>EU Blue Economy sectors analysed</p></div>
  <div class="card"><h3>⚠️ Avg Gap</h3><p style="font-size:2rem;margin:0">{avg_gap:.1f}%</p>
    <p>Average competence gap across sectors</p></div>
</div>

<h2>Data Sources</h2>
<table>
  <tr><th>File</th><th>Type</th><th>Count</th><th>GitHub Link</th></tr>
  <tr>
    <td>Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv</td>
    <td>Baseline</td><td>{len(baseline)}</td>
    <td><a href="{baseline_csv_url}" target="_blank">View on GitHub</a></td>
  </tr>
"""
    for lit in LITERATURE_FILES:
        lit_comps = [c for c in literature if lit["theme"] in c.id]
        html += f"""  <tr>
    <td>{lit["filename"]}</td>
    <td>Literature</td><td>{len(lit_comps)}</td>
    <td><a href="{REPO_GITHUB_BASE}/data/derived/{lit["filename"].replace(" ", "%20")}" target="_blank">View on GitHub</a></td>
  </tr>
"""
    if analysis_input_mode == "live-enriched":
        html += f"""  <tr>
    <td>outputs/research_sources/live_records_triangulated.json</td>
    <td>Live</td><td>{live_count}</td>
    <td><a href="{live_records_url}" target="_blank">View on GitHub</a></td>
  </tr>
  <tr>
    <td>outputs/research_sources/live_source_coverage.csv</td>
    <td>Live</td><td>{len(SECTORS)}</td>
    <td><a href="{live_coverage_url}" target="_blank">View on GitHub</a></td>
  </tr>
"""
        if live_count == 0:
            html += (
                "<tr><td colspan='4'>"
                "Live-enriched mode requested, but zero live records were ingested."
                "</td></tr>\n"
            )
    html += "</table>\n"

    html += "<h2>Sector Gap Overview</h2>\n"
    html += "<table>\n"
    axis_columns = ["MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION"]
    axis_header = "".join(f"<th>{name}</th>" for name in axis_columns)
    html += (
        "<tr><th>Sector</th><th>Required</th><th>Available</th>"
        f"<th>Missing</th><th>Gap %</th>{axis_header}</tr>\n"
    )
    for sector in SECTORS:
        g = gaps[sector]
        axis_counts = [len(g.by_axis.get(axis, [])) for axis in axis_columns]
        axis_cells = "".join(f"<td>{count}</td>" for count in axis_counts)
        html += (
            f"<tr><td><a href='gaps_by_sector.html#{SECTOR_SLUG[sector]}'>{_html_module.escape(sector)}</a></td>"
            f"<td>{len(g.required_ids)}</td><td>{len(g.available_ids)}</td>"
            f"<td>{len(g.missing_ids)}</td><td>{g.gap_pct:.1f}%</td>"
            f"{axis_cells}</tr>\n"
        )
    html += "</table>\n"

    html += _HTML_FOOT.format(
        repo_url="https://github.com/robertbartlomiejski/morskamary"
    )

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    log.info("  Generated: %s", output_path)


def generate_gaps_html(
    gaps: Dict[str, GapAnalysis],
    all_comps: Dict[str, Competence],
    output_path: Path,
) -> None:
    """Generate interactive gap analysis HTML report."""
    html = _HTML_HEAD.format(
        title="Competence Gap Analysis by Sector",
        subtitle="Required vs Available vs Missing — TMBD Axis Breakdown",
    )

    for sector in SECTORS:
        g = gaps[sector]
        slug = SECTOR_SLUG[sector]
        html += f'<h2 id="{slug}">{_html_module.escape(sector)}</h2>\n'
        html += f'<div class="bar-bg"><div class="gap-bar" style="width:{g.gap_pct:.0f}%"></div></div>\n'
        html += (
            f"<p>Gap: <strong>{g.gap_pct:.1f}%</strong> &nbsp;|&nbsp; "
            f"Required: {len(g.required_ids)} &nbsp;|&nbsp; "
            f"Available: {len(g.available_ids)} &nbsp;|&nbsp; "
            f"Missing: {len(g.missing_ids)}</p>\n"
        )

        html += "<h3>TMBD Axis Breakdown of Missing Competences</h3>\n"
        html += "<table>\n"
        html += (
            "<tr><th>Axis</th><th>Missing Count</th><th>Example Competences</th></tr>\n"
        )
        for ax in TMBDAxis:
            ax_missing = g.by_axis.get(ax.name, [])
            examples = ", ".join(
                _html_module.escape(all_comps[mid].name)
                for mid in ax_missing[:3]
                if mid in all_comps
            )
            html += (
                f"<tr><td>{_axis_badge(ax)}</td>"
                f"<td>{len(ax_missing)}</td>"
                f"<td>{examples}</td></tr>\n"
            )
        html += "</table>\n"

        # Show top 5 missing competences
        if g.missing_ids:
            html += "<h3>Top Missing Competences</h3>\n"
            html += "<table>\n"
            html += "<tr><th>ID</th><th>Name</th><th>Axis</th><th>Source</th></tr>\n"
            for mid in g.missing_ids[:10]:
                if mid not in all_comps:
                    continue
                c = all_comps[mid]
                html += (
                    f"<tr><td><code>{_html_module.escape(c.id)}</code></td>"
                    f"<td>{_html_module.escape(c.name)}</td>"
                    f"<td>{_axis_badge(c.axis)}</td>"
                    f"<td><a href='{c.source.github_url}' target='_blank'>"
                    f"{_html_module.escape(Path(c.source.file).name)}#L{c.source.row}</a></td></tr>\n"
                )
            html += "</table>\n"

    html += _HTML_FOOT.format(
        repo_url="https://github.com/robertbartlomiejski/morskamary"
    )
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    log.info("  Generated: %s", output_path)


def generate_credentials_html(
    credentials: List[MicroCredential],
    output_path: Path,
) -> None:
    """Generate micro-credential matrix HTML with stackability cards."""
    html = _HTML_HEAD.format(
        title="Micro-Credential Matrix",
        subtitle="Auto-generated credentials with EQF levels, ECTS, assessment & stackability",
    )

    for sector in SECTORS:
        slug = SECTOR_SLUG[sector]
        sector_creds = [c for c in credentials if c.sector == sector]
        html += f'<h2 id="{slug}">{_html_module.escape(sector)}</h2>\n'
        html += (
            '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:1rem">\n'
        )

        for cred in sector_creds:
            prereq_links = (
                ", ".join(
                    f"<code>{_html_module.escape(p)}</code>" for p in cred.prerequisites
                )
                or "None"
            )
            outcomes_html = "".join(
                f"<li>{_html_module.escape(lo)}</li>" for lo in cred.learning_outcomes
            )
            html += f"""<div class="card">
  <h3>🎓 {_html_module.escape(cred.title)}</h3>
  <p><strong>ID:</strong> <code>{_html_module.escape(cred.id)}</code> &nbsp;|&nbsp;
     <strong>EQF:</strong> {cred.eqf_level.value} &nbsp;|&nbsp;
     <strong>ECTS:</strong> {cred.ects}</p>
  <p><strong>Learner profile:</strong> {_html_module.escape(cred.learner_profile)}</p>
  <p><strong>Assessment:</strong> {_html_module.escape(cred.assessment_method)}</p>
  <p><strong>Prerequisites:</strong> {prereq_links}</p>
  <p><strong>Stackability:</strong> {_html_module.escape(cred.stackability_rules)}</p>
  <p><strong>Learning outcomes:</strong></p>
  <ul>{outcomes_html}</ul>
</div>
"""
        html += "</div>\n"

    html += _HTML_FOOT.format(
        repo_url="https://github.com/robertbartlomiejski/morskamary"
    )
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    log.info("  Generated: %s", output_path)


def generate_literature_html(
    literature: List[Competence],
    output_path: Path,
    *,
    analysis_input_mode: str = "static",
    static_literature_count: Optional[int] = None,
    live_enrichment_count: Optional[int] = None,
) -> None:
    """Generate literature integration HTML: papers → competences mapping."""
    live_competences = [c for c in literature if c.id.startswith("lit_live_")]
    static_competences = [c for c in literature if c not in live_competences]
    static_count = (
        int(static_literature_count)
        if static_literature_count is not None
        else len(static_competences)
    )
    live_count = (
        int(live_enrichment_count)
        if live_enrichment_count is not None
        else len(live_competences)
    )

    subtitle = "Static literature with QMBD axis assignment"
    if analysis_input_mode == "live-enriched" and live_count:
        subtitle = "Static literature + live-enriched evidence with QMBD axis assignment"

    html = _HTML_HEAD.format(
        title="Literature Integration — Papers to Competences Mapping",
        subtitle=subtitle,
    )

    html += "<h2>Overview</h2>\n"
    html += f"<p>Total literature-derived competences: <strong>{len(literature)}</strong></p>\n"
    if analysis_input_mode == "live-enriched" and live_count:
        html += (
            "<p>Breakdown: "
            f"<strong>{static_count}</strong> static literature + "
            f"<strong>{live_count}</strong> live-enriched.</p>\n"
        )
    elif analysis_input_mode == "live-enriched":
        html += (
            "<p>Live-enriched mode requested, but no live records were available "
            "for this run.</p>\n"
        )

    by_axis: Dict[str, List[Competence]] = {ax.name: [] for ax in TMBDAxis}
    for c in literature:
        by_axis[c.axis.name].append(c)

    html += "<table>\n"
    html += "<tr><th>TMBD Axis</th><th>Count</th><th>Justification</th></tr>\n"
    justifications = {
        "MARINE": "Competences derived from papers on marine biodiversity, ecosystem science, and fisheries ecology",
        "MARITIME": "Competences from papers on labour relations, maritime industry, and techno-economic dimensions",
        "OCEANIC": "Competences from papers on ocean governance, blue justice, and planetary sustainability",
        "HYDRONIZATION": "Competences from papers on hydrosocial relations, wet ontology, and water-society co-constitution",
    }
    for ax in TMBDAxis:
        html += (
            f"<tr><td>{_axis_badge(ax)}</td>"
            f"<td>{len(by_axis[ax.name])}</td>"
            f"<td>{justifications[ax.name]}</td></tr>\n"
        )
    html += "</table>\n"

    for lit in LITERATURE_FILES:
        theme = lit["theme"]
        theme_comps = [c for c in static_competences if theme in c.id]
        if not theme_comps:
            continue

        file_url = f"{REPO_GITHUB_BASE}/data/derived/{quote(lit['filename'], safe='/')}"
        safe_file_url = _html_module.escape(file_url, quote=True)
        safe_description = _html_module.escape(lit["description"])
        safe_filename = _html_module.escape(lit["filename"])
        html += f"<h2>{safe_description}</h2>\n"
        html += (
            f"<p>Source: <a href='{safe_file_url}' target='_blank'>"
            f"{safe_filename}</a></p>\n"
        )
        html += "<table>\n"
        html += (
            "<tr><th>Competence Name</th><th>Axis</th><th>Source Row</th>"
            "<th>Authors</th><th>Year</th><th>GitHub Link</th></tr>\n"
        )
        for c in theme_comps:
            html += (
                f"<tr><td>{_html_module.escape(c.name)}</td>"
                f"<td>{_axis_badge(c.axis)}</td>"
                f"<td>{c.source.row}</td>"
                f"<td>{_html_module.escape(c.source.authors[:50])}</td>"
                f"<td>{c.source.year}</td>"
                f"<td><a href='{c.source.github_url}' target='_blank'>"
                f"{_html_module.escape(Path(c.source.file).name)}#L{c.source.row}</a></td></tr>\n"
            )
        html += "</table>\n"

    if analysis_input_mode == "live-enriched" and live_competences:
        live_records_url = f"{REPO_GITHUB_BASE}/outputs/research_sources/live_records_triangulated.json"
        live_coverage_url = (
            f"{REPO_GITHUB_BASE}/outputs/research_sources/live_source_coverage.csv"
        )
        html += "<h2>Live API evidence (triangulated winners)</h2>\n"
        html += (
            "<p>Source: "
            f"<a href='{_html_module.escape(live_records_url, quote=True)}' target='_blank'>"
            "live_records_triangulated.json</a> &nbsp;|&nbsp; "
            f"<a href='{_html_module.escape(live_coverage_url, quote=True)}' target='_blank'>"
            "live_source_coverage.csv</a></p>\n"
        )
        max_rows = 200
        html += "<table>\n"
        html += (
            "<tr><th>Paper Title</th><th>Axis</th><th>Sectors</th>"
            "<th>Authors</th><th>Year</th><th>Source</th></tr>\n"
        )
        for c in live_competences[:max_rows]:
            sectors_text = (
                ", ".join(_html_module.escape(sec) for sec in c.sectors) or ""
            )
            html += (
                f"<tr><td>{_html_module.escape(c.source.paper_title)}</td>"
                f"<td>{_axis_badge(c.axis)}</td>"
                f"<td>{sectors_text}</td>"
                f"<td>{_html_module.escape(c.source.authors[:50])}</td>"
                f"<td>{c.source.year}</td>"
                f"<td><a href='{c.source.github_url}' target='_blank'>"
                f"{_html_module.escape(Path(c.source.file).name)}#L{c.source.row}</a></td></tr>\n"
            )
        html += "</table>\n"
        if len(live_competences) > max_rows:
            html += (
                f"<p>Showing first {max_rows} live records out of "
                f"{len(live_competences)}.</p>\n"
            )

    html += _HTML_FOOT.format(
        repo_url="https://github.com/robertbartlomiejski/morskamary"
    )
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    log.info("  Generated: %s", output_path)


# ---------------------------------------------------------------------------
# 8. Main
# ---------------------------------------------------------------------------


def main(
    selected_sectors: Optional[List[str]] = None,
    analysis_input_mode: str = "static",
    live_records_path: Optional[Path] = None,
) -> int:
    """
    Execute the full analysis pipeline:
      1. Load baseline competences (15 from University of Szczecin CSV)
      2. Extract literature competences (from 3 combined_*.csv files)
      3. Merge and deduplicate
      4. Run gap analysis for all 12 sectors
      5. Generate micro-credentials for each sector (4 EQF levels each)
      6. Calculate learning pathways / sector transitions
      7. Generate HTML reports with hyperlinks
      8. Export JSON/CSV databases (including sector TMBD dictionaries)
      9. Print summary

    Returns:
        Exit code (0 = success, 1 = error)
    """
    target_sectors = selected_sectors or SECTORS
    live_path = live_records_path or DEFAULT_LIVE_RECORDS_JSON

    log.info("=" * 65)
    log.info("Blue Economy Full Analysis — morskamary")
    log.info("=" * 65)

    # --- Setup output directory ---
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Output directory: %s", OUTPUTS_DIR)

    # --- Step 1: Baseline competences ---
    if not BASELINE_CSV.exists():
        log.error("Baseline CSV not found: %s", BASELINE_CSV)
        return 1

    baseline = load_baseline_competences()

    # --- Step 2: Literature competences ---
    literature = extract_literature_competences()
    static_literature = list(literature)
    live_competences: List[Competence] = []
    if analysis_input_mode == "live-enriched":
        baseline_titles = {
            _normalize_title_for_dedup(getattr(c.source, "paper_title", None) or c.name)
            for c in literature
        }
        live_competences = extract_live_records_competences(live_path, baseline_titles)
        literature.extend(live_competences)
        log.info(
            "Live enrichment enabled — merged %d live competences from %s.",
            len(live_competences),
            live_path,
        )

    static_qmbd_records = _build_static_qmbd_records(
        baseline, record_origin="STATIC_BASELINE"
    ) + _build_static_qmbd_records(static_literature, record_origin="STATIC_LITERATURE")
    qmbd_repository = LocalizedQMBDRecordRepository(
        static_records=static_qmbd_records,
        live_records_path=live_path,
        include_live_records=(analysis_input_mode == "live-enriched"),
    )
    cumulative_qmbd_records_path = OUTPUTS_DIR / CUMULATIVE_QMBD_RECORDS_FILENAME
    qmbd_enriched_records = enrich_and_store_records(
        qmbd_repository.iter_records(),
        cumulative_qmbd_records_path,
    )
    log.info(
        "QMBD cumulative output generated: %s (%d records)",
        cumulative_qmbd_records_path,
        len(qmbd_enriched_records),
    )

    if not literature:
        log.warning("No literature competences extracted — check data/derived files.")

    # --- Step 3: Build combined lookup ---
    all_comps: Dict[str, Competence] = {}
    for c in baseline + literature:
        all_comps[c.id] = c

    log.info(
        "Total competences: %d (baseline: %d + literature: %d)",
        len(all_comps),
        len(baseline),
        len(literature),
    )

    # --- Step 4: Gap analysis ---
    gaps, _ = run_gap_analysis(baseline, literature)

    # --- Step 5: Micro-credentials ---
    credentials = generate_micro_credentials(baseline, literature, gaps)

    # --- Step 6: Pathways ---
    pathways = compute_sector_pathways(credentials, baseline)

    # --- Step 7: Export JSON/CSV databases ---
    log.info("Exporting databases…")
    export_competences_json(
        baseline, literature, OUTPUTS_DIR / "competences_full_database.json"
    )
    export_credentials_json(credentials, OUTPUTS_DIR / "credentials_database.json")
    export_pathways_json(pathways, OUTPUTS_DIR / "sector_pathways.json")
    export_gaps_summary_csv(gaps, OUTPUTS_DIR / "gaps_summary.csv")
    sector_dictionary_paths = export_sector_dictionaries(
        competences=literature,
        sectors=target_sectors,
        output_dir=OUTPUTS_DIR / "sector_dictionaries",
    )
    log.info("  Exported: %d sector TMBD dictionaries", len(sector_dictionary_paths))

    # --- Step 8: HTML reports ---
    log.info("Generating HTML reports…")
    generate_report_index(
        baseline,
        literature,
        gaps,
        credentials,
        OUTPUTS_DIR / "report_index.html",
        analysis_input_mode=analysis_input_mode,
        static_literature_count=len(static_literature),
        live_enrichment_count=len(live_competences),
    )
    generate_gaps_html(gaps, all_comps, OUTPUTS_DIR / "gaps_by_sector.html")
    generate_credentials_html(credentials, OUTPUTS_DIR / "credentials_matrix.html")
    generate_literature_html(
        literature,
        OUTPUTS_DIR / "literature_integration.html",
        analysis_input_mode=analysis_input_mode,
        static_literature_count=len(static_literature),
        live_enrichment_count=len(live_competences),
    )

    # --- Step 9: Summary ---
    log.info("=" * 65)
    log.info("ANALYSIS COMPLETE")
    log.info("=" * 65)
    log.info("")
    log.info(
        "  Competences:  %d total (%d baseline, %d literature)",
        len(all_comps),
        len(baseline),
        len(literature),
    )
    log.info(
        "  Credentials:  %d (%d sectors × 4 EQF levels)", len(credentials), len(SECTORS)
    )
    log.info("  Pathways:     %d sector transitions", len(pathways))
    log.info("")
    log.info("Output files:")
    for fname in [
        "report_index.html",
        "gaps_by_sector.html",
        "credentials_matrix.html",
        "literature_integration.html",
        "competences_full_database.json",
        "credentials_database.json",
        "sector_pathways.json",
        "gaps_summary.csv",
        "cumulative_qmbd_records.json",
    ]:
        fpath = OUTPUTS_DIR / fname
        if fpath.exists():
            log.info("  ✓ %s", fpath)
    sector_dictionary_dir = OUTPUTS_DIR / "sector_dictionaries"
    if sector_dictionary_dir.exists():
        log.info(
            "  ✓ %s (%d files)", sector_dictionary_dir, len(sector_dictionary_paths)
        )
    log.info("")
    log.info("GitHub repository: https://github.com/robertbartlomiejski/morskamary")
    return 0


def parse_cli_args() -> argparse.Namespace:
    """
    Parse command-line arguments for optional sector-scoped execution.

    Returns:
        argparse.Namespace with parsed CLI options.
    """
    parser = argparse.ArgumentParser(
        description="Run full blue economy competence analysis."
    )
    parser.add_argument(
        "--sector",
        dest="sectors",
        action="append",
        default=[],
        choices=SECTORS,
        help="Limit execution scope to one or more sectors (repeatable).",
    )
    parser.add_argument(
        "--analysis-input-mode",
        choices=["static", "live-enriched"],
        default="static",
        help="Use static literature inputs only, or enrich with live API exports.",
    )
    parser.add_argument(
        "--live-records-path",
        default=str(DEFAULT_LIVE_RECORDS_JSON),
        help="Path to live_records.json used when --analysis-input-mode=live-enriched.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_cli_args()
    sys.exit(
        main(
            selected_sectors=cli_args.sectors,
            analysis_input_mode=cli_args.analysis_input_mode,
            live_records_path=Path(cli_args.live_records_path),
        )
    )
