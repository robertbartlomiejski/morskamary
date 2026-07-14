#!/usr/bin/env python3
"""Build reports while preserving executable H1-H3 hypothesis serialization.

The original report implementation is retained in
``_build_statistical_research_report_base.py``.  This entrypoint adds the
required H3 Omniocean Axis Translation section to the statistical HTML/PDF
and methodological audit without recomputing any scientific result.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_CORE_PATH = Path(__file__).with_name("_build_statistical_research_report_base.py")
_SPEC = importlib.util.spec_from_file_location(
    "morskamary_statistical_report_base",
    _CORE_PATH,
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import guard
    raise RuntimeError(f"Unable to load report implementation: {_CORE_PATH}")
_CORE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CORE)

REPORT_TITLE = _CORE.REPORT_TITLE
DEMAND_STRENGTH_FORMULA = _CORE.DEMAND_STRENGTH_FORMULA
REQUIRED_VALIDITY_THREATS = _CORE.REQUIRED_VALIDITY_THREATS
maybe_build_pdf = _CORE.maybe_build_pdf


def __getattr__(name: str) -> Any:
    """Delegate unchanged helper attributes to the retained implementation."""
    return getattr(_CORE, name)


def _load_h3(database_dir: Path) -> Dict[str, Any]:
    manifest_path = database_dir / "layer5_manifest.json"
    if not manifest_path.is_file():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    hypotheses = payload.get("hypothesis_results", {})
    if not isinstance(hypotheses, dict):
        return {}
    h3 = hypotheses.get("H3", {})
    return h3 if isinstance(h3, dict) else {}


def _h3_html(database_dir: Path, *, heading_level: int = 3) -> str:
    heading = (
        "H3 — Omniocean Axis Translation "
        "(MARINE vs OCEANIC Differential Coverage)"
    )
    return (
        f"<h{heading_level}>{_CORE._e(heading)}</h{heading_level}>"
        + _CORE._fmt_hypothesis(_load_h3(database_dir))
    )


def _inject_h3_into_statistical_report(path: Path, database_dir: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "<h3>H3 —" in text:
        return
    marker = "<p><em>Note: unsupported hypotheses are scientific results"
    h3 = _h3_html(database_dir)
    if marker in text:
        text = text.replace(marker, h3 + marker, 1)
    else:  # defensive fallback for future report-layout changes
        text = text.replace("</body></html>", h3 + "</body></html>", 1)
    path.write_text(text, encoding="utf-8")


def _inject_h3_into_methodological_audit(path: Path, database_dir: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "H3 — Omniocean Axis Translation" in text:
        return
    section = (
        "<h2>Executable hypothesis result</h2>"
        + _h3_html(database_dir)
    )
    text = text.replace("</body></html>", section + "</body></html>", 1)
    path.write_text(text, encoding="utf-8")


def build_html_report(
    *,
    database_dir: Path,
    reports_dir: Path,
    generated_at: str,
) -> Path:
    path = _CORE.build_html_report(
        database_dir=database_dir,
        reports_dir=reports_dir,
        generated_at=generated_at,
    )
    _inject_h3_into_statistical_report(path, database_dir)
    return path


def build_methodological_audit(
    *,
    database_dir: Path,
    reports_dir: Path,
    generated_at: str,
) -> Path:
    path = _CORE.build_methodological_audit(
        database_dir=database_dir,
        reports_dir=reports_dir,
        generated_at=generated_at,
    )
    _inject_h3_into_methodological_audit(path, database_dir)
    return path


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-dir", default="outputs/cumulative_database")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument(
        "--formats",
        default="html,pdf",
        help="Comma-separated: html, pdf.",
    )
    args = parser.parse_args(argv)

    database_dir = Path(args.database_dir)
    reports_dir = Path(args.output_dir)
    formats = {
        item.strip().lower()
        for item in args.formats.split(",")
        if item.strip()
    }
    generated_at = _CORE.datetime.now(_CORE.timezone.utc).replace(
        microsecond=0
    ).isoformat()

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

    print(json.dumps({
        "html_report": str(html_path),
        "methodological_audit": str(audit_path),
        **pdf_status,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
