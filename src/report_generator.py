"""
Report generator: produce HTML, JSON, and CSV outputs from analysis results.

All output files are written to the ``outputs/`` directory.  Functions return
the :class:`~pathlib.Path` of the written file(s) so callers can log them.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from src.core import Competence, MicroCredential

# ---------------------------------------------------------------------------
# Shared HTML helpers
# ---------------------------------------------------------------------------

_NAV = """
<nav>
  <a href="report_index.html">🏠 Index</a> |
  <a href="gaps_by_sector.html">📊 Gaps</a> |
  <a href="credentials_matrix.html">🎓 Credentials</a> |
  <a href="literature_integration.html">📚 Literature</a>
</nav>
"""

_CSS = """
<style>
  body { font-family: Arial, sans-serif; background: #f8f9fa; color: #212529; margin: 0; padding: 0; }
  header { background: #1a6eb5; color: white; padding: 16px 24px; }
  header h1 { margin: 0; font-size: 1.5rem; }
  nav { background: #155a93; padding: 8px 24px; }
  nav a { color: #cce4ff; text-decoration: none; margin-right: 16px; font-size: 0.9rem; }
  nav a:hover { color: white; text-decoration: underline; }
  main { padding: 24px; max-width: 1200px; margin: auto; }
  h2 { color: #1a6eb5; border-bottom: 2px solid #1a6eb5; padding-bottom: 4px; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 24px; }
  th { background: #1a6eb5; color: white; padding: 8px 12px; text-align: left; }
  td { padding: 7px 12px; border: 1px solid #dee2e6; }
  tr:nth-child(even) { background: #f0f6ff; }
  .green { background: #d4edda !important; }
  .yellow { background: #fff3cd !important; }
  .red { background: #f8d7da !important; }
  .card { background: white; border: 1px solid #dee2e6; border-radius: 6px;
    padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
  .card h3 { margin-top: 0; color: #1a6eb5; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.78rem; font-weight: bold; margin: 2px; }
  .badge-M { background: #d4edda; color: #155724; }
  .badge-T { background: #cce5ff; color: #004085; }
  .badge-O { background: #fff3cd; color: #856404; }
  footer { text-align: center; padding: 16px; color: #6c757d; font-size: 0.85rem; margin-top: 32px; }
</style>
"""


def _wrap_html(title: str, body: str) -> str:
    """Wrap *body* in a full HTML document with shared CSS and nav."""
    today = date.today().isoformat()
    return (
        f"<!DOCTYPE html>\n<html lang='en'>\n<head>\n"
        f"<meta charset='UTF-8'>\n"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
        f"<title>{title} | Blue Sociology</title>\n"
        f"{_CSS}\n</head>\n<body>\n"
        f"<header><h1>🌊 Blue Sociology Analysis — {title}</h1></header>\n"
        f"{_NAV}\n<main>\n"
        f"{body}\n"
        f"</main>\n"
        f"<footer>Generated {today} | morskamary · Blue Sociology Research</footer>\n"
        f"</body>\n</html>\n"
    )


def _axis_badge(axis_value: str) -> str:
    """Return a coloured HTML badge for a TMBD axis code."""
    labels = {"M": "Marine", "T": "Maritime", "O": "Oceanic"}
    label = labels.get(axis_value, axis_value)
    return f"<span class='badge badge-{axis_value}'>{label}</span>"


# ---------------------------------------------------------------------------
# Public report functions
# ---------------------------------------------------------------------------


def generate_html_index(
    all_competences: List[Competence],
    all_credentials: List[MicroCredential],
    gap_results: Dict[str, Dict[str, Any]],
    output_dir: Path,
) -> Path:
    """Generate the main ``report_index.html`` with summary statistics.

    Args:
        all_competences: Complete merged competence list.
        all_credentials: All generated micro-credentials.
        gap_results: Gap analysis output.
        output_dir: Directory to write into.

    Returns:
        Path to the written HTML file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- stats ---
    n_comp = len(all_competences)
    n_cred = len(all_credentials)
    n_sectors = len(gap_results)

    axis_counts: Dict[str, int] = {"M": 0, "T": 0, "O": 0}
    for c in all_competences:
        axis_counts[c.axis.value] = axis_counts.get(c.axis.value, 0) + 1

    avg_gap = sum(d.get("gap_pct", 0) for d in gap_results.values()) / max(
        1, len(gap_results)
    )

    stat_row = (
        f"<tr><td>{n_comp}</td><td>{n_cred}</td>"
        f"<td>{n_sectors}</td><td>{avg_gap:.1f}%</td></tr>"
    )

    axis_rows = "".join(
        f"<tr><td>{_axis_badge(code)}</td><td>{cnt}</td>"
        f"<td>{cnt / max(1, n_comp) * 100:.1f}%</td></tr>"
        for code, cnt in axis_counts.items()
    )

    body = f"""
<h2>Summary Statistics</h2>
<table>
  <tr><th>Total Competences</th><th>Total Credentials</th><th>Sectors</th><th>Avg Gap %</th></tr>
  {stat_row}
</table>

<h2>TMBD Axis Distribution</h2>
<table>
  <tr><th>Axis</th><th>Count</th><th>Share</th></tr>
  {axis_rows}
</table>

<h2>Quick Navigation</h2>
<ul>
  <li><a href="gaps_by_sector.html">📊 Competence Gaps by Sector</a></li>
  <li><a href="credentials_matrix.html">🎓 Micro-Credential Cards</a></li>
  <li><a href="literature_integration.html">📚 Literature Integration</a></li>
  <li><a href="competences_full_database.json">🗄️ Competences JSON DB</a></li>
  <li><a href="credentials_database.json">🗄️ Credentials JSON DB</a></li>
  <li><a href="sector_pathways.json">🗄️ Pathways JSON</a></li>
  <li><a href="gaps_summary.csv">📋 Gaps CSV</a></li>
</ul>
"""

    path = output_dir / "report_index.html"
    path.write_text(_wrap_html("Index", body), encoding="utf-8")
    return path


def generate_gaps_html(
    gap_results: Dict[str, Dict[str, Any]],
    output_dir: Path,
) -> Path:
    """Generate ``gaps_by_sector.html`` with colour-coded gap table.

    Args:
        gap_results: Gap analysis output.
        output_dir: Directory to write into.

    Returns:
        Path to the written HTML file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: List[str] = []
    for sector, data in gap_results.items():
        req = len(data.get("required", []))
        avail = len(data.get("available", []))
        miss = len(data.get("missing", []))
        pct = data.get("gap_pct", 0.0)
        css_class = "green" if pct < 20 else ("yellow" if pct < 50 else "red")

        axis_bk = data.get("axis_breakdown", {})
        axis_html = " ".join(
            f"{_axis_badge(ax[0])} {len(ids)}"
            for ax, ids in [
                ("Marine", axis_bk.get("MARINE", [])),
                ("Maritime", axis_bk.get("MARITIME", [])),
                ("Oceanic", axis_bk.get("OCEANIC", [])),
            ]
            if ids
        )

        rows.append(
            f"<tr class='{css_class}'>"
            f"<td>{sector}</td><td>{req}</td><td>{avail}</td>"
            f"<td>{miss}</td><td>{pct:.1f}%</td><td>{axis_html}</td></tr>"
        )

    body = f"""
<h2>Competence Gaps by Sector</h2>
<p>🟢 &lt;20% gap &nbsp; 🟡 20–50% gap &nbsp; 🔴 &gt;50% gap</p>
<table>
  <tr>
    <th>Sector</th><th>Required</th><th>Available</th>
    <th>Missing</th><th>Gap %</th><th>Axis Breakdown</th>
  </tr>
  {"".join(rows)}
</table>
"""

    path = output_dir / "gaps_by_sector.html"
    path.write_text(_wrap_html("Gaps by Sector", body), encoding="utf-8")
    return path


def generate_credentials_html(
    credentials_by_sector: Dict[str, List[MicroCredential]],
    output_dir: Path,
) -> Path:
    """Generate ``credentials_matrix.html`` with credential cards.

    Args:
        credentials_by_sector: Sector → list of credentials mapping.
        output_dir: Directory to write into.

    Returns:
        Path to the written HTML file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    cards: List[str] = []
    for sector, cred_list in credentials_by_sector.items():
        cards.append(f"<h2>{sector}</h2>")
        for cred in cred_list:
            prereq_html = (
                ", ".join(f"<code>{p}</code>" for p in cred.prerequisites)
                if cred.prerequisites
                else "None"
            )
            comp_count = len(cred.competences)
            cards.append(f"""<div class='card'>
  <h3>{cred.title}</h3>
  <table>
    <tr><td><strong>ID</strong></td><td><code>{cred.id}</code></td></tr>
    <tr><td><strong>Sector</strong></td><td>{cred.sector}</td></tr>
    <tr><td><strong>ECTS</strong></td><td>{cred.ects}</td></tr>
    <tr><td><strong>EQF Level</strong></td><td>{cred.eqf_level}</td></tr>
    <tr><td><strong>Competences</strong></td><td>{comp_count}</td></tr>
    <tr><td><strong>Assessment</strong></td><td>{cred.assessment_method}</td></tr>
    <tr><td><strong>Prerequisites</strong></td><td>{prereq_html}</td></tr>
    <tr><td><strong>Stackability</strong></td><td>{cred.stackability_rules}</td></tr>
    <tr><td><strong>Description</strong></td><td>{cred.description}</td></tr>
  </table>
</div>""")

    body = "<h2>Micro-Credential Matrix</h2>\n" + "\n".join(cards)
    path = output_dir / "credentials_matrix.html"
    path.write_text(_wrap_html("Credentials Matrix", body), encoding="utf-8")
    return path


def generate_literature_html(
    literature_competences: List[Competence],
    output_dir: Path,
) -> Path:
    """Generate ``literature_integration.html`` mapping papers to competences.

    Args:
        literature_competences: Competences extracted from literature.
        output_dir: Directory to write into.

    Returns:
        Path to the written HTML file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    _GITHUB_BASE = (
        "https://github.com/robertbartlomiejski/morskamary/blob/main/data/raw/"
    )

    rows: List[str] = []
    for comp in literature_competences:
        meta = comp.source_metadata or {}
        fname = meta.get("file", "")
        row_num = meta.get("row", "")
        authors = meta.get("authors", "")
        year = meta.get("year", "")

        if fname and row_num:
            link_url = f"{_GITHUB_BASE}{fname}#L{row_num}"
            paper_cell = f"<a href='{link_url}' target='_blank'>{comp.name[:60]}</a>"
        else:
            paper_cell = comp.name[:60]

        axis_html = _axis_badge(comp.axis.value)
        rows.append(
            f"<tr>"
            f"<td>{paper_cell}</td>"
            f"<td>{axis_html}</td>"
            f"<td><code>{comp.id}</code></td>"
            f"<td>{authors[:40]}</td>"
            f"<td>{year}</td>"
            f"</tr>"
        )

    body = f"""
<h2>Literature Integration ({len(literature_competences)} competences)</h2>
<table>
  <tr><th>Paper Title</th><th>Axis</th><th>Competence ID</th><th>Authors</th><th>Year</th></tr>
  {"".join(rows)}
</table>
"""

    path = output_dir / "literature_integration.html"
    path.write_text(_wrap_html("Literature Integration", body), encoding="utf-8")
    return path


def generate_json_databases(
    all_competences: List[Competence],
    all_credentials: List[MicroCredential],
    pathways: Dict[str, Any],
    output_dir: Path,
) -> List[Path]:
    """Write competences, credentials, and pathway JSON databases.

    Args:
        all_competences: Complete merged competence list.
        all_credentials: All generated micro-credentials.
        pathways: Pathway graph from credential designer.
        output_dir: Directory to write into.

    Returns:
        List of paths to the three written JSON files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []

    comp_path = output_dir / "competences_full_database.json"
    comp_path.write_text(
        json.dumps(
            [c.to_dict() for c in all_competences], ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    written.append(comp_path)

    cred_path = output_dir / "credentials_database.json"
    cred_path.write_text(
        json.dumps(
            [c.to_dict() for c in all_credentials], ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    written.append(cred_path)

    path_path = output_dir / "sector_pathways.json"
    path_path.write_text(
        json.dumps(pathways, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    written.append(path_path)

    return written


def generate_csv_exports(
    gap_results: Dict[str, Dict[str, Any]],
    output_dir: Path,
) -> Path:
    """Write ``gaps_summary.csv`` with one row per sector.

    Args:
        gap_results: Gap analysis output.
        output_dir: Directory to write into.

    Returns:
        Path to the written CSV file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "gaps_summary.csv"

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "sector",
                "required",
                "available",
                "missing",
                "gap_pct",
                "dominant_axis",
            ],
        )
        writer.writeheader()
        for sector, data in gap_results.items():
            axis_bk = data.get("axis_breakdown", {})
            # Dominant axis: the axis with the most *missing* competences, or
            # the axis with the most *required* competences when gap is 0.
            missing_counts = {ax: len(ids) for ax, ids in axis_bk.items()}
            total_missing = sum(missing_counts.values())
            if total_missing > 0:
                dominant = max(missing_counts, key=lambda k: missing_counts[k])
            else:
                # No gap → report as empty (gap analysis not axis-specific here)
                dominant = ""
            writer.writerow(
                {
                    "sector": sector,
                    "required": len(data.get("required", [])),
                    "available": len(data.get("available", [])),
                    "missing": len(data.get("missing", [])),
                    "gap_pct": data.get("gap_pct", 0.0),
                    "dominant_axis": dominant,
                }
            )

    return path


def create_outputs_readme(
    output_dir: Path,
    all_competences: List[Competence],
    all_credentials: List[MicroCredential],
) -> Path:
    """Write ``outputs/README.md`` describing all output files.

    Args:
        output_dir: Outputs directory.
        all_competences: Full competence list (for count).
        all_credentials: Full credential list (for count).

    Returns:
        Path to the written README file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    content = f"""# Blue Sociology Analysis Outputs

Generated: {today}

## Statistics
- **Competences**: {len(all_competences)} (baseline + literature)
- **Micro-credentials**: {len(all_credentials)}

## Files

| File | Description |
|------|-------------|
| `report_index.html` | Main navigation page with summary statistics |
| `gaps_by_sector.html` | Colour-coded gap analysis table for all 12 sectors |
| `credentials_matrix.html` | Full credential card matrix |
| `literature_integration.html` | Literature → competence mapping with GitHub links |
| `competences_full_database.json` | All competences in JSON (baseline + literature) |
| `credentials_database.json` | All micro-credentials in JSON |
| `sector_pathways.json` | Pathway graph (nodes + edges) |
| `gaps_summary.csv` | Gap metrics per sector in CSV |
| `execution_log.txt` | Execution log from `run_full_analysis.py` |

## Usage

Open `report_index.html` in a browser to navigate all reports.

JSON files can be imported into any visualisation tool.

The CSV can be opened in Excel/LibreOffice Calc for further analysis.
"""
    path = output_dir / "README.md"
    path.write_text(content, encoding="utf-8")
    return path
