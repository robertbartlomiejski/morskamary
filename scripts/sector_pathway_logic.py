#!/usr/bin/env python3
from typing import Dict, List, Set

class SectorPathway:
    """
    Identifies efficient reskilling routes by calculating a cross-sectoral weight.
    If a competence appears in multiple domains, its 'Bridge Weight' increases.
    """
    def __init__(self, competence_name: str):
        self.competence = competence_name
        self.sector_appearances: Set[str] = set()
        self.triangulation_score: float = 0.0

    def add_appearance(self, sector: str, confidence_score: float):
        """Adds a sector appearance and updates the triangulation score."""
        self.sector_appearances.add(sector)
        self.triangulation_score += confidence_score

    def calculate_bridge_weight(self) -> float:
        """
        Mathematical definition of Bridge Weight based on cross-sectoral utility.
        The weight scales linearly with sector count and triangulation confidence.
        """
        sector_count = len(self.sector_appearances)
        if sector_count <= 1:
            return 0.0
        
        # Linear scaling with sector count and triangulation confidence
        return (sector_count * 1.5) + self.triangulation_score

def identify_bridge_competences(competence_data: List[Dict]) -> List[Dict]:
    """
    Processes a list of competences to identify those with high bridge weights.
    """
    pathways: Dict[str, SectorPathway] = {}
    
    for comp in competence_data:
        name = comp.get("name", "Unknown")
        if name not in pathways:
            pathways[name] = SectorPathway(name)
        
        # Simulate confidence score based on tier and metadata presence
        confidence = 1.0 if comp.get("tier") == 1 else 0.5
        if comp.get("doi") and comp.get("doi") != "[CITATION_REQUIRED]":
            confidence += 0.5
            
        sector = comp.get("sector", "General")
        pathways[name].add_appearance(sector, confidence)
        
    results = []
    for name, pathway in pathways.items():
        weight = pathway.calculate_bridge_weight()
        if weight > 0:
            results.append({
                "competence": name,
                "sectors": list(pathway.sector_appearances),
                "bridge_weight": round(weight, 2)
            })
            
    return sorted(results, key=lambda x: x["bridge_weight"], reverse=True)

if __name__ == "__main__":
    # Example usage
    sample_data = [
        {"name": "Project Management", "sector": "Blue Biotech", "tier": 1, "doi": "10.123/456"},
        {"name": "Project Management", "sector": "Renewable Energy", "tier": 1, "doi": "10.123/456"},
        {"name": "Marine Biology", "sector": "Blue Biotech", "tier": 2, "doi": "[CITATION_REQUIRED]"}
    ]
    bridges = identify_bridge_competences(sample_data)
    print(f"Detected Bridge Competences: {bridges}")
