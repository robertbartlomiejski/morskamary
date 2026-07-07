from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "revalidate_historical_outputs.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "revalidate_historical_outputs", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _seed_bundle_dir(path: Path) -> None:
    (path / "outputs" / "research_sources").mkdir(parents=True, exist_ok=True)
    (path / "outputs").mkdir(parents=True, exist_ok=True)
    (path / "outputs" / "research_sources" / "live_records.json").write_text(
        json.dumps([{"doi": "10.1234/demo", "title": "Demo Live"}]),
        encoding="utf-8",
    )
    (
        path / "outputs" / "research_sources" / "live_records_triangulated.json"
    ).write_text(
        json.dumps({"records": [{"source_id": "tri-1", "title": "Demo Tri"}]}),
        encoding="utf-8",
    )
    (path / "outputs" / "cumulative_qmbd_records.json").write_text(
        json.dumps({"records": [{"source_id": "cum-1", "title": "Demo Cum"}]}),
        encoding="utf-8",
    )


def test_revalidate_historical_outputs_generates_compatibility_and_cumulative_rows(
    tmp_path: Path,
) -> None:
    module = _load_module()
    bundle_dir = tmp_path / "bundle"
    _seed_bundle_dir(bundle_dir)

    zip_path = tmp_path / "bundle.zip"
    with ZipFile(zip_path, "w") as archive:
        for file_path in bundle_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(bundle_dir).as_posix())

    output_dir = tmp_path / "outputs" / "manual_sources"
    exit_code = module.main(
        [
            "--input",
            str(bundle_dir),
            "--input",
            str(zip_path),
            "--output-dir",
            str(output_dir),
        ]
    )
    assert exit_code == 0

    compatibility_csv = output_dir / "historical_compatibility.csv"
    cumulative_jsonl = output_dir / "historical_cumulative_records.jsonl"
    report_json = output_dir / "historical_revalidation_report.json"
    assert compatibility_csv.exists()
    assert cumulative_jsonl.exists()
    assert report_json.exists()

    with compatibility_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert all(row["status"] == "compatible" for row in rows)

    cumulative_rows = [
        json.loads(line)
        for line in cumulative_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert cumulative_rows
    assert all("canonical_record_id" in row for row in cumulative_rows)


def test_revalidate_historical_outputs_cli_entrypoint_receives_input_flag(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "bundle"
    _seed_bundle_dir(bundle_dir)
    output_dir = tmp_path / "outputs" / "manual_sources"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input",
            str(bundle_dir),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "historical_compatibility.csv").exists()
