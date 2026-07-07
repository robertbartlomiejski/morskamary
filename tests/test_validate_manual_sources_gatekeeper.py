from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "validate_manual_sources_gatekeeper.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "validate_manual_sources_gatekeeper", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_gatekeeper_reports_and_passes_without_issues(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "outputs" / "manual_sources"
    root.mkdir(parents=True)
    files_dir = root / "files"
    files_dir.mkdir()

    payload = b"manual source body"
    stored_path = files_dir / "manual_src_aabbccdd11223344.txt"
    stored_path.write_bytes(payload)

    sha = hashlib.sha256(payload).hexdigest()
    ledger_row = {
        "source_id": "manual_src_aabbccdd11223344",
        "sha256": sha,
        "stored_path": stored_path.as_posix(),
        "title": "Manual Source",
    }
    (root / "manual_sources_ledger.jsonl").write_text(
        json.dumps(ledger_row) + "\n", encoding="utf-8"
    )
    (root / "historical_cumulative_records.jsonl").write_text(
        json.dumps({"canonical_record_id": "hist_001"}) + "\n",
        encoding="utf-8",
    )
    (root / "historical_compatibility.csv").write_text(
        "bundle_id,status\nb1,compatible\n",
        encoding="utf-8",
    )

    exit_code = module.main(
        [
            "--root",
            str(root),
            "--fail-on-issues",
            "true",
        ]
    )
    assert exit_code == 0
    assert (root / "gatekeeper_duplicate_ids.json").exists()
    assert (root / "gatekeeper_checksum_mismatches.json").exists()
    assert (root / "gatekeeper_cumulative_growth_delta.json").exists()
    assert (root / "gatekeeper_compatibility_summary.json").exists()


def test_validate_manual_sources_gatekeeper_cli_entrypoint_receives_root_flag(
    tmp_path: Path,
) -> None:
    root = tmp_path / "outputs" / "manual_sources"
    root.mkdir(parents=True)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--root",
            str(root),
            "--fail-on-issues",
            "false",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (root / "gatekeeper_compatibility_summary.json").exists()
