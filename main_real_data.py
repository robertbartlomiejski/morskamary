#!/usr/bin/env python3
"""
MORSKAMARY: Blue Sociology Competence Mapping with Real Data

This script loads real Blue Social Competences from CSV and demonstrates
competence mapping, gap analysis, and micro-credential design.
"""

import sys
from pathlib import Path
from src.core import MicroCredential, BlueDynamicsAxis
from src.competence_mapper import CompetenceMapper
from load_real_competences import load_blue_competences


def main():
    """Run competence mapping with real data from University of Szczecin baseline"""
    
    print("\n" + "=" * 70)
    print("🌊 MORSKAMARY: Blue Sociology Competence Mapping")
    print("   Using University of Szczecin Blue Social Competences Baseline")
    print("=" * 70 + "\n")

    # Initialize mapper
    mapper = CompetenceMapper()

    # Load real competences from CSV
    print("[STEP 1] Loading real competence data...")
    repo_root = Path(__file__).resolve().parent
    csv_path = repo_root / "data" / "derived" / "Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv"
    
    if not csv_path.exists():
        print(f"❌ ERROR: CSV file not found: {csv_path}")
        return 1
    
    mapper = load_blue_competences(csv_path)
    print()

    # Display axis distribution
    print("[STEP 2] Competence Distribution by TMBD Axis:")
    for axis in BlueDynamicsAxis:
        comps = mapper.get_competences_by_axis(axis)
        print(f"    {axis.name:10s} ({axis.value}): {len(comps):2d} competences")
    print()

    # Create sample micro-credentials based on real competences
    print("[STEP 3] Creating sample micro-credentials...")
    
    # Get some real competence IDs to use
    marine_comps = [c.id for c in mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)[:2]]
    maritime_comps = [c.id for c in mapper.get_competences_by_axis(BlueDynamicsAxis.MARITIME)[:2]]
    oceanic_comps = [c.id for c in mapper.get_competences_by_axis(BlueDynamicsAxis.OCEANIC)[:2]]
    
    credentials = [
        MicroCredential(
            id="cred_renewable_001",
            title="Sustainable Renewable Energy Specialist",
            competences=marine_comps + maritime_comps,
            description="Micro-credential for professionals in ocean renewable energy transitioning to sustainable practices",
            sector="renewable-energy",
        ),
        MicroCredential(
            id="cred_marine_001",
            title="Marine Ecosystem Manager",
            competences=marine_comps + oceanic_comps,
            description="Micro-credential for marine resource management with governance awareness",
            sector="marine-resources",
        ),
        MicroCredential(
            id="cred_governance_001",
            title="Blue Ocean Governance Practitioner",
            competences=oceanic_comps + maritime_comps,
            description="Micro-credential for ocean governance, policy, and inclusive decision-making",
            sector="ocean-governance",
        ),
    ]

    for cred in credentials:
        mapper.add_credentials(cred)
        print(f"    ✓ {cred.title}")
    print()

    # Show mapping summary
    print("[STEP 4] Competence Mapping Summary:")
    summary = mapper.get_summary()
    print(f"    Total competences loaded: {summary['total_competences']}")
    print(f"    Total micro-credentials defined: {summary['total_credentials']}")
    print()

    # Demonstrate gap analysis
    print("[STEP 5] Competence Gap Analysis Example:")
    print(f"    Scenario: Worker transitions from Fisheries to Renewable Energy")
    print(f"    Currently has: [Sustainable resource management, Blue systems thinking]")
    
    available = [c.id for c in mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)[:2]]
    gaps = mapper.analyze_competence_gaps(
        available=available,
        required_sector="renewable-energy",
    )
    
    print(f"\n    Available competences: {len(gaps['available'])}")
    print(f"    Missing competences: {len(gaps['missing'])}")
    
    if gaps['missing']:
        print(f"\n    Top missing competences for renewable energy:")
        for missing_id in list(gaps['missing'])[:3]:
            if missing_id in mapper.competences:
                comp = mapper.competences[missing_id]
                print(f"      • {comp.name} ({comp.axis.name} axis)")
    print()

    # Suggest credential pathway
    print("[STEP 6] Recommended Micro-Credential Pathway:")
    pathway = mapper.suggest_credential_pathway()
    for i, cred in enumerate(pathway, 1):
        print(f"\n    {i}. {cred.title}")
        print(f"       Sector: {cred.sector}")
        print(f"       Competences: {len(cred.competences)} competence modules")
    print()

    print("=" * 70)
    print("✅ Real Data Analysis Complete!")
    print("=" * 70)
    print()
    print("📊 Key Stats:")
    print(f"   • Total unique competences: {summary['total_competences']}")
    print(f"   • Blue Economy sectors covered: {len(set(c.sector for c in mapper.credentials.values()))}")
    print(f"   • MARINE competences: {len(mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE))}")
    print(f"   • MARITIME competences: {len(mapper.get_competences_by_axis(BlueDynamicsAxis.MARITIME))}")
    print(f"   • OCEANIC competences: {len(mapper.get_competences_by_axis(BlueDynamicsAxis.OCEANIC))}")
    print()
    print("💡 Next Steps:")
    print("   1. Load more sectors from 'Blue competences x blue economy sector' CSV")
    print("   2. Integrate with LMS or credential platform")
    print("   3. Export to Europass format for EU recognition")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
