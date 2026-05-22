from __future__ import annotations

from pathlib import Path

import yaml

import run_full_analysis


def test_research_queries_cover_all_canonical_sectors() -> None:
    """Live query groups must map explicitly to the 12 canonical sector labels."""
    repo_root = Path(__file__).resolve().parents[1]
    query_file = repo_root / "config" / "research_queries.yml"
    payload = yaml.safe_load(query_file.read_text(encoding="utf-8")) or {}
    query_groups = payload.get("query_groups")
    assert (
        isinstance(query_groups, dict) and query_groups
    ), "query_groups must be a mapping"

    labels = []
    for group in query_groups.values():
        assert isinstance(group, dict), "Each query group must be a mapping"
        label = group.get("label")
        assert (
            isinstance(label, str) and label.strip()
        ), "Each query group must define label"
        labels.append(label.strip())

    assert set(labels) == set(run_full_analysis.SECTORS), (
        "config/research_queries.yml labels must match run_full_analysis.SECTORS exactly "
        "(12 canonical blue economy sectors)."
    )
