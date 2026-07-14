"""Tests for the Layer 2-3 novelty gate evaluator (PR-190 Task C, Gates A-E)."""

from __future__ import annotations

import importlib.util
import json
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
main = _MOD.main


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


def test_gate_a_reconciles_wos_alias_when_health_uses_long_label() -> None:
    """Gate A must canonicalise provider aliases so a healthy provider
    reported as ``Web of Science (Clarivate)`` in health, but as ``wos`` in
    contribution counts, is not falsely flagged as zero-contribution."""
    m = _base_metrics(
        provider_record_count_by_provider={"crossref": 10, "wos": 7},
    )
    r = evaluate_gates(
        metrics=m,
        provider_health={
            "crossref": {"status": "ok"},
            "Web of Science (Clarivate)": {"status": "ok"},
        },
    )
    gate_a = next(g for g in r["gates"] if g["gate_id"] == "A")
    assert gate_a["status"] == "pass"
    assert gate_a["detail"]["providers_ok_zero_records"] == []


def test_gate_a_reconciles_wos_alias_when_counts_use_long_label() -> None:
    """The inverse: contribution counts use ``Web of Science`` while health
    reports the short ``wos`` slug.  Both sides must canonicalise to the same
    slug so Gate A passes."""
    m = _base_metrics(
        provider_record_count_by_provider={"crossref": 10, "Web of Science": 4},
    )
    r = evaluate_gates(
        metrics=m,
        provider_health={"crossref": {"status": "ok"}, "wos": {"status": "ok"}},
    )
    gate_a = next(g for g in r["gates"] if g["gate_id"] == "A")
    assert gate_a["status"] == "pass"


def test_gate_a_flags_zero_wos_even_when_health_uses_alias() -> None:
    """Negative control: a healthy WoS provider that contributed zero
    records must still be flagged, regardless of the alias used in either
    the health report or the contribution counts."""
    m = _base_metrics(
        provider_record_count_by_provider={"crossref": 10, "wos": 0},
    )
    r = evaluate_gates(
        metrics=m,
        provider_health={
            "crossref": {"status": "ok"},
            "Web of Science (Clarivate)": {"status": "ok"},
        },
    )
    gate_a = next(g for g in r["gates"] if g["gate_id"] == "A")
    assert gate_a["status"] == "warn"
    assert "wos" in gate_a["detail"]["providers_ok_zero_records"]


def test_gate_a_accumulates_counts_across_alias_labels() -> None:
    """When the same canonical provider is reported under multiple raw
    labels (e.g. ``wos`` and ``Web of Science``), the counts must be summed
    for Gate A comparison so a healthy provider with any contribution
    passes."""
    m = _base_metrics(
        provider_record_count_by_provider={
            "crossref": 10,
            "wos": 3,
            "Web of Science": 2,
        },
    )
    r = evaluate_gates(
        metrics=m,
        provider_health={
            "crossref": {"status": "ok"},
            "Clarivate WoS": {"status": "ok"},
        },
    )
    gate_a = next(g for g in r["gates"] if g["gate_id"] == "A")
    assert gate_a["status"] == "pass"


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


def test_cli_gate_d_failure_exits_nonzero_without_strict(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(_base_metrics()), encoding="utf-8")
    run_root = tmp_path / "outputs"
    live_records_path = run_root / "research_sources" / "live_records.json"
    live_records_path.parent.mkdir(parents=True, exist_ok=True)
    live_records_path.write_text(
        json.dumps([{"record_origin": "static_baseline"}]),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--metrics",
            str(metrics_path),
            "--provider-health",
            str(tmp_path / "missing-provider-health.json"),
            "--current-run",
            str(run_root),
            "--output",
            str(report_path),
        ]
    )

    assert exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    gate_d = next(g for g in report["gates"] if g["gate_id"] == "D")
    assert gate_d["status"] == "fail"


def test_cli_gate_b_consecutive_zero_failure_exits_nonzero_without_strict(
    tmp_path: Path,
) -> None:
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(
        json.dumps(_base_metrics(new_unique_doi_count=0, semantic_new_signal_count=0)),
        encoding="utf-8",
    )
    previous_metrics_path = tmp_path / "previous_metrics.json"
    previous_metrics_path.write_text(
        json.dumps({"new_unique_doi_count": 0, "semantic_new_signal_count": 0}),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--metrics",
            str(metrics_path),
            "--provider-health",
            str(tmp_path / "missing-provider-health.json"),
            "--previous-metrics",
            str(previous_metrics_path),
            "--current-run",
            str(tmp_path / "outputs"),
            "--output",
            str(report_path),
        ]
    )

    assert exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    gate_b = next(g for g in report["gates"] if g["gate_id"] == "B")
    assert gate_b["status"] == "fail"
