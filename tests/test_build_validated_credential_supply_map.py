"""Tests for the H2 validated credential-supply registry builder."""

from __future__ import annotations

import csv
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

import scripts.build_validated_credential_supply_map as supply_map_builder
from scripts.build_validated_credential_supply_map import (
    REGISTRY_FIELDS,
    build_validated_supply_map,
    main,
)
from src.scientific_sources.derived_competence_analysis import (
    DerivedCompetenceDemand,
    build_layer5,
)


def _write_demands(path: Path, demand_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["competence_demand_id", "sector"])
        writer.writeheader()
        for demand_id in demand_ids:
            writer.writerow({"competence_demand_id": demand_id, "sector": "desalination"})


def _registry_row(**overrides: str) -> dict[str, str]:
    row = {
        "credential_supply_id": "SUP-001",
        "programme_title": "Validated Hydronization Programme",
        "awarding_institution": "Blue University",
        "country": "PL",
        "programme_url": "https://example.edu/programme",
        "source_type": "programme_catalogue",
        "source_access_date": "2026-07-25",
        "eqf_level": "6",
        "qualification_framework": "EQF",
        "competence_demand_id": "cd:hydro:1",
        "mapping_basis": "manual curriculum outcome match",
        "mapping_evidence": "learning outcome 1 explicitly covers hydronization planning",
        "mapping_confidence": "high",
        "validation_status": "validated",
        "validated_by": "reviewer-a",
        "validation_date": "2026-07-25",
        "validation_evidence_ids": "E-1|E-2",
        "notes": "",
    }
    row.update(overrides)
    return row


def _write_registry(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REGISTRY_FIELDS))
        writer.writeheader()
        writer.writerows(rows)


def _build(
    tmp_path: Path,
    rows: list[dict[str, str]],
    demand_ids: list[str] | None = None,
):
    demand_ids = demand_ids or ["cd:hydro:1", "cd:hydro:2"]
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    output_path = tmp_path / "validated_credential_supply_map.json"
    audit_path = tmp_path / "validated_credential_supply_audit.json"
    _write_demands(demands_path, demand_ids)
    _write_registry(registry_path, rows)
    result = build_validated_supply_map(
        registry_path=registry_path,
        derived_demands_path=demands_path,
        output_path=output_path,
        audit_output_path=audit_path,
        built_at_utc="2026-07-25T00:00:00+00:00",
    )
    return result, output_path, audit_path


def test_builder_emits_only_validated_mappings_and_audits_candidates(
    tmp_path: Path,
) -> None:
    result, output_path, audit_path = _build(
        tmp_path,
        [
            _registry_row(),
            _registry_row(
                credential_supply_id="SUP-002",
                competence_demand_id="cd:hydro:2",
                validation_status="candidate",
                eqf_level="7",
            ),
        ],
    )

    written = json.loads(output_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert result == written
    assert written["validation_status"] == "validated"
    assert set(written["validated_supply_by_demand_id"]) == {"cd:hydro:1"}
    entry = written["validated_supply_by_demand_id"]["cd:hydro:1"]
    assert entry["validation_status"] == "validated"
    assert entry["eqf_levels"] == [6]
    assert entry["credential_supply_ids"] == ["SUP-001"]
    assert entry["validation_evidence_ids"] == ["E-1", "E-2"]
    assert audit["validated_mapping_rows"] == 1
    assert audit["excluded_row_count"] == 1
    assert audit["excluded_rows"][0]["reason"] == "not_explicitly_validated"


def test_candidate_only_registry_fails_closed_without_output(tmp_path: Path) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    output_path = tmp_path / "validated_credential_supply_map.json"
    audit_path = tmp_path / "audit.json"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row(validation_status="candidate")])

    result = build_validated_supply_map(
        registry_path=registry_path,
        derived_demands_path=demands_path,
        output_path=output_path,
        audit_output_path=audit_path,
    )

    # An empty registry now produces a not_computable map rather than raising.
    assert output_path.exists()
    assert result["validation_status"] == "not_computable"
    assert result["has_validated_supply"] is False
    assert result["validated_supply_by_demand_id"] == {}


def test_unknown_demand_id_fails(tmp_path: Path) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(
        registry_path,
        [_registry_row(competence_demand_id="cd:unknown", validation_status="validated")],
    )

    with pytest.raises(ValueError, match="unknown competence_demand_id"):
        build_validated_supply_map(
            registry_path=registry_path,
            derived_demands_path=demands_path,
            output_path=tmp_path / "map.json",
            audit_output_path=tmp_path / "audit.json",
        )


def test_validated_mapping_requires_source_and_validation_provenance(
    tmp_path: Path,
) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row(programme_url="")])

    with pytest.raises(ValueError, match="missing required field"):
        build_validated_supply_map(
            registry_path=registry_path,
            derived_demands_path=demands_path,
            output_path=tmp_path / "map.json",
            audit_output_path=tmp_path / "audit.json",
        )


def test_validated_mapping_requires_validation_evidence_ids(tmp_path: Path) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row(validation_evidence_ids="")])

    with pytest.raises(ValueError, match="validation_evidence_ids"):
        build_validated_supply_map(
            registry_path=registry_path,
            derived_demands_path=demands_path,
            output_path=tmp_path / "map.json",
            audit_output_path=tmp_path / "audit.json",
        )


def test_validated_mapping_rejects_separator_only_evidence_ids(tmp_path: Path) -> None:
    """Pipe-only strings like '|' pass _clean() but must fail the evidence-ID gate."""
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row(validation_evidence_ids="|")])

    with pytest.raises(ValueError, match="validation_evidence_id"):
        build_validated_supply_map(
            registry_path=registry_path,
            derived_demands_path=demands_path,
            output_path=tmp_path / "map.json",
            audit_output_path=tmp_path / "audit.json",
        )


def _hydro_demand(demand_id: str) -> DerivedCompetenceDemand:
    return DerivedCompetenceDemand(
        competence_demand_id=demand_id,
        competence_label="hydronization governance",
        competence_definition="validated hydronization competence",
        view_kind="legacy_category_aggregate_compatibility_view",
        scientific_status="legacy_not_validated_canonical_competence",
        sector="desalination",
        axis_group="HYDRONIZATION",
        axis_code="H",
        eqf_relevance="5|6|7",
        demand_strength_score=0.8,
        evidence_record_count=1,
        unique_doi_count=1,
        record_occurrence_count=1,
        provider_count=1,
        providers_seen="openalex",
        provider_diversity_score=1.0,
        query_count=1,
        query_families_seen="validation_eqf_translation",
        query_diversity_score=1.0,
        temporal_recency_score=1.0,
        cross_sector_recurrence_score=0.1,
        semantic_confidence_mean=0.9,
        first_seen_run_id="RUN-1",
        latest_seen_run_id="RUN-1",
        first_seen_at_utc="2026-07-25T00:00:00+00:00",
        latest_seen_at_utc="2026-07-25T00:00:00+00:00",
        status="high_demand",
        manual_review_status="validated",
        validity_warning="",
        evidence_ids="E-1",
        signal_types="competence_demand",
    )


def test_only_validated_eqf_6_7_supply_affects_h2(tmp_path: Path) -> None:
    demand = _hydro_demand("cd:hydro:1")

    eqf5 = build_layer5(
        derived_demands=[demand],
        evidence_records=[],
        validated_credential_supply={"cd:hydro:1": [5]},
        output_dir=tmp_path / "eqf5",
        current_run_id="RUN-EQF5",
    ).hypothesis_results["H2"]
    assert eqf5["validated_covered_demand_count"] == 0
    assert eqf5["validated_missing_demand_count"] == 1
    assert eqf5["interpretation"] == "supported"

    eqf6 = build_layer5(
        derived_demands=[demand],
        evidence_records=[],
        validated_credential_supply={"cd:hydro:1": [6]},
        output_dir=tmp_path / "eqf6",
        current_run_id="RUN-EQF6",
    ).hypothesis_results["H2"]
    assert eqf6["validated_covered_demand_count"] == 1
    assert eqf6["validated_missing_demand_count"] == 0
    assert eqf6["interpretation"] == "not_supported"


def test_cli_returns_nonzero_for_candidate_only_registry(tmp_path: Path, capsys) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    output_path = tmp_path / "map.json"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row(validation_status="candidate")])

    result = main(
        [
            "--registry",
            str(registry_path),
            "--derived-demands",
            str(demands_path),
            "--output",
            str(output_path),
            "--audit-output",
            str(tmp_path / "audit.json"),
        ]
    )

    captured = capsys.readouterr()
    # An empty (candidate-only) registry now exits 0 with a not_computable map.
    assert result == 0
    assert "not_computable" in captured.err
    assert output_path.exists()
    data = json.loads(output_path.read_text())
    assert data["has_validated_supply"] is False


def test_empty_demand_set_produces_not_computable_supply_map(tmp_path: Path) -> None:
    """A schema-valid derived demands CSV with no data rows is a valid outcome.

    When live acquisition yields records but no legally retained semantic
    competence signals, Layer 4 emits a header-only demands CSV.  The supply
    map builder must accept this and produce a not_computable output rather
    than aborting with an error.
    """
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    output_path = tmp_path / "map.json"
    audit_path = tmp_path / "audit.json"
    # Header-only CSV: valid schema but no demand rows
    demands_path.write_text(
        "competence_demand_id,sector\n", encoding="utf-8"
    )
    _write_registry(registry_path, [_registry_row()])

    result = main(
        [
            "--registry",
            str(registry_path),
            "--derived-demands",
            str(demands_path),
            "--output",
            str(output_path),
            "--audit-output",
            str(audit_path),
        ]
    )
    assert result == 0
    assert output_path.exists()
    data = json.loads(output_path.read_text())
    assert data["has_validated_supply"] is False


def test_cli_redacts_out_of_tree_output_paths(tmp_path: Path, capsys) -> None:
    demands_path = tmp_path / "derived_competence_demands.csv"
    registry_path = tmp_path / "credential_supply_registry.csv"
    output_path = tmp_path / "map.json"
    audit_path = tmp_path / "audit.json"
    _write_demands(demands_path, ["cd:hydro:1"])
    _write_registry(registry_path, [_registry_row()])

    result = main(
        [
            "--registry",
            str(registry_path),
            "--derived-demands",
            str(demands_path),
            "--output",
            str(output_path),
            "--audit-output",
            str(audit_path),
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert result == 0
    assert summary["output"] == "[redacted-out-of-tree-path]"
    assert summary["audit_output"] == "[redacted-out-of-tree-path]"
    assert str(output_path) not in captured.out
    assert str(audit_path) not in captured.out


def test_cli_redacts_all_supplied_paths_from_error_text(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    registry_path = tmp_path / "credential_supply_registry.csv"
    demands_path = tmp_path / "derived_competence_demands.csv"
    output_path = tmp_path / "map.json"
    audit_path = tmp_path / "audit.json"

    def fail_build(**kwargs) -> None:
        raise OSError(
            "failed paths: "
            + ", ".join(str(kwargs[key]) for key in sorted(kwargs))
        )

    monkeypatch.setattr(supply_map_builder, "build_validated_supply_map", fail_build)

    result = main(
        [
            "--registry",
            str(registry_path),
            "--derived-demands",
            str(demands_path),
            "--output",
            str(output_path),
            "--audit-output",
            str(audit_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "[redacted-out-of-tree-path]" in captured.err
    for path in (registry_path, demands_path, output_path, audit_path):
        assert str(path) not in captured.err


def _stub_cli_build(monkeypatch) -> None:
    """Prevent CLI path-display tests from writing any real output file."""

    def fake_build(**_kwargs):
        return {"validated_supply_by_demand_id": {}}

    monkeypatch.setattr(supply_map_builder, "build_validated_supply_map", fake_build)


def test_cli_default_relative_output_paths_are_repo_relative(monkeypatch, capsys) -> None:
    _stub_cli_build(monkeypatch)
    monkeypatch.chdir(supply_map_builder._REPO_ROOT_SUPPLY)

    assert main([]) == 0

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary == {
        "audit_output": "outputs/cumulative_database/validated_credential_supply_audit.json",
        "output": "outputs/cumulative_database/validated_credential_supply_map.json",
        "validated_demand_count": 0,
    }
    assert str(supply_map_builder._REPO_ROOT_SUPPLY) not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("windows_style", [False, True])
def test_cli_absolute_in_repo_output_paths_are_rendered_relative_posix(
    monkeypatch, capsys, windows_style: bool
) -> None:
    _stub_cli_build(monkeypatch)
    repo_root = supply_map_builder._REPO_ROOT_SUPPLY
    output_path = repo_root / ".path-display-test" / "map.json"
    audit_path = repo_root / ".path-display-test" / "audit.json"
    output_arg = str(output_path)
    audit_arg = str(audit_path)
    if windows_style:
        output_arg = output_arg.replace("/", "\\")
        audit_arg = audit_arg.replace("/", "\\")

    assert main(["--output", output_arg, "--audit-output", audit_arg]) == 0

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["output"] == ".path-display-test/map.json"
    assert summary["audit_output"] == ".path-display-test/audit.json"
    assert output_arg not in captured.out
    assert audit_arg not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    ("output_arg", "audit_arg"),
    [
        (
            r"C:\codex-external-path-test\validated_credential_supply_map.json",
            r"C:\codex-external-path-test\validated_credential_supply_audit.json",
        ),
        (
            "/tmp/codex-external-path-test/validated_credential_supply_map.json",
            "/tmp/codex-external-path-test/validated_credential_supply_audit.json",
        ),
    ],
)
def test_cli_redacts_external_windows_and_posix_output_paths(
    monkeypatch, capsys, output_arg: str, audit_arg: str
) -> None:
    _stub_cli_build(monkeypatch)

    assert main(["--output", output_arg, "--audit-output", audit_arg]) == 0

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["output"] == "[redacted-out-of-tree-path]"
    assert summary["audit_output"] == "[redacted-out-of-tree-path]"
    assert output_arg not in captured.out
    assert audit_arg not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    ("path_text", "expected"),
    [
        ("/workspace/morskamary/outputs/./map.json", "outputs/map.json"),
        (r"\workspace\morskamary\outputs\.\map.json", "outputs/map.json"),
        ("/workspace\\morskamary/mixed\\map.json", "mixed/map.json"),
        ("/workspace/morskamary", "."),
        (
            "/workspace/morskamary-copy/map.json",
            "[redacted-out-of-tree-path]",
        ),
        (
            r"C:\codex-external-path-test\validated_credential_supply_map.json",
            "[redacted-out-of-tree-path]",
        ),
        (
            r"\\server\share\external\validated_credential_supply_map.json",
            "[redacted-out-of-tree-path]",
        ),
    ],
)
def test_redact_path_string_classifies_absolute_syntax_lexically(
    path_text: str, expected: str
) -> None:
    repo_root = PurePosixPath("/workspace/morskamary")

    assert supply_map_builder._redact_path_string(path_text, repo_root) == expected


def test_redact_path_string_normalises_relative_paths_and_rejects_escapes(
    monkeypatch, tmp_path: Path
) -> None:
    repo_root = tmp_path / "morskamary"
    repo_root.mkdir()
    monkeypatch.chdir(repo_root)

    assert (
        supply_map_builder._redact_path_string(
            r"outputs\nested/../validated_supply_map.json", repo_root
        )
        == "outputs/validated_supply_map.json"
    )
    assert (
        supply_map_builder._redact_path_string(
            "../morskamary-copy/validated_supply_map.json", repo_root
        )
        == "[redacted-out-of-tree-path]"
    )


def test_redact_path_string_requires_compatible_windows_drive_and_unc_share() -> None:
    windows_repo_root = PureWindowsPath(r"C:\work\morskamary")
    unc_repo_root = PureWindowsPath(r"\\server\share\morskamary")

    assert (
        supply_map_builder._redact_path_string(
            r"D:\work\morskamary\validated_supply_map.json", windows_repo_root
        )
        == "[redacted-out-of-tree-path]"
    )
    assert (
        supply_map_builder._redact_path_string(
            r"\\server\share\morskamary\outputs\validated_supply_map.json",
            unc_repo_root,
        )
        == "outputs/validated_supply_map.json"
    )
    assert (
        supply_map_builder._redact_path_string(
            r"\\server\other-share\morskamary\validated_supply_map.json",
            unc_repo_root,
        )
        == "[redacted-out-of-tree-path]"
    )


@pytest.mark.parametrize(
    ("output_arg", "audit_arg", "expected_output", "expected_audit"),
    [
        (
            r"\home\runner\work\morskamary\morskamary\.path-display-test\map.json",
            r"\home\runner\work\morskamary\morskamary\.path-display-test\audit.json",
            ".path-display-test/map.json",
            ".path-display-test/audit.json",
        ),
        (
            r"C:\codex-external-path-test\validated_credential_supply_map.json",
            r"C:\codex-external-path-test\validated_credential_supply_audit.json",
            "[redacted-out-of-tree-path]",
            "[redacted-out-of-tree-path]",
        ),
    ],
)
def test_cli_lexically_displays_foreign_syntax_against_posix_repository(
    monkeypatch,
    capsys,
    output_arg: str,
    audit_arg: str,
    expected_output: str,
    expected_audit: str,
) -> None:
    _stub_cli_build(monkeypatch)
    monkeypatch.setattr(
        supply_map_builder,
        "_REPO_ROOT_SUPPLY",
        PurePosixPath("/home/runner/work/morskamary/morskamary"),
    )

    assert main(["--output", output_arg, "--audit-output", audit_arg]) == 0

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["output"] == expected_output
    assert summary["audit_output"] == expected_audit
    assert output_arg not in captured.out
    assert audit_arg not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "external_output",
    [
        r"C:\codex-external-path-test\validated_credential_supply_map.json",
        "/tmp/codex-external-path-test/validated_credential_supply_map.json",
    ],
)
def test_cli_error_scrubs_raw_and_native_external_path_variants(
    monkeypatch, capsys, external_output: str
) -> None:
    external_audit = external_output.replace("map.json", "audit.json")

    def path_variants(raw_path: str) -> set[str]:
        native_path = Path(raw_path)
        variants = {
            raw_path,
            raw_path.replace("\\", "/"),
            raw_path.replace("/", "\\"),
        }
        for candidate in (str(native_path), str(native_path.resolve(strict=False))):
            variants.update(
                {
                    candidate,
                    candidate.replace("\\", "/"),
                    candidate.replace("/", "\\"),
                }
            )
        return variants

    leaked_forms = path_variants(external_output) | path_variants(external_audit)

    def fail_build(**_kwargs) -> None:
        raise OSError("external paths: " + " | ".join(sorted(leaked_forms)))

    monkeypatch.setattr(supply_map_builder, "build_validated_supply_map", fail_build)

    assert (
        main(
            [
                "--output",
                external_output,
                "--audit-output",
                external_audit,
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[redacted-out-of-tree-path]" in captured.err
    for leaked_form in leaked_forms:
        assert leaked_form not in captured.out
        assert leaked_form not in captured.err


def test_cli_error_scrubs_external_parent_directory_path(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    external_output = tmp_path / "external" / "validated_credential_supply_map.json"
    external_audit = external_output.with_name("validated_credential_supply_audit.json")
    external_parent = external_output.parent

    def fail_build(**_kwargs) -> None:
        raise PermissionError(13, "Permission denied", str(external_parent))

    monkeypatch.setattr(supply_map_builder, "build_validated_supply_map", fail_build)

    assert (
        main(
            [
                "--output",
                str(external_output),
                "--audit-output",
                str(external_audit),
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[redacted-out-of-tree-path]" in captured.err
    for leaked_form in supply_map_builder._path_text_variants(str(external_parent)):
        assert leaked_form not in captured.err


@pytest.mark.parametrize(
    "external_output",
    [
        r"C:\codex-external-path-test\validated_credential_supply_map.json",
        r"\tmp\codex-external-path-test\validated_credential_supply_map.json",
        r"\\server\share\codex-external-path-test\validated_credential_supply_map.json",
    ],
)
def test_cli_error_scrubs_escaped_oserror_path_forms(
    monkeypatch, capsys, external_output: str
) -> None:
    escaped_output = repr(external_output)[1:-1]

    def fail_build(**_kwargs) -> None:
        raise FileNotFoundError(2, "No such file or directory", external_output)

    monkeypatch.setattr(supply_map_builder, "build_validated_supply_map", fail_build)

    assert main(["--output", external_output]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[redacted-out-of-tree-path]" in captured.err
    assert external_output not in captured.err
    assert escaped_output not in captured.err
