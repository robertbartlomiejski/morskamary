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

REQUIRED_GAP_COLUMNS = [
    "Sector",
    "Required",
    "Missing",
    "Gap %",
    "Missing MARINE",
    "Missing MARITIME",
    "Missing OCEANIC",
]

REQUIRED_CREDENTIAL_FIELDS = (
    "id",
    "title",
    "sector",
    "eqf_level",
    "ects",
    "assessment_method",
    "learner_profile",
    "learning_outcomes",
    "stackability_rules",
    "prerequisites",
    "competences",
)

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
# Load artifacts — validate schema loudly on required fields
# ---------------------------------------------------------------------------


def load_competences(path: Path) -> dict[str, dict]:
    """Load competences_full_database.json → flat dict id→competence.

    Fails loudly if required top-level keys or per-entry fields are absent.
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        fail(
            f"{path.name}: expected a JSON object at top level, "
            f"got {type(data).__name__}"
        )
        return {}

    for key in ("baseline", "literature"):
        if key not in data:
            fail(
                f"{path.name}: required top-level key '{key}' is missing"
            )

    comps: dict[str, dict] = {}
    required_comp_fields = ("id", "dimension", "sectors")
    for section in ("baseline", "literature"):
        entries = data.get(section, [])
        if not isinstance(entries, list):
            fail(
                f"{path.name}: '{section}' must be a list, "
                f"got {type(entries).__name__}"
            )
            continue
        for i, c in enumerate(entries):
            if not isinstance(c, dict):
                fail(
                    f"{path.name}: {section}[{i}] is not an object"
                )
                continue
            for field in required_comp_fields:
                if field not in c:
                    fail(
                        f"{path.name}: {section}[{i}] is missing required "
                        f"field '{field}' (id={c.get('id', '<unknown>')})"
                    )
            if "id" in c:
                comps[c["id"]] = c

    return comps


def load_credentials(path: Path) -> list[dict]:
    """Load credentials_database.json → list of credential dicts.

    Fails loudly if required top-level key or per-entry fields are absent.
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        fail(
            f"{path.name}: expected a JSON object at top level, "
            f"got {type(data).__name__}"
        )
        return []

    if "credentials" not in data:
        fail(
            f"{path.name}: required top-level key 'credentials' is missing"
        )
        return []

    entries = data["credentials"]
    if not isinstance(entries, list):
        fail(
            f"{path.name}: 'credentials' must be a list, "
            f"got {type(entries).__name__}"
        )
        return []

    for i, c in enumerate(entries):
        if not isinstance(c, dict):
            fail(f"{path.name}: credentials[{i}] is not an object")
            continue
        for field in REQUIRED_CREDENTIAL_FIELDS:
            if field not in c:
                fail(
                    f"{path.name}: credentials[{i}] is missing required "
                    f"field '{field}' (id={c.get('id', '<unknown>')})"
                )

    return entries


def load_gaps_csv(path: Path) -> list[dict]:
    """Load gaps_summary.csv → list of row dicts.

    Fails loudly if required columns are absent.
    """
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        fail(f"{path.name}: file is empty or has no data rows")
        return []

    present_cols = set(rows[0].keys())
    for col in REQUIRED_GAP_COLUMNS:
        if col not in present_cols:
            fail(
                f"{path.name}: required column '{col}' is missing "
                f"(found: {sorted(present_cols)})"
            )

    return rows


def load_sector_dict_ids(path: Path) -> set[str]:
    """Load a sector TMBD dictionary and return all competence IDs.

    Raises ValueError with a clear message if the dictionary schema is
    unreadable or yields no IDs.
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a JSON object at top level, got {type(data).__name__}"
        )

    if "dictionary" not in data:
        raise ValueError("Required key 'dictionary' is missing from sector dictionary")

    dictionary = data["dictionary"]
    if not isinstance(dictionary, dict):
        raise ValueError(
            f"'dictionary' must be a JSON object, got {type(dictionary).__name__}"
        )

    ids: set[str] = set()
    for axis, entries in dictionary.items():
        if not isinstance(entries, list):
            continue
        for j, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            if "id" not in entry:
                raise ValueError(
                    f"Entry {j} under axis '{axis}' is missing required field 'id'"
                )
            ids.add(entry["id"])

    return ids


def load_cumulative_qmbd_records(path: Path) -> list[dict]:
    """Load cumulative_qmbd_records.json and validate required schema fields."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        fail(
            f"{path.name}: expected a list of records, got {type(data).__name__}"
        )
        return []

    required_record_fields = (
        "source_id",
        "title",
        "axis_name",
        "record_origin",
        "qmbd_analysis",
    )
    required_sentence_fields = ("axis", "axis_code", "text_scope", "sentence")

    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            fail(f"{path.name}: record[{idx}] is not an object")
            continue
        for field in required_record_fields:
            if field not in item:
                fail(f"{path.name}: record[{idx}] missing required field '{field}'")

        qmbd_analysis = item.get("qmbd_analysis")
        if not isinstance(qmbd_analysis, list):
            fail(
                f"{path.name}: record[{idx}] field 'qmbd_analysis' must be a list"
            )
            continue
        if not qmbd_analysis:
            fail(f"{path.name}: record[{idx}] has empty qmbd_analysis")
            continue

        for sentence_idx, sentence_item in enumerate(qmbd_analysis):
            if not isinstance(sentence_item, dict):
                fail(
                    f"{path.name}: record[{idx}] qmbd_analysis[{sentence_idx}] "
                    "is not an object"
                )
                continue
            for field in required_sentence_fields:
                if field not in sentence_item:
                    fail(
                        f"{path.name}: record[{idx}] qmbd_analysis[{sentence_idx}] "
                        f"missing required field '{field}'"
                    )
            if not str(sentence_item.get("text_scope", "")).strip():
                fail(
                    f"{path.name}: record[{idx}] qmbd_analysis[{sentence_idx}] "
                    "has empty text_scope"
                )
            if not str(sentence_item.get("sentence", "")).strip():
                fail(
                    f"{path.name}: record[{idx}] qmbd_analysis[{sentence_idx}] "
                    "has empty sentence"
                )

    return data


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_gaps_csv(rows: list[dict]) -> None:
    """Validate gaps_summary.csv contents."""
    print("\n[gaps_summary.csv]")

    # 1. All 12 canonical sectors present
    found_sectors = {r.get("Sector", "") for r in rows}
    missing = set(CANONICAL_SECTORS) - found_sectors
    if missing:
        fail(f"Missing sectors in gaps_summary.csv: {sorted(missing)}")
    else:
        ok("All 12 canonical sectors present")

    # 2. Must NOT have identical values for all sectors
    numeric_cols = [
        "Required",
        "Missing",
        "Gap %",
        "Missing MARINE",
        "Missing MARITIME",
        "Missing OCEANIC",
    ]
    for col in numeric_cols:
        values = set()
        for row in rows:
            val = row.get(col)
            if val is not None:
                values.add(val.strip())
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

    # 2. EQF levels 4–7 must be present per sector
    eqf_levels_by_sector: dict[str, set] = {}
    for c in credentials:
        sector = c.get("sector", "")
        lvl = c.get("eqf_level")
        eqf_levels_by_sector.setdefault(sector, set()).add(lvl)

    eqf_ok = True
    for sector in CANONICAL_SECTORS:
        levels = eqf_levels_by_sector.get(sector, set())
        expected = {4, 5, 6, 7}
        if not expected.issubset(levels):
            fail(
                f"Sector '{sector}' is missing EQF levels: "
                f"{sorted(expected - levels)}"
            )
            eqf_ok = False

    if eqf_ok:
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

    # 4.5 Ensure each credential has complete and non-empty quality fields
    completeness_errors = False
    for cred in credentials:
        cred_id = cred.get("id", "<unknown>")
        outcomes = cred.get("learning_outcomes", [])
        if not isinstance(outcomes, list) or not outcomes:
            fail(f"Credential '{cred_id}' has missing/empty learning_outcomes list")
            completeness_errors = True
        stackability = str(cred.get("stackability_rules", "")).strip()
        if not stackability:
            fail(f"Credential '{cred_id}' has empty stackability_rules")
            completeness_errors = True
        assessment = str(cred.get("assessment_method", "")).strip()
        if not assessment:
            fail(f"Credential '{cred_id}' has empty assessment_method")
            completeness_errors = True

    if not completeness_errors:
        ok("Credential completeness fields are present and non-empty")

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


def check_cumulative_qmbd_records(records: list[dict]) -> None:
    """Validate cumulative_qmbd_records integrity and provenance coverage."""
    print("\n[cumulative_qmbd_records.json]")

    if not records:
        fail("cumulative_qmbd_records.json is empty")
        return

    origins = {str(item.get("record_origin", "")) for item in records}
    if "STATIC_BASELINE" not in origins:
        fail("Missing STATIC_BASELINE records in cumulative_qmbd_records.json")
    else:
        ok("STATIC_BASELINE origin present")
    if "STATIC_LITERATURE" not in origins:
        fail("Missing STATIC_LITERATURE records in cumulative_qmbd_records.json")
    else:
        ok("STATIC_LITERATURE origin present")

    duplicate_keys = set()
    seen_keys = set()
    for item in records:
        key = (str(item.get("record_origin", "")), str(item.get("source_id", "")))
        if key in seen_keys:
            duplicate_keys.add(key)
        seen_keys.add(key)
    if duplicate_keys:
        fail(
            "Duplicate (record_origin, source_id) keys found in cumulative records: "
            f"{sorted(duplicate_keys)[:5]}"
        )
    else:
        ok("No duplicate (record_origin, source_id) keys detected")


def check_desalination_integrity(
    credentials: list[dict],
    all_comps: dict[str, dict],
) -> None:
    """Desalination-specific integrity check."""
    print("\n[Desalination integrity]")

    desal_ok = True
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
                desal_ok = False
            if "Living Res." in comp_sectors and "Desalination" not in comp_sectors:
                fail(
                    f"Living Res. literature competence '{cid}' leaked into "
                    f"Desalination EQF{cred['eqf_level']} credential but "
                    f"Desalination is not in its sectors: {comp_sectors}"
                )
                desal_ok = False

    if desal_ok:
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
        ok("Exactly 12 sector dictionary JSON files found")

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
            ok(
                f"Sector dictionary competence ID sets differ "
                f"({len(unique_sets)} distinct sets)"
            )

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
    # Reset global state so that repeated in-process calls are independent.
    ERRORS.clear()
    WARNINGS.clear()

    print("=" * 65)
    print("Semantic Output Validator — morskamary")
    print("=" * 65)

    # Required files
    gaps_csv_path = OUTPUTS_DIR / "gaps_summary.csv"
    creds_path = OUTPUTS_DIR / "credentials_database.json"
    comps_path = OUTPUTS_DIR / "competences_full_database.json"
    cumulative_path = OUTPUTS_DIR / "cumulative_qmbd_records.json"
    sector_dict_dir = OUTPUTS_DIR / "sector_dictionaries"

    required_files = [gaps_csv_path, creds_path, comps_path, cumulative_path]
    all_present = all(require_file(p) for p in required_files)
    if not all_present:
        print("\nAbort: one or more required files are missing.")
        return 1

    # Load data (schema errors are collected via fail() during loading)
    all_comps = load_competences(comps_path)
    credentials = load_credentials(creds_path)
    gaps_rows = load_gaps_csv(gaps_csv_path)
    cumulative_records = load_cumulative_qmbd_records(cumulative_path)

    # Run semantic checks
    check_gaps_csv(gaps_rows)
    check_credentials(credentials, all_comps)
    check_cumulative_qmbd_records(cumulative_records)
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
