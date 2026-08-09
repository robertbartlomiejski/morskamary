from __future__ import annotations

import csv
import hashlib
import io
import importlib.util
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_versioned_research_data_package.py"
SCHEMA_V2_ENTITY_NAMES = (
    "evidence_fragments",
    "semantic_signals",
    "competence_candidates",
    "canonical_competences",
    "sector_competence_assignments",
    "validation_decisions",
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_versioned_research_data_package", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_schema_v2_enums_generate_variable_and_value_labels() -> None:
    module = _load_module()
    variable_rows, value_rows = module._load_variable_and_value_labels(
        REPO_ROOT / "schemas"
    )
    variables = {
        (row["schema_file"], row["variable_name"]): row for row in variable_rows
    }
    values = {
        (row["schema_file"], row["variable_name"], row["code"]): row["label"]
        for row in value_rows
    }

    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        schema_name = f"{entity_name}.schema.json"
        schema = json.loads((REPO_ROOT / "schemas" / schema_name).read_text())
        for field_name, definition in schema["properties"].items():
            if "enum" not in definition:
                continue
            assert (schema_name, field_name) in variables
            for code in definition["enum"]:
                key = (schema_name, field_name, str(code))
                assert key in values
                if code == "":
                    assert values[key] == "Unbound"


def _copy_required_schemas(repo_root: Path) -> None:
    schema_dir = repo_root / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    required = [
        "runs.schema.json",
        "source_bundles.schema.json",
        "evidence_records.schema.json",
        "evidence_occurrences.schema.json",
        "evidence_fragments.schema.json",
        "semantic_signals.schema.json",
        "competence_candidates.schema.json",
        "canonical_competences.schema.json",
        "sector_competence_assignments.schema.json",
        "validation_decisions.schema.json",
        "gap_clusters.schema.json",
        "dynamic_credentials.schema.json",
        "data_quality_indicators.schema.json",
        "research_data_package_manifest.schema.json",
    ]
    for name in required:
        (schema_dir / name).write_text(
            (REPO_ROOT / "schemas" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def _seed_minimal_outputs(repo_root: Path) -> None:
    out = repo_root / "outputs"
    (out / "run_archive").mkdir(parents=True, exist_ok=True)
    (out / "manual_sources").mkdir(parents=True, exist_ok=True)
    cumulative_database = out / "cumulative_database"
    cumulative_database.mkdir(parents=True, exist_ok=True)
    (cumulative_database / "evidence_records.csv").write_text(
        "evidence_id,canonical_doi,canonical_title,first_seen_run_id,latest_seen_run_id,providers_seen,record_novelty_status\n"
        "E-0001,10.1000/demo,Demo title,123-1,123-1,crossref,new_record\n",
        encoding="utf-8",
    )
    (cumulative_database / "evidence_records.jsonl").write_text(
        json.dumps(
            {
                "evidence_id": "E-0001",
                "canonical_doi": "10.1000/demo",
                "canonical_title": "Demo title",
                "first_seen_run_id": "123-1",
                "latest_seen_run_id": "123-1",
                "providers_seen": "crossref",
                "record_novelty_status": "new_record",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    (out / "run_archive" / "cross_run_run_summary.csv").write_text(
        (
            "run_id,run_path,timestamp_utc,manifest_timestamp_utc,"
            "live_records_count,triangulated_records_count,cumulative_qmbd_records_count,"
            "evidence_rows_total,evidence_rows_dedupable,unique_dedupe_values\n"
            "123-1,runs/123-1,2026-07-07T00:00:00+00:00,2026-07-07T00:00:00+00:00,"
            "1,1,1,3,3,1\n"
        ),
        encoding="utf-8",
    )
    (out / "run_archive" / "cross_run_evidence_occurrences.csv").write_text(
        (
            "run_id,run_path,timestamp_utc,manifest_timestamp_utc,dataset,record_index,"
            "dedupe_value,dedupe_field_used,doi,source_id,title,record_origin,axis_name\n"
            "123-1,runs/123-1,2026-07-07T00:00:00+00:00,2026-07-07T00:00:00+00:00,"
            "cumulative_qmbd_records,0,10.1234/demo,doi,10.1234/demo,"
            "crossref:10.1234/demo,Demo title,LIVE_API,OCEANIC\n"
        ),
        encoding="utf-8",
    )
    (out / "run_archive" / "cross_run_evidence_build_report.json").write_text(
        json.dumps({"dedupe_groups_total": 1}),
        encoding="utf-8",
    )
    (out / "manual_sources" / "historical_compatibility.csv").write_text(
        (
            "bundle_id,source_path,extracted_dir,status,reason,live_records_count,"
            "triangulated_records_count,cumulative_qmbd_records_count\n"
            "bundle_abc,example.zip,tmp/dir,compatible,ok,1,1,1\n"
        ),
        encoding="utf-8",
    )
    (out / "manual_sources" / "manual_sources_index.csv").write_text(
        (
            "source_id,ingested_at_utc,source_kind,file_name,extension,size_bytes,sha256,"
            "text_available,original_path,zip_member_path,stored_path,archive_sha256\n"
            "manual_src_a,2026-07-07T00:00:00+00:00,manual_document,demo.json,.json,10,"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,"
            "yes,C:/tmp/demo.json,,outputs/manual_sources/files/demo.json,\n"
        ),
        encoding="utf-8",
    )
    (out / "credentials_dynamic_database.json").write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "mc_demo",
                        "sector": "Blue Biotech",
                        "eqf_level": 6,
                        "review_required": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (out / "gaps_detailed.json").write_text(
        json.dumps(
            {
                "all_clusters": [
                    {
                        "sector": "Blue Biotech",
                        "qmbd_axis": "OCEANIC",
                        "missing_count": 1,
                        "gap_ratio": 1.0,
                        "priority_score": 0.7,
                        "demand_count": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    schema_v2_samples = json.loads(
        (REPO_ROOT / "tests/fixtures/cumulative_database_schema_samples.json").read_text(
            encoding="utf-8"
        )
    )
    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        row = schema_v2_samples[entity_name]
        schema = json.loads(
            (repo_root / "schemas" / f"{entity_name}.schema.json").read_text(
                encoding="utf-8"
            )
        )
        fields = list(schema["properties"])
        with (cumulative_database / f"{entity_name}.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerow(row)
        (cumulative_database / f"{entity_name}.jsonl").write_text(
            json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    (cumulative_database / "cumulative_database_manifest.json").write_text(
        json.dumps(
            {"counts": {entity_name: 1 for entity_name in SCHEMA_V2_ENTITY_NAMES}}
        )
        + "\n",
        encoding="utf-8",
    )


def _read_schema_v2_entity_rows(
    repo_root: Path, entity_name: str
) -> list[dict[str, object]]:
    path = repo_root / "outputs" / "cumulative_database" / f"{entity_name}.jsonl"
    return [
        json.loads(raw_line)
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if raw_line.strip()
    ]


def _sync_schema_v2_manifest_counts(repo_root: Path) -> None:
    manifest_path = (
        repo_root / "outputs" / "cumulative_database" / "cumulative_database_manifest.json"
    )
    if not manifest_path.exists():
        return
    counts = {
        entity_name: len(_read_schema_v2_entity_rows(repo_root, entity_name))
        for entity_name in SCHEMA_V2_ENTITY_NAMES
    }
    manifest_path.write_text(
        json.dumps({"counts": counts}) + "\n", encoding="utf-8"
    )


def _write_schema_v2_entity_rows(
    repo_root: Path,
    entity_name: str,
    rows: list[dict[str, object]],
) -> None:
    schema = json.loads(
        (repo_root / "schemas" / f"{entity_name}.schema.json").read_text(
            encoding="utf-8"
        )
    )
    fields = list(schema["properties"])
    cumulative_database = repo_root / "outputs" / "cumulative_database"
    with (cumulative_database / f"{entity_name}.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (cumulative_database / f"{entity_name}.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    _sync_schema_v2_manifest_counts(repo_root)


def _append_shared_signal_fragment(
    repo_root: Path,
    module: Any,
    *,
    sector: str = "blue_biotech",
    axis_group: str = "OCEANIC",
    axis_code: str = "O",
) -> dict[str, object]:
    """Add a valid second occurrence of the fixture's stable signal identity."""
    fragments = _read_schema_v2_entity_rows(repo_root, "evidence_fragments")
    signals = _read_schema_v2_entity_rows(repo_root, "semantic_signals")
    second_fragment = dict(fragments[0])
    second_fragment.update(
        {
            "fragment_id": "",
            "source_provenance_id": "",
            "source_provider_id": "crossref:rec_001:second",
            "fragment_text": "governance",
            "span_start_offset": 0,
            "span_end_offset": 10,
            "surface_text_hash": module._normalized_text_hash(
                "governance context"
            ),
            "provenance_hash": "",
        }
    )
    signal_id = str(signals[0]["signal_id"])
    second_fragment["source_provenance_id"] = (
        module._expected_fragment_provenance_id(second_fragment)
    )
    second_fragment["provenance_hash"] = hashlib.sha256(
        str(second_fragment["source_provenance_id"]).encode("utf-8")
    ).hexdigest()
    second_fragment["fragment_id"] = module._expected_fragment_id(
        second_fragment, signal_id
    )
    second_signal = dict(signals[0])
    second_signal.update(
        {
            "fragment_id": second_fragment["fragment_id"],
            "source_provenance_id": second_fragment["source_provenance_id"],
            "sector": sector,
            "axis_group": axis_group,
            "axis_code": axis_code,
            "context_text": "governance context",
        }
    )
    fragments.append(second_fragment)
    signals.append(second_signal)
    _write_schema_v2_entity_rows(repo_root, "evidence_fragments", fragments)
    _write_schema_v2_entity_rows(repo_root, "semantic_signals", signals)
    return second_fragment


def _aggregate_candidate_fragment(
    repo_root: Path, second_fragment: dict[str, object]
) -> None:
    candidates = _read_schema_v2_entity_rows(repo_root, "competence_candidates")
    candidates[0]["fragment_ids"] = "|".join(
        sorted(
            {
                str(candidates[0]["fragment_id"]),
                str(second_fragment["fragment_id"]),
            }
        )
    )
    candidates[0]["source_provenance_ids"] = "|".join(
        sorted(
            {
                *str(candidates[0]["source_provenance_ids"]).split("|"),
                str(second_fragment["source_provenance_id"]),
            }
        )
    )
    _write_schema_v2_entity_rows(repo_root, "competence_candidates", candidates)


def _append_shared_canonical_candidate(repo_root: Path, module: Any) -> None:
    """Add an accepted candidate that intentionally shares a canonical label."""
    fragments = _read_schema_v2_entity_rows(repo_root, "evidence_fragments")
    signals = _read_schema_v2_entity_rows(repo_root, "semantic_signals")
    candidates = _read_schema_v2_entity_rows(repo_root, "competence_candidates")
    decisions = _read_schema_v2_entity_rows(repo_root, "validation_decisions")
    assignments = _read_schema_v2_entity_rows(
        repo_root, "sector_competence_assignments"
    )

    second_fragment = dict(fragments[0])
    second_fragment.update(
        {
            "fragment_id": "",
            "source_provenance_id": "",
            "source_provider_id": "crossref:rec_001:shared",
            "fragment_text": "coordination",
            "span_start_offset": 0,
            "span_end_offset": 12,
            "surface_text_hash": module._normalized_text_hash(
                "coordination context"
            ),
            "provenance_hash": "",
        }
    )
    second_fragment["source_provenance_id"] = (
        module._expected_fragment_provenance_id(second_fragment)
    )
    second_fragment["provenance_hash"] = hashlib.sha256(
        str(second_fragment["source_provenance_id"]).encode("utf-8")
    ).hexdigest()

    second_signal = dict(signals[0])
    second_signal.update(
        {
            "signal_id": "",
            "fragment_id": "",
            "source_provenance_id": second_fragment["source_provenance_id"],
            "sector": "coastal_tourism",
            "axis_group": "MARITIME",
            "axis_code": "T",
            "signal_type": "coordination_skill",
            "matched_phrase": "coordination",
            "action_text": "coordination",
            "context_text": "coordination context",
            "evidence_text_hash": "a" * 64,
        }
    )
    second_signal["signal_id"] = module._expected_signal_id(second_signal)
    second_fragment["fragment_id"] = module._expected_fragment_id(
        second_fragment, str(second_signal["signal_id"])
    )
    second_signal["fragment_id"] = second_fragment["fragment_id"]

    second_candidate = dict(candidates[0])
    second_candidate.update(
        {
            "candidate_id": "",
            "signal_id": second_signal["signal_id"],
            "fragment_id": second_fragment["fragment_id"],
            "sector": "coastal_tourism",
            "axis_group": "MARITIME",
            "axis_code": "T",
            "source_provenance_ids": second_fragment["source_provenance_id"],
            "fragment_ids": second_fragment["fragment_id"],
            "candidate_label": "coordination",
            "exact_evidence_span": "coordination",
            "exact_span_start_offset": 0,
            "exact_span_end_offset": 12,
        }
    )
    second_candidate["candidate_id"] = module._expected_candidate_id(second_candidate)

    second_decision = dict(decisions[0])
    second_decision.update(
        {
            "validation_decision_id": "decision_002",
            "target_candidate_id": second_candidate["candidate_id"],
            "reviewer": "reviewer-fixture-002",
            "decision_reason": "Second accepted evidence path.",
            "fragment_ids": second_fragment["fragment_id"],
            "source_provenance_ids": second_fragment["source_provenance_id"],
        }
    )
    second_assignment = dict(assignments[0])
    second_assignment.update(
        {
            "assignment_id": "assignment_002",
            "validation_decision_id": second_decision["validation_decision_id"],
            "source_candidate_id": second_candidate["candidate_id"],
            "sector": "coastal_tourism",
            "axis_group": "MARITIME",
            "axis_code": "T",
        }
    )

    fragments.append(second_fragment)
    signals.append(second_signal)
    candidates.append(second_candidate)
    decisions.append(second_decision)
    assignments.append(second_assignment)
    _write_schema_v2_entity_rows(repo_root, "evidence_fragments", fragments)
    _write_schema_v2_entity_rows(repo_root, "semantic_signals", signals)
    _write_schema_v2_entity_rows(repo_root, "competence_candidates", candidates)
    _write_schema_v2_entity_rows(repo_root, "validation_decisions", decisions)
    _write_schema_v2_entity_rows(
        repo_root, "sector_competence_assignments", assignments
    )


def _run_package(
    module: Any, repo_root: Path, output_dir: Path, version: str
) -> tuple[int, str]:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = module.main(
            [
                "--repo-root",
                str(repo_root),
                "--output-dir",
                str(output_dir),
                "--version-tag",
                version,
                "--source-commit-sha",
                "fixture_source_sha",
                "--include-xlsx",
                "false",
                "--include-sav",
                "false",
            ]
        )
    return exit_code, stdout.getvalue()


def test_build_versioned_research_data_package_creates_manifest_checksums_and_views(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    output_dir = tmp_path / "release_out"
    exit_code = module.main(
        [
            "--repo-root",
            str(repo_root),
            "--output-dir",
            str(output_dir),
            "--version-tag",
            "v0.1.0",
            "--release-tag",
            "v0.1.0",
            "--commit-sha",
            "abc1234",
            "--include-xlsx",
            "false",
            "--include-sav",
            "false",
        ]
    )
    assert exit_code == 0

    package_dir = output_dir / "morskamary_cumulative_evidence_v0.1.0"
    assert package_dir.exists()
    assert (package_dir / "RELEASE_MANIFEST.json").exists()
    assert (package_dir / "CHECKSUMS.sha256").exists()
    assert (package_dir / "CITATION_APA.txt").exists()
    assert (package_dir / "data" / "csv" / "analysis_view_record_level.csv").exists()
    assert (
        package_dir / "data" / "csv" / "analysis_view_occurrence_level.csv"
    ).exists()

    manifest = json.loads(
        (package_dir / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["version_tag"] == "v0.1.0"
    assert manifest["source_commit_sha"] == "abc1234"
    assert manifest["package_commit_sha"] == "pending_until_merge"
    assert manifest["exports"]["csv_utf8"] is True
    assert manifest["schema_v2_entities"]["entities"] == list(
        SCHEMA_V2_ENTITY_NAMES
    )
    assert manifest["schema_validation"]["validated_exports"] == {
        "csv": list(SCHEMA_V2_ENTITY_NAMES),
        "jsonl": list(SCHEMA_V2_ENTITY_NAMES),
    }
    assert manifest["schema_v2_entities"]["contract_paths"] == {
        entity_name: f"schemas/{entity_name}.schema.json"
        for entity_name in SCHEMA_V2_ENTITY_NAMES
    }
    checksum_paths = {
        line.split("  ", maxsplit=1)[1]
        for line in (package_dir / "CHECKSUMS.sha256").read_text(
            encoding="utf-8"
        ).splitlines()
    }
    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        csv_path = package_dir / "data" / "csv" / f"{entity_name}.csv"
        jsonl_path = package_dir / "data" / "jsonl" / f"{entity_name}.jsonl"
        contract_path = package_dir / "schemas" / f"{entity_name}.schema.json"
        assert csv_path.exists()
        assert jsonl_path.exists()
        assert contract_path.exists()
        assert entity_name in manifest["schema_validation"]["validated_tables"]
        assert manifest["schema_v2_entities"]["package_paths"][entity_name] == {
            "csv": f"data/csv/{entity_name}.csv",
            "jsonl": f"data/jsonl/{entity_name}.jsonl",
        }
        assert csv_path.read_bytes() == (
            repo_root / "outputs" / "cumulative_database" / f"{entity_name}.csv"
        ).read_bytes()
        assert jsonl_path.read_bytes() == (
            repo_root / "outputs" / "cumulative_database" / f"{entity_name}.jsonl"
        ).read_bytes()
        assert contract_path.read_bytes() == (
            repo_root / "schemas" / f"{entity_name}.schema.json"
        ).read_bytes()
        assert f"schemas/{entity_name}.schema.json" in checksum_paths

    with (package_dir / "data" / "csv" / "runs.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        run_rows = list(csv.DictReader(handle))
    assert run_rows
    assert run_rows[0]["run_id"] == "123-1"

    archive_path = output_dir / "morskamary_cumulative_evidence_v0.1.0.zip"
    assert archive_path.exists()
    with ZipFile(archive_path) as archive:
        archived_paths = set(archive.namelist())
    for entity_name in SCHEMA_V2_ENTITY_NAMES:
        assert f"data/csv/{entity_name}.csv" in archived_paths
        assert f"data/jsonl/{entity_name}.jsonl" in archived_paths
        assert f"schemas/{entity_name}.schema.json" in archived_paths

    with (package_dir / "VALUE_LABELS.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        value_rows = list(csv.DictReader(handle))
    value_keys = {
        (row["schema_file"], row["variable_name"], row["code"]) for row in value_rows
    }
    assert len(value_keys) == len(value_rows)
    axis_blank_key = ("semantic_signals.schema.json", "axis_group", "")
    assert axis_blank_key in value_keys
    assert (
        next(
            row["label"]
            for row in value_rows
            if (
                row["schema_file"],
                row["variable_name"],
                row["code"],
            )
            == axis_blank_key
        )
        == "Unbound / not assigned"
    )


def test_build_versioned_package_rejects_invalid_schema_v2_jsonl(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    invalid_jsonl = repo_root / "outputs/cumulative_database/semantic_signals.jsonl"
    row = json.loads(invalid_jsonl.read_text(encoding="utf-8"))
    row["confidence_score"] = 1.5
    invalid_jsonl.write_text(json.dumps(row) + "\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--repo-root",
            str(repo_root),
            "--output-dir",
            str(tmp_path / "release_out"),
            "--version-tag",
            "v0.1.1",
            "--include-xlsx",
            "false",
            "--include-sav",
            "false",
        ]
    )

    assert exit_code == 1

    release_out = tmp_path / "release_out"
    assert not release_out.exists(), (
        "Package output directory must not be created when validation fails"
    )
    expected_zip = release_out / "morskamary_cumulative_evidence_v0.1.1.zip"
    assert not expected_zip.exists(), (
        "ZIP artifact must not be created when validation fails"
    )


def test_build_versioned_package_rejects_schema_v2_projection_mismatch(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    mismatch_csv = repo_root / "outputs/cumulative_database/semantic_signals.csv"
    with mismatch_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0].keys())
    rows[0]["manual_review_status"] = "review_required"
    with mismatch_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    release_out = tmp_path / "release_out"
    exit_code = module.main(
        [
            "--repo-root",
            str(repo_root),
            "--output-dir",
            str(release_out),
            "--version-tag",
            "v0.1.2",
            "--include-xlsx",
            "false",
            "--include-sav",
            "false",
        ]
    )

    assert exit_code == 1
    assert not release_out.exists()
    assert not (release_out / "morskamary_cumulative_evidence_v0.1.2.zip").exists()


def test_build_versioned_package_rejects_schema_v2_lineage_mismatch(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    bad_signal = repo_root / "outputs/cumulative_database/semantic_signals.jsonl"
    signal_row = json.loads(bad_signal.read_text(encoding="utf-8"))
    signal_row["context_text"] = "abstract"
    bad_signal.write_text(json.dumps(signal_row) + "\n", encoding="utf-8")

    release_out = tmp_path / "release_out"
    exit_code = module.main(
        [
            "--repo-root",
            str(repo_root),
            "--output-dir",
            str(release_out),
            "--version-tag",
            "v0.1.3",
            "--include-xlsx",
            "false",
            "--include-sav",
            "false",
        ]
    )

    assert exit_code == 1
    assert not release_out.exists()
    assert not (release_out / "morskamary_cumulative_evidence_v0.1.3.zip").exists()


def test_build_versioned_package_preserves_composite_semantic_signal_identity(
    tmp_path: Path,
) -> None:
    """The same stable signal may have multiple evidence-fragment occurrences."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    second_fragment = _append_shared_signal_fragment(repo_root, module)
    _aggregate_candidate_fragment(repo_root, second_fragment)

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.4"
    )

    assert exit_code == 0, stdout


def test_build_versioned_package_rejects_missing_composite_signal_projection(
    tmp_path: Path,
) -> None:
    """CSV/JSONL parity is keyed by signal and fragment, not signal alone."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    second_fragment = _append_shared_signal_fragment(repo_root, module)
    _aggregate_candidate_fragment(repo_root, second_fragment)
    signals = _read_schema_v2_entity_rows(repo_root, "semantic_signals")
    (repo_root / "outputs/cumulative_database/semantic_signals.jsonl").write_text(
        json.dumps(signals[0], ensure_ascii=False) + "\n", encoding="utf-8"
    )

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.4-parity"
    )

    assert exit_code == 1
    assert "semantic_signals:projection_parity:missing_in_jsonl:" in stdout


def test_build_versioned_package_rejects_incomplete_aggregate_assignment_contexts(
    tmp_path: Path,
) -> None:
    """Assignments must retain every bound sector/axis context of a candidate."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    second_fragment = _append_shared_signal_fragment(
        repo_root,
        module,
        sector="coastal_tourism",
        axis_group="MARITIME",
        axis_code="T",
    )
    _aggregate_candidate_fragment(repo_root, second_fragment)

    assignments = _read_schema_v2_entity_rows(
        repo_root, "sector_competence_assignments"
    )
    duplicate_context = dict(assignments[0])
    duplicate_context["assignment_id"] = "assignment_002"
    assignments.append(duplicate_context)
    _write_schema_v2_entity_rows(
        repo_root, "sector_competence_assignments", assignments
    )

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.5"
    )

    assert exit_code == 1
    assert "sector_competence_assignments:lineage:assignment_001:" in stdout
    assert "semantic_context_set" in stdout


def test_build_versioned_package_accepts_later_unreviewed_candidate_context(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    second_fragment = _append_shared_signal_fragment(
        repo_root,
        module,
        sector="coastal_tourism",
        axis_group="MARITIME",
        axis_code="T",
    )
    _aggregate_candidate_fragment(repo_root, second_fragment)

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.5-snapshot-ok"
    )

    assert exit_code == 0, stdout


def test_schema_v2_readers_reject_non_finite_numbers(tmp_path: Path) -> None:
    """NaN and infinity are never valid values in schema-v2 projections."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    sample = json.loads(
        (REPO_ROOT / "tests/fixtures/cumulative_database_schema_samples.json").read_text(
            encoding="utf-8"
        )
    )["semantic_signals"]
    schema_path = repo_root / "schemas" / "semantic_signals.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    fields = list(schema["properties"])

    csv_path = tmp_path / "semantic_signals.csv"
    csv_row = dict(sample)
    csv_row["confidence_score"] = "NaN"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(csv_row)
    _, csv_errors = module._read_schema_v2_csv(
        csv_path, schema_path, "semantic_signals"
    )
    assert csv_errors == [
        "semantic_signals.csv row 2 column confidence_score "
        "contains a non-finite numeric value"
    ]

    jsonl_path = tmp_path / "semantic_signals.jsonl"
    jsonl_path.write_text(
        '{"confidence_score": Infinity}\n', encoding="utf-8"
    )
    jsonl_rows, jsonl_errors = module._read_schema_v2_jsonl(
        jsonl_path, "semantic_signals"
    )
    assert jsonl_rows == []
    assert jsonl_errors == [
        "semantic_signals.jsonl line 1 contains a non-finite numeric value"
    ]


def test_build_versioned_package_rejects_schema_v2_manifest_count_mismatch(
    tmp_path: Path,
) -> None:
    """Published source manifest counts must match both validated projections."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)
    manifest_path = (
        repo_root / "outputs/cumulative_database/cumulative_database_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["semantic_signals"] = 0
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.8"
    )

    assert exit_code == 1
    assert "schema_v2_manifest_count_mismatch:" in stdout
    assert "cumulative_database_manifest.json:semantic_signals:" in stdout


def test_build_versioned_package_enforces_schema_datetime_formats(
    tmp_path: Path,
) -> None:
    """Draft-2020-12 format checking rejects impossible calendar timestamps."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)
    decisions = _read_schema_v2_entity_rows(repo_root, "validation_decisions")
    decisions[0]["decision_at_utc"] = "2026-07-07T25:00:00+00:00"
    _write_schema_v2_entity_rows(repo_root, "validation_decisions", decisions)

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.9"
    )

    assert exit_code == 1
    assert "is not a 'date-time'" in stdout


def test_build_versioned_package_rejects_provenance_and_snapshot_tampering(
    tmp_path: Path,
) -> None:
    """Fragments and decision snapshots retain immutable source preimages."""
    module = _load_module()
    scenarios = {
        "provenance": "evidence_fragments:lineage:",
        "provenance-hash": "provenance_hash",
        "snapshot": "validation_decisions:lineage:decision_001:fragment_ids",
        "timestamp": "validation_decisions:lineage:decision_001:source_retrieved_at_utc",
    }
    for scenario, expected_error in scenarios.items():
        repo_root = tmp_path / scenario / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        _copy_required_schemas(repo_root)
        _seed_minimal_outputs(repo_root)
        if scenario in {"provenance", "provenance-hash", "timestamp"}:
            fragments = _read_schema_v2_entity_rows(repo_root, "evidence_fragments")
            if scenario == "provenance":
                fragments[0]["source_provider_id"] = "crossref:tampered"
            elif scenario == "provenance-hash":
                fragments[0]["provenance_hash"] = "0" * 64
            else:
                fragments[0]["source_retrieved_at_utc"] = "2026-07-08T00:00:00+00:00"
            _write_schema_v2_entity_rows(repo_root, "evidence_fragments", fragments)
        else:
            decisions = _read_schema_v2_entity_rows(repo_root, "validation_decisions")
            decisions[0]["fragment_ids"] = "fragment:missing"
            _write_schema_v2_entity_rows(repo_root, "validation_decisions", decisions)

        exit_code, stdout = _run_package(
            module,
            repo_root,
            tmp_path / scenario / "release_out",
            f"v0.1.10-{scenario}",
        )
        assert exit_code == 1
        assert expected_error in stdout


def test_build_versioned_package_rejects_candidate_selected_fragment_mismatch(
    tmp_path: Path,
) -> None:
    """Candidate scalar spans must remain an exact copy of their fragment."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)
    candidates = _read_schema_v2_entity_rows(repo_root, "competence_candidates")
    candidates[0]["exact_evidence_span"] = "tampered span"
    _write_schema_v2_entity_rows(repo_root, "competence_candidates", candidates)

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.11"
    )

    assert exit_code == 1
    assert "competence_candidates:lineage:" in stdout
    assert "selected_fragment_content" in stdout


def test_build_versioned_package_supports_shared_canonical_label_assignments(
    tmp_path: Path,
) -> None:
    """Distinct accepted candidates may legitimately share one canonical label."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)
    _append_shared_canonical_candidate(repo_root, module)

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.12"
    )

    assert exit_code == 0, stdout


def _replace_candidate_references(
    repo_root: Path, old_candidate_id: str, new_candidate_id: str
) -> None:
    for entity_name, field_name in (
        ("canonical_competences", "source_candidate_id"),
        ("sector_competence_assignments", "source_candidate_id"),
        ("validation_decisions", "target_candidate_id"),
    ):
        rows = _read_schema_v2_entity_rows(repo_root, entity_name)
        for row in rows:
            if row[field_name] == old_candidate_id:
                row[field_name] = new_candidate_id
        _write_schema_v2_entity_rows(repo_root, entity_name, rows)


def test_build_versioned_package_rejects_tampered_deterministic_identities(
    tmp_path: Path,
) -> None:
    """Published schema-v2 identities must be reproducible from their preimages."""
    module = _load_module()
    expected_errors = {
        "signal": "semantic_signals:identity:",
        "fragment": "evidence_fragments:identity:",
        "candidate": "competence_candidates:identity:",
        "canonical": "canonical_competences:identity:",
    }
    for identity_kind, expected_error in expected_errors.items():
        repo_root = tmp_path / identity_kind / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        _copy_required_schemas(repo_root)
        _seed_minimal_outputs(repo_root)
        fragments = _read_schema_v2_entity_rows(repo_root, "evidence_fragments")
        signals = _read_schema_v2_entity_rows(repo_root, "semantic_signals")
        candidates = _read_schema_v2_entity_rows(repo_root, "competence_candidates")

        if identity_kind == "signal":
            new_signal_id = "signal:tampered"
            fragments[0]["fragment_id"] = module._expected_fragment_id(
                fragments[0], new_signal_id
            )
            signals[0]["signal_id"] = new_signal_id
            signals[0]["fragment_id"] = fragments[0]["fragment_id"]
            candidates[0]["signal_id"] = new_signal_id
            candidates[0]["fragment_id"] = fragments[0]["fragment_id"]
            candidates[0]["fragment_ids"] = fragments[0]["fragment_id"]
            old_candidate_id = str(candidates[0]["candidate_id"])
            candidates[0]["candidate_id"] = module._expected_candidate_id(candidates[0])
            _replace_candidate_references(
                repo_root, old_candidate_id, str(candidates[0]["candidate_id"])
            )
        elif identity_kind == "fragment":
            fragments[0]["fragment_id"] = "fragment:tampered"
            signals[0]["fragment_id"] = fragments[0]["fragment_id"]
            candidates[0]["fragment_id"] = fragments[0]["fragment_id"]
            candidates[0]["fragment_ids"] = fragments[0]["fragment_id"]
        elif identity_kind == "candidate":
            old_candidate_id = str(candidates[0]["candidate_id"])
            candidates[0]["candidate_id"] = "candidate:tampered"
            _replace_candidate_references(
                repo_root, old_candidate_id, str(candidates[0]["candidate_id"])
            )
        else:
            canonicals = _read_schema_v2_entity_rows(
                repo_root, "canonical_competences"
            )
            canonicals[0]["canonical_competence_id"] = "canonical:tampered"
            _write_schema_v2_entity_rows(
                repo_root, "canonical_competences", canonicals
            )

        _write_schema_v2_entity_rows(repo_root, "evidence_fragments", fragments)
        _write_schema_v2_entity_rows(repo_root, "semantic_signals", signals)
        _write_schema_v2_entity_rows(repo_root, "competence_candidates", candidates)
        exit_code, stdout = _run_package(
            module,
            repo_root,
            tmp_path / identity_kind / "release_out",
            f"v0.1.6-{identity_kind}",
        )
        assert exit_code == 1
        assert expected_error in stdout


def test_build_versioned_package_rejects_padded_assignment_lineage_id(
    tmp_path: Path,
) -> None:
    """Published assignment foreign keys retain exact canonical syntax."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)
    canonicals = _read_schema_v2_entity_rows(repo_root, "canonical_competences")
    assignments = _read_schema_v2_entity_rows(
        repo_root, "sector_competence_assignments"
    )
    padded_id = f" {canonicals[0]['canonical_competence_id']} "
    assignments[0]["canonical_competence_id"] = padded_id
    _write_schema_v2_entity_rows(
        repo_root, "sector_competence_assignments", assignments
    )

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.13-padded-assignment"
    )

    assert exit_code == 1
    assert "canonical_competence_id:outer_whitespace" in stdout


def test_build_versioned_package_rejects_noncanonical_assignment_evidence_ids(
    tmp_path: Path,
) -> None:
    """Published assignment evidence references retain exact serialization."""
    module = _load_module()
    for scenario in ("outer-whitespace", "duplicate"):
        repo_root = tmp_path / scenario / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        _copy_required_schemas(repo_root)
        _seed_minimal_outputs(repo_root)
        assignments = _read_schema_v2_entity_rows(
            repo_root, "sector_competence_assignments"
        )
        expected_evidence_id = str(assignments[0]["evidence_ids"])
        assignments[0]["evidence_ids"] = (
            f" {expected_evidence_id} "
            if scenario == "outer-whitespace"
            else f"{expected_evidence_id}|{expected_evidence_id}"
        )
        _write_schema_v2_entity_rows(
            repo_root, "sector_competence_assignments", assignments
        )

        exit_code, stdout = _run_package(
            module,
            repo_root,
            tmp_path / scenario / "release_out",
            f"v0.1.13-{scenario}",
        )

        assert exit_code == 1
        assert "sector_competence_assignments:lineage:" in stdout
        assert ":evidence_ids" in stdout


def test_build_versioned_package_rejects_invalid_supersession_graphs(
    tmp_path: Path,
) -> None:
    """Decision ledgers reject cycles and multiple active decisions per candidate."""
    module = _load_module()
    expected_errors = {
        "cycle": "validation_decisions:supersession:cycle:",
        "multiple-active": (
            "validation_decisions:supersession:multiple_active_decisions:"
        ),
    }
    for scenario, expected_error in expected_errors.items():
        repo_root = tmp_path / scenario / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)
        _copy_required_schemas(repo_root)
        _seed_minimal_outputs(repo_root)
        decisions = _read_schema_v2_entity_rows(repo_root, "validation_decisions")
        second_decision = dict(decisions[0])
        second_decision.update(
            {
                "validation_decision_id": "decision_002",
                "canonical_label": "",
                "decision_status": "review_required",
                "decision_reason": "Regression decision ledger entry.",
            }
        )
        if scenario == "cycle":
            decisions[0]["superseded_validation_decision_id"] = "decision_002"
            second_decision["superseded_validation_decision_id"] = "decision_001"
        else:
            second_decision["superseded_validation_decision_id"] = ""
        decisions.append(second_decision)
        _write_schema_v2_entity_rows(repo_root, "validation_decisions", decisions)

        exit_code, stdout = _run_package(
            module,
            repo_root,
            tmp_path / scenario / "release_out",
            f"v0.1.7-{scenario}",
        )
        assert exit_code == 1
        assert expected_error in stdout


def test_build_versioned_package_rejects_equal_time_supersession(
    tmp_path: Path,
) -> None:
    """Versioned-package validation requires superseding timestamps to advance."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)
    decisions = _read_schema_v2_entity_rows(repo_root, "validation_decisions")
    replacement = dict(decisions[0])
    replacement.update(
        {
            "validation_decision_id": "decision_002",
            "canonical_label": "",
            "decision_status": "review_required",
            "decision_reason": "Equal-time replacement is invalid.",
            "superseded_validation_decision_id": "decision_001",
        }
    )
    _write_schema_v2_entity_rows(
        repo_root, "validation_decisions", [*decisions, replacement]
    )

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.1.13"
    )

    assert exit_code == 1
    assert (
        "validation_decisions:supersession:"
        "decision_002:not_later_than:decision_001"
    ) in stdout


def test_build_versioned_research_data_package_cli_entrypoint_forwards_argv(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)
    output_dir = tmp_path / "release_out"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--repo-root",
            str(repo_root),
            "--output-dir",
            str(output_dir),
            "--version-tag",
            "v0.2.0",
            "--release-tag",
            "v0.2.0",
            "--commit-sha",
            "deadbeef",
            "--include-xlsx",
            "false",
            "--include-sav",
            "false",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "[OK]" in result.stdout
    assert (output_dir / "morskamary_cumulative_evidence_v0.2.0").exists()


def test_build_versioned_package_fails_on_missing_prerequisites(
    tmp_path: Path,
) -> None:
    """Package builder must exit non-zero with a clear message when inputs are missing."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    # Deliberately do NOT seed outputs - simulate missing prerequisites.

    output_dir = tmp_path / "release_out"
    import io
    from contextlib import redirect_stdout

    stdout_capture = io.StringIO()
    with redirect_stdout(stdout_capture):
        exit_code = module.main(
            [
                "--repo-root",
                str(repo_root),
                "--output-dir",
                str(output_dir),
                "--version-tag",
                "v0.3.0",
                "--include-xlsx",
                "false",
                "--include-sav",
                "false",
            ]
        )

    assert exit_code != 0, "Should fail with missing prerequisites"
    output = stdout_capture.getvalue()
    assert "[ERROR]" in output, f"Expected error message in stdout, got: {output!r}"
    # Must mention at least one prerequisite command
    assert "python" in output.lower() or "scripts/" in output, (
        f"Should mention prerequisite commands, got: {output!r}"
    )


def test_build_versioned_package_preserves_distinct_legacy_and_schema_v2_evidence_records(
    tmp_path: Path,
) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    exit_code, stdout = _run_package(
        module, repo_root, tmp_path / "release_out", "v0.3.1"
    )

    assert exit_code == 0, stdout
    package_dir = tmp_path / "release_out" / "morskamary_cumulative_evidence_v0.3.1"
    assert (package_dir / "data/csv/evidence_records.csv").exists()
    assert (package_dir / "data/jsonl/evidence_records.jsonl").exists()
    assert (
        package_dir
        / "data/csv/schema_v2_supporting_evidence_records.csv"
    ).exists()
    assert (
        package_dir
        / "data/jsonl/schema_v2_supporting_evidence_records.jsonl"
    ).exists()


def test_build_versioned_package_restores_previous_directory_after_failed_rebuild(
    tmp_path: Path,
) -> None:
    """On a failed rebuild, the previous package directory must be restored.

    The quarantine pattern renames the old package to ``.stale`` before
    validation so that a partial new build cannot corrupt the good output.
    When validation fails the old directory must be moved back so the user
    is not left without any usable package.
    """
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)
    output_dir = tmp_path / "release_out"

    exit_code, stdout = _run_package(module, repo_root, output_dir, "v0.3.2")
    assert exit_code == 0, stdout
    package_dir = output_dir / "morskamary_cumulative_evidence_v0.3.2"
    assert package_dir.exists()

    decisions = _read_schema_v2_entity_rows(repo_root, "validation_decisions")
    decisions[0]["decision_at_utc"] = "2026-07-07T25:00:00+00:00"
    _write_schema_v2_entity_rows(repo_root, "validation_decisions", decisions)

    exit_code, stdout = _run_package(module, repo_root, output_dir, "v0.3.2")
    assert exit_code == 1
    # The previous good package must be restored to its original path so the
    # caller is not left without any usable artifact.
    assert package_dir.exists(), (
        "Previous good package was not restored after failed rebuild"
    )
    assert not (output_dir / "morskamary_cumulative_evidence_v0.3.2.stale").exists(), (
        "Stale quarantine directory must not persist after restoring the previous package"
    )


def test_build_versioned_package_bootstrap_creates_empty_manual_sources(
    tmp_path: Path,
) -> None:
    """--bootstrap-empty-manual-sources true must create header-only manual source files."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    # Seed only cross-run and analysis outputs (not manual sources).
    _seed_minimal_outputs(repo_root)
    # Remove manual source files to simulate missing state.
    for rel in (
        "outputs/manual_sources/historical_compatibility.csv",
        "outputs/manual_sources/manual_sources_index.csv",
    ):
        p = repo_root / rel
        if p.exists():
            p.unlink()

    output_dir = tmp_path / "release_out"
    exit_code = module.main(
        [
            "--repo-root",
            str(repo_root),
            "--output-dir",
            str(output_dir),
            "--version-tag",
            "v0.4.0",
            "--source-commit-sha",
            "bootstrap_sha_test",
            "--bootstrap-empty-manual-sources",
            "true",
            "--include-xlsx",
            "false",
            "--include-sav",
            "false",
        ]
    )
    assert exit_code == 0, "Bootstrap mode should succeed"
    # Files must have been created (header-only)
    for rel in (
        "outputs/manual_sources/historical_compatibility.csv",
        "outputs/manual_sources/manual_sources_index.csv",
    ):
        p = repo_root / rel
        assert p.exists(), f"Bootstrap should have created {rel}"
        content = p.read_text(encoding="utf-8")
        assert content.strip(), f"Bootstrapped file {rel} should have a header row"


def test_build_versioned_package_no_implicit_bootstrap_without_flag(
    tmp_path: Path,
) -> None:
    """Without --bootstrap-empty-manual-sources, missing manual sources must cause failure."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)
    # Remove manual source files
    for rel in (
        "outputs/manual_sources/historical_compatibility.csv",
        "outputs/manual_sources/manual_sources_index.csv",
    ):
        p = repo_root / rel
        if p.exists():
            p.unlink()

    output_dir = tmp_path / "release_out"
    exit_code = module.main(
        [
            "--repo-root",
            str(repo_root),
            "--output-dir",
            str(output_dir),
            "--version-tag",
            "v0.5.0",
            "--include-xlsx",
            "false",
            "--include-sav",
            "false",
        ]
    )
    assert exit_code != 0, (
        "Should fail when manual sources are missing and bootstrap flag is not set"
    )


def test_build_versioned_package_manifest_uses_source_and_package_commit_sha(
    tmp_path: Path,
) -> None:
    """RELEASE_MANIFEST.json must contain source_commit_sha and package_commit_sha."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    _copy_required_schemas(repo_root)
    _seed_minimal_outputs(repo_root)

    output_dir = tmp_path / "release_out"
    exit_code = module.main(
        [
            "--repo-root",
            str(repo_root),
            "--output-dir",
            str(output_dir),
            "--version-tag",
            "v0.6.0",
            "--source-commit-sha",
            "source_abc123",
            "--package-commit-sha",
            "pending_until_merge",
            "--include-xlsx",
            "false",
            "--include-sav",
            "false",
        ]
    )
    assert exit_code == 0

    package_dir = output_dir / "morskamary_cumulative_evidence_v0.6.0"
    manifest = json.loads(
        (package_dir / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest["source_commit_sha"] == "source_abc123"
    assert manifest["package_commit_sha"] == "pending_until_merge"
    assert "commit_sha" not in manifest, (
        "Manifest must not contain the deprecated 'commit_sha' key"
    )

    citation = (package_dir / "CITATION_APA.txt").read_text(encoding="utf-8")
    assert "source_abc123" in citation
    assert "Source commit" in citation
