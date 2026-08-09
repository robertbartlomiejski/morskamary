from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from src.scientific_sources.cumulative_scientific_database import (
    build_cumulative_scientific_database,
)
from src.scientific_sources.derived_competence_analysis import (
    write_layer45_checksums,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "build_layer4_5_scientific_analysis",
    str(REPO_ROOT / "scripts" / "build_layer4_5_scientific_analysis.py"),
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

LAYER45_CHECKSUMS_FILENAME = _MOD.LAYER45_CHECKSUMS_FILENAME
_merge_layer45_checksums_into_canonical = _MOD._merge_layer45_checksums_into_canonical
_parse_checksum_manifest = _MOD._parse_checksum_manifest

_PROTOCOL_PATH = REPO_ROOT / "config" / "live_query_protocol.yml"
_HYDRONIZATION_QUERY = "desalination hydrosocial water justice governance"


def _write_live_records(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, sort_keys=True), encoding="utf-8")


def test_canonical_checksum_merge_removes_stale_layer45_entries(tmp_path: Path) -> None:
    out = tmp_path / "db"
    out.mkdir()
    old_stats = tmp_path / "old_stats"
    old_stats.mkdir()
    new_stats = tmp_path / "layer4_statistics"
    new_stats.mkdir()

    old_stat = old_stats / "qmbd_cross_tables.csv"
    old_stat.write_text("axis,count\nM,1\n", encoding="utf-8")
    new_stat = new_stats / "qmbd_cross_tables.csv"
    new_stat.write_text("axis,count\nM,2\n", encoding="utf-8")
    demand_csv = out / "derived_competence_demands.csv"
    demand_csv.write_text("competence_demand_id\nD-1\n", encoding="utf-8")
    preserved = out / "run_novelty_metrics.json"
    preserved.write_text('{"status":"ok"}\n', encoding="utf-8")

    layer45_checksum_path = out / LAYER45_CHECKSUMS_FILENAME
    layer45_checksum_path.write_text(
        hashlib.sha256(old_stat.read_bytes()).hexdigest()
        + "  ../old_stats/qmbd_cross_tables.csv\n",
        encoding="utf-8",
    )
    canonical_path = out / "_checksums.sha256"
    canonical_path.write_text(
        "\n".join(
            [
                hashlib.sha256(preserved.read_bytes()).hexdigest()
                + "  run_novelty_metrics.json",
                hashlib.sha256(old_stat.read_bytes()).hexdigest()
                + "  ../old_stats/qmbd_cross_tables.csv",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    previous_entries = _parse_checksum_manifest(layer45_checksum_path)
    managed_files = [demand_csv, new_stat]
    write_layer45_checksums(managed_files, out)
    _merge_layer45_checksums_into_canonical(
        output_dir=out,
        managed_files=managed_files,
        previous_layer45_entries=previous_entries,
    )

    canonical_entries = _parse_checksum_manifest(canonical_path)
    assert canonical_entries["run_novelty_metrics.json"] == hashlib.sha256(
        preserved.read_bytes()
    ).hexdigest()
    assert "../old_stats/qmbd_cross_tables.csv" not in canonical_entries
    assert canonical_entries["../layer4_statistics/qmbd_cross_tables.csv"] == hashlib.sha256(
        new_stat.read_bytes()
    ).hexdigest()


def test_write_layer45_checksums_excludes_checksum_manifests_from_inputs(
    tmp_path: Path,
) -> None:
    out = tmp_path / "db"
    out.mkdir()

    payload = out / "derived_competence_demands.csv"
    payload.write_text("competence_demand_id\nD-1\n", encoding="utf-8")
    layer45_manifest = out / LAYER45_CHECKSUMS_FILENAME
    layer45_manifest.write_text("stale\n", encoding="utf-8")
    canonical_manifest = out / "_checksums.sha256"
    canonical_manifest.write_text("stale\n", encoding="utf-8")

    write_layer45_checksums(
        [payload, layer45_manifest, canonical_manifest],
        out,
    )

    entries = _parse_checksum_manifest(layer45_manifest)
    assert entries == {
        "derived_competence_demands.csv": hashlib.sha256(
            payload.read_bytes()
        ).hexdigest()
    }
    assert LAYER45_CHECKSUMS_FILENAME not in entries
    assert "_checksums.sha256" not in entries


def test_write_layer45_checksums_rejects_non_file_inputs(tmp_path: Path) -> None:
    out = tmp_path / "db"
    out.mkdir()
    non_file = out / "layer4_statistics"
    non_file.mkdir()

    with pytest.raises(FileNotFoundError, match="non_file_emitted_artifact"):
        write_layer45_checksums([non_file], out)


def test_cli_emits_accepted_canonical_hydronization_lineage_demand(
    tmp_path: Path,
) -> None:
    """The CLI must wire accepted schema-v2 lineage into Layer 4 and H2.

    This uses the cumulative builder to materialize a valid retained
    evidence -> semantic signal -> candidate -> decision -> canonical ->
    assignment chain.  The Layer 4-5 CLI must load the emitted JSONL lineage
    itself; it cannot infer validation from the legacy demand projection.
    """
    current_run = tmp_path / "current-run"
    initial_db = tmp_path / "initial-database"
    database_dir = tmp_path / "cumulative-database"
    stats_dir = tmp_path / "layer4-statistics"
    source_retrieved_at = "2026-07-01T00:00:00+00:00"
    decision_at = "2026-07-10T00:00:00+00:00"
    canonical_label = "Hydrosocial governance capability"

    _write_live_records(
        current_run / "research_sources" / "live_records.json",
        [
            {
                "title": "Water governance competence needs in desalination",
                "abstract": (
                    "Desalination operators need governance competence for "
                    "hydrosocial water justice."
                ),
                "doi": "10.1000/accepted-hydronization-lineage",
                "source_id": "crossref:accepted-hydronization-lineage",
                "provider": "Crossref",
                "source_query": _HYDRONIZATION_QUERY,
                "retrieval_timestamp": source_retrieved_at,
            }
        ],
    )
    initial = build_cumulative_scientific_database(
        current_run_dir=current_run,
        output_dir=initial_db,
        protocol_path=_PROTOCOL_PATH,
        current_run_id="RUN-CANONICAL-H",
        built_at_utc=decision_at,
    )
    candidate = next(
        row
        for row in initial.competence_candidates
        if row.axis_group == "HYDRONIZATION"
        and row.candidate_label.lower() == "governance"
    )

    validated = build_cumulative_scientific_database(
        current_run_dir=current_run,
        output_dir=database_dir,
        protocol_path=_PROTOCOL_PATH,
        current_run_id="RUN-CANONICAL-H",
        built_at_utc=decision_at,
        validation_decisions=[
            {
                "target_candidate_id": candidate.candidate_id,
                "canonical_label": canonical_label,
                "decision_status": "accepted",
                "reviewer": "reviewer-fixture-001",
                "decision_at_utc": decision_at,
                "decision_reason": "Accepted hydronization lineage fixture.",
                "evidence_ids": candidate.evidence_id,
                "fragment_ids": candidate.fragment_ids,
                "source_provenance_ids": candidate.source_provenance_ids,
            }
        ],
    )
    assert len(validated.canonical_competences) == 1
    assert len(validated.sector_competence_assignments) == 1

    exit_code = _MOD.main(
        [
            "--database-dir",
            str(database_dir),
            "--output-dir",
            str(database_dir),
            "--stats-dir",
            str(stats_dir),
            "--repository-root",
            str(REPO_ROOT),
            "--outputs-root",
            str(tmp_path),
            "--current-run-id",
            "RUN-CANONICAL-H",
            "--analysis-timestamp-utc",
            "2026-07-12T00:00:00+00:00",
        ]
    )

    assert exit_code == 0
    demand_rows = [
        json.loads(line)
        for line in (database_dir / "derived_competence_demands.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    canonical_rows = [
        row
        for row in demand_rows
        if row["scientific_status"] == "validated_canonical_competence"
    ]
    assert len(canonical_rows) == 1
    canonical_row = canonical_rows[0]
    assert canonical_row["competence_label"] == canonical_label
    assert canonical_row["view_kind"] == "accepted_canonical_lineage_view"
    assert canonical_row["axis_group"] == "HYDRONIZATION"
    assert canonical_row["axis_code"] == "H"
    assert canonical_row["sector"] == "desalination"
    assert canonical_row["manual_review_status"] == "manually_reviewed"
    assert canonical_row["evidence_ids"] == candidate.evidence_id
    assert canonical_row["canonical_competence_id"] == (
        validated.canonical_competences[0].canonical_competence_id
    )
    assert canonical_row["validation_decision_ids"] == (
        validated.validation_decisions[0].validation_decision_id
    )
    assert canonical_row["source_candidate_ids"] == candidate.candidate_id
    assert canonical_row["assignment_ids"] == (
        validated.sector_competence_assignments[0].assignment_id
    )

    layer5_manifest = json.loads(
        (database_dir / "layer5_manifest.json").read_text(encoding="utf-8")
    )
    h2 = layer5_manifest["hypothesis_results"]["H2"]
    assert h2["validated_hydronization_demand_count"] == 1
    assert h2["validated_missing_demand_count"] == 1
