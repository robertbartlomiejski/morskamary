#!/usr/bin/env python3
"""
emergent_sector_logic.py — Manus Contribution: Dynamic Sector Discovery
Moves beyond the static 12-sector model to identify emerging themes in Blue Sociology.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import Counter

# Enhanced QMBD Keywords for the "Hydrosocial Turn", "Maritimisation", and "Hydronization"
ENHANCED_KEYWORDS = {
    "MARINE": {
        # Biophysical Agency (M)
        "ecosystem", "biodiversity", "ecology", "habitat", "benthic", "pelagic",
        "biophysical", "trophic", "marine biology", "ocean acidification",
        "restoration", "conservation", "wildlife", "blue carbon", "nature-based",
        "eutrophication", "invasive species", "marine heatwaves", "biophysical agency",
        "marinization", "demarinization", "remarinization", "comarinization"
    },
    "MARITIME": {
        # Techno-economic Mediation (T) & Institutional Terraforming
        "labour", "labor", "seafarer", "vessel", "port", "shipping", "logistics",
        "infrastructure", "technology", "digital", "automation", "industry",
        "trade", "economic", "work", "safety", "regulation", "decarbonisation",
        "smart-port", "autonomous shipping", "green retrofitting", "supply chain",
        "maritimisation", "institutional terraforming", "property regimes", "msp",
        "maritime spatial planning", "terraforming", "institutionalisation",
        "demaritimization", "remaritimization", "comaritimization"
    },
    "OCEANIC": {
        # Hydrosocial Subjectivity (O)
        "governance", "policy", "international", "sustainability", "justice",
        "equity", "community", "stakeholder", "transboundary", "institution",
        "blue economy", "resilience", "human rights", "participatory",
        "hydrosocial", "planetary", "ocean citizenship", "blue justice",
        "post-colonial", "subjectivity", "transcorporeal", "ocean literacy",
        "wet ontologies", "agential realism", "marinisation", "cultural adaptation",
        "oceanization", "deoceanization", "reoceanization", "cooceanization"
    },
    "HYDRONIZATION": {
        # Posthuman Wet Agentism (H)
        "posthuman", "wet agentism", "liquid materialism", "hydro-social",
        "water personhood", "more-than-human", "liquid agency", "water body",
        "hydronization", "dehydronization", "rehydronization", "cohydronization"
    }
}

def detect_emergent_sectors(competences: List[Dict], min_cluster_size: int = 3) -> List[str]:
    """
    Identifies clusters of literature competences that don't fit the 12 canonical sectors.
    Uses keyword co-occurrence to suggest 'Emergent Sectors'.
    """
    # Extract keywords from literature competences
    all_keywords = []
    for comp in competences:
        if comp.get("dimension") == "literature":
            # Use keywords and description for clustering
            all_keywords.extend(comp.get("keywords", []))
            
    # Count frequencies
    counts = Counter(all_keywords)
    
    # Filter out canonical sectors and low-frequency terms
    canonical_slugs = {
        "blue-biotech", "coastal-tourism", "desalination", "infra-robotics",
        "living-resources", "non-living-resources", "renewable-energy",
        "maritime-defence", "maritime-transport", "port-activities",
        "research-innovation", "ship-repair", "literature", "marine", "maritime", "oceanic"
    }
    
    emergent = [
        term for term, count in counts.most_common(20)
        if term not in canonical_slugs and count >= min_cluster_size
    ]
    
    return emergent

def enhance_detect_axis(text: str, default: str = "OCEANIC") -> str:
    """
    Manus-Enhanced Axis Detection: Uses weighted scoring for better semantic accuracy.
    """
    lower = text.lower()
    scores = {axis: 0 for axis in ENHANCED_KEYWORDS}
    
    for axis, kws in ENHANCED_KEYWORDS.items():
        for kw in kws:
            if kw in lower:
                # Give higher weight to multi-word phrases
                weight = 2 if " " in kw else 1
                scores[axis] += weight
                
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "UNCLASSIFIED"  # Eradicate Oceanic Default Bias
    return best

# Deterministic EQF Level mapping based on complexity verbs
EQF_VERBS = {
    "EQF7": r"\b(strategize|govern|architect|synthesize)\b",
    "EQF6": r"\b(manage|implement|design|evaluate)\b",
    "EQF5": r"\b(operate|coordinate|maintain)\b"
}

def assign_eqf_level(text: str) -> str:
    """Rule-based syntactic parsing for EQF levels. No probabilistic guessing."""
    lower = text.lower()
    for eqf, pattern in EQF_VERBS.items():
        if re.search(pattern, lower):
            return eqf
    return "EQF_UNKNOWN"

if __name__ == "__main__":
    # Example usage: Load full database and check for emergent sectors
    db_path = Path("outputs/competences_full_database.json")
    if db_path.exists():
        with open(db_path, "r") as f:
            data = json.load(f)
        
        all_comps = data.get("baseline", []) + data.get("literature", [])
        emergent = detect_emergent_sectors(all_comps)
        
        print(f"Detected Emergent Themes: {', '.join(emergent)}")
    else:
        print("Database not found. Run run_full_analysis.py first.")
