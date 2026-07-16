from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from src.scientific_sources.live_query_protocol import load_live_query_protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "export_live_query_protocol_projection.py"
PROTOCOL_PATH = REPO_ROOT / "config" / "live_query_protocol.yml"


def test_projection_script_generates_legacy_query_groups(tmp_path: Path) -> None:
    output_path = tmp_path / "research_queries_from_protocol.yml"
    summary_path = tmp_path / "summary.json"
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--protocol-path",
        str(PROTOCOL_PATH),
        "--output-path",
        str(output_path),
        "--emit-summary-path",
        str(summary_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert "query_groups" in payload

    protocol = load_live_query_protocol(PROTOCOL_PATH)
    projected = []
    for group in payload["query_groups"].values():
        projected.extend(group["queries"])
    assert projected == protocol.flattened_query_texts()


def test_projection_script_fails_when_minimum_query_count_not_met(tmp_path: Path) -> None:
    output_path = tmp_path / "research_queries_from_protocol.yml"
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--protocol-path",
        str(PROTOCOL_PATH),
        "--output-path",
        str(output_path),
        "--min-total-queries",
        "999",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "below required minimum" in result.stderr
