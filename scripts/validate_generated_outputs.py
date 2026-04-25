#!/usr/bin/env python3
"""
scripts/validate_generated_outputs.py — Semantic Validator for Generated Outputs

Validates that the committed outputs/ directory reflects the corrected
sector-aware literature competence logic introduced by PR #95 and PR #97.

Usage:
    python scripts/validate_generated_outputs.py

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs"

CANONICAL_SECTORS = [
    "Blue Biotech",
    "Coastal Tourism",
    "Desalination",
    "Infra & Robotics",
    "Living Res.",
    "Non-living Res.",
    "Renewable Energy",
    "Maritime Defence",
    "Maritime Transport",
    "Port Activities",
    "R&I",
    "Ship Repair",
]

ERRORS: list[str] = []
WARNINGS: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)
    print(f"  FAIL: {msg}")


def ok(msg: str) -> None:
    print(f"  OK:   {msg}")


def require_file(path: Path) -> bool:
    """Check that a required file exists. Returns False if missing."""
    if not path.exists():
        fail(f"Required file missing: {path}")
        return False
    return True


# ---------------------------------------------------------------------------
# Load artifacts
# ---------------------------------------------------------------------------


def load_competences(path: Path) -> dict:
    """Load competences_full_database.json → flat dict id→competence."""
    with path.open() as f:
        data = json.load(f)
    comps: dict[str, dict] = {}
    for c in data.get("baseline", []):
        comps[c["id"]] = c
    for c in data.get("literature", []):
        comps[c["id"]] = c
    return comps


def load_credentials(path: Path) -> list[dict]:
    """Load credentials_database.json → list of credential dicts."""
    with path.open() as f:
        data = json.load(f)
    return data.get("credentials", [])


def load_gaps_csv(path: Path) -> list[dict]:
    """Load gaps_summary.csv → list of row dicts."""
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def load_sector_dict_ids(path: Path) -> set[str]:
    """Load a sector TMBD dictionary and return all competence IDs."""
    with path.open() as f:
        data = json.load(f)
    ids: set[str] = set()
    dictionary = data.get("dictionary", {})
    if isinstance(dictionary, dict):
        for entries in dictionary.values():
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and "id" in entry:
                        ids.add(entry["id"])
    return ids


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_gaps_csv(rows: list[dict]) -> None:
    """Validate gaps_summary.csv contents."""
    print("\n[gaps_summary.csv]")

    # 1. All 12 canonical sectors present
    found_sectors = {r["Sector"] for r in rows}
    missing = set(CANONICAL_SECTORS) - found_sectors
    if missing:
        fail(f"Missing sectors in gaps_summary.csv: {sorted(missing)}")
    else:
        ok(f"All 12 canonical sectors present")

    # 2. Must NOT have identical values for all sectors
    # Check the key numeric columns
    numeric_cols = ["Required", "Missing", "Gap %", "Missing MARINE", "Missing MARITIME", "Missing OCEANIC"]
    for col in numeric_cols:
        values = set()
        for row in rows:
            if col in row:
                values.add(row[col].strip())
        if len(values) <= 1 and len(rows) > 1:
            fail(
                f"Column '{col}' has identical value ({next(iter(values))!r}) "
                f"for all sectors — outputs appear stale (pre-PR#95)"
            )
        else:
            ok(f"Column '{col}' has {len(values)} distinct values across sectors")


def check_credentials(
    credentials: list[dict],
    all_comps: dict[str, dict],
) -> None:
    """Validate credentials_database.json contents."""
    print("\n[credentials_database.json]")

    # 1. All 12 sectors must appear
    cred_sectors = {c.get("sector") for c in credentials}
    missing_sectors = set(CANONICAL_SECTORS) - cred_sectors
    if missing_sectors:
        fail(f"Missing sectors in credentials: {sorted(missing_sectors)}")
    else:
        ok("All 12 canonical sectors have credentials")

    # 2. EQF levels 4–7 must be present per sector (or at minimum EQF 4 and 7)
    eqf_levels_by_sector: dict[str, set] = {}
    for c in credentials:
        sector = c.get("sector", "")
        lvl = c.get("eqf_level")
        eqf_levels_by_sector.setdefault(sector, set()).add(lvl)

    for sector in CANONICAL_SECTORS:
        levels = eqf_levels_by_sector.get(sector, set())
        expected = {4, 5, 6, 7}
        if not expected.issubset(levels):
            fail(
                f"Sector '{sector}' is missing EQF levels: "
                f"{sorted(expected - levels)}"
            )
    else:
        ok("EQF levels 4–7 present for all 12 sectors")

    # 3. For EQF6/EQF7: every literature competence in a credential must have
    #    that credential's sector in its own sectors list.
    leakage_found = False
    for cred in credentials:
        if cred.get("eqf_level") not in [6, 7]:
            continue
        sector = cred.get("sector", "")
        for cid in cred.get("competences", []):
            comp = all_comps.get(cid)
            if comp is None or comp.get("dimension") != "literature":
                continue
            comp_sectors = comp.get("sectors", [])
            if sector not in comp_sectors:
                fail(
                    f"EQF{cred['eqf_level']} credential for '{sector}' "
                    f"contains literature competence '{cid}' whose sectors "
                    f"list does not include '{sector}': {comp_sectors}"
                )
                leakage_found = True

    if not leakage_found:
        ok("No cross-sector literature leakage in EQF6/EQF7 credentials")

    # 4. EQF6/EQF7 literature ID sets must not be identical for all sectors
    eqf67_lit_sets: dict[str, frozenset] = {}
    for cred in credentials:
        if cred.get("eqf_level") not in [6, 7]:
            continue
        sector = cred.get("sector", "")
        lit_ids = frozenset(
            cid
            for cid in cred.get("competences", [])
            if all_comps.get(cid, {}).get("dimension") == "literature"
        )
        eqf67_lit_sets.setdefault(sector, frozenset())
        eqf67_lit_sets[sector] = eqf67_lit_sets[sector] | lit_ids

    if len(eqf67_lit_sets) > 1:
        unique_sets = set(eqf67_lit_sets.values())
        if len(unique_sets) == 1:
            fail(
                "All sectors have the same EQF6/EQF7 literature competence set "
                "— outputs appear stale (pre-PR#97)"
            )
        else:
            ok(
                f"EQF6/EQF7 literature ID sets differ across sectors "
                f"({len(unique_sets)} distinct sets)"
            )


def check_desalination_integrity(
    credentials: list[dict],
    all_comps: dict[str, dict],
) -> None:
    """Desalination-specific integrity check."""
    print("\n[Desalination integrity]")

    for cred in credentials:
        if cred.get("sector") != "Desalination" or cred.get("eqf_level") not in [6, 7]:
            continue
        for cid in cred.get("competences", []):
            comp = all_comps.get(cid)
            if comp is None or comp.get("dimension") != "literature":
                continue
            comp_sectors = comp.get("sectors", [])
            if "Desalination" not in comp_sectors:
                fail(
                    f"Desalination EQF{cred['eqf_level']} credential contains "
                    f"literature competence '{cid}' whose sectors list does not "
                    f"include 'Desalination': {comp_sectors}"
                )
            if "Living Res." in comp_sectors and "Desalination" not in comp_sectors:
                fail(
                    f"Living Res. literature competence '{cid}' leaked into "
                    f"Desalination EQF{cred['eqf_level']} credential but "
                    f"Desalination is not in its sectors: {comp_sectors}"
                )

    ok("Desalination EQF6/EQF7 credentials contain only Desalination-valid literature")


def check_sector_dictionaries(sector_dict_dir: Path) -> None:
    """Validate sector TMBD dictionary files."""
    print("\n[sector_dictionaries/]")

    if not sector_dict_dir.exists():
        fail(f"Sector dictionary directory missing: {sector_dict_dir}")
        return

    dict_files = sorted(sector_dict_dir.glob("*_tmbd_dictionary.json"))

    # 1. Exactly 12 files
    if len(dict_files) != 12:
        fail(
            f"Expected exactly 12 sector dictionary files, found {len(dict_files)}: "
            f"{[f.name for f in dict_files]}"
        )
    else:
        ok(f"Exactly 12 sector dictionary JSON files found")

    # 2. Load ID sets
    id_sets: dict[str, frozenset] = {}
    for f in dict_files:
        try:
            ids = load_sector_dict_ids(f)
            id_sets[f.stem] = frozenset(ids)
        except Exception as exc:
            fail(f"Failed to parse {f.name}: {exc}")

    # 3. ID sets must not be all identical
    if id_sets:
        unique_sets = set(id_sets.values())
        if len(unique_sets) == 1:
            fail(
                "All sector dictionary competence ID sets are identical — "
                "sector-scoping logic may not be applied correctly"
            )
        else:
            ok(f"Sector dictionary competence ID sets differ ({len(unique_sets)} distinct sets)")

    # 4. Spot-check: Desalination, Living Res., Maritime Transport differ
    key_map = {
        "Desalination": "desalination_tmbd_dictionary",
        "Living Res.": "living_res_tmbd_dictionary",
        "Maritime Transport": "maritime_transport_tmbd_dictionary",
    }
    spot_ids: dict[str, frozenset] = {}
    for label, stem in key_map.items():
        if stem in id_sets:
            spot_ids[label] = id_sets[stem]

    if len(spot_ids) == 3:
        spot_unique = set(spot_ids.values())
        if len(spot_unique) < 2:
            fail(
                "Desalination, Living Res., and Maritime Transport sector "
                "dictionaries all have the same competence ID set"
            )
        else:
            ok(
                "Desalination, Living Res., and Maritime Transport dictionaries "
                "have distinct competence ID sets"
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("=" * 65)
    print("Semantic Output Validator — morskamary")
    print("=" * 65)

    # Required files
    gaps_csv_path = OUTPUTS_DIR / "gaps_summary.csv"
    creds_path = OUTPUTS_DIR / "credentials_database.json"
    comps_path = OUTPUTS_DIR / "competences_full_database.json"
    sector_dict_dir = OUTPUTS_DIR / "sector_dictionaries"

    required_files = [gaps_csv_path, creds_path, comps_path]
    all_present = all(require_file(p) for p in required_files)
    if not all_present:
        print("\nAbort: one or more required files are missing.")
        return 1

    # Load data
    all_comps = load_competences(comps_path)
    credentials = load_credentials(creds_path)
    gaps_rows = load_gaps_csv(gaps_csv_path)

    # Run checks
    check_gaps_csv(gaps_rows)
    check_credentials(credentials, all_comps)
    check_desalination_integrity(credentials, all_comps)
    check_sector_dictionaries(sector_dict_dir)

    print()
    if ERRORS:
        print("=" * 65)
        print(f"VALIDATION FAILED — {len(ERRORS)} error(s):")
        for i, err in enumerate(ERRORS, 1):
            print(f"  [{i}] {err}")
        print("=" * 65)
        return 1
    else:
        print("=" * 65)
        print("VALIDATION PASSED — all checks OK.")
        print("=" * 65)
        return 0


if __name__ == "__main__":
    sys.exit(main())
