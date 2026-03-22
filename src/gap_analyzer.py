"""
Gap analyzer: identify competence gaps across all 12 Blue Economy sectors.

Loads the University of Szczecin 16-competence baseline matrix and computes
required vs. available competences per sector, returning structured gap
analysis results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pandas as pd  # type: ignore[import-untyped]

from src.core import BlueDynamicsAxis, Competence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SECTORS: List[str] = [
    "Blue Biotech",
    "Coastal Tourism",
    "Desalination",
    "Infrastructure & Robotics",
    "Living Resources",
    "Non-living Resources",
    "Renewable Energy",
    "Maritime Defence",
    "Maritime Transport",
    "Port Activities",
    "Research & Innovation",
    "Ship Repair & Shipbuilding",
]

SECTOR_TO_CSV_COL: Dict[str, str] = {
    "Blue Biotech": "Blue Biotech",
    "Coastal Tourism": "Coastal Tourism",
    "Desalination": "Desalination",
    "Infrastructure & Robotics": "Infra & Robotics",
    "Living Resources": "Living Res.",
    "Non-living Resources": "Non-living Res.",
    "Renewable Energy": "Renewable Energy",
    "Maritime Defence": "Maritime Defence",
    "Maritime Transport": "Maritime Transport",
    "Port Activities": "Port Activities",
    "Research & Innovation": "R&I",
    "Ship Repair & Shipbuilding": "Ship Repair",
}

# Valid baseline competence IDs per the TMBD specification.
# Note: A.4 is defined in the spec but is absent from the current baseline CSV;
# the list below acts as an allow-list and any ID missing from the CSV is simply
# not matched, so the effective baseline count from the CSV is 15, not 16.
BASELINE_IDS = [
    "A.1", "A.2", "A.3", "A.4",
    "B.1", "B.2", "B.3", "B.4",
    "C.1", "C.2", "C.3", "C.4",
    "D.1", "D.2", "D.3", "D.4",
]


def load_sector_matrix(csv_path: Path) -> pd.DataFrame:
    """Load the sector–competence matrix CSV into a DataFrame.

    Args:
        csv_path: Path to the *Overall Blue Competences Dimension* CSV.

    Returns:
        Cleaned :class:`pandas.DataFrame` with competence rows only.
    """
    df = pd.read_csv(csv_path, dtype=str)
    # Keep only rows whose ID column matches a known competence ID
    id_col = "ID"
    df = df[df[id_col].isin(BASELINE_IDS)].copy()
    df.reset_index(drop=True, inplace=True)
    return df


def get_sector_required_competence_ids(
    sector: str,
    df: pd.DataFrame,
) -> List[str]:
    """Return baseline competence IDs that have "X" for a given sector column.

    Args:
        sector: Sector name (must be a key in :data:`SECTOR_TO_CSV_COL`).
        df: Filtered DataFrame from :func:`load_sector_matrix`.

    Returns:
        List of competence IDs (e.g. ``["A.1", "B.2", ...]``).
    """
    col = SECTOR_TO_CSV_COL.get(sector)
    if col is None or col not in df.columns:
        return []

    ids: List[str] = []
    for _, row in df.iterrows():
        cell = str(row.get(col, "")).strip().upper()
        if cell == "X":
            ids.append(str(row["ID"]).strip())
    return ids


def analyze_gap(
    required_ids: List[str],
    available_ids: List[str],
    all_competences: Dict[str, Competence],
) -> Dict[str, Any]:
    """Compute gap metrics between required and available competences.

    Args:
        required_ids: Competence IDs required by the sector.
        available_ids: Competence IDs currently available/held.
        all_competences: Mapping of competence ID → :class:`Competence`.

    Returns:
        Dict with keys:

        - ``required`` – list of required IDs
        - ``available`` – list of available IDs that overlap with required
        - ``missing`` – IDs required but not available
        - ``gap_pct`` – percentage of required competences missing
        - ``axis_breakdown`` – mapping of axis name → list of missing IDs
    """
    required_set = set(required_ids)
    available_set = set(available_ids)

    covered = required_set & available_set
    missing = sorted(required_set - available_set)

    gap_pct = len(missing) / max(1, len(required_set)) * 100

    axis_breakdown: Dict[str, List[str]] = {ax.name: [] for ax in BlueDynamicsAxis}
    for cid in missing:
        comp = all_competences.get(cid)
        if comp:
            axis_breakdown[comp.axis.name].append(cid)

    return {
        "required": sorted(required_set),
        "available": sorted(covered),
        "missing": missing,
        "gap_pct": round(gap_pct, 2),
        "axis_breakdown": axis_breakdown,
    }


def identify_bridge_competences(
    sector_a: str,
    sector_b: str,
    gap_results: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Find competences missing in *sector_a* but available in *sector_b*.

    Useful for designing transition / bridge credentials.

    Args:
        sector_a: Source sector name.
        sector_b: Target sector name.
        gap_results: Output of :func:`analyze_gaps_all_sectors`.

    Returns:
        List of competence IDs that bridge the gap.
    """
    result_a = gap_results.get(sector_a, {})
    result_b = gap_results.get(sector_b, {})

    missing_in_a = set(result_a.get("missing", []))
    available_in_b = set(result_b.get("available", []))

    return sorted(missing_in_a & available_in_b)


def analyze_gaps_all_sectors(
    competences: Dict[str, Competence],
    df: pd.DataFrame,
) -> Dict[str, Dict[str, Any]]:
    """Run gap analysis for every sector using the baseline matrix.

    Available competences for each sector are the full baseline set (A.1–D.4).
    Required competences are those marked "X" in the sector's CSV column.

    Args:
        competences: Mapping of competence ID → :class:`Competence`.
        df: Sector matrix DataFrame from :func:`load_sector_matrix`.

    Returns:
        Dict mapping sector name → gap result dict.
    """
    baseline_ids = [cid for cid in competences if cid.startswith("baseline_")]
    # Map baseline object IDs back to CSV IDs for matrix lookup
    # e.g. "baseline_a_1" → "A.1"
    baseline_csv_ids = [
        cid.replace("baseline_", "").replace("_", ".").upper()
        for cid in baseline_ids
    ]

    results: Dict[str, Dict[str, Any]] = {}
    for sector in SECTORS:
        required_csv_ids = get_sector_required_competence_ids(sector, df)

        # Convert CSV IDs to object IDs for gap analysis
        required_obj_ids = [
            "baseline_" + cid.lower().replace(".", "_")
            for cid in required_csv_ids
        ]
        results[sector] = analyze_gap(
            required_obj_ids,
            baseline_ids,
            competences,
        )

    return results


def generate_gap_report(gap_results: Dict[str, Dict[str, Any]]) -> str:
    """Produce a plain-text summary of gap analysis results.

    Args:
        gap_results: Output of :func:`analyze_gaps_all_sectors`.

    Returns:
        Multi-line human-readable report string.
    """
    lines: List[str] = [
        "=" * 60,
        "BLUE ECONOMY COMPETENCE GAP ANALYSIS REPORT",
        "=" * 60,
        "",
    ]

    for sector, data in gap_results.items():
        gap_pct = data.get("gap_pct", 0.0)
        required = data.get("required", [])
        missing = data.get("missing", [])
        axis_bk = data.get("axis_breakdown", {})

        flag = "🟢" if gap_pct < 20 else ("🟡" if gap_pct < 50 else "🔴")
        lines.append(f"{flag}  {sector}")
        lines.append(f"    Required: {len(required)}  |  Missing: {len(missing)}  |  Gap: {gap_pct:.1f}%")

        for axis, ids in axis_bk.items():
            if ids:
                lines.append(f"    [{axis}] missing: {', '.join(ids)}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
