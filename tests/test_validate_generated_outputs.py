"""Tests for scripts/validate_generated_outputs.py."""

import json
from pathlib import Path

import pytest

# Ensure repo root is on the path so the validator can be imported.
REPO_ROOT = Path(__file__).parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_generated_outputs.py"


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
        outputs_dir / "cumulative_qmbd_records.json",
    ]
    for f in required:
        if not f.exists():
            pytest.skip(f"Required output file missing: {f}")

    mod = _load_validator_module()
    result = mod.main()
    assert result == 0, "Validator reported failures on regenerated outputs"


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


# ---------------------------------------------------------------------------
# State-reset regression test
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_main_state_reset_between_calls() -> None:
    """main() must clear ERRORS at start so repeated in-process calls are independent.

    Verify that pre-existing ERRORS (e.g., from a prior call or manual injection)
    do not contaminate a subsequent successful run.
    """
    outputs_dir = REPO_ROOT / "outputs"
    if not outputs_dir.exists():
        pytest.skip("outputs/ directory does not exist — run run_full_analysis.py first")
    required = [
        outputs_dir / "gaps_summary.csv",
        outputs_dir / "credentials_database.json",
        outputs_dir / "competences_full_database.json",
        outputs_dir / "cumulative_qmbd_records.json",
    ]
    for f in required:
        if not f.exists():
            pytest.skip(f"Required output file missing: {f}")

    mod = _load_validator_module()

    # Manually inject a stale error before the first call.
    mod.ERRORS.append("stale-sentinel-error-from-previous-run")
    assert "stale-sentinel-error-from-previous-run" in mod.ERRORS

    # Run main() — it should clear ERRORS first, then pass on real outputs.
    result = mod.main()

    # After a successful run, the sentinel must be gone and result must be 0.
    assert result == 0, f"Validator failed after state reset; ERRORS: {mod.ERRORS}"
    assert "stale-sentinel-error-from-previous-run" not in mod.ERRORS, (
        "main() did not clear stale ERRORS from a prior run"
    )


# ---------------------------------------------------------------------------
# Schema validation tests (load_competences / load_credentials / load_gaps_csv)
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_load_competences_fails_on_missing_baseline_key(self, tmp_path: Path) -> None:
        """load_competences must fail loudly when 'baseline' key is absent."""
        mod = _load_validator_module()
        bad_file = tmp_path / "competences.json"
        bad_file.write_text(json.dumps({"literature": []}))
        mod.load_competences(bad_file)
        assert any("baseline" in e for e in mod.ERRORS), (
            f"Expected failure for missing 'baseline' key (errors: {mod.ERRORS})"
        )

    def test_load_competences_fails_on_missing_literature_key(self, tmp_path: Path) -> None:
        """load_competences must fail loudly when 'literature' key is absent."""
        mod = _load_validator_module()
        bad_file = tmp_path / "competences.json"
        bad_file.write_text(json.dumps({"baseline": []}))
        mod.load_competences(bad_file)
        assert any("literature" in e for e in mod.ERRORS), (
            f"Expected failure for missing 'literature' key (errors: {mod.ERRORS})"
        )

    def test_load_competences_fails_on_entry_missing_required_field(self, tmp_path: Path) -> None:
        """load_competences must fail when a competence entry is missing 'sectors'."""
        mod = _load_validator_module()
        bad_file = tmp_path / "competences.json"
        bad_file.write_text(json.dumps({
            "baseline": [{"id": "b1", "dimension": "A"}],  # missing 'sectors'
            "literature": [],
        }))
        mod.load_competences(bad_file)
        assert any("sectors" in e for e in mod.ERRORS), (
            f"Expected failure for missing 'sectors' field (errors: {mod.ERRORS})"
        )

    def test_load_credentials_fails_on_missing_credentials_key(self, tmp_path: Path) -> None:
        """load_credentials must fail loudly when 'credentials' key is absent."""
        mod = _load_validator_module()
        bad_file = tmp_path / "creds.json"
        bad_file.write_text(json.dumps({"metadata": {}}))
        mod.load_credentials(bad_file)
        assert any("credentials" in e for e in mod.ERRORS), (
            f"Expected failure for missing 'credentials' key (errors: {mod.ERRORS})"
        )

    def test_load_credentials_fails_on_entry_missing_required_field(self, tmp_path: Path) -> None:
        """load_credentials must fail when a credential entry is missing 'eqf_level'."""
        mod = _load_validator_module()
        bad_file = tmp_path / "creds.json"
        bad_file.write_text(json.dumps({
            "credentials": [{"sector": "Blue Biotech", "competences": []}]  # missing eqf_level
        }))
        mod.load_credentials(bad_file)
        assert any("eqf_level" in e for e in mod.ERRORS), (
            f"Expected failure for missing 'eqf_level' field (errors: {mod.ERRORS})"
        )

    def test_load_gaps_csv_fails_on_missing_required_column(self, tmp_path: Path) -> None:
        """load_gaps_csv must fail loudly when a required column is absent."""
        mod = _load_validator_module()
        bad_csv = tmp_path / "gaps.csv"
        # Write a CSV missing 'Gap %'
        bad_csv.write_text("Sector,Required,Available,Missing,Missing MARINE,Missing MARITIME,Missing OCEANIC\n"
                           "Blue Biotech,100,15,85,10,20,55\n")
        mod.load_gaps_csv(bad_csv)
        assert any("Gap %" in e for e in mod.ERRORS), (
            f"Expected failure for missing 'Gap %' column (errors: {mod.ERRORS})"
        )

    def test_load_sector_dict_ids_raises_on_missing_dictionary_key(self, tmp_path: Path) -> None:
        """load_sector_dict_ids must raise ValueError when 'dictionary' key is missing."""
        mod = _load_validator_module()
        bad_file = tmp_path / "sector.json"
        bad_file.write_text(json.dumps({"metadata": {}}))
        with pytest.raises(ValueError, match="dictionary"):
            mod.load_sector_dict_ids(bad_file)

    def test_load_sector_dict_ids_raises_on_entry_missing_id(self, tmp_path: Path) -> None:
        """load_sector_dict_ids must raise ValueError when an entry has no 'id' field."""
        mod = _load_validator_module()
        bad_file = tmp_path / "sector.json"
        bad_file.write_text(json.dumps({
            "metadata": {},
            "dictionary": {"MARINE": [{"name": "no-id-here"}]}
        }))
        with pytest.raises(ValueError, match="'id'"):
            mod.load_sector_dict_ids(bad_file)


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
                        "id": f"{sector.lower().replace(' ', '_')}_eqf{level}",
                        "title": f"{sector} EQF{level}",
                        "sector": sector,
                        "eqf_level": level,
                        "ects": 3.0,
                        "assessment_method": "Portfolio and applied case study",
                        "learner_profile": "Practitioner transitioning into blue sector roles",
                        "learning_outcomes": [f"Outcome EQF{level}"],
                        "stackability_rules": "Stackable toward sector specialization pathway",
                        "prerequisites": [],
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
        # No cross-sector leakage errors expected
        assert not any("lit_" in e for e in mod.ERRORS), (
            f"Unexpected errors: {mod.ERRORS}"
        )

    def test_eqf_ok_message_suppressed_when_sector_missing_level(self) -> None:
        """OK message for EQF levels must not appear when a sector is missing a level."""
        mod = _load_validator_module()
        comps = self._make_comps()
        # Build credentials missing EQF7 for Desalination
        creds = []
        for sector in CANONICAL_SECTORS:
            levels = [4, 5, 6, 7] if sector != "Desalination" else [4, 5, 6]
            for level in levels:
                creds.append(
                    {
                        "id": f"{sector.lower().replace(' ', '_')}_eqf{level}",
                        "title": f"{sector} EQF{level}",
                        "sector": sector,
                        "eqf_level": level,
                        "ects": 3.0,
                        "assessment_method": "Portfolio and applied case study",
                        "learner_profile": "Practitioner transitioning into blue sector roles",
                        "learning_outcomes": [f"Outcome EQF{level}"],
                        "stackability_rules": "Stackable toward sector specialization pathway",
                        "prerequisites": [],
                        "competences": ["baseline_a_1"],
                    }
                )
        mod.check_credentials(creds, comps)
        # A failure for Desalination must be present
        assert any("Desalination" in e and "7" in e for e in mod.ERRORS), (
            f"Expected EQF-level failure for Desalination (errors: {mod.ERRORS})"
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


class TestCumulativeQmbdValidation:
    def test_load_cumulative_qmbd_records_fails_on_static_missing_axis_name(
        self, tmp_path: Path
    ) -> None:
        """Static-origin records must have axis_name."""
        mod = _load_validator_module()
        payload = {
            "metadata": {
                "analysis_input_mode": "live-enriched",
                "is_static_recovery_mode": False,
                "static_recovery_reason": "",
                "allow_static_recovery_mode_env": "ALLOW_STATIC_RECOVERY_MODE",
                "provider_set": "crossref",
                "github_run_id": "123",
                "commit_sha": "abc123",
                "created_at_utc": "2026-07-07T00:00:00+00:00",
                "warnings": [],
            },
            "records": [
                {
                    "source_id": "s1",
                    "title": "t1",
                    "record_origin": "STATIC_BASELINE",
                    "qmbd_analysis": [
                        {
                            "axis": "OCEANIC",
                            "axis_code": "O",
                            "text_scope": "full_sentence",
                            "sentence": "Ocean literacy.",
                        }
                    ],
                }
            ],
        }
        bad_file = tmp_path / "cumulative.json"
        bad_file.write_text(json.dumps(payload))
        mod.load_cumulative_qmbd_records(bad_file)
        assert any("axis_name" in e for e in mod.ERRORS), mod.ERRORS

    def test_check_cumulative_qmbd_records_detects_duplicate_origin_source_id(self) -> None:
        mod = _load_validator_module()
        record = {
            "source_id": "dup-id",
            "title": "Title",
            "axis_name": "MARINE",
            "record_origin": "STATIC_BASELINE",
            "qmbd_analysis": [
                {
                    "axis": "MARINE",
                    "axis_code": "M",
                    "text_scope": "full_sentence",
                    "sentence": "Marine ecosystem dynamics.",
                }
            ],
        }
        mod.check_cumulative_qmbd_records([record, dict(record)])
        assert any("Duplicate (record_origin, source_id)" in e for e in mod.ERRORS)

    def test_check_cumulative_qmbd_records_passes_with_required_origins(self) -> None:
        mod = _load_validator_module()
        records = [
            {
                "source_id": "baseline_1",
                "title": "Ocean literacy",
                "axis_name": "OCEANIC",
                "record_origin": "STATIC_BASELINE",
                "qmbd_analysis": [
                    {
                        "axis": "OCEANIC",
                        "axis_code": "O",
                        "text_scope": "full_sentence",
                        "sentence": "Ocean literacy.",
                    }
                ],
            },
            {
                "source_id": "lit_1",
                "title": "Policy competence",
                "axis_name": "MARITIME",
                "record_origin": "STATIC_LITERATURE",
                "qmbd_analysis": [
                    {
                        "axis": "MARITIME",
                        "axis_code": "T",
                        "text_scope": "full_sentence",
                        "sentence": "Port governance and policy.",
                    }
                ],
            },
        ]
        mod.check_cumulative_qmbd_records(records)
        assert not mod.ERRORS, mod.ERRORS

    def test_empty_cumulative_file_produces_controlled_error(self, tmp_path: Path) -> None:
        """Empty cumulative_qmbd_records.json should produce a clear error, not JSONDecodeError."""
        mod = _load_validator_module()
        empty_file = tmp_path / "cumulative.json"
        empty_file.write_text("", encoding="utf-8")
        result = mod.load_cumulative_qmbd_records(empty_file)
        assert result == []
        assert any("empty" in e.lower() for e in mod.ERRORS), mod.ERRORS
        # Should NOT be a raw JSONDecodeError message
        assert not any("JSONDecodeError" in e for e in mod.ERRORS), mod.ERRORS

    def test_live_cumulative_record_without_static_only_fields_passes(
        self, tmp_path: Path
    ) -> None:
        """Live-enriched records (LIVE_TRIANGULATED) should not require axis_name/record_origin."""
        mod = _load_validator_module()
        payload = {
            "metadata": {
                "analysis_input_mode": "live-enriched",
                "is_static_recovery_mode": False,
                "static_recovery_reason": "",
                "allow_static_recovery_mode_env": "ALLOW_STATIC_RECOVERY_MODE",
                "provider_set": "crossref",
                "github_run_id": "123",
                "commit_sha": "abc123",
                "created_at_utc": "2026-07-07T00:00:00+00:00",
                "warnings": [],
            },
            "records": [
                {
                    "source_id": "live_crossref_1",
                    "title": "Blue economy governance",
                    "record_origin": "LIVE_TRIANGULATED",
                    "qmbd_analysis": [
                        {
                            "axis": "OCEANIC",
                            "axis_code": "O",
                            "text_scope": "full_sentence",
                            "sentence": "Ocean governance framework.",
                        }
                    ],
                }
            ],
        }
        live_file = tmp_path / "cumulative.json"
        live_file.write_text(json.dumps(payload))
        mod.load_cumulative_qmbd_records(live_file)
        # axis_name not present but record_origin is LIVE_TRIANGULATED → no error
        assert not any("axis_name" in e for e in mod.ERRORS), mod.ERRORS

    def test_live_record_without_record_origin_passes_schema(
        self, tmp_path: Path
    ) -> None:
        """Records without record_origin (live) should pass base schema check."""
        mod = _load_validator_module()
        payload = {
            "metadata": {
                "analysis_input_mode": "live-enriched",
                "is_static_recovery_mode": False,
                "static_recovery_reason": "",
                "allow_static_recovery_mode_env": "ALLOW_STATIC_RECOVERY_MODE",
                "provider_set": "",
                "github_run_id": "",
                "commit_sha": "abc123",
                "created_at_utc": "2026-07-07T00:00:00+00:00",
                "warnings": [],
            },
            "records": [
                {
                    "source_id": "live_unknown_1",
                    "title": "Marine social science",
                    "qmbd_analysis": [
                        {
                            "axis": "MARINE",
                            "axis_code": "M",
                            "text_scope": "full_sentence",
                            "sentence": "Marine social dynamics.",
                        }
                    ],
                }
            ],
        }
        live_file = tmp_path / "cumulative.json"
        live_file.write_text(json.dumps(payload))
        mod.load_cumulative_qmbd_records(live_file)
        # No record_origin → not a static record → should not fail on missing axis_name/record_origin
        assert not mod.ERRORS, mod.ERRORS

    def test_cumulative_metadata_missing_required_field_fails(self, tmp_path: Path) -> None:
        mod = _load_validator_module()
        payload = {
            "metadata": {
                "analysis_input_mode": "static",
                "is_static_recovery_mode": True,
                "allow_static_recovery_mode_env": "ALLOW_STATIC_RECOVERY_MODE",
                "provider_set": "",
                "github_run_id": "",
                "commit_sha": "abc123",
                "created_at_utc": "2026-07-07T00:00:00+00:00",
            },
            "records": [],
        }
        bad_file = tmp_path / "cumulative.json"
        bad_file.write_text(json.dumps(payload), encoding="utf-8")
        mod.load_cumulative_qmbd_records(bad_file)
        assert any("static_recovery_reason" in e for e in mod.ERRORS), mod.ERRORS
