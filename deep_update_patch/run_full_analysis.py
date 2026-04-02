#!/usr/bin/env python3
"""
Simplified saved copy of the deep update reporting pipeline.
This in-repo copy documents the saved patch entrypoint and expected outputs.
"""

from pathlib import Path
import json

from load_real_competences import load_blue_competences

REPO_ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = REPO_ROOT / "outputs"
SECTOR_DIR = OUTPUTS_DIR / "sectors"


def main() -> int:
    mapper = load_blue_competences(REPO_ROOT)
    OUTPUTS_DIR.mkdir(exist_ok=True)
    SECTOR_DIR.mkdir(parents=True, exist_ok=True)

    summary = mapper.get_summary()
    profiles = [mapper.get_sector_profile(sector) for sector in summary["sectors"]]

    with open(OUTPUTS_DIR / "sector_requirements.json", "w", encoding="utf-8") as fh:
        json.dump({
            "summary": summary,
            "profiles": profiles,
        }, fh, indent=2, ensure_ascii=False)

    index_lines = [
        "<html><body>",
        "<h1>deep update patch report index</h1>",
        f"<p>competences={summary['total_competences']}</p>",
        f"<p>sector_requirements={summary['total_sector_requirements']}</p>",
        "<ul>",
    ]
    for profile in profiles:
        slug = profile["sector"]
        label = profile["sector_label"]
        index_lines.append(f"<li><a href='sectors/{slug}.html'>{label}</a></li>")
        with open(SECTOR_DIR / f"{slug}.html", "w", encoding="utf-8") as fh:
            fh.write(
                "<html><body>"
                f"<h1>{label}</h1>"
                f"<p>cluster={profile['cluster_name']}</p>"
                f"<p>total={profile['total_requirements']}</p>"
                f"<p>skills={profile['requirements_by_kind']['skill']}</p>"
                f"<p>competences={profile['requirements_by_kind']['competence']}</p>"
                "</body></html>"
            )
    index_lines.extend(["</ul>", "</body></html>"])
    with open(OUTPUTS_DIR / "report_index.html", "w", encoding="utf-8") as fh:
        fh.write("\n".join(index_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
