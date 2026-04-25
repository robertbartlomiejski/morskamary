"""Tests for scripts/validate_generated_outputs.py."""

import csv
import json
import sys
from pathlib import Path

import pytest

# Ensure repo root is on the path so the validator can be imported.
REPO_ROOT = Path(__file__).parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_generated_outputs.py"


def run_validator() -> int:
    """Run the validator as a subprocess-equivalent and return exit code."""
    import importlib.util
    import importlib

    spec = importlib.util.spec_from_file_location("validate_generated_outputs", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.main()


# ---------------------------------------------------------------------------
# Integration test: validator passes on real outputs
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_validator_passes_on_regenerated_outputs() -> None:
    """Validator must pass against the regenerated outputs/ directory."""
    outputs_dir = REPO_ROOT / "outputs"
    if not outputs_dir.exists():
        pytest.skip("outputs/ directory does not exist — run run_full_analysis.py first")

    required = [
        outputs_dir / "gaps_summary.csv",
        outputs_dir / "credentials_database.json",
        outputs_dir / "competences_full_database.json",
    ]
    for f in required:
        if not f.exists():
            pytest.skip(f"Required output file missing: {f}")

    # Import and run the validator
    import importlib.util

    spec = importlib.util.spec_from_file_location("validate_generated_outputs", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    result = mod.main()
    assert result == 0, "Validator reported failures on regenerated outputs"


# ---------------------------------------------------------------------------
# Unit tests for individual check functions
# ---------------------------------------------------------------------------


def _load_validator_module():
    """Load the validator module fresh (resetting global ERRORS)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("validate_generated_outputs_fresh", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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


def _make_gaps_rows(required: str = "100") -> list[dict]:
    """Return gaps CSV rows where all sectors have the same values."""
    return [
        {
            "Sector": s,
            "Required": required,
            "Available": "15",
            "Missing": "85",
            "Gap %": "85.0",
            "Missing MARINE": "10",
            "Missing MARITIME": "20",
            "Missing OCEANIC": "55",
        }
        for s in CANONICAL_SECTORS
    ]


class TestCheckGapsCsv:
    def test_fails_when_all_rows_identical(self) -> None:
        mod = _load_validator_module()
        rows = _make_gaps_rows(required="100")
        mod.check_gaps_csv(rows)
        assert any("identical" in e for e in mod.ERRORS), (
            "Expected failure when all sector rows are identical"
        )

    def test_passes_when_rows_differ(self) -> None:
        mod = _load_validator_module()
        rows = _make_gaps_rows()
        # Make rows differ
        for i, row in enumerate(rows):
            row["Required"] = str(100 + i)
            row["Missing"] = str(85 + i)
            row["Gap %"] = str(85.0 + i)
            row["Missing MARINE"] = str(10 + i)
            row["Missing MARITIME"] = str(20 + i)
            row["Missing OCEANIC"] = str(55 + i)
        mod.check_gaps_csv(rows)
        assert not mod.ERRORS, f"Expected no errors but got: {mod.ERRORS}"

    def test_fails_when_sector_missing(self) -> None:
        mod = _load_validator_module()
        rows = _make_gaps_rows()
        rows_partial = [r for r in rows if r["Sector"] != "Desalination"]
        mod.check_gaps_csv(rows_partial)
        assert any("Desalination" in e for e in mod.ERRORS)


class TestCheckCredentials:
    def _make_comps(self) -> dict:
        """Minimal competences dict with a couple of lit competences."""
        return {
            "lit_001": {
                "id": "lit_001",
                "dimension": "literature",
                "sectors": ["Blue Biotech", "Coastal Tourism"],
            },
            "lit_002": {
                "id": "lit_002",
                "dimension": "literature",
                "sectors": ["Desalination", "Maritime Transport"],
            },
            "baseline_a_1": {
                "id": "baseline_a_1",
                "dimension": "A",
                "sectors": CANONICAL_SECTORS,
            },
        }

    def _make_credentials(self, *, eqf6_lit_ids: dict[str, list[str]]) -> list[dict]:
        """Build a minimal credentials list.

        eqf6_lit_ids: sector → list of literature IDs to include in EQF6
        """
        creds = []
        for sector in CANONICAL_SECTORS:
            for level in [4, 5, 6, 7]:
                lit_ids = eqf6_lit_ids.get(sector, []) if level in [6, 7] else []
                creds.append(
                    {
                        "sector": sector,
                        "eqf_level": level,
                        "competences": ["baseline_a_1"] + lit_ids,
                    }
                )
        return creds

    def test_fails_when_lit_competence_not_in_sector(self) -> None:
        """EQF6 credential uses lit_001 for Desalination, but lit_001 is not in Desalination."""
        mod = _load_validator_module()
        comps = self._make_comps()
        creds = self._make_credentials(
            eqf6_lit_ids={s: ["lit_001"] for s in CANONICAL_SECTORS}
        )
        mod.check_credentials(creds, comps)
        assert any("lit_001" in e and "Desalination" in e for e in mod.ERRORS), (
            "Expected failure for lit_001 in Desalination EQF6 credential "
            f"(errors: {mod.ERRORS})"
        )

    def test_fails_when_all_sectors_same_lit_set(self) -> None:
        """All sectors sharing identical EQF6/EQF7 lit ID sets must fail."""
        mod = _load_validator_module()
        comps = self._make_comps()
        # Use a lit competence that is in all sectors so sector check passes
        comps["lit_all"] = {
            "id": "lit_all",
            "dimension": "literature",
            "sectors": CANONICAL_SECTORS,
        }
        creds = self._make_credentials(
            eqf6_lit_ids={s: ["lit_all"] for s in CANONICAL_SECTORS}
        )
        mod.check_credentials(creds, comps)
        assert any("same" in e or "identical" in e for e in mod.ERRORS), (
            f"Expected failure for identical EQF6/EQF7 sets (errors: {mod.ERRORS})"
        )

    def test_passes_with_valid_sector_specific_lit(self) -> None:
        """Valid sector-specific literature assignment must pass."""
        mod = _load_validator_module()
        comps = self._make_comps()
        # Blue Biotech → lit_001, Desalination → lit_002, others → []
        eqf6 = {s: [] for s in CANONICAL_SECTORS}
        eqf6["Blue Biotech"] = ["lit_001"]
        eqf6["Coastal Tourism"] = ["lit_001"]
        eqf6["Desalination"] = ["lit_002"]
        eqf6["Maritime Transport"] = ["lit_002"]
        creds = self._make_credentials(eqf6_lit_ids=eqf6)
        mod.check_credentials(creds, comps)
        leakage_errors = [e for e in mod.ERRORS if "literature" in e.lower() and "sector" not in e.lower()]
        # No cross-sector leakage errors expected
        assert not any("lit_" in e for e in mod.ERRORS), (
            f"Unexpected errors: {mod.ERRORS}"
        )


class TestCheckSectorDictionaries:
    def _write_dict_files(self, tmp_path: Path, ids_by_sector: dict[str, list[str]]) -> Path:
        """Write mock sector dictionary JSON files and return the directory."""
        for stem, ids in ids_by_sector.items():
            entries = [{"id": cid, "name": f"Competence {cid}", "description": "", "axis": "MARINE", "source": {}} for cid in ids]
            data = {
                "metadata": {"sector": stem, "source_workflow": "test", "axes": []},
                "dictionary": {"MARINE": entries, "MARITIME": [], "OCEANIC": []},
            }
            (tmp_path / f"{stem}_tmbd_dictionary.json").write_text(json.dumps(data))
        return tmp_path

    def test_fails_when_all_sector_dicts_identical(self, tmp_path: Path) -> None:
        mod = _load_validator_module()
        # 12 files with identical competence ID sets
        identical_ids = ["comp_a", "comp_b"]
        stems = [f"sector_{i:02d}" for i in range(12)]
        self._write_dict_files(tmp_path, {s: identical_ids for s in stems})
        mod.check_sector_dictionaries(tmp_path)
        assert any("identical" in e for e in mod.ERRORS), (
            f"Expected failure for identical sector dict sets (errors: {mod.ERRORS})"
        )

    def test_fails_when_not_exactly_12_files(self, tmp_path: Path) -> None:
        mod = _load_validator_module()
        # Only 3 files
        self._write_dict_files(tmp_path, {f"sector_{i}": [f"comp_{i}"] for i in range(3)})
        mod.check_sector_dictionaries(tmp_path)
        assert any("12" in e for e in mod.ERRORS), (
            f"Expected failure for != 12 sector dicts (errors: {mod.ERRORS})"
        )

    def test_passes_when_12_distinct_files(self, tmp_path: Path) -> None:
        mod = _load_validator_module()
        # 12 files each with unique IDs
        stems = [f"sector_{i:02d}" for i in range(12)]
        self._write_dict_files(tmp_path, {s: [f"comp_{s}"] for s in stems})
        mod.check_sector_dictionaries(tmp_path)
        assert not mod.ERRORS, f"Unexpected errors: {mod.ERRORS}"
