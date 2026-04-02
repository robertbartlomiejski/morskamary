#!/usr/bin/env python3
"""
Full Blue Sociology Analysis Orchestrator

Executes all analysis steps:
1. Load 16 baseline competences from University of Szczecin CSV
2. Extract 200+ literature competences from combined_*.csv files
3. Merge and deduplicate all competences
4. Analyze gaps for all 12 sectors
5. Design micro-credentials for all sectors
6. Calculate transition pathways
7. Generate HTML/JSON/CSV reports
8. Export databases

Usage: python run_full_analysis.py
Output: outputs/ directory with all reports and databases
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent
OUTPUTS_DIR = REPO_ROOT / "outputs"
DATA_DERIVED = REPO_ROOT / "data" / "derived"
DATA_RAW = REPO_ROOT / "data" / "raw"
LOG_FILE = OUTPUTS_DIR / "execution_log.txt"

_BASELINE_CSV = (
    DATA_DERIVED
    / "Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv"
)

# ---------------------------------------------------------------------------
# Imports from src (after path is set up)
# ---------------------------------------------------------------------------

from src.core import (
    BlueDynamicsAxis,
    Competence,
    CompetenceLevel,
    MicroCredential,
)  # noqa: E402
from src import (
    literature_extractor,
    gap_analyzer,
    credential_designer,
    report_generator,
)  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_log_lines: List[str] = []


def log(msg: str, symbol: str = "✅") -> None:
    """Print *msg* to stdout and append it to the execution log buffer."""
    line = f"{symbol}  {msg}"
    print(line)
    _log_lines.append(line)


def _flush_log() -> None:
    """Write accumulated log lines to *LOG_FILE*."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("\n".join(_log_lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Dimension → axis + level mapping
# ---------------------------------------------------------------------------

_DIM_TO_AXIS: Dict[str, BlueDynamicsAxis] = {
    "A": BlueDynamicsAxis.OCEANIC,
    "B": BlueDynamicsAxis.MARITIME,
    "C": BlueDynamicsAxis.MARINE,
    "D": BlueDynamicsAxis.MARITIME,
}

_DIM_TO_LEVEL: Dict[str, CompetenceLevel] = {
    "A": CompetenceLevel.INTERMEDIATE,
    "B": CompetenceLevel.INTERMEDIATE,
    "C": CompetenceLevel.ADVANCED,
    "D": CompetenceLevel.ADVANCED,
}

# Note: A.4 is listed per the TMBD spec but is absent from the current baseline
# CSV (which has 15 competence rows).  The set acts as an allow-list; any ID
# not present in the CSV simply matches no rows and is harmlessly ignored.
_VALID_IDS = {
    "A.1",
    "A.2",
    "A.3",
    "A.4",
    "B.1",
    "B.2",
    "B.3",
    "B.4",
    "C.1",
    "C.2",
    "C.3",
    "C.4",
    "D.1",
    "D.2",
    "D.3",
    "D.4",
}


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------


def load_baseline_competences() -> List[Competence]:
    """Load the 16 University of Szczecin baseline competences.

    Returns:
        List of :class:`Competence` objects with IDs like ``baseline_a_1``.
    """
    if not _BASELINE_CSV.exists():
        log(f"Baseline CSV not found: {_BASELINE_CSV}", "❌")
        return []

    df = pd.read_csv(_BASELINE_CSV, dtype=str)
    competences: List[Competence] = []
    row_num = 1

    for _, row in df.iterrows():
        row_num += 1
        raw_id = str(row.get("ID", "") or "").strip()
        if raw_id not in _VALID_IDS:
            continue

        dim = raw_id[0]
        axis = _DIM_TO_AXIS.get(dim, BlueDynamicsAxis.MARITIME)
        level = _DIM_TO_LEVEL.get(dim, CompetenceLevel.INTERMEDIATE)

        name = str(row.get("Competence Name", "") or "").strip()
        description = str(
            row.get("Key Simplified Focus (Applied to all 12 Sectors)", "") or ""
        ).strip()
        comp_id = "baseline_" + raw_id.lower().replace(".", "_")

        competences.append(
            Competence(
                id=comp_id,
                name=name,
                description=description,
                axis=axis,
                level=level,
                keywords=[w.lower() for w in name.split() if len(w) >= 4],
                source_metadata={
                    "file": _BASELINE_CSV.name,
                    "row": row_num,
                    "authors": "University of Szczecin",
                    "year": 2024,
                },
            )
        )

    return competences


def extract_literature_competences() -> List[Competence]:
    """Extract competences from all ``combined_*.csv`` literature files.

    Returns:
        Deduplicated list of :class:`Competence` objects.
    """
    return literature_extractor.extract_literature_competences(DATA_RAW)


def merge_and_deduplicate(
    baseline: List[Competence],
    literature: List[Competence],
) -> List[Competence]:
    """Combine baseline and literature competences, removing duplicates by name.

    Args:
        baseline: Baseline competences (always kept first).
        literature: Literature-derived competences.

    Returns:
        Merged, deduplicated list.
    """
    combined = baseline + literature
    seen: set[str] = set()
    unique: List[Competence] = []
    for comp in combined:
        key = comp.name.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(comp)
    return unique


def analyze_gaps_all_sectors(
    all_competences: List[Competence],
) -> Dict[str, Dict[str, Any]]:
    """Run gap analysis for all 12 sectors.

    Args:
        all_competences: Merged competence list.

    Returns:
        Sector → gap result mapping.
    """
    if not _BASELINE_CSV.exists():
        log("Baseline CSV missing — cannot run gap analysis", "❌")
        return {}

    comp_dict: Dict[str, Competence] = {c.id: c for c in all_competences}
    df = gap_analyzer.load_sector_matrix(_BASELINE_CSV)
    return gap_analyzer.analyze_gaps_all_sectors(comp_dict, df)


def design_credentials_all_sectors(
    all_competences: List[Competence],
    gap_results: Dict[str, Dict[str, Any]],
) -> Dict[str, List[MicroCredential]]:
    """Group competences by sector and generate credentials.

    Args:
        all_competences: Merged competence list.
        gap_results: Gap analysis results (used to identify required comps).

    Returns:
        Sector → credential list mapping.
    """
    comp_dict: Dict[str, Competence] = {c.id: c for c in all_competences}

    sector_comps: Dict[str, List[Competence]] = {}
    for sector, data in gap_results.items():
        required_ids = data.get("required", [])
        comps = [comp_dict[cid] for cid in required_ids if cid in comp_dict]
        # If a sector has no required comps mapped (all X), fall back to baseline
        if not comps:
            comps = [c for c in all_competences if c.id.startswith("baseline_")]
        sector_comps[sector] = comps

    return credential_designer.design_credentials_all_sectors(sector_comps)


def _calculate_pathways(
    credentials_by_sector: Dict[str, List[MicroCredential]],
) -> Dict[str, Any]:
    """Delegate to :func:`credential_designer.calculate_pathways`.

    Args:
        credentials_by_sector: Sector → credential list.

    Returns:
        Pathway graph dict.
    """
    return credential_designer.calculate_pathways(credentials_by_sector)


def generate_reports(
    all_competences: List[Competence],
    all_credentials_flat: List[MicroCredential],
    credentials_by_sector: Dict[str, List[MicroCredential]],
    gap_results: Dict[str, Dict[str, Any]],
    literature_competences: List[Competence],
    pathways: Dict[str, Any],
) -> None:
    """Run all report generators and log output paths.

    Args:
        all_competences: Full merged competence list.
        all_credentials_flat: Flat list of all credentials.
        credentials_by_sector: Sector-grouped credentials.
        gap_results: Gap analysis results.
        literature_competences: Literature-only competences (for lit report).
        pathways: Pathway graph.
    """
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    idx = report_generator.generate_html_index(
        all_competences, all_credentials_flat, gap_results, OUTPUTS_DIR
    )
    log(f"Index HTML → {idx}")

    gaps_html = report_generator.generate_gaps_html(gap_results, OUTPUTS_DIR)
    log(f"Gaps HTML → {gaps_html}")

    cred_html = report_generator.generate_credentials_html(
        credentials_by_sector, OUTPUTS_DIR
    )
    log(f"Credentials HTML → {cred_html}")

    lit_html = report_generator.generate_literature_html(
        literature_competences, OUTPUTS_DIR
    )
    log(f"Literature HTML → {lit_html}")

    json_paths = report_generator.generate_json_databases(
        all_competences, all_credentials_flat, pathways, OUTPUTS_DIR
    )
    for p in json_paths:
        log(f"JSON DB → {p}")

    csv_path = report_generator.generate_csv_exports(gap_results, OUTPUTS_DIR)
    log(f"Gaps CSV → {csv_path}")

    readme = report_generator.create_outputs_readme(
        OUTPUTS_DIR, all_competences, all_credentials_flat
    )
    log(f"Outputs README → {readme}")


def _update_changelog(
    n_comp: int,
    n_cred: int,
    n_sectors: int,
) -> None:
    """Append a summary entry to CHANGELOG.txt."""
    changelog = REPO_ROOT / "CHANGELOG.txt"
    today = date.today().isoformat()
    entry = (
        f"\n[{today}] run_full_analysis.py executed\n"
        f"  - Total competences: {n_comp}\n"
        f"  - Total credentials: {n_cred}\n"
        f"  - Sectors analysed: {n_sectors}\n"
        f"  - Reports written to: outputs/\n"
    )
    with changelog.open("a", encoding="utf-8") as fh:
        fh.write(entry)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Execute the full analysis pipeline end-to-end."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    log("Blue Sociology Full Analysis — starting", "🌊")

    # Step 1: baseline
    log("Step 1: Loading 16 baseline competences …", "📋")
    baseline = load_baseline_competences()
    log(f"Loaded {len(baseline)} baseline competences")

    # Step 2: literature
    log("Step 2: Extracting literature competences …", "📚")
    literature = extract_literature_competences()
    log(f"Extracted {len(literature)} literature competences")

    # Step 3: merge
    log("Step 3: Merging and deduplicating …", "🔀")
    all_competences = merge_and_deduplicate(baseline, literature)
    log(f"Merged total: {len(all_competences)} competences")

    # Step 4: gap analysis
    log("Step 4: Analyzing gaps for all 12 sectors …", "🔍")
    gap_results = analyze_gaps_all_sectors(all_competences)
    log(f"Gap analysis complete for {len(gap_results)} sectors")

    # Step 5: credentials
    log("Step 5: Designing micro-credentials …", "🎓")
    credentials_by_sector = design_credentials_all_sectors(all_competences, gap_results)
    all_credentials_flat = [
        cred for creds in credentials_by_sector.values() for cred in creds
    ]
    log(
        f"Designed {len(all_credentials_flat)} credentials across {len(credentials_by_sector)} sectors"
    )

    # Step 6: pathways
    log("Step 6: Calculating pathways …", "🗺️")
    pathways = _calculate_pathways(credentials_by_sector)
    log(
        f"Pathway graph: {len(pathways.get('nodes', []))} nodes, {len(pathways.get('edges', []))} edges"
    )

    # Steps 7+8: reports
    log("Step 7+8: Generating reports and exporting databases …", "📊")
    generate_reports(
        all_competences,
        all_credentials_flat,
        credentials_by_sector,
        gap_results,
        literature,
        pathways,
    )

    # Flush log
    _flush_log()

    # Final summary
    print("\n" + "=" * 60)
    print("🌊  BLUE SOCIOLOGY ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"  Competences total : {len(all_competences)}")
    print(f"    Baseline        : {len(baseline)}")
    print(f"    Literature      : {len(literature)}")
    print(f"  Credentials       : {len(all_credentials_flat)}")
    print(f"  Sectors analysed  : {len(gap_results)}")
    print(f"  Reports in        : {OUTPUTS_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
