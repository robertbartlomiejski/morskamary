#!/usr/bin/env python3
"""Build TMBD competence dictionaries directly from literature source files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "sector_dictionaries"
AXES = ("MARINE", "MARITIME", "OCEANIC")


def slugify(text: str) -> str:
    """Convert a free-text label to a stable file-safe slug."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _to_dictionary_record(competence: Any) -> Dict[str, Any]:
    """Convert a literature competence object to dictionary row."""
    return {
        "id": competence.id,
        "name": competence.name,
        "description": competence.description,
        "axis": competence.axis.name,
        "source": {
            "file": competence.source.file,
            "row": competence.source.row,
            "paper_title": competence.source.paper_title,
            "authors": competence.source.authors,
            "year": competence.source.year,
            "doi": competence.source.doi,
        },
    }


def build_axis_dictionary(
    competences: Sequence[Any],
) -> Dict[str, List[Dict[str, Any]]]:
    """Group competences by TMBD axis."""
    grouped: Dict[str, List[Dict[str, Any]]] = {axis: [] for axis in AXES}
    for competence in competences:
        grouped[competence.axis.name].append(_to_dictionary_record(competence))
    return grouped


def build_sector_dictionary(
    competences: Sequence[Any], sector: str
) -> Dict[str, List[Dict[str, Any]]]:
    """Build TMBD dictionary for one sector from literature-derived competences."""
    filtered = [
        competence for competence in competences if sector in competence.sectors
    ]
    return build_axis_dictionary(filtered)


def export_sector_dictionary(
    sector: str, grouped: Dict[str, List[Dict[str, Any]]], output_dir: Path
) -> Path:
    """Export one sector dictionary as JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{slugify(sector)}_tmbd_dictionary.json"
    payload = {
        "metadata": {
            "sector": sector,
            "source_workflow": "literature -> competences -> TMBD -> sector dictionary",
            "axes": list(AXES),
        },
        "dictionary": grouped,
    }
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return output_path


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Build TMBD sector dictionary from literature sources. "
            "This script does not consume outputs/competences_full_database.json."
        )
    )
    parser.add_argument(
        "--sector",
        default="Blue Biotech",
        help="Blue economy sector name for dictionary export.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where sector dictionary JSON will be written.",
    )
    return parser.parse_args()


def main() -> int:
    """Run sector dictionary build from literature sources."""
    args = parse_args()
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from run_full_analysis import extract_literature_competences

    competences = extract_literature_competences()
    grouped = build_sector_dictionary(competences, sector=args.sector)
    output_path = export_sector_dictionary(
        sector=args.sector, grouped=grouped, output_dir=args.output_dir
    )
    total = sum(len(rows) for rows in grouped.values())
    print(f"Sector: {args.sector}")
    print(f"Competences: {total}")
    print(f"Output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
