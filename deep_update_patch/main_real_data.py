#!/usr/bin/env python3
"""
main_real_data.py

Primary substantive script for the deep update patch.
Loads the shared baseline, sector matrix, and cluster matrix through the
shared loader, then prints a concise real-data summary.
"""

from pathlib import Path
import sys

from load_real_competences import load_blue_competences
from src.core import BlueDynamicsAxis


REPO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    mapper = load_blue_competences(REPO_ROOT)
    summary = mapper.get_summary()

    print("=" * 72)
    print("MORSKAMARY — unified real-data competence pipeline")
    print("=" * 72)
    print(f"Total competence objects: {summary['total_competences']}")
    print(f"Total sector requirements: {summary['total_sector_requirements']}")
    print(f"Total credentials: {summary['total_credentials']}")
    print(f"Sectors: {len(summary['sectors'])}")
    print()

    print("TMBD axis distribution")
    for axis in BlueDynamicsAxis:
        print(f"- {axis.name}: {summary['competences_by_axis'][axis.name]}")
    print()

    print("Sector profiles")
    for sector in summary["sectors"]:
        profile = mapper.get_sector_profile(sector)
        print(
            f"- {profile['sector_label']}: total={profile['total_requirements']}, "
            f"skills={profile['requirements_by_kind']['skill']}, "
            f"competences={profile['requirements_by_kind']['competence']}, "
            f"cluster={profile['cluster_name']}"
        )
    print()

    gaps = mapper.analyze_competence_gaps(
        available=["blue_comp_a_1", "blue_comp_c_1"],
        required_sector="offshore-energy",
    )
    print("Example gap analysis")
    print(f"- normalized sector: {gaps['sector']}")
    print(f"- available in target: {len(gaps['available'])}")
    print(f"- missing in target: {len(gaps['missing'])}")
    print()
    print("Run `python run_full_analysis.py` for the general report and all 12 sector reports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
