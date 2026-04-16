#!/usr/bin/env python3
"""
run_full_analysis.py  (deep_update_patch edition)

Full reporting pipeline for the morskamary real-data pipeline.
Loads baseline, sector, and cluster matrices then writes:

  outputs/sector_requirements.json   — machine-readable sector profiles
  outputs/report_index.html          — HTML index linking all sector reports
  outputs/sectors/<slug>.html        — one HTML report per sector (12 files)

Run from the repository root or from deep_update_patch/:
    python deep_update_patch/run_full_analysis.py
"""

from pathlib import Path
import html
import json
import sys

# Ensure deep_update_patch/ is on the path when run from repo root.
_BUNDLE_ROOT = Path(__file__).resolve().parent
if str(_BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BUNDLE_ROOT))

from load_real_competences import load_blue_competences  # noqa: E402

# This file lives inside deep_update_patch/; the repository root is one level up.
REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_CSV = (
    REPO_ROOT
    / "data"
    / "derived"
    / "Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv"
)
OUTPUTS_DIR = REPO_ROOT / "outputs"
SECTOR_DIR = OUTPUTS_DIR / "sectors"


def main() -> int:
    mapper = load_blue_competences(BASELINE_CSV)
    OUTPUTS_DIR.mkdir(exist_ok=True)
    SECTOR_DIR.mkdir(parents=True, exist_ok=True)

    summary = mapper.get_summary()
    profiles = [mapper.get_sector_profile(sector) for sector in summary["sectors"]]

    # ------------------------------------------------------------------
    # sector_requirements.json
    # ------------------------------------------------------------------
    req_path = OUTPUTS_DIR / "sector_requirements.json"
    with open(req_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"summary": summary, "profiles": profiles},
            fh,
            indent=2,
            ensure_ascii=False,
        )
    print(f"✓ Wrote {req_path.relative_to(REPO_ROOT)}")

    # ------------------------------------------------------------------
    # Per-sector HTML reports
    # ------------------------------------------------------------------
    for profile in profiles:
        slug = profile["sector"]
        label = html.escape(profile["sector_label"])
        cluster = html.escape(profile["cluster_name"] or "—")
        sector_html = (
            "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
            f"<title>{label}</title></head><body>"
            f"<h1>{label}</h1>"
            f"<p><strong>Cluster:</strong> {cluster}</p>"
            f"<p><strong>Total requirements:</strong> {profile['total_requirements']}</p>"
            f"<p><strong>Skills:</strong> {profile['requirements_by_kind']['skill']}</p>"
            f"<p><strong>Competences:</strong> {profile['requirements_by_kind']['competence']}</p>"
            "</body></html>"
        )
        sector_path = SECTOR_DIR / f"{slug}.html"
        sector_path.write_text(sector_html, encoding="utf-8")

    print(f"✓ Wrote {len(profiles)} sector reports to {SECTOR_DIR.relative_to(REPO_ROOT)}/")

    # ------------------------------------------------------------------
    # report_index.html
    # ------------------------------------------------------------------
    index_lines = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head><meta charset='utf-8'><title>morskamary report index</title></head>",
        "<body>",
        "<h1>morskamary report index</h1>",
        f"<p>competences: {summary['total_competences']}</p>",
        f"<p>sector requirements: {summary['total_sector_requirements']}</p>",
        "<ul>",
    ]
    for profile in profiles:
        slug = profile["sector"]
        label = html.escape(profile["sector_label"])
        index_lines.append(f"<li><a href='sectors/{slug}.html'>{label}</a></li>")
    index_lines.extend(["</ul>", "</body>", "</html>"])

    index_path = OUTPUTS_DIR / "report_index.html"
    index_path.write_text("\n".join(index_lines), encoding="utf-8")
    print(f"✓ Wrote {index_path.relative_to(REPO_ROOT)}")
    print()
    print("Done. Open outputs/report_index.html to browse the results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

