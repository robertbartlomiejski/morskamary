from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

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
