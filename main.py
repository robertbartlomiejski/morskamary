"""
Main entry point for morskamary Blue Sociology analysis

This script demonstrates the core functionality of competence mapping
and micro-credential design based on TMBD principles.
"""

import sys
from src.core import (
    Competence,
    MicroCredential,
    BlueDynamicsAxis,
    CompetenceLevel,
    create_sample_competences,
)
from src.competence_mapper import CompetenceMapper


def main():
    """Run the main demonstration"""
    print("=" * 70)
    print("MORSKAMARY: Blue Sociology Competence Mapping")
    print("=" * 70)
    print()

    # Initialize mapper
    mapper = CompetenceMapper()

    # Load sample competences
    print("[1] Loading sample competences...")
    competences = create_sample_competences()
    for comp in competences:
        mapper.add_competence(comp)
        print(f"    - {comp.name} ({comp.axis.name} axis, {comp.level.name})")
    print()

    # Create sample micro-credentials
    print("[2] Creating sample micro-credentials...")
    credentials = [
        MicroCredential(
            id="cred_offshore_001",
            title="Offshore Energy Operations Specialist",
            competences=["comp_marine_001", "comp_maritime_001"],
            description="Micro-credential for professionals in offshore renewable energy",
            sector="offshore-energy",
        ),
        MicroCredential(
            id="cred_ocean_gov_001",
            title="Ocean Governance Practitioner",
            competences=["comp_oceanic_001"],
            description="Micro-credential for ocean governance and policy professionals",
            sector="governance",
        ),
    ]

    for cred in credentials:
        mapper.add_credentials(cred)
        print(f"    - {cred.title} ({cred.sector} sector)")
    print()

    # Display mapping summary
    print("[3] Competence Mapping Summary:")
    summary = mapper.get_summary()
    print(f"    Total competences: {summary['total_competences']}")
    print(f"    Total credentials: {summary['total_credentials']}")
    print(f"    Competences by TMBD axis:")
    for axis, count in summary['competences_by_axis'].items():
        print(f"      - {axis}: {count}")
    print(f"    Competences by level:")
    for level, count in summary['competences_by_level'].items():
        print(f"      - {level}: {count}")
    print()

    # Demonstrate competence gap analysis
    print("[4] Competence Gap Analysis Example:")
    print("    User has: ['comp_marine_001']")
    print("    Target sector: offshore-energy")
    gaps = mapper.analyze_competence_gaps(
        available=["comp_marine_001"],
        required_sector="offshore-energy",
    )
    print(f"    Missing competences:")
    for missing in gaps['missing']:
        if missing in mapper.competences:
            comp = mapper.competences[missing]
            print(f"      - {comp.name} ({comp.level.name})")
    print()

    # Suggest credential pathway
    print("[5] Suggested Micro-Credential Pathway:")
    pathway = mapper.suggest_credential_pathway()
    for i, cred in enumerate(pathway, 1):
        print(f"    {i}. {cred.title}")
        print(f"       Sector: {cred.sector}")
        print(f"       Description: {cred.description}")
    print()

    print("=" * 70)
    print("Setup complete! Core functionality is now available.")
    print("=" * 70)
    print()
    print("Next steps:")
    print("1. Install dependencies: pip install -r requirements.txt")
    print("2. Run tests: pytest tests/")
    print("3. Load your competence data: see src/core.py for examples")
    print("4. Map to sectors and create credentials")
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
