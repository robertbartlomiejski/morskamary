from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_versioned_research_data_package.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_versioned_research_data_package", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _copy_required_schemas(repo_root: Path) -> None:
    schema_dir = repo_root / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    required = [
        "runs.schema.json",
        "source_bundles.schema.json",
        "evidence_records.schema.json",
        "evidence_occurrences.schema.json",
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

    with (package_dir / "data" / "csv" / "runs.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        run_rows = list(csv.DictReader(handle))
    assert run_rows
    assert run_rows[0]["run_id"] == "123-1"

    assert (output_dir / "morskamary_cumulative_evidence_v0.1.0.zip").exists()


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
