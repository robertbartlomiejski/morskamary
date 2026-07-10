"""Tests for the Layer 2-3 novelty gate evaluator (PR-190 Task C, Gates A-E)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "compute_live_novelty_metrics",
    str(REPO_ROOT / "scripts" / "compute_live_novelty_metrics.py"),
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
evaluate_gates = _MOD.evaluate_gates


def _base_metrics(**overrides: Any) -> Dict[str, Any]:
    base = {
        "current_run_id": "RUN-2",
        "previous_run_id": "RUN-1",
        "new_unique_doi_count": 5,
        "semantic_new_signal_count": 3,
        "jaccard_similarity_with_previous_run": 0.5,
        "provider_record_count_by_provider": {"crossref": 10, "scopus": 4},
        "crossref_dominance_ratio": 0.7,
        "query_families_seen": ["ports", "energy"],
        "query_diversity_score": 0.8,
        "validity_warnings": [],
    }
    base.update(overrides)
    return base


def test_gate_a_pass_when_all_providers_return_records() -> None:
    r = evaluate_gates(
        metrics=_base_metrics(),
        provider_health={"crossref": {"status": "ok"}, "scopus": {"status": "ok"}},
    )
    gate_a = next(g for g in r["gates"] if g["gate_id"] == "A")
    assert gate_a["status"] == "pass"


def test_gate_a_warn_when_ok_provider_returns_zero() -> None:
    m = _base_metrics(provider_record_count_by_provider={"crossref": 10, "scopus": 0})
    r = evaluate_gates(
        metrics=m,
        provider_health={"crossref": {"status": "ok"}, "scopus": {"status": "ok"}},
    )
    gate_a = next(g for g in r["gates"] if g["gate_id"] == "A")
    assert gate_a["status"] == "warn"
    assert "scopus" in gate_a["detail"]["providers_ok_zero_records"]


def test_gate_a_fails_in_strict_mode() -> None:
    m = _base_metrics(provider_record_count_by_provider={"crossref": 10, "scopus": 0})
    r = evaluate_gates(
        metrics=m,
        provider_health={"scopus": {"status": "ok"}},
        strict=True,
    )
    assert r["overall_status"] == "fail"


def test_gate_b_warn_on_zero_novelty() -> None:
    m = _base_metrics(new_unique_doi_count=0, semantic_new_signal_count=0)
    r = evaluate_gates(metrics=m)
    b = next(g for g in r["gates"] if g["gate_id"] == "B")
    assert b["status"] == "warn"


def test_gate_b_fail_after_two_consecutive_zero_runs() -> None:
    m = _base_metrics(new_unique_doi_count=0, semantic_new_signal_count=0)
    prev = {"new_unique_doi_count": 0, "semantic_new_signal_count": 0}
    r = evaluate_gates(metrics=m, previous_metrics=prev)
    b = next(g for g in r["gates"] if g["gate_id"] == "B")
    assert b["status"] == "fail"
    assert r["overall_status"] == "fail"


def test_gate_c_jaccard_thresholds() -> None:
    # 0.92 -> warn
    r = evaluate_gates(
        metrics=_base_metrics(jaccard_similarity_with_previous_run=0.92)
    )
    c = next(g for g in r["gates"] if g["gate_id"] == "C")
    assert c["status"] == "warn"
    # 0.99 + zero semantic -> warn (fail only strict)
    r_strict = evaluate_gates(
        metrics=_base_metrics(
            jaccard_similarity_with_previous_run=0.99,
            semantic_new_signal_count=0,
        ),
        strict=True,
    )
    c2 = next(g for g in r_strict["gates"] if g["gate_id"] == "C")
    assert c2["status"] == "fail"


def test_gate_d_static_baseline_leak_fails() -> None:
    r = evaluate_gates(
        metrics=_base_metrics(),
        static_baseline_field_in_live=True,
    )
    d = next(g for g in r["gates"] if g["gate_id"] == "D")
    assert d["status"] == "fail"
    assert r["overall_status"] == "fail"


def test_gate_e_warns_on_single_provider() -> None:
    m = _base_metrics(
        provider_record_count_by_provider={"crossref": 20, "scopus": 0},
        crossref_dominance_ratio=1.0,
    )
    r = evaluate_gates(metrics=m)
    e = next(g for g in r["gates"] if g["gate_id"] == "E")
    assert e["status"] == "warn"
