#!/usr/bin/env python3
"""Build Layer 4 (derived competence-demand database + statistics) and
Layer 5 (gap model, credential translation, learning outcomes) on top of
the Layer 2-3 cumulative scientific database.

CLI::

    python scripts/build_layer4_5_scientific_analysis.py \
      --database-dir outputs/cumulative_database \
      --output-dir outputs/cumulative_database \
      --stats-dir outputs/layer4_statistics \
      --current-run-id RUN-XYZ

Reads:
    <database-dir>/evidence_records.jsonl
    <database-dir>/competence_demand_signals.jsonl

Writes:
    <output-dir>/derived_competence_demands.{csv,jsonl}
    <output-dir>/sector_axis_gap_model.csv
    <output-dir>/credential_translation_eqf4_7.csv
    <output-dir>/learning_outcomes.csv
    <output-dir>/VARIABLE_LABELS.csv
    <output-dir>/VALUE_LABELS.csv
    <output-dir>/layer4_manifest.json
    <output-dir>/layer5_manifest.json
    <output-dir>/layer_readiness_report.json
    <output-dir>/_checksums_layer45.sha256
    <stats-dir>/qmbd_cross_tables.csv
    <stats-dir>/sector_gap_matrices.json
    <stats-dir>/multivariate_induction_results.json
    <stats-dir>/taxonomic_clusters.csv
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.scientific_sources.derived_competence_analysis import (  # noqa: E402
    build_layer4,
    build_layer5,
    build_layer_readiness_report,
    write_variable_and_value_labels,
)

LAYER45_CHECKSUMS_FILENAME = "_checksums_layer45.sha256"
CANONICAL_CHECKSUMS_FILENAME = "_checksums.sha256"
_CHECKSUM_LINE_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _load_static_baseline_by_sector(path: Optional[Path]) -> Dict[str, int]:
    """Load a static baseline sector→count mapping if a JSON file is provided.

    The file format is either:
        {"sector_slug": count, ...}
    or:
        {"baseline_count_by_sector": {"sector_slug": count, ...}}
    """
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict) and "baseline_count_by_sector" in data:
        data = data["baseline_count_by_sector"]
    if not isinstance(data, dict):
        return {}
    return {str(k): int(v or 0) for k, v in data.items()}


def _load_validated_supply_map(
    path: Optional[Path],
) -> Optional[Dict[str, List[int]]]:
    """Load an explicitly validated demand-level EQF supply map."""
    if path is None:
        return None
    if not path.is_file():
        raise ValueError(f"validated supply map does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("validated supply map must be a JSON object")
    if str(payload.get("validation_status", "")).lower() != "validated":
        raise ValueError(
            "validated supply map must declare validation_status='validated'"
        )
    rows = payload.get("validated_supply_by_demand_id")
    if not isinstance(rows, dict):
        raise ValueError(
            "validated supply map must contain validated_supply_by_demand_id"
        )

    validated: Dict[str, List[int]] = {}
    for demand_id, raw_entry in rows.items():
        if isinstance(raw_entry, dict):
            if str(raw_entry.get("validation_status", "")).lower() != "validated":
                raise ValueError(
                    f"supply entry {demand_id!r} is not explicitly validated"
                )
            raw_levels = raw_entry.get("eqf_levels", [])
        else:
            raw_levels = raw_entry
        if isinstance(raw_levels, (str, int)):
            raw_levels = [raw_levels]
        if not isinstance(raw_levels, list):
            raise ValueError(f"supply entry {demand_id!r} has invalid eqf_levels")
        levels = sorted(
            {
                int(level)
                for level in raw_levels
                if str(level).strip().isdigit()
            }
        )
        if any(level < 4 or level > 7 for level in levels):
            raise ValueError(
                f"supply entry {demand_id!r} has EQF level outside 4-7 scope"
            )
        validated[str(demand_id)] = levels
    return validated


def _resolve_classifier_version(database_dir: Path) -> str:
    """Resolve authoritative classifier provenance for Layer 4-5 manifests.

    The upstream cumulative database manifest is authoritative when it exists.
    Only an absent manifest permits fallback to the module-level classifier
    constant used by isolated tests.
    """
    upstream_manifest_path = database_dir / "cumulative_database_manifest.json"
    if not upstream_manifest_path.exists():
        from src.scientific_sources.cumulative_scientific_database import (  # noqa: E402
            CLASSIFIER_VERSION as _CLASSIFIER_VERSION,
        )

        return _CLASSIFIER_VERSION

    try:
        upstream_manifest = json.loads(
            upstream_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "cumulative_database_manifest.json exists but is unreadable or malformed; "
            "refusing to stamp Layer 4-5 with guessed classifier provenance"
        ) from exc

    if not isinstance(upstream_manifest, dict):
        raise ValueError(
            "cumulative_database_manifest.json must be a JSON object when present"
        )
    if "classifier_version" not in upstream_manifest:
        raise ValueError(
            "cumulative_database_manifest.json exists but classifier_version is missing"
        )

    classifier_version = upstream_manifest.get("classifier_version")
    if not isinstance(classifier_version, str):
        raise ValueError(
            "cumulative_database_manifest.json classifier_version must be a string"
        )

    classifier_version = classifier_version.strip()
    if not classifier_version:
        raise ValueError(
            "cumulative_database_manifest.json classifier_version must be non-empty"
        )
    return classifier_version


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _normalize_emitted_files(files: List[Path]) -> List[Path]:
    normalized: List[Path] = []
    seen: set[str] = set()
    errors: List[str] = []
    for raw_path in files:
        candidate = Path(raw_path)
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not candidate.exists():
            errors.append(f"missing_emitted_artifact:{candidate}")
            continue
        if not candidate.is_file():
            errors.append(f"non_file_emitted_artifact:{candidate}")
            continue
        normalized.append(candidate)
    if errors:
        raise FileNotFoundError("; ".join(errors))
    return normalized


def _relative_checksum_path(path: Path, output_dir: Path) -> str:
    rel = os.path.relpath(path, start=output_dir).replace("\\", "/")
    if rel in {".", ""}:
        raise ValueError(f"cannot compute checksum path relative to output_dir: {path}")
    return rel


def _parse_checksum_manifest(path: Path) -> Dict[str, str]:
    entries: Dict[str, str] = {}
    if not path.is_file():
        return entries
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split("  ", 1)
        if len(parts) != 2 or not _CHECKSUM_LINE_RE.match(parts[0]):
            raise ValueError(f"malformed_checksum_line:{path.name}:L{line_no}")
        digest, relpath = parts[0].lower(), parts[1]
        if relpath in entries:
            raise ValueError(f"duplicate_checksum_entry:{path.name}:{relpath}")
        entries[relpath] = digest
    return entries


def _write_checksum_manifest(path: Path, entries: Dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for relpath in sorted(entries):
            handle.write(f"{entries[relpath]}  {relpath}\n")
    return path


def _write_layer45_checksums(files: List[Path], output_dir: Path) -> Path:
    emitted_files = _normalize_emitted_files(files)
    layer45_entries = {
        _relative_checksum_path(path, output_dir): _sha256_file(path)
        for path in emitted_files
    }
    checksum_path = _write_checksum_manifest(
        output_dir / LAYER45_CHECKSUMS_FILENAME,
        layer45_entries,
    )

    canonical_path = output_dir / CANONICAL_CHECKSUMS_FILENAME
    if canonical_path.is_file():
        canonical_entries = _parse_checksum_manifest(canonical_path)
        canonical_entries.update(layer45_entries)
        _write_checksum_manifest(canonical_path, canonical_entries)
    return checksum_path


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--database-dir",
                   default="outputs/cumulative_database",
                   help="Layer 2-3 output directory (source of evidence + signals).")
    p.add_argument("--output-dir",
                   default="outputs/cumulative_database",
                   help="Destination directory for Layer 4-5 outputs.")
    p.add_argument("--stats-dir",
                   default="outputs/layer4_statistics",
                   help="Destination directory for Layer 4 statistical files.")
    p.add_argument("--repository-root", default=".",
                   help="Repository root (for layer readiness audit).")
    p.add_argument("--outputs-root", default="outputs",
                   help="Outputs root (for layer readiness audit).")
    p.add_argument("--static-baseline-by-sector", default=None,
                   help="Optional JSON mapping of sector → static baseline count.")
    p.add_argument(
        "--validated-supply-map",
        default=None,
        help="Optional explicitly validated demand-level EQF supply JSON.",
    )
    p.add_argument(
        "--analysis-timestamp-utc",
        default=None,
        help="Fixed ISO-8601 timestamp used for deterministic recency scoring.",
    )
    p.add_argument("--current-run-id", default="")
    args = p.parse_args(argv)

    db_dir = Path(args.database_dir)
    out_dir = Path(args.output_dir)
    stats_dir = Path(args.stats_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_dir.mkdir(parents=True, exist_ok=True)

    try:
        classifier_version = _resolve_classifier_version(db_dir)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    evidence = _load_jsonl(db_dir / "evidence_records.jsonl")
    signals = _load_jsonl(db_dir / "competence_demand_signals.jsonl")

    # Layer readiness audit written first — captures the state before build.
    readiness_report_path = out_dir / "layer_readiness_report.json"
    build_layer_readiness_report(
        repository_root=args.repository_root,
        outputs_root=args.outputs_root,
        output_path=readiness_report_path,
    )

    if not evidence:
        print(
            "WARNING: no evidence records found; Layer 4-5 will emit empty files.",
            file=sys.stderr,
        )

    layer4 = build_layer4(
        evidence_records=evidence,
        competence_signals=signals,
        output_dir=out_dir,
        current_run_id=args.current_run_id,
        stats_dir=stats_dir,
        analysis_timestamp_utc=args.analysis_timestamp_utc,
        classifier_version=classifier_version,
    )

    baseline_map = _load_static_baseline_by_sector(
        Path(args.static_baseline_by_sector) if args.static_baseline_by_sector else None
    )
    validated_supply = _load_validated_supply_map(
        Path(args.validated_supply_map) if args.validated_supply_map else None
    )
    layer5 = build_layer5(
        derived_demands=layer4.derived_demands,
        evidence_records=evidence,
        hypothesis_fragments=_load_jsonl(db_dir / "hypothesis_semantic_fragments.jsonl"),
        static_baseline_count_by_sector=baseline_map,
        existing_credential_coverage=None,
        validated_credential_supply=validated_supply,
        output_dir=out_dir,
        current_run_id=args.current_run_id,
        built_at_utc=args.analysis_timestamp_utc,
        classifier_version=classifier_version,
    )

    label_paths = list(write_variable_and_value_labels(out_dir))

    try:
        checksum_path = _write_layer45_checksums(
            list(layer4.files)
            + list(layer5.files)
            + label_paths
            + [readiness_report_path],
            out_dir,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = {
        "derived_demand_count": len(layer4.derived_demands),
        "gap_row_count": len(layer5.gap_rows),
        "credential_count": len(layer5.credentials),
        "learning_outcome_count": len(layer5.learning_outcomes),
        "hypothesis_results": layer5.hypothesis_results,
        "indices": layer4.indices,
        "analysis_timestamp_utc": args.analysis_timestamp_utc or "",
        "validated_supply_map_provided": validated_supply is not None,
        "classifier_version": classifier_version,
        "layer45_checksums": str(checksum_path),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
