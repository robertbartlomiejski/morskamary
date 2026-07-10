#!/usr/bin/env python3
"""Build the cumulative statistical research report + methodological audit.

Emits (deterministic):

    reports/morskamary_statistical_report.html
    reports/morskamary_statistical_report.pdf   (skipped fallback text if
                                                  weasyprint / reportlab not
                                                  installed)
    reports/morskamary_methodological_audit.html

Report title:

    "Live-Enriched Literature-Based Blue Economy Competence Demand,
     Sectoral Gaps, and EQF 4-7 Credential Translation: A Cumulative
     Evidence Report"

All content is generated strictly from files under ``--database-dir``.
No new inference happens here — this builder only formats, aggregates,
and interprets pre-computed Layer 2-5 outputs.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _e(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


def _section(title: str, body: str, anchor: str) -> str:
    return f'<section id="{_e(anchor)}"><h2>{_e(title)}</h2>{body}</section>'


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    thead = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body_rows = []
    for r in rows:
        body_rows.append("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>")
    return (
        '<table class="grid">'
        f"<thead><tr>{thead}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


def _kv_list(pairs: Sequence[Any]) -> str:
    items = []
    for k, v in pairs:
        items.append(f"<li><strong>{_e(k)}</strong>: {_e(v)}</li>")
    return f"<ul class='kv'>{''.join(items)}</ul>"


def _fmt_hypothesis(h: Dict[str, Any]) -> str:
    if not h:
        return "<p>Not computable — inputs missing.</p>"
    pairs = [(k, v) for k, v in sorted(h.items())]
    return _kv_list(pairs)


def build_html_report(
    *,
    database_dir: Path,
    reports_dir: Path,
    generated_at: str,
) -> Path:
    ev = _load_csv(database_dir / "evidence_records.csv")
    sig = _load_csv(database_dir / "competence_demand_signals.csv")
    demands = _load_csv(database_dir / "derived_competence_demands.csv")
    gap = _load_csv(database_dir / "sector_axis_gap_model.csv")
    creds = _load_csv(database_dir / "credential_translation_eqf4_7.csv")
    outcomes = _load_csv(database_dir / "learning_outcomes.csv")
    novelty = _load_json(database_dir / "run_novelty_metrics.json") or {}
    l4_manifest = _load_json(database_dir / "layer4_manifest.json") or {}
    l5_manifest = _load_json(database_dir / "layer5_manifest.json") or {}
    readiness = _load_json(database_dir / "layer_readiness_report.json") or {}
    indices = l4_manifest.get("indices", {})
    hyp = l5_manifest.get("hypothesis_results", {})

    provenance = _kv_list([
        ("Generated at (UTC)", generated_at),
        ("Layer 4 built at", l4_manifest.get("built_at_utc", "")),
        ("Layer 5 built at", l5_manifest.get("built_at_utc", "")),
        ("Current run id", l4_manifest.get("current_run_id", "")),
        ("Demand strength formula", DEMAND_STRENGTH_FORMULA),
    ])
    s_provenance = _section("1. Data provenance", provenance, "sec-1-provenance")

    corpus_stats = _kv_list([
        ("Deduplicated evidence records", len(ev)),
        ("Layer 3 competence-demand signals", len(sig)),
        ("Growth-eligible evidence (new/updated/enriched)",
         sum(1 for r in ev if r.get("record_novelty_status") in {
             "new_record", "updated_metadata",
             "provider_enriched", "semantic_enriched"})),
        ("Duplicate-only records excluded from growth metrics",
         sum(1 for r in ev if r.get("record_novelty_status") == "duplicate_only")),
    ])
    s_corpus = _section("2. Literature corpus", corpus_stats, "sec-2-corpus")

    axis_counts: Dict[str, int] = {}
    for r in sig:
        axis_counts[r.get("axis_group", "")] = axis_counts.get(r.get("axis_group", ""), 0) + 1
    axis_rows = sorted(axis_counts.items())
    s_axis = _section(
        "3. Four-axis semantic classification (MARINE, MARITIME, OCEANIC, HYDRONIZATION)",
        _table(("axis_group", "signal_count"), axis_rows) or "<p>No signals present.</p>",
        "sec-3-axis",
    )

    demand_rows = [
        (d.get("sector"), d.get("axis_group"), d.get("competence_label"),
         d.get("demand_strength_score"), d.get("status"), d.get("eqf_relevance"))
        for d in sorted(demands, key=lambda x: (
            x.get("sector", ""), x.get("axis_group", ""), x.get("competence_label", "")
        ))[:200]
    ]
    s_demand = _section(
        "4. Competence-demand model",
        (f"<p>Total derived demands: {len(demands)}. "
         f"Formula: <code>{DEMAND_STRENGTH_FORMULA}</code>.</p>"
         + _table(
             ("sector", "axis_group", "competence_label",
              "demand_strength_score", "status", "eqf_relevance"),
             demand_rows,
         )),
        "sec-4-demand",
    )

    gap_rows = [
        (g.get("sector"), g.get("axis_group"),
         g.get("static_baseline_available_count"),
         g.get("live_literature_demand_count"),
         g.get("validated_demand_count"),
         g.get("uncovered_demand_count"),
         g.get("gap_ratio"), g.get("validity_warning"))
        for g in sorted(gap, key=lambda x: (x.get("sector", ""), x.get("axis_group", "")))
    ]
    s_gap = _section(
        "5. Gap model (static baseline vs live literature demand)",
        _table(
            ("sector", "axis_group", "static_baseline_available_count",
             "live_literature_demand_count", "validated_demand_count",
             "uncovered_demand_count", "gap_ratio", "validity_warning"),
            gap_rows,
        ) or "<p>No gap rows.</p>",
        "sec-5-gap",
    )

    cred_rows = [
        (c.get("credential_id"), c.get("sector"), c.get("axis_group"),
         c.get("eqf_level"), c.get("ects"), c.get("coverage_status"),
         c.get("confidence_score"))
        for c in sorted(creds, key=lambda x: (
            x.get("sector", ""), x.get("axis_group", ""),
            x.get("eqf_level", "")))[:200]
    ]
    s_eqf = _section(
        "6. EQF 4-7 credential translation",
        (f"<p>Credentials: {len(creds)}. Learning outcomes: {len(outcomes)}.</p>"
         + _table(
             ("credential_id", "sector", "axis_group", "eqf_level",
              "ects", "coverage_status", "confidence_score"),
             cred_rows,
         )),
        "sec-6-eqf",
    )

    index_rows = sorted(indices.items()) if isinstance(indices, dict) else []
    s_stats = _section(
        "7. Statistical analysis and measurements",
        _kv_list(index_rows) or "<p>No indices available.</p>",
        "sec-7-stats",
    )

    s_hyp = _section(
        "8. Scientific hypothesis verification",
        (
            "<h3>H1 — Maritimisation Shift</h3>"
            + _fmt_hypothesis(hyp.get("H1", {}))
            + "<h3>H2 — Hydronization Lag</h3>"
            + _fmt_hypothesis(hyp.get("H2", {}))
            + "<p><em>Note: unsupported hypotheses are scientific results and do "
              "not fail CI.</em></p>"
        ),
        "sec-8-hypotheses",
    )

    threat_items = "".join(f"<li>{_e(t)}</li>" for t in REQUIRED_VALIDITY_THREATS)
    s_valid = _section(
        "9. Validity threats",
        f"<ul>{threat_items}</ul>",
        "sec-9-validity",
    )

    repro = _kv_list([
        ("Layer readiness report", "outputs/cumulative_database/layer_readiness_report.json"),
        ("Layer 4 manifest", "outputs/cumulative_database/layer4_manifest.json"),
        ("Layer 5 manifest", "outputs/cumulative_database/layer5_manifest.json"),
        ("Novelty metrics", "outputs/cumulative_database/run_novelty_metrics.json"),
        ("Novelty gate report", "outputs/cumulative_database/novelty_gate_report.json"),
        ("Layer readiness", str(readiness.get("generated_at_utc", ""))),
    ])
    s_repro = _section("10. Reproducibility appendix", repro, "sec-10-repro")

    novelty_summary = _kv_list([
        ("Current run id", novelty.get("current_run_id", "")),
        ("Previous run id", novelty.get("previous_run_id", "")),
        ("New unique DOIs", novelty.get("new_unique_doi_count", 0)),
        ("Repeated DOIs", novelty.get("repeated_doi_count", 0)),
        ("Updated metadata", novelty.get("updated_metadata_count", 0)),
        ("Provider enriched", novelty.get("provider_enriched_count", 0)),
        ("Semantic new signals", novelty.get("semantic_new_signal_count", 0)),
        ("Jaccard vs previous run",
         novelty.get("jaccard_similarity_with_previous_run", "")),
        ("Crossref dominance ratio", novelty.get("crossref_dominance_ratio", 0.0)),
    ])
    s_novelty = _section(
        "Appendix A. Novelty snapshot",
        novelty_summary,
        "sec-appendix-novelty",
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
    nav_items = "".join(
        f'<li><a href="#{anchor}">{title}</a></li>'
        for title, anchor in [
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
        ]
    )
    body_html = (
        f"<h1>{_e(REPORT_TITLE)}</h1>"
        f"<p><em>Generated {_e(generated_at)}</em></p>"
        f"<nav><strong>Contents</strong><ol>{nav_items}</ol></nav>"
        + s_provenance + s_corpus + s_axis + s_demand + s_gap + s_eqf
        + s_stats + s_hyp + s_valid + s_repro + s_novelty
    )
    doc = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{_e(REPORT_TITLE)}</title>"
        f"<style>{style}</style></head><body>{body_html}</body></html>"
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "morskamary_statistical_report.html"
    out.write_text(doc, encoding="utf-8")
    return out


def build_methodological_audit(
    *,
    database_dir: Path,
    reports_dir: Path,
    generated_at: str,
) -> Path:
    readiness = _load_json(database_dir / "layer_readiness_report.json") or {}
    l4_manifest = _load_json(database_dir / "layer4_manifest.json") or {}
    novelty = _load_json(database_dir / "run_novelty_metrics.json") or {}
    gate_report = _load_json(database_dir / "novelty_gate_report.json") or {}

    layer_rows = [
        (layer.get("layer_name"), layer.get("schema_valid"),
         layer.get("usable_for_layer4"), layer.get("action_taken"))
        for layer in (readiness.get("layers") or [])
    ]
    gate_rows = [
        (g.get("gate_id"), g.get("name"), g.get("status"))
        for g in (gate_report.get("gates") or [])
    ]
    threats_html = "".join(f"<li>{_e(t)}</li>" for t in REQUIRED_VALIDITY_THREATS)
    style = "body{font-family:sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem}"
    doc = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>Methodological audit — {_e(REPORT_TITLE)}</title>"
        f"<style>{style}</style></head><body>"
        f"<h1>Methodological audit</h1>"
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
        + f"<ul>{threats_html}</ul>"
        + "<h2>Indices</h2>"
        + _kv_list(sorted((l4_manifest.get("indices") or {}).items()))
        + "<h2>Novelty snapshot</h2>"
        + _kv_list(sorted(novelty.items() if isinstance(novelty, dict) else []))
        + "</body></html>"
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "morskamary_methodological_audit.html"
    out.write_text(doc, encoding="utf-8")
    return out


def maybe_build_pdf(html_path: Path, pdf_path: Path) -> Dict[str, str]:
    """Try to build a PDF; fall back to a clearly-marked text stub."""
    try:
        # WeasyPrint is not a hard dependency of morskamary. If absent,
        # emit a deterministic text stub so the file exists in the release.
        from weasyprint import HTML  # type: ignore[import-not-found]
    except Exception:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_text(
            "PDF rendering skipped: 'weasyprint' is not installed in the "
            "build environment. The authoritative report is the HTML at "
            f"{html_path.name}.\n",
            encoding="utf-8",
        )
        return {"pdf_status": "skipped",
                "pdf_skip_reason": "weasyprint not installed"}
    try:
        HTML(string=html_path.read_text(encoding="utf-8")).write_pdf(str(pdf_path))
        return {"pdf_status": "generated", "pdf_skip_reason": ""}
    except Exception as exc:  # pragma: no cover
        pdf_path.write_text(
            f"PDF rendering failed: {exc}\n", encoding="utf-8",
        )
        return {"pdf_status": "skipped", "pdf_skip_reason": str(exc)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-dir", default="outputs/cumulative_database")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--formats", default="html,pdf",
                        help="Comma-separated: html, pdf.")
    args = parser.parse_args(argv)

    database_dir = Path(args.database_dir)
    reports_dir = Path(args.output_dir)
    formats = {f.strip().lower() for f in args.formats.split(",") if f.strip()}
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

    pdf_status = {"pdf_status": "skipped",
                  "pdf_skip_reason": "not requested"}
    if "pdf" in formats:
        pdf_path = reports_dir / "morskamary_statistical_report.pdf"
        pdf_status = maybe_build_pdf(html_path, pdf_path)

    summary = {
        "html_report": str(html_path),
        "methodological_audit": str(audit_path),
        **pdf_status,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
