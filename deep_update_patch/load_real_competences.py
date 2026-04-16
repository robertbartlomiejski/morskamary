#!/usr/bin/env python3
"""
load_real_competences.py  (deep_update_patch edition)

Plug-and-play loader for the morskamary real-data pipeline.

Loads three CSV matrices from data/derived/ and populates a CompetenceMapper:

1. Baseline CSV  — Overall Blue Competences Dimension
   (transversal competence objects; one per row)
2. Sector CSV    — Blue competences x blue economy sector
   (sector-specific operationalisation; creates SectorRequirement records)
3. Cluster CSV   — Blue Clusters for Microcredentials
   (sector-to-cluster mapping; registers sector_cluster on the mapper)

Public API
----------
load_blue_competences(baseline_csv, sector_csv=None, cluster_csv=None)
    -> CompetenceMapper

All three paths default to the canonical locations inside data/derived/ when
the caller omits them.  Pass an explicit path to override.
"""

import csv
import sys
from pathlib import Path
from typing import Dict, Optional

# Allow running from the deep_update_patch/ directory directly.
_BUNDLE_ROOT = Path(__file__).resolve().parent
if str(_BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BUNDLE_ROOT))

# Re-export the repo-root's path calculation so callers can rely on it.
REPO_ROOT = _BUNDLE_ROOT.parent

# Canonical locations of the three input CSV files
_DERIVED = REPO_ROOT / "data" / "derived"
_DEFAULT_BASELINE = _DERIVED / (
    "Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv"
)
_DEFAULT_SECTOR = _DERIVED / (
    "Blue Social Competences Univ Szczecin - Blue competences x blue economy sector.csv"
)
_DEFAULT_CLUSTER = _DERIVED / (
    "Blue Social Competences Univ Szczecin - Blue Clusters for Microcredentials.csv"
)

from src.core import (  # noqa: E402  (import after sys.path manipulation)
    BlueDynamicsAxis,
    Competence,
    CompetenceLevel,
    RequirementKind,
    SectorRequirement,
    SourceRef,
    normalize_sector_name,
    sector_label,
)
from src.competence_mapper import CompetenceMapper  # noqa: E402


# ---------------------------------------------------------------------------
# Dimension → TMBD axis mapping
# ---------------------------------------------------------------------------

_DIMENSION_AXIS: Dict[str, BlueDynamicsAxis] = {
    "A": BlueDynamicsAxis.OCEANIC,   # Understanding / planetary literacy
    "B": BlueDynamicsAxis.MARITIME,  # Digital & Data / infrastructure
    "C": BlueDynamicsAxis.MARINE,    # Sustainability / ecological
    "D": BlueDynamicsAxis.MARITIME,  # Business & Governance / institutional
}


def _axis_for_dimension(dimension_letter: str) -> BlueDynamicsAxis:
    return _DIMENSION_AXIS.get(dimension_letter.upper(), BlueDynamicsAxis.OCEANIC)


def _dimension_letter(dim_str: str) -> str:
    """Extract the single letter from a dimension string like 'A.1' or 'A. Understanding'."""
    s = dim_str.strip()
    if s:
        return s[0].upper()
    return ""


# ---------------------------------------------------------------------------
# Baseline CSV loader
# ---------------------------------------------------------------------------

def _load_baseline(csv_path: Path, mapper: CompetenceMapper) -> None:
    """Load baseline (overall) competences from CSV into mapper."""
    with open(csv_path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        dim_current = ""
        for row_num, row in enumerate(reader, start=2):
            comp_id = row.get("ID", "").strip()
            comp_name = row.get("Competence Name", "").strip()
            if not comp_name:
                continue

            # Handle both "Dimension (Aspect)" and the truncated "imension (Aspect)"
            # header variant present in the Szczecin baseline CSV (missing leading D).
            dim_cell = (
                row.get("Dimension (Aspect)")
                or row.get("imension (Aspect)")
                or ""
            ).strip()
            if dim_cell:
                dim_current = dim_cell

            dim_letter = _dimension_letter(dim_current)
            axis = _axis_for_dimension(dim_letter)

            # Skill rows use "—" as ID; competence rows use "A.1" style IDs.
            # Use a deterministic ID per dimension letter so IDs stay consistent
            # with any other loader that references the same skills.
            if not comp_id or comp_id == "—":
                req_kind = RequirementKind.SKILL
                safe_id = f"blue_skill_{dim_letter.lower()}"
                comp_id = safe_id
            else:
                req_kind = RequirementKind.COMPETENCE
                safe_id = f"blue_comp_{comp_id.replace('.', '_').lower()}"

            focus = row.get(
                "Key Simplified Focus (Applied to all 12 Sectors)", ""
            ).strip()

            competence = Competence(
                id=safe_id,
                name=comp_name,
                description=focus or comp_name,
                axis=axis,
                level=CompetenceLevel.INTERMEDIATE,
                keywords=["blue-economy", "sustainability", "ocean"],
                dimension=dim_letter,
                requirement_kind=req_kind,
                source=SourceRef(file=csv_path.name, row=row_num),
            )
            mapper.add_competence(competence)


# ---------------------------------------------------------------------------
# Sector CSV loader
# ---------------------------------------------------------------------------

def _load_sector_requirements(csv_path: Path, mapper: CompetenceMapper) -> None:
    """Load per-sector requirement text and create SectorRequirement records."""
    with open(csv_path, "r", encoding="utf-8") as fh:
        raw_lines = fh.readlines()

    # The header row is the first row that starts with "Dimension (Aspect)"
    header_row_index = None
    for i, line in enumerate(raw_lines):
        if line.startswith("Dimension (Aspect)") or "Dimension (Aspect)" in line:
            header_row_index = i
            break
    if header_row_index is None:
        return  # Unrecognised format — skip silently

    data_lines = raw_lines[header_row_index:]
    reader = csv.DictReader(data_lines)

    # Build a mapping from the short sector header name to the canonical slug.
    sector_col_map: Dict[str, str] = {}
    if reader.fieldnames:
        for col in reader.fieldnames[3:]:
            stripped = col.strip()
            if stripped:
                sector_col_map[col] = normalize_sector_name(stripped)

    dim_current = ""
    for row_num, row in enumerate(reader, start=header_row_index + 2):
        comp_name = row.get("Competence Name", "").strip()
        if not comp_name:
            continue

        comp_id_raw = row.get("ID", "").strip()
        # Handle both "Dimension (Aspect)" and truncated "imension (Aspect)"
        dim_cell = (
            row.get("Dimension (Aspect)")
            or row.get("imension (Aspect)")
            or ""
        ).strip()
        if dim_cell:
            dim_current = dim_cell

        dim_letter = _dimension_letter(dim_current)
        axis = _axis_for_dimension(dim_letter)

        # Use the same deterministic skill ID scheme as the baseline loader
        # so SectorRequirement.competence_id references valid Competence IDs.
        if not comp_id_raw or comp_id_raw == "—":
            req_kind = RequirementKind.SKILL
            safe_id = f"blue_skill_{dim_letter.lower()}"
        else:
            req_kind = RequirementKind.COMPETENCE
            safe_id = f"blue_comp_{comp_id_raw.replace('.', '_').lower()}"

        for col, sector_slug in sector_col_map.items():
            cell_text = row.get(col, "").strip()
            if not cell_text:
                continue
            mapper.add_sector_requirement(
                SectorRequirement(
                    competence_id=safe_id,
                    sector=sector_slug,
                    sector_label=sector_label(sector_slug),
                    sector_text=cell_text,
                    requirement_kind=req_kind,
                    axis=axis,
                    dimension=dim_letter,
                    source=SourceRef(
                        file=csv_path.name,
                        row=row_num,
                        column=col.strip(),
                    ),
                )
            )


# ---------------------------------------------------------------------------
# Cluster CSV loader
# ---------------------------------------------------------------------------

def _load_clusters(csv_path: Path, mapper: CompetenceMapper) -> None:
    """Register sector→cluster mappings from the cluster CSV."""
    with open(csv_path, "r", encoding="utf-8") as fh:
        raw_lines = fh.readlines()

    # Row 0 contains cluster names spread across columns; row 2 is the header.
    if len(raw_lines) < 3:
        return

    # Parse cluster names row (row 0)
    cluster_row = next(csv.reader([raw_lines[0]]))
    # Parse header row (row 2) to get sector names
    header_row = next(csv.reader([raw_lines[2]]))

    for col_idx, sector_name in enumerate(header_row[1:], start=1):
        sector_name = sector_name.strip()
        if not sector_name or sector_name.startswith("Kolumna"):
            continue
        # Find the cluster name for this column (scan cluster_row backwards)
        cluster_name = ""
        for i in range(col_idx, -1, -1):
            candidate = cluster_row[i].strip() if i < len(cluster_row) else ""
            if candidate:
                cluster_name = candidate
                break
        if cluster_name:
            mapper.register_sector_cluster(
                normalize_sector_name(sector_name), cluster_name
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_blue_competences(
    baseline_csv: Optional[Path] = None,
    sector_csv: Optional[Path] = None,
    cluster_csv: Optional[Path] = None,
) -> CompetenceMapper:
    """
    Load Blue Social Competences from CSV matrices into a CompetenceMapper.

    Parameters
    ----------
    baseline_csv : Path, optional
        Path to the Overall Blue Competences Dimension CSV.
        Defaults to the canonical location inside data/derived/.
    sector_csv : Path, optional
        Path to the Blue competences x blue economy sector CSV.
        Defaults to the canonical location inside data/derived/.
        If the file does not exist, sector requirements are skipped.
    cluster_csv : Path, optional
        Path to the Blue Clusters for Microcredentials CSV.
        Defaults to the canonical location inside data/derived/.
        If the file does not exist, cluster registration is skipped.

    Returns
    -------
    CompetenceMapper
        Mapper pre-populated with competences, sector requirements, and
        cluster mappings drawn from the three matrices.
    """
    baseline = Path(baseline_csv) if baseline_csv else _DEFAULT_BASELINE
    sector = Path(sector_csv) if sector_csv else _DEFAULT_SECTOR
    cluster = Path(cluster_csv) if cluster_csv else _DEFAULT_CLUSTER

    if not baseline.exists():
        raise FileNotFoundError(
            f"Baseline CSV not found: {baseline}\n"
            "Run `python scripts/build_derived.py` to generate data/derived/ files."
        )

    mapper = CompetenceMapper()

    print(f"\n📂 Loading baseline competences from: {baseline.name}")
    _load_baseline(baseline, mapper)
    print(f"   ✓ {len(mapper.competences)} competences loaded")

    if sector.exists():
        print(f"📂 Loading sector requirements from: {sector.name}")
        _load_sector_requirements(sector, mapper)
        print(f"   ✓ {len(mapper.sector_requirements)} sector requirement records loaded")
    else:
        print(f"   ℹ Sector CSV not found (skipped): {sector.name}")

    if cluster.exists():
        print(f"📂 Loading cluster mappings from: {cluster.name}")
        _load_clusters(cluster, mapper)
        print(f"   ✓ {len(mapper.sector_clusters)} sector-cluster mappings loaded")
    else:
        print(f"   ℹ Cluster CSV not found (skipped): {cluster.name}")

    print()
    return mapper


# ---------------------------------------------------------------------------
# CLI smoke-test entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Quick smoke-test: load all matrices and print a summary."""
    mapper = load_blue_competences()
    summary = mapper.get_summary()
    print("=" * 70)
    print("MORSKAMARY — load_real_competences smoke-test")
    print("=" * 70)
    print(f"Competences    : {summary['total_competences']}")
    print(f"Sector reqs    : {summary['total_sector_requirements']}")
    print(f"Sectors        : {len(summary['sectors'])}")
    print(f"Clusters       : {len(mapper.sector_clusters)}")
    print()
    for axis in BlueDynamicsAxis:
        count = summary["competences_by_axis"][axis.name]
        print(f"  {axis.name:10s}: {count}")
    print()
    for s in summary["sectors"]:
        lbl = summary["sector_labels"][s]
        total = mapper.get_sector_profile(s)["total_requirements"]
        cluster = mapper.get_sector_cluster(s)
        print(f"  {lbl:30s} reqs={total:3d}  cluster={cluster[:40] if cluster else '—'}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
