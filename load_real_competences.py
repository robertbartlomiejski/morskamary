#!/usr/bin/env python3
"""
Load Blue Social Competences from CSV into the CompetenceMapper

This script demonstrates how to load real data from:
data/derived/Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv
"""

import csv
from pathlib import Path
from src.core import Competence, BlueDynamicsAxis, CompetenceLevel
from src.competence_mapper import CompetenceMapper


def map_dimension_to_axis(dimension: str) -> BlueDynamicsAxis:
    """
    Map the competence dimension to TMBD axis.
    
    A (Understanding) → OCEANIC (planetary perspective)
    B (Digital & Data) → MARITIME (techno-economic infrastructure)
    C (Sustainability) → MARINE (biophysical/ecological)
    D (Business/Governance) → MARITIME (institutional/economic)
    """
    dimension_letter = dimension.split(".")[0] if "." in dimension else dimension[0]
    
    mapping = {
        "A": BlueDynamicsAxis.OCEANIC,      # Understanding/literacy → planetary
        "B": BlueDynamicsAxis.MARITIME,     # Digital/technical → infrastructure
        "C": BlueDynamicsAxis.MARINE,       # Sustainability → ecological
        "D": BlueDynamicsAxis.MARITIME,     # Governance → institutional
    }
    
    return mapping.get(dimension_letter, BlueDynamicsAxis.OCEANIC)


def load_blue_competences(csv_path: Path) -> CompetenceMapper:
    """
    Load Blue Social Competences from CSV into CompetenceMapper.

    Args:
        csv_path: Path to the Blue Competences CSV file

    Returns:
        CompetenceMapper with all competences loaded

    Raises:
        ValueError: If csv_path is empty or None
        FileNotFoundError: If the CSV file does not exist
    """
    if csv_path is None:
        raise ValueError("csv_path cannot be empty")

    csv_path = Path(csv_path)

    if str(csv_path) == "." or not str(csv_path).strip():
        raise ValueError("csv_path cannot be empty")

    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    mapper = CompetenceMapper()
    
    print(f"\n📂 Loading competences from: {csv_path.name}")
    print("=" * 70)
    
    competence_count = 0
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (after header)
            # Skip rows without a competence ID or name
            comp_id = row.get("ID", "").strip()
            comp_name = row.get("Competence Name", "").strip()
            comp_focus = row.get("Key Simplified Focus (Applied to all 12 Sectors)", "").strip()
            
            if not comp_id or not comp_name:
                continue
            
            # Determine TMBD axis based on dimension
            axis = map_dimension_to_axis(comp_id)
            
            # Fixed proficiency level (all are considered INTERMEDIATE in this baseline)
            level = CompetenceLevel.INTERMEDIATE
            
            # Create competence object
            competence = Competence(
                id=f"blue_comp_{comp_id.replace('.', '_').lower()}",
                name=comp_name,
                description=comp_focus or comp_name,
                axis=axis,
                level=level,
                keywords=["blue-economy", "sustainability", "ocean"],  # Keywords for discovery
            )
            
            # Add to mapper
            mapper.add_competence(competence)
            competence_count += 1
            
            # Print sample
            if competence_count <= 5:
                print(f"✓ {comp_id:4s} | {comp_name:40s} | {axis.name:8s}")
        
        if competence_count > 5:
            print(f"... and {competence_count - 5} more competences")
    
    print(f"\n✅ Loaded {competence_count} competences")
    print(f"\nAxis Distribution:")
    for axis in BlueDynamicsAxis:
        count = len(mapper.get_competences_by_axis(axis))
        print(f"   {axis.name:10s}: {count:3d}")
    
    print("=" * 70 + "\n")
    
    return mapper


def main():
    """Demonstrate loading and using real competence data."""
    
    # Path to the Blue Competences CSV
    repo_root = Path(__file__).resolve().parent
    csv_path = repo_root / "data" / "derived" / "Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv"
    
    if not csv_path.exists():
        print(f"❌ CSV not found: {csv_path}")
        return 1
    
    # Load competences
    mapper = load_blue_competences(csv_path)
    
    # Show what we loaded
    print("\n📊 COMPETENCE MAPPER SUMMARY")
    print("=" * 70)
    
    summary = mapper.get_summary()
    print(f"Total competences: {summary['total_competences']}")
    print(f"Total credentials: {summary['total_credentials']}")
    print(f"Sectors covered: {summary['sectors']}")
    
    # Example: Show all MARINE competences
    print(f"\n🌊 MARINE Axis Competences:")
    marine_comps = mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)
    for comp in marine_comps[:5]:
        print(f"   • {comp.name}")
    if len(marine_comps) > 5:
        print(f"   ... and {len(marine_comps) - 5} more")
    
    # Example: Show analysis
    print(f"\n🔍 Example Gap Analysis")
    print("   Sector: Renewable Energy")
    print("   User has: [blue_comp_a_1, blue_comp_b_1]")
    
    gaps = mapper.analyze_competence_gaps(
        available=["blue_comp_a_1", "blue_comp_b_1"],
        required_sector="offshore-energy"
    )
    
    print(f"   Available: {len(gaps['available'])} competences")
    print(f"   Missing: {len(gaps['missing'])} competences")
    
    print("\n✅ Real competence data is now loaded and ready to use!")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
