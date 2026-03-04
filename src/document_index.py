"""
Semantic extraction utilities for Blue Sociology documents.

Extracts structured entities (competences, values, policy terms) from source documents
with TMBD axis classification and provenance tracking.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import hashlib
from .core import BlueDynamicsAxis, CompetenceLevel


class EntityType(Enum):
    """Types of entities that can be extracted from documents"""
    BLUE_COMPETENCE = "blue_competence"
    BLUE_VALUE = "blue_value"
    POLICY_TERM = "policy_term"
    SECTOR_ACTIVITY = "sector_activity"
    GOVERNANCE_MECHANISM = "governance_mechanism"
    THEORETICAL_CONCEPT = "theoretical_concept"


@dataclass
class SourceLocator:
    """Precise location of extracted content in source document"""
    file_name: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    paragraph_number: Optional[int] = None
    line_range: Optional[str] = None  # e.g., "45-47"
    confidence: float = 1.0  # 0.0-1.0 confidence in extraction accuracy
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "file_name": self.file_name,
            "page_number": self.page_number,
            "section_title": self.section_title,
            "paragraph_number": self.paragraph_number,
            "line_range": self.line_range,
            "confidence": self.confidence,
        }


@dataclass
class DocumentMetadata:
    """Metadata for a source document"""
    file_name: str
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    institution: Optional[str] = None
    document_type: Optional[str] = None  # e.g., "policy brief", "report", "treaty"
    language: str = "en"
    sha256_hash: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "file_name": self.file_name,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "institution": self.institution,
            "document_type": self.document_type,
            "language": self.language,
            "sha256_hash": self.sha256_hash,
        }


@dataclass
class ExtractedEntity:
    """
    A semantic entity extracted from source documents.
    
    Follows evidence discipline: every entity must link back to source location(s).
    """
    entity_id: str
    entity_type: EntityType
    text: str  # The actual extracted text
    description: str  # Human-readable explanation
    source_locators: List[SourceLocator] = field(default_factory=list)
    tmbd_axis: Optional[BlueDynamicsAxis] = None
    competence_level: Optional[CompetenceLevel] = None
    blue_economy_sectors: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    related_entities: List[str] = field(default_factory=list)  # IDs of related entities
    confidence: float = 1.0
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type.value,
            "text": self.text,
            "description": self.description,
            "source_locators": [loc.to_dict() for loc in self.source_locators],
            "tmbd_axis": self.tmbd_axis.value if self.tmbd_axis else None,
            "competence_level": self.competence_level.name if self.competence_level else None,
            "blue_economy_sectors": self.blue_economy_sectors,
            "keywords": self.keywords,
            "related_entities": self.related_entities,
            "confidence": self.confidence,
            "notes": self.notes,
        }
    
    def add_source(self, locator: SourceLocator) -> None:
        """Add a source locator (supports multi-source evidence)"""
        self.source_locators.append(locator)
    
    def get_citation(self) -> str:
        """
        Generate a citation string following CITATION.txt rules.
        
        Returns placeholder if source metadata is incomplete.
        """
        if not self.source_locators:
            return "[citation needed]"
        
        primary = self.source_locators[0]
        citation_parts = [primary.file_name]
        
        if primary.page_number:
            citation_parts.append(f"p. {primary.page_number}")
        if primary.section_title:
            citation_parts.append(f"§ {primary.section_title}")
        
        return ", ".join(citation_parts)


def generate_entity_id(text: str, entity_type: EntityType) -> str:
    """
    Generate a deterministic ID for an entity based on its content.
    
    Args:
        text: The extracted text
        entity_type: Type of entity
        
    Returns:
        Unique ID string
    """
    content = f"{entity_type.value}:{text.lower()}"
    hash_digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    return f"{entity_type.value[:8]}_{hash_digest[:12]}"


def compute_file_hash(file_path: Path) -> str:
    """
    Compute SHA-256 hash of a file for provenance tracking.
    
    Args:
        file_path: Path to file
        
    Returns:
        Hexadecimal hash string
    """
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


class SemanticExtractor:
    """
    Base class for extracting semantic entities from documents.
    
    Subclass this for specific extraction strategies (manual, LLM-assisted, etc.)
    """
    
    def __init__(self):
        """Initialize the extractor"""
        self.extracted_entities: List[ExtractedEntity] = []
        self.document_metadata: Dict[str, DocumentMetadata] = {}
    
    def extract_from_document(self, 
                             file_path: Path, 
                             metadata: Optional[DocumentMetadata] = None) -> List[ExtractedEntity]:
        """
        Extract entities from a document.
        
        Args:
            file_path: Path to document
            metadata: Optional document metadata
            
        Returns:
            List of extracted entities
        """
        raise NotImplementedError("Subclasses must implement extract_from_document")
    
    def register_document(self, metadata: DocumentMetadata) -> None:
        """Register document metadata for provenance tracking"""
        self.document_metadata[metadata.file_name] = metadata
    
    def get_all_entities(self) -> List[ExtractedEntity]:
        """Get all extracted entities from all processed documents"""
        return self.extracted_entities
    
    def filter_by_type(self, entity_type: EntityType) -> List[ExtractedEntity]:
        """Filter entities by type"""
        return [e for e in self.extracted_entities if e.entity_type == entity_type]
    
    def filter_by_axis(self, axis: BlueDynamicsAxis) -> List[ExtractedEntity]:
        """Filter entities by TMBD axis"""
        return [e for e in self.extracted_entities if e.tmbd_axis == axis]
    
    def filter_by_sector(self, sector: str) -> List[ExtractedEntity]:
        """Filter entities associated with a specific blue economy sector"""
        return [e for e in self.extracted_entities 
                if sector.lower() in [s.lower() for s in e.blue_economy_sectors]]
