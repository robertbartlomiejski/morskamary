#!/usr/bin/env python3
"""Build TMBD competence dictionaries directly from literature source files."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence

from src.competence_repository import LiteratureCompetenceRepository

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


def build_sector_dictionary_from_repository(
    repository: LiteratureCompetenceRepository, sector: str
) -> Dict[str, List[Dict[str, Any]]]:
    """Build TMBD dictionary for one sector via repository data access methods."""
    return build_axis_dictionary(list(repository.iter_competences_for_sector(sector)))


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


def load_literature_competence_extractor() -> Any:
    """Load extraction function from run_full_analysis.py with explicit checks."""
    module_path = REPO_ROOT / "run_full_analysis.py"
    spec = importlib.util.spec_from_file_location("run_full_analysis", module_path)
    if spec is None or spec.loader is None:
        exists = module_path.exists()
        raise ImportError(
            f"Cannot load module spec from {module_path} (exists={exists}). "
            "Verify run_full_analysis.py is present in the repository root."
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    extract_fn = getattr(module, "extract_literature_competences", None)
    if not callable(extract_fn):
        found_type = type(extract_fn).__name__
        raise ImportError(
            "run_full_analysis.py must define a callable function named "
            "extract_literature_competences(). "
            f"Found type: {found_type}."
        )
    return extract_fn


def main() -> int:
    """Run sector dictionary build from literature sources."""
    args = parse_args()
    extract_literature_competences = load_literature_competence_extractor()
    repository = LiteratureCompetenceRepository(extract_literature_competences)
    grouped = build_sector_dictionary_from_repository(repository, sector=args.sector)
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
