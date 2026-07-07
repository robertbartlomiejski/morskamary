from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ingest_manual_supporting_sources.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "ingest_manual_supporting_sources", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_ingest_manual_sources_writes_append_only_ledger_and_index(
    tmp_path: Path,
) -> None:
    module = _load_module()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "a.txt").write_text("hello", encoding="utf-8")
    (docs_dir / "b.pdf").write_bytes(b"%PDF-1.4 fake")

    zip_path = tmp_path / "archive.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("nested/c.docx", b"fake-docx-payload")

    output_dir = tmp_path / "outputs" / "manual_sources"
    exit_code = module.main(
        [
            "--input",
            str(docs_dir),
            "--input",
            str(zip_path),
            "--ledger-dir",
            str(output_dir),
            "--copy-files",
            "true",
        ]
    )
    assert exit_code == 0

    ledger_path = output_dir / "manual_sources_ledger.jsonl"
    index_path = output_dir / "manual_sources_index.csv"
    report_path = output_dir / "manual_sources_ingest_report.json"
    assert ledger_path.exists()
    assert index_path.exists()
    assert report_path.exists()

    ledger_rows = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(ledger_rows) == 3
    assert all("source_id" in row for row in ledger_rows)

    with index_path.open("r", encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 3

    second_exit_code = module.main(
        [
            "--input",
            str(docs_dir),
            "--ledger-dir",
            str(output_dir),
            "--copy-files",
            "true",
        ]
    )
    assert second_exit_code == 0
    ledger_rows_after = [
        line
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(ledger_rows_after) == 3


def test_ingest_manual_sources_cli_entrypoint_receives_input_flag(
    tmp_path: Path,
) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "a.txt").write_text("hello", encoding="utf-8")
    output_dir = tmp_path / "outputs" / "manual_sources"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input",
            str(docs_dir),
            "--ledger-dir",
            str(output_dir),
            "--copy-files",
            "false",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "manual_sources_ledger.jsonl").exists()
