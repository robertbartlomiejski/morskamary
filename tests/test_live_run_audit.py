"""Unit tests for the Layer 1 raw-provider-acquisition audit builder.

Covers PR-190 / Layer 1: preserving raw provider acquisition separately from
normalized evidence under ``outputs/live_runs/<run_id>/``.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.scientific_sources.live_run_audit import (
    AUDIT_CHECKSUMS_FILENAME,
    AUDIT_MANIFEST_FILENAME,
    RAW_ACQUISITION_INDEX_COLUMNS,
    LiveRunAuditBuilder,
    LiveRunAuditError,
    build_live_run_audit,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / "config" / "live_query_protocol.yml"

FROZEN_TS = "2026-07-09T00:00:00+00:00"

# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------


def _sample_raw_records() -> List[Dict[str, Any]]:
    return [
        {
            "title": "Sample paper A",
            "authors": "Doe, J.",
            "year": 2024,
            "doi": "10.1000/xyz.001",
            "source_id": "crossref:10.1000/xyz.001",
            "provider": "Crossref",
            "source_query": "marine biotechnology blue bioeconomy innovation governance",
            "retrieval_timestamp": "2026-07-02T22:30:10.838173+00:00",
        },
        {
            "title": "Sample paper B",
            "authors": "Roe, J.",
            "year": 2023,
            "doi": "10.1000/xyz.002",
            "source_id": "crossref:10.1000/xyz.002",
            "provider": "Crossref",
            "source_query": "marine biotechnology blue bioeconomy innovation governance",
            "retrieval_timestamp": "2026-07-02T22:30:10.838173+00:00",
        },
        {
            "title": "Sample paper C",
            "authors": "Moe, J.",
            "year": 2022,
            "doi": "10.1000/xyz.003",
            "source_id": "scopus:10.1000/xyz.003",
            "provider": "Scopus",
            "source_query": "unknown query never declared in protocol",
            "retrieval_timestamp": "2026-07-02T22:30:10.838173+00:00",
        },
    ]


def _sample_normalized_records() -> List[Dict[str, Any]]:
    return [
        {
            "title": "Sample paper A",
            "doi": "10.1000/xyz.001",
            "source_id": "crossref:10.1000/xyz.001",
            "provider": "Crossref",
            "source_query": "marine biotechnology blue bioeconomy innovation governance",
        },
        # Second record has an evidence[] list that contributes a distinct
        # (provider, query) bucket.
        {
            "title": "Sample paper D",
            "doi": "10.1000/xyz.004",
            "source_id": "crossref:10.1000/xyz.004",
            "provider": "Crossref",
            "source_query": "marine biotechnology blue bioeconomy innovation governance",
            "evidence": [
                {
                    "source_provider": "scopus",
                    "query": "another query only seen in evidence",
                },
            ],
        },
    ]


def _sample_provenance_rows() -> List[Dict[str, Any]]:
    return [
        {
            "record_id": "crossref:10.1000/xyz.001",
            "source_provider": "Crossref",
            "retrieval_mode": "live",
            "query": "marine biotechnology blue bioeconomy innovation governance",
            "api_endpoint_label": "crossref/works",
            "timestamp": "2026-07-02T22:30:10.838428+00:00",
            "confidence_score": 0.9,
            "provenance_hash": "aaaaaaaaaaaaaaaa",
        }
    ]


def _sample_coverage_rows() -> str:
    return (
        "sector,provider,query,record_count\n"
        "Blue Biotech,crossref,marine biotechnology blue bioeconomy innovation governance,2\n"
        "Blue Biotech,scopus,unknown query never declared in protocol,1\n"
    )


def _write_sample_research_sources(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "raw_provider_records.json").write_text(
        json.dumps(_sample_raw_records(), indent=2), encoding="utf-8"
    )
    (base / "live_records.json").write_text(
        json.dumps(_sample_normalized_records(), indent=2), encoding="utf-8"
    )
    (base / "live_provenance.json").write_text(
        json.dumps(_sample_provenance_rows(), indent=2), encoding="utf-8"
    )
    (base / "live_source_coverage.csv").write_text(
        _sample_coverage_rows(), encoding="utf-8"
    )


@pytest.fixture()
def research_sources_dir(tmp_path: Path) -> Path:
    base = tmp_path / "research_sources"
    _write_sample_research_sources(base)
    return base


@pytest.fixture()
def output_root(tmp_path: Path) -> Path:
    return tmp_path / "live_runs"


# ---------------------------------------------------------------------------
# smoke tests
# ---------------------------------------------------------------------------


class TestBundleShape:
    def test_bundle_directory_layout(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        bundle = result.bundle_dir
        assert bundle == output_root / "R1"
        assert (bundle / AUDIT_MANIFEST_FILENAME).is_file()
        assert (bundle / AUDIT_CHECKSUMS_FILENAME).is_file()
        assert (bundle / "raw").is_dir()
        assert (bundle / "normalized").is_dir()
        assert (bundle / "raw" / "raw_acquisition_index.csv").is_file()
        assert (bundle / "raw" / "raw_provider_records.json").is_file()
        assert (bundle / "normalized" / "live_records.json").is_file()
        assert (bundle / "normalized" / "live_provenance.json").is_file()
        assert (bundle / "normalized" / "live_source_coverage.csv").is_file()

    def test_raw_and_normalized_counts_match_inputs(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        assert result.raw_row_count == 3
        assert result.normalized_row_count == 2

    def test_manifest_has_schema_version_and_counts(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        manifest = json.loads(
            (result.bundle_dir / AUDIT_MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert manifest["schema_version"] == "1.0.0"
        assert manifest["run_id"] == "R1"
        assert manifest["built_at_utc"] == FROZEN_TS
        assert manifest["counts"]["raw_records"] == 3
        assert manifest["counts"]["normalized_records"] == 2
        assert manifest["counts"]["acquisition_rows"] >= 2
        # files[] excludes the manifest itself; it is listed only in
        # _checksums.sha256 to keep the manifest hash stable.
        file_paths = {entry["path"] for entry in manifest["files"]}
        assert AUDIT_MANIFEST_FILENAME not in file_paths
        assert "raw/raw_acquisition_index.csv" in file_paths
        assert "normalized/live_records.json" in file_paths


# ---------------------------------------------------------------------------
# acquisition index behaviour
# ---------------------------------------------------------------------------


class TestAcquisitionIndex:
    def _load_index(self, bundle_dir: Path) -> List[Dict[str, str]]:
        path = bundle_dir / "raw" / "raw_acquisition_index.csv"
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            return list(reader)

    def test_columns_are_stable(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        path = result.bundle_dir / "raw" / "raw_acquisition_index.csv"
        with path.open(newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh))
        assert tuple(header) == RAW_ACQUISITION_INDEX_COLUMNS

    def test_rows_bound_when_protocol_covers_query(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        rows = self._load_index(result.bundle_dir)
        bound_bio = [
            r for r in rows if r["query_id"] == "Q_BLUE_BIOTECH_CORE_001"
            and r["provider"] == "crossref"
        ]
        assert len(bound_bio) == 1
        row = bound_bio[0]
        assert row["sector_slug"] == "blue_biotech"
        assert row["axis_target"] == "M"
        assert row["query_family"] == "core_sector"
        assert row["raw_record_count"] == "2"
        assert row["normalized_record_count"] == "2"
        assert row["unique_source_ids"] == "2"
        assert row["coverage_record_count"] == "2"
        assert row["protocol_binding"] == "bound"

    def test_unknown_query_becomes_unbound(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        rows = self._load_index(result.bundle_dir)
        unbound = [r for r in rows if r["protocol_binding"] == "unbound"]
        assert unbound, "expected at least one unbound acquisition row"
        for r in unbound:
            assert r["query_id"].startswith("unbound:")
            assert r["sector_slug"] == ""
            assert r["axis_target"] == ""
            assert r["query_family"] == ""

    def test_evidence_only_query_produces_row_with_zero_raw(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        rows = self._load_index(result.bundle_dir)
        evidence_only = [
            r for r in rows
            if r["query_text"] == "another query only seen in evidence"
        ]
        assert len(evidence_only) == 1
        assert evidence_only[0]["provider"] == "scopus"
        assert evidence_only[0]["raw_record_count"] == "0"
        assert evidence_only[0]["normalized_record_count"] == "1"

    def test_no_protocol_marks_all_rows_no_protocol(
        self, research_sources_dir: Path, output_root: Path, tmp_path: Path
    ) -> None:
        missing_path = tmp_path / "does_not_exist.yml"
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=missing_path,
            built_at_utc=FROZEN_TS,
        )
        rows = self._load_index(result.bundle_dir)
        assert rows
        for r in rows:
            assert r["protocol_binding"] == "no_protocol"


# ---------------------------------------------------------------------------
# checksums / determinism
# ---------------------------------------------------------------------------


class TestChecksumsAndDeterminism:
    def test_checksum_file_lists_every_file_including_manifest(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        text = (result.bundle_dir / AUDIT_CHECKSUMS_FILENAME).read_text(
            encoding="utf-8"
        )
        lines = [line for line in text.strip().splitlines() if line]
        listed_paths = {line.split(None, 1)[1] for line in lines}
        assert AUDIT_MANIFEST_FILENAME in listed_paths
        assert "raw/raw_acquisition_index.csv" in listed_paths
        assert "normalized/live_records.json" in listed_paths
        # Every checksum is a 64-char lowercase hex string
        for line in lines:
            sha, _rel = line.split(None, 1)
            assert len(sha) == 64
            int(sha, 16)  # raises if not hex

    def test_two_builds_are_byte_identical_with_frozen_timestamp(
        self, research_sources_dir: Path, tmp_path: Path
    ) -> None:
        first = tmp_path / "a"
        second = tmp_path / "b"
        r1 = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=first,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        r2 = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=second,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        assert r1.raw_row_count == r2.raw_row_count
        for rel, sha, _size in r1.files:
            counterpart = next(
                (entry for entry in r2.files if entry[0] == rel), None
            )
            assert counterpart is not None, f"missing file {rel} in second build"
            assert sha == counterpart[1], f"checksum drift for {rel}"

    def test_rebuild_replaces_prior_bundle(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        # Populate the bundle with a stale file first.
        target = output_root / "R1"
        target.mkdir(parents=True, exist_ok=True)
        stale = target / "stale.txt"
        stale.write_text("leftover from a prior build", encoding="utf-8")
        build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        assert not stale.exists()


# ---------------------------------------------------------------------------
# validation and error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_missing_research_sources_dir_rejected(
        self, tmp_path: Path, output_root: Path
    ) -> None:
        with pytest.raises(LiveRunAuditError, match="research_sources_dir"):
            build_live_run_audit(
                run_id="R1",
                research_sources_dir=tmp_path / "does_not_exist",
                output_root=output_root,
                built_at_utc=FROZEN_TS,
            )

    def test_missing_raw_records_rejected(
        self, tmp_path: Path, output_root: Path
    ) -> None:
        base = tmp_path / "research_sources"
        base.mkdir()
        (base / "live_records.json").write_text("[]", encoding="utf-8")
        (base / "live_provenance.json").write_text("[]", encoding="utf-8")
        with pytest.raises(LiveRunAuditError, match="raw_provider_records.json"):
            build_live_run_audit(
                run_id="R1",
                research_sources_dir=base,
                output_root=output_root,
                built_at_utc=FROZEN_TS,
            )

    def test_non_list_raw_records_rejected(
        self, tmp_path: Path, output_root: Path
    ) -> None:
        base = tmp_path / "research_sources"
        base.mkdir()
        (base / "raw_provider_records.json").write_text('{"nope": 1}', encoding="utf-8")
        (base / "live_records.json").write_text("[]", encoding="utf-8")
        (base / "live_provenance.json").write_text("[]", encoding="utf-8")
        with pytest.raises(LiveRunAuditError, match="must be a JSON array"):
            build_live_run_audit(
                run_id="R1",
                research_sources_dir=base,
                output_root=output_root,
                built_at_utc=FROZEN_TS,
            )

    def test_invalid_json_raw_records_rejected(
        self, tmp_path: Path, output_root: Path
    ) -> None:
        base = tmp_path / "research_sources"
        base.mkdir()
        (base / "raw_provider_records.json").write_text("not json", encoding="utf-8")
        (base / "live_records.json").write_text("[]", encoding="utf-8")
        (base / "live_provenance.json").write_text("[]", encoding="utf-8")
        with pytest.raises(LiveRunAuditError, match="not valid JSON"):
            build_live_run_audit(
                run_id="R1",
                research_sources_dir=base,
                output_root=output_root,
                built_at_utc=FROZEN_TS,
            )

    def test_non_object_row_in_raw_records_rejected(
        self, tmp_path: Path, output_root: Path
    ) -> None:
        base = tmp_path / "research_sources"
        base.mkdir()
        (base / "raw_provider_records.json").write_text("[1, 2, 3]", encoding="utf-8")
        (base / "live_records.json").write_text("[]", encoding="utf-8")
        (base / "live_provenance.json").write_text("[]", encoding="utf-8")
        with pytest.raises(LiveRunAuditError, match="non-object item"):
            build_live_run_audit(
                run_id="R1",
                research_sources_dir=base,
                output_root=output_root,
                built_at_utc=FROZEN_TS,
            )

    @pytest.mark.parametrize(
        "bad_run_id",
        ["", "  ", "../escape", "abc/def", ".hidden", "space here", "abc..def"],
    )
    def test_unsafe_run_ids_rejected(
        self,
        research_sources_dir: Path,
        output_root: Path,
        bad_run_id: str,
    ) -> None:
        with pytest.raises(LiveRunAuditError):
            build_live_run_audit(
                run_id=bad_run_id,
                research_sources_dir=research_sources_dir,
                output_root=output_root,
                built_at_utc=FROZEN_TS,
            )

    def test_malformed_payload_envelope_rejected(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        envelopes_dir = research_sources_dir / "raw_api_payloads"
        envelopes_dir.mkdir()
        (envelopes_dir / "corrupt.json").write_text("not json", encoding="utf-8")
        with pytest.raises(LiveRunAuditError, match="payload envelope"):
            build_live_run_audit(
                run_id="R1",
                research_sources_dir=research_sources_dir,
                output_root=output_root,
                built_at_utc=FROZEN_TS,
            )


# ---------------------------------------------------------------------------
# payload envelopes
# ---------------------------------------------------------------------------


class TestPayloadEnvelopes:
    def test_envelope_metadata_surfaces_in_index(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        envelopes_dir = research_sources_dir / "raw_api_payloads"
        envelopes_dir.mkdir()
        envelope = {
            "provider": "crossref",
            "query": "marine biotechnology blue bioeconomy innovation governance",
            "captured_at": "2026-07-02T22:30:10+00:00",
            "payload_sha256": "d" * 64,
            "payload": {"items": []},
        }
        (envelopes_dir / "crossref_abc.json").write_text(
            json.dumps(envelope), encoding="utf-8"
        )
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        # The envelope should have been copied into the bundle and its metadata
        # should appear on the bound acquisition row for Q_BLUE_BIOTECH_CORE_001.
        assert (
            result.bundle_dir / "raw" / "raw_api_payloads" / "crossref_abc.json"
        ).is_file()
        path = result.bundle_dir / "raw" / "raw_acquisition_index.csv"
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        for row in rows:
            if (
                row["query_id"] == "Q_BLUE_BIOTECH_CORE_001"
                and row["provider"] == "crossref"
            ):
                assert row["has_raw_payload_envelope"] == "true"
                assert row["raw_payload_sha256"] == "d" * 64
                assert row["raw_payload_captured_at"] == "2026-07-02T22:30:10+00:00"
                break
        else:
            pytest.fail("expected bound crossref row for Q_BLUE_BIOTECH_CORE_001")


# ---------------------------------------------------------------------------
# workflow context passthrough
# ---------------------------------------------------------------------------


class TestWorkflowContext:
    def test_context_is_embedded_in_manifest(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=research_sources_dir,
            output_root=output_root,
            protocol_path=PROTOCOL_PATH,
            workflow_context={"github_run_id": "42", "commit_sha": "deadbeef"},
            built_at_utc=FROZEN_TS,
        )
        manifest = json.loads(
            (result.bundle_dir / AUDIT_MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        assert manifest["workflow_context"] == {
            "commit_sha": "deadbeef",
            "github_run_id": "42",
        }

    def test_builder_class_accepts_string_paths_via_dataclass(
        self, research_sources_dir: Path, output_root: Path
    ) -> None:
        builder = LiveRunAuditBuilder(
            run_id="R1",
            research_sources_dir=str(research_sources_dir),  # type: ignore[arg-type]
            output_root=str(output_root),  # type: ignore[arg-type]
            built_at_utc=FROZEN_TS,
        )
        result = builder.build()
        assert result.bundle_dir.is_dir()


# ---------------------------------------------------------------------------
# large-run smoke against shipped protocol
# ---------------------------------------------------------------------------


class TestShippedProtocolBinding:
    def test_shipped_protocol_binds_synthetic_queries_by_query_text(
        self, tmp_path: Path
    ) -> None:
        # Craft a synthetic research_sources dir whose queries all exist in the
        # shipped protocol; the resulting bundle should have zero unbound rows.
        base = tmp_path / "research_sources"
        base.mkdir()
        raw = [
            {
                "title": "T1",
                "provider": "Crossref",
                "source_query": "marine biotechnology blue bioeconomy innovation governance",
                "source_id": "crossref:1",
            },
            {
                "title": "T2",
                "provider": "Crossref",
                "source_query": "coastal tourism sustainability overtourism management",
                "source_id": "crossref:2",
            },
        ]
        (base / "raw_provider_records.json").write_text(
            json.dumps(raw), encoding="utf-8"
        )
        (base / "live_records.json").write_text("[]", encoding="utf-8")
        (base / "live_provenance.json").write_text("[]", encoding="utf-8")

        result = build_live_run_audit(
            run_id="R1",
            research_sources_dir=base,
            output_root=tmp_path / "live_runs",
            protocol_path=PROTOCOL_PATH,
            built_at_utc=FROZEN_TS,
        )
        rows = list(csv.DictReader(
            (result.bundle_dir / "raw" / "raw_acquisition_index.csv").open(
                newline="", encoding="utf-8"
            )
        ))
        assert rows
        assert all(r["protocol_binding"] == "bound" for r in rows)


# ---------------------------------------------------------------------------
# safety net for downstream removal of copied files
# ---------------------------------------------------------------------------


def test_source_files_are_not_moved_or_altered(
    research_sources_dir: Path, output_root: Path
) -> None:
    before = {
        p.name: p.read_bytes()
        for p in research_sources_dir.iterdir()
        if p.is_file()
    }
    build_live_run_audit(
        run_id="R1",
        research_sources_dir=research_sources_dir,
        output_root=output_root,
        protocol_path=PROTOCOL_PATH,
        built_at_utc=FROZEN_TS,
    )
    after = {
        p.name: p.read_bytes()
        for p in research_sources_dir.iterdir()
        if p.is_file()
    }
    assert before == after


def test_cli_script_exposes_main_returning_int(tmp_path: Path) -> None:
    """The CLI wrapper importable module returns an int exit code."""
    import importlib.util

    script_path = REPO_ROOT / "scripts" / "build_live_run_audit.py"
    spec = importlib.util.spec_from_file_location("build_live_run_audit", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    base = tmp_path / "research_sources"
    _write_sample_research_sources(base)
    output_root = tmp_path / "live_runs"

    exit_code = module.main(
        [
            "--run-id",
            "R1",
            "--research-sources-dir",
            str(base),
            "--output-root",
            str(output_root),
            "--protocol-path",
            str(PROTOCOL_PATH),
            "--built-at-utc",
            FROZEN_TS,
            "--emit-summary",
        ]
    )
    assert exit_code == 0
    assert (output_root / "R1" / AUDIT_MANIFEST_FILENAME).is_file()

    # Rebuild silently succeeds a second time (idempotent bundle regeneration)
    exit_code_again = module.main(
        [
            "--run-id",
            "R1",
            "--research-sources-dir",
            str(base),
            "--output-root",
            str(output_root),
            "--protocol-path",
            str(PROTOCOL_PATH),
            "--built-at-utc",
            FROZEN_TS,
        ]
    )
    assert exit_code_again == 0


def test_cli_reports_missing_protocol_via_warning(tmp_path: Path, capsys) -> None:
    """CLI still succeeds when the protocol path is absent."""
    import importlib.util

    script_path = REPO_ROOT / "scripts" / "build_live_run_audit.py"
    spec = importlib.util.spec_from_file_location(
        "build_live_run_audit_missing", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    base = tmp_path / "research_sources"
    _write_sample_research_sources(base)
    output_root = tmp_path / "live_runs"

    exit_code = module.main(
        [
            "--run-id",
            "R1",
            "--research-sources-dir",
            str(base),
            "--output-root",
            str(output_root),
            "--protocol-path",
            str(tmp_path / "missing.yml"),
            "--built-at-utc",
            FROZEN_TS,
        ]
    )
    err = capsys.readouterr().err
    assert exit_code == 0
    assert "protocol file not found" in err


def test_cli_reports_missing_research_sources_dir(tmp_path: Path, capsys) -> None:
    """CLI surfaces LiveRunAuditError as a non-zero exit code."""
    import importlib.util

    script_path = REPO_ROOT / "scripts" / "build_live_run_audit.py"
    spec = importlib.util.spec_from_file_location(
        "build_live_run_audit_error", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    exit_code = module.main(
        [
            "--run-id",
            "R1",
            "--research-sources-dir",
            str(tmp_path / "does_not_exist"),
            "--output-root",
            str(tmp_path / "live_runs"),
            "--protocol-path",
            str(PROTOCOL_PATH),
            "--built-at-utc",
            FROZEN_TS,
        ]
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "failed to build live-run audit bundle" in err


# Guard against an accidental noop rewrite that would erase downstream data
def test_bundle_dir_only_touches_its_own_run_subdirectory(
    research_sources_dir: Path, tmp_path: Path
) -> None:
    output_root = tmp_path / "live_runs"
    (output_root / "OtherRun").mkdir(parents=True)
    canary = output_root / "OtherRun" / "canary.txt"
    canary.write_text("do-not-touch", encoding="utf-8")
    build_live_run_audit(
        run_id="R1",
        research_sources_dir=research_sources_dir,
        output_root=output_root,
        protocol_path=PROTOCOL_PATH,
        built_at_utc=FROZEN_TS,
    )
    assert canary.exists()
    assert canary.read_text(encoding="utf-8") == "do-not-touch"


def test_module_public_surface_documented() -> None:
    """The module docstring names every public symbol from __all__."""
    from src.scientific_sources import live_run_audit

    docstring = live_run_audit.__doc__ or ""
    for symbol in live_run_audit.__all__:
        # We only require that the docstring mention symbols the caller is
        # meant to consume (classes and functions), not filename constants.
        if symbol.isupper():
            continue
        assert symbol in docstring, f"missing docstring entry for {symbol!r}"


def _sanity_shutil_import_used() -> None:
    """The tests import shutil for future cleanup helpers; keep the import."""
    _ = shutil.rmtree
