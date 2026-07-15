#!/usr/bin/env python3
"""Build the cumulative statistical report and methodological audit.

All report content is formatted from pre-computed Layer 2-5 outputs.  The
reporting layer does not recompute scientific results.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.scientific_sources.live_query_protocol import (
    LiveQueryProtocolError,
    load_live_query_protocol,
)

REPORT_TITLE = (
    "Live-Enriched Literature-Based Blue Economy Competence Demand, "
    "Sectoral Gaps, and EQF 4-7 Credential Translation: "
    "A Cumulative Evidence Report"
)

DEMAND_STRENGTH_FORMULA = (
    "demand_strength_score = "
    "0.30*normalized_unique_doi_count "
    "+ 0.20*provider_diversity_score "
    "+ 0.20*temporal_recency_score "
    "+ 0.15*query_diversity_score "
    "+ 0.15*semantic_confidence_mean"
)

REQUIRED_VALIDITY_THREATS: List[str] = [
    "Crossref dominance",
    "Scopus zero-contribution despite API health",
    "WoS invalid credentials or no records",
    "SciVal entitlement or scope limitations",
    "Static baseline contamination",
    "Query design bias",
    "English-language bias",
    "Metadata-only limitation",
    "Absence of abstracts",
    "Citation-count availability bias",
    "Duplicate-run inflation",
    "Deterministic top-50 retrieval bias",
    "Small-cell statistical instability",
    "Non-computable advanced statistics",
]

# Declared hypothesis IDs that must each appear in Layer 5 output.
# A missing entry is a structural pipeline defect, not a scientific result.
DECLARED_HYPOTHESIS_IDS = ("H1", "H2", "H3")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _section(title: str, body: str, anchor: str) -> str:
    return f'<section id="{_e(anchor)}"><h2>{_e(title)}</h2>{body}</section>'


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    heading = "".join(f"<th>{_e(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return (
        '<table class="grid">'
        f"<thead><tr>{heading}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _kv_list(pairs: Sequence[Sequence[Any]]) -> str:
    items = "".join(
        f"<li><strong>{_e(pair[0])}</strong>: {_e(pair[1])}</li>"
        for pair in pairs
    )
    return f"<ul class='kv'>{items}</ul>"


def _fmt_hypothesis(result: Dict[str, Any]) -> str:
    if not result:
        return "<p>Not computable — inputs missing.</p>"
    return _kv_list([[key, value] for key, value in sorted(result.items())])


def _load_hypothesis_contract(
    protocol_path: Optional[Path] = None,
) -> Dict[str, Sequence[str]]:
    path = protocol_path or Path("config/live_query_protocol.yml")
    if not path.is_file():
        return {hypothesis_id: () for hypothesis_id in DECLARED_HYPOTHESIS_IDS}
    try:
        protocol = load_live_query_protocol(path)
    except (LiveQueryProtocolError, FileNotFoundError):
        return {hypothesis_id: () for hypothesis_id in DECLARED_HYPOTHESIS_IDS}
    contract: Dict[str, Sequence[str]] = {}
    for hypothesis_id, declaration in sorted(protocol.hypotheses.items()):
        contract[hypothesis_id] = tuple(declaration.required_result_fields)
    return contract


def _validate_hypothesis_results(
    hypotheses: Mapping[str, Any],
    *,
    protocol_path: Optional[Path] = None,
) -> None:
    contract = _load_hypothesis_contract(protocol_path)
    declared_hypotheses = tuple(contract.keys()) or DECLARED_HYPOTHESIS_IDS
    missing_hypotheses = [
        hid for hid in declared_hypotheses if hid not in hypotheses
    ]
    if missing_hypotheses:
        raise ValueError(
            f"Declared hypothesis outputs missing from Layer 5: "
            f"{', '.join(missing_hypotheses)}. "
            "This is a structural pipeline defect, not a scientific result."
        )
    missing_fields: List[str] = []
    for hypothesis_id in declared_hypotheses:
        required_fields = tuple(contract.get(hypothesis_id, ()))
        payload = hypotheses.get(hypothesis_id, {})
        if not isinstance(payload, dict):
            missing_fields.append(f"{hypothesis_id}:not_an_object")
            continue
        for field_name in required_fields:
            if field_name not in payload:
                missing_fields.append(f"{hypothesis_id}:{field_name}")
    if missing_fields:
        raise ValueError(
            "Declared hypothesis result fields missing from Layer 5: "
            + ", ".join(missing_fields)
        )


def _assert_current_run_consistency(
    *,
    expected_run_id: str,
    novelty: Any,
    layer4: Any,
    layer5: Any,
) -> None:
    """Fail when report inputs do not all belong to the same current run."""
    if not expected_run_id:
        return
    mismatches: List[str] = []
    sources = {
        "run_novelty_metrics.json": novelty,
        "layer4_manifest.json": layer4,
        "layer5_manifest.json": layer5,
    }
    for name, payload in sources.items():
        if not isinstance(payload, dict):
            mismatches.append(f"{name}:missing_or_invalid")
            continue
        run_id = str(payload.get("current_run_id", "")).strip()
        if not run_id:
            mismatches.append(f"{name}:missing_current_run_id")
        elif run_id != expected_run_id:
            mismatches.append(f"{name}:{run_id}")
    if mismatches:
        raise ValueError(
            "current-run-only report assembly failed: expected "
            f"{expected_run_id}; mismatches={mismatches}"
        )


def build_html_report(
    *,
    database_dir: Path,
    reports_dir: Path,
    generated_at: str,
) -> Path:
    evidence = _load_csv(database_dir / "evidence_records.csv")
    signals = _load_csv(database_dir / "competence_demand_signals.csv")
    demands = _load_csv(database_dir / "derived_competence_demands.csv")
    gaps = _load_csv(database_dir / "sector_axis_gap_model.csv")
    credentials = _load_csv(database_dir / "credential_translation_eqf4_7.csv")
    outcomes = _load_csv(database_dir / "learning_outcomes.csv")
    novelty = _load_json(database_dir / "run_novelty_metrics.json") or {}
    layer4 = _load_json(database_dir / "layer4_manifest.json") or {}
    layer5 = _load_json(database_dir / "layer5_manifest.json") or {}
    readiness = _load_json(database_dir / "layer_readiness_report.json") or {}
    indices = layer4.get("indices", {}) if isinstance(layer4, dict) else {}
    hypotheses = (
        layer5.get("hypothesis_results", {})
        if isinstance(layer5, dict)
        else {}
    )
    if not isinstance(hypotheses, dict):
        hypotheses = {}
    _validate_hypothesis_results(hypotheses)

    # Validate declared hypothesis set and required result fields.
    _validate_hypothesis_results(hypotheses)

    provenance = _kv_list([
        ["Generated at (UTC)", generated_at],
        ["Layer 4 built at", layer4.get("built_at_utc", "")],
        ["Layer 5 built at", layer5.get("built_at_utc", "")],
        ["Current run id", layer4.get("current_run_id", "")],
        ["Demand strength formula", DEMAND_STRENGTH_FORMULA],
    ])
    section_provenance = _section(
        "1. Data provenance", provenance, "sec-1-provenance"
    )

    growth_statuses = {
        "new_record",
        "updated_metadata",
        "provider_enriched",
        "semantic_enriched",
    }
    corpus = _kv_list([
        ["Deduplicated evidence records", len(evidence)],
        ["Layer 3 competence-demand signals", len(signals)],
        [
            "Growth-eligible evidence (new/updated/enriched)",
            sum(
                1
                for row in evidence
                if row.get("record_novelty_status") in growth_statuses
            ),
        ],
        [
            "Duplicate-only records excluded from growth metrics",
            sum(
                1
                for row in evidence
                if row.get("record_novelty_status") == "duplicate_only"
            ),
        ],
    ])
    section_corpus = _section("2. Literature corpus", corpus, "sec-2-corpus")

    axis_counts: Dict[str, int] = {}
    for signal in signals:
        axis = signal.get("axis_group", "")
        axis_counts[axis] = axis_counts.get(axis, 0) + 1
    section_axis = _section(
        "3. Four-axis semantic classification "
        "(MARINE, MARITIME, OCEANIC, HYDRONIZATION)",
        _table(("axis_group", "signal_count"), sorted(axis_counts.items())),
        "sec-3-axis",
    )

    demand_rows = [
        (
            row.get("sector"),
            row.get("axis_group"),
            row.get("competence_label"),
            row.get("demand_strength_score"),
            row.get("status"),
            row.get("eqf_relevance"),
        )
        for row in sorted(
            demands,
            key=lambda item: (
                item.get("sector", ""),
                item.get("axis_group", ""),
                item.get("competence_label", ""),
            ),
        )[:200]
    ]
    section_demands = _section(
        "4. Competence-demand model",
        (
            f"<p>Total derived demands: {len(demands)}. "
            f"Formula: <code>{_e(DEMAND_STRENGTH_FORMULA)}</code>.</p>"
            + _table(
                (
                    "sector",
                    "axis_group",
                    "competence_label",
                    "demand_strength_score",
                    "status",
                    "eqf_relevance",
                ),
                demand_rows,
            )
        ),
        "sec-4-demand",
    )

    gap_rows = [
        (
            row.get("sector"),
            row.get("axis_group"),
            row.get("static_baseline_available_count"),
            row.get("live_literature_demand_count"),
            row.get("validated_demand_count"),
            row.get("uncovered_demand_count"),
            row.get("gap_ratio"),
            row.get("validity_warning"),
        )
        for row in sorted(
            gaps,
            key=lambda item: (
                item.get("sector", ""),
                item.get("axis_group", ""),
            ),
        )
    ]
    section_gaps = _section(
        "5. Gap model (static baseline vs live literature demand)",
        _table(
            (
                "sector",
                "axis_group",
                "static_baseline_available_count",
                "live_literature_demand_count",
                "validated_demand_count",
                "uncovered_demand_count",
                "gap_ratio",
                "validity_warning",
            ),
            gap_rows,
        ),
        "sec-5-gap",
    )

    credential_rows = [
        (
            row.get("credential_id"),
            row.get("sector"),
            row.get("axis_group"),
            row.get("eqf_level"),
            row.get("ects"),
            row.get("coverage_status"),
            row.get("confidence_score"),
        )
        for row in sorted(
            credentials,
            key=lambda item: (
                item.get("sector", ""),
                item.get("axis_group", ""),
                item.get("eqf_level", ""),
            ),
        )[:200]
    ]
    section_credentials = _section(
        "6. EQF 4-7 credential translation",
        (
            f"<p>Credentials: {len(credentials)}. "
            f"Learning outcomes: {len(outcomes)}.</p>"
            + _table(
                (
                    "credential_id",
                    "sector",
                    "axis_group",
                    "eqf_level",
                    "ects",
                    "coverage_status",
                    "confidence_score",
                ),
                credential_rows,
            )
        ),
        "sec-6-eqf",
    )

    index_rows = (
        [[key, value] for key, value in sorted(indices.items())]
        if isinstance(indices, dict)
        else []
    )
    section_statistics = _section(
        "7. Statistical analysis and measurements",
        _kv_list(index_rows) if index_rows else "<p>No indices available.</p>",
        "sec-7-stats",
    )

    section_hypotheses = _section(
        "8. Scientific hypothesis verification",
        (
            "<h3>H1 — Maritimisation Shift</h3>"
            + _fmt_hypothesis(hypotheses.get("H1", {}))
            + "<h3>H2 — Hydronization Lag</h3>"
            + _fmt_hypothesis(hypotheses.get("H2", {}))
            + "<h3>H3 — Omniocean Axis Translation "
            "(MARINE vs OCEANIC Differential Coverage)</h3>"
            + _fmt_hypothesis(hypotheses.get("H3", {}))
            + "<p><em>Note: unsupported hypotheses are scientific results and "
            "do not fail CI.</em></p>"
        ),
        "sec-8-hypotheses",
    )

    threats = "".join(
        f"<li>{_e(threat)}</li>" for threat in REQUIRED_VALIDITY_THREATS
    )
    section_validity = _section(
        "9. Validity threats", f"<ul>{threats}</ul>", "sec-9-validity"
    )

    section_reproducibility = _section(
        "10. Reproducibility appendix",
        _kv_list([
            [
                "Layer readiness report",
                "outputs/cumulative_database/layer_readiness_report.json",
            ],
            ["Layer 4 manifest", "outputs/cumulative_database/layer4_manifest.json"],
            ["Layer 5 manifest", "outputs/cumulative_database/layer5_manifest.json"],
            [
                "Novelty metrics",
                "outputs/cumulative_database/run_novelty_metrics.json",
            ],
            [
                "Novelty gate report",
                "outputs/cumulative_database/novelty_gate_report.json",
            ],
            [
                "Layer readiness",
                readiness.get("generated_at_utc", "")
                if isinstance(readiness, dict)
                else "",
            ],
        ]),
        "sec-10-repro",
    )

    novelty_rows = [
        ["Current run id", novelty.get("current_run_id", "")],
        ["Previous run id", novelty.get("previous_run_id", "")],
        ["New unique DOIs", novelty.get("new_unique_doi_count", 0)],
        ["Repeated DOIs", novelty.get("repeated_doi_count", 0)],
        ["Updated metadata", novelty.get("updated_metadata_count", 0)],
        ["Provider enriched", novelty.get("provider_enriched_count", 0)],
        ["Semantic new signals", novelty.get("semantic_new_signal_count", 0)],
        [
            "Jaccard vs previous run",
            novelty.get("jaccard_similarity_with_previous_run", ""),
        ],
        ["Crossref dominance ratio", novelty.get("crossref_dominance_ratio", 0.0)],
    ]
    section_novelty = _section(
        "Appendix A. Novelty snapshot",
        _kv_list(novelty_rows),
        "sec-appendix-novelty",
    )

    navigation = "".join(
        f'<li><a href="#{anchor}">{_e(title)}</a></li>'
        for title, anchor in (
            ("Data provenance", "sec-1-provenance"),
            ("Literature corpus", "sec-2-corpus"),
            ("Four-axis semantic classification", "sec-3-axis"),
            ("Competence-demand model", "sec-4-demand"),
            ("Gap model", "sec-5-gap"),
            ("EQF 4-7 credential translation", "sec-6-eqf"),
            ("Statistical analysis and measurements", "sec-7-stats"),
            ("Scientific hypothesis verification", "sec-8-hypotheses"),
            ("Validity threats", "sec-9-validity"),
            ("Reproducibility appendix", "sec-10-repro"),
            ("Novelty snapshot", "sec-appendix-novelty"),
        )
    )
    style = """
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         max-width:1100px;margin:2rem auto;padding:0 1.5rem;color:#1f2328;line-height:1.55}
    h1{border-bottom:2px solid #d0d7de;padding-bottom:.4rem}
    h2{margin-top:2rem;border-bottom:1px solid #eaeef2;padding-bottom:.3rem}
    table.grid{border-collapse:collapse;width:100%;margin:.75rem 0;font-size:.92rem}
    table.grid th,table.grid td{border:1px solid #d0d7de;padding:.35rem .55rem;text-align:left}
    table.grid th{background:#f6f8fa}
    ul.kv li{margin:.15rem 0}
    code{background:#f6f8fa;padding:.1rem .3rem;border-radius:.25rem}
    nav{background:#f6f8fa;border:1px solid #d0d7de;padding:.75rem 1rem;border-radius:.35rem}
    nav ol{margin:0;padding-left:1.4rem}
    """
    body = (
        f"<h1>{_e(REPORT_TITLE)}</h1>"
        f"<p><em>Generated {_e(generated_at)}</em></p>"
        f"<nav><strong>Contents</strong><ol>{navigation}</ol></nav>"
        + section_provenance
        + section_corpus
        + section_axis
        + section_demands
        + section_gaps
        + section_credentials
        + section_statistics
        + section_hypotheses
        + section_validity
        + section_reproducibility
        + section_novelty
    )
    document = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{_e(REPORT_TITLE)}</title>"
        f"<style>{style}</style></head><body>{body}</body></html>"
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    output = reports_dir / "morskamary_statistical_report.html"
    output.write_text(document, encoding="utf-8")
    return output


def build_methodological_audit(
    *,
    database_dir: Path,
    reports_dir: Path,
    generated_at: str,
) -> Path:
    readiness = _load_json(database_dir / "layer_readiness_report.json") or {}
    layer4 = _load_json(database_dir / "layer4_manifest.json") or {}
    layer5 = _load_json(database_dir / "layer5_manifest.json") or {}
    novelty = _load_json(database_dir / "run_novelty_metrics.json") or {}
    gate_report = _load_json(database_dir / "novelty_gate_report.json") or {}
    hypotheses = (
        layer5.get("hypothesis_results", {})
        if isinstance(layer5, dict)
        else {}
    )
    if not isinstance(hypotheses, dict):
        hypotheses = {}

    layer_rows = [
        (
            row.get("layer_name"),
            row.get("schema_valid"),
            row.get("usable_for_layer4"),
            row.get("action_taken"),
        )
        for row in (
            readiness.get("layers", []) if isinstance(readiness, dict) else []
        )
    ]
    gate_rows = [
        (row.get("gate_id"), row.get("name"), row.get("status"))
        for row in (
            gate_report.get("gates", [])
            if isinstance(gate_report, dict)
            else []
        )
    ]
    threats = "".join(
        f"<li>{_e(threat)}</li>" for threat in REQUIRED_VALIDITY_THREATS
    )
    indices = layer4.get("indices", {}) if isinstance(layer4, dict) else {}
    index_rows = (
        [[key, value] for key, value in sorted(indices.items())]
        if isinstance(indices, dict)
        else []
    )
    novelty_rows = (
        [[key, value] for key, value in sorted(novelty.items())]
        if isinstance(novelty, dict)
        else []
    )
    document = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Methodological audit — {_e(REPORT_TITLE)}</title>"
        "<style>body{font-family:sans-serif;max-width:1000px;"
        "margin:2rem auto;padding:0 1rem}</style></head><body>"
        "<h1>Methodological audit</h1>"
        f"<p>Generated {_e(generated_at)}.</p>"
        "<h2>Layer readiness (Layers 0-3)</h2>"
        + _table(
            ("layer", "schema_valid", "usable_for_layer4", "action_taken"),
            layer_rows,
        )
        + "<h2>Novelty gates</h2>"
        + _table(("gate_id", "name", "status"), gate_rows)
        + "<h2>Demand-strength formula</h2>"
        + f"<pre>{_e(DEMAND_STRENGTH_FORMULA)}</pre>"
        + "<h2>Reliability rule</h2>"
        + "<p>Records with <code>record_novelty_status = duplicate_only</code> "
        "are excluded from statistical growth metrics.</p>"
        + "<h2>Validity threats considered</h2>"
        + f"<ul>{threats}</ul>"
        + "<h2>Indices</h2>"
        + (_kv_list(index_rows) if index_rows else "<p>No indices available.</p>")
        + "<h2>Executable hypothesis results</h2>"
        + "<h3>H1 — Maritimisation Shift</h3>"
        + _fmt_hypothesis(hypotheses.get("H1", {}))
        + "<h3>H2 — Hydronization Lag</h3>"
        + _fmt_hypothesis(hypotheses.get("H2", {}))
        + "<h3>H3 — Omniocean Axis Translation "
        "(MARINE vs OCEANIC Differential Coverage)</h3>"
        + _fmt_hypothesis(hypotheses.get("H3", {}))
        + "<h2>Novelty snapshot</h2>"
        + (_kv_list(novelty_rows) if novelty_rows else "<p>No novelty data.</p>")
        + "</body></html>"
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    output = reports_dir / "morskamary_methodological_audit.html"
    output.write_text(document, encoding="utf-8")
    return output


def maybe_build_pdf(html_path: Path, pdf_path: Path) -> Dict[str, str]:
    try:
        from weasyprint import HTML  # type: ignore[import-not-found]
    except Exception:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text(
            "PDF rendering skipped: 'weasyprint' is not installed in the "
            "build environment. The authoritative report is the HTML at "
            f"{html_path.name}.\n",
            encoding="utf-8",
        )
        return {
            "pdf_status": "skipped",
            "pdf_skip_reason": "weasyprint not installed",
        }
    try:
        HTML(string=html_path.read_text(encoding="utf-8")).write_pdf(
            str(pdf_path)
        )
        return {"pdf_status": "generated", "pdf_skip_reason": ""}
    except Exception as exc:  # pragma: no cover
        pdf_path.write_text(f"PDF rendering failed: {exc}\n", encoding="utf-8")
        return {"pdf_status": "skipped", "pdf_skip_reason": str(exc)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-dir", default="outputs/cumulative_database")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument(
        "--formats",
        default="html,pdf",
        help="Comma-separated: html, pdf.",
    )
    parser.add_argument(
        "--current-run-id",
        default="",
        help=(
            "Optional run id guard (e.g. <github.run_id>-<run_attempt>). "
            "When set, report assembly fails if novelty/layer manifests do not match."
        ),
    )
    args = parser.parse_args(argv)

    database_dir = Path(args.database_dir)
    reports_dir = Path(args.output_dir)
    formats = {
        item.strip().lower()
        for item in args.formats.split(",")
        if item.strip()
    }

    try:
        _assert_current_run_consistency(
            expected_run_id=str(args.current_run_id or "").strip(),
            novelty=_load_json(database_dir / "run_novelty_metrics.json"),
            layer4=_load_json(database_dir / "layer4_manifest.json"),
            layer5=_load_json(database_dir / "layer5_manifest.json"),
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    html_path = build_html_report(
        database_dir=database_dir,
        reports_dir=reports_dir,
        generated_at=generated_at,
    )
    audit_path = build_methodological_audit(
        database_dir=database_dir,
        reports_dir=reports_dir,
        generated_at=generated_at,
    )
    pdf_status = {
        "pdf_status": "skipped",
        "pdf_skip_reason": "not requested",
    }
    if "pdf" in formats:
        pdf_path = reports_dir / "morskamary_statistical_report.pdf"
        pdf_status = maybe_build_pdf(html_path, pdf_path)

    print(
        json.dumps(
            {
                "html_report": str(html_path),
                "methodological_audit": str(audit_path),
                **pdf_status,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
