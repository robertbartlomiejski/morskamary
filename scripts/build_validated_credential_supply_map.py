"""Build an explicitly validated H2 credential-supply map.

The input registry is an auditable external credential/programme mapping table.
Only rows with validation_status=validated are eligible for the H2 supply map;
candidate or review-required rows are preserved in the audit and never promoted.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set

REGISTRY_SCHEMA_VERSION = "1.0.0"
MAP_SCHEMA_VERSION = "1.0.0"
DEFAULT_REGISTRY_PATH = Path("data/validated/credential_supply_registry.csv")
DEFAULT_DERIVED_DEMANDS_PATH = Path(
    "outputs/cumulative_database/derived_competence_demands.csv"
)
DEFAULT_OUTPUT_PATH = Path(
    "outputs/cumulative_database/validated_credential_supply_map.json"
)
DEFAULT_AUDIT_OUTPUT_PATH = Path(
    "outputs/cumulative_database/validated_credential_supply_audit.json"
)
_REPO_ROOT_SUPPLY = Path(__file__).resolve().parents[1]

REGISTRY_FIELDS: Sequence[str] = (
    "credential_supply_id",
    "programme_title",
    "awarding_institution",
    "country",
    "programme_url",
    "source_type",
    "source_access_date",
    "eqf_level",
    "qualification_framework",
    "competence_demand_id",
    "mapping_basis",
    "mapping_evidence",
    "mapping_confidence",
    "validation_status",
    "validated_by",
    "validation_date",
    "validation_evidence_ids",
    "notes",
)

VALIDATED_REQUIRED_FIELDS: Sequence[str] = (
    "credential_supply_id",
    "programme_title",
    "awarding_institution",
    "country",
    "programme_url",
    "source_type",
    "source_access_date",
    "eqf_level",
    "qualification_framework",
    "competence_demand_id",
    "mapping_basis",
    "mapping_evidence",
    "mapping_confidence",
    "validation_status",
    "validated_by",
    "validation_date",
    "validation_evidence_ids",
)

_ALLOWED_VALIDATION_STATUSES = {
    "candidate",
    "review_required",
    "unvalidated",
    "rejected",
    "validated",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _to_repo_relative_posix(path: Path) -> str:
    """Return a repository-relative POSIX path; redact if outside the repository."""
    try:
        return path.resolve().relative_to(_REPO_ROOT_SUPPLY).as_posix()
    except ValueError:
        return "[redacted-out-of-tree-path]"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _split_pipe(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").split("|") if item.strip()]


def load_derived_demand_ids(path: Path) -> Set[str]:
    """Read valid competence_demand_id values from Layer 4 demand outputs."""
    if not path.is_file():
        raise ValueError(f"derived demands file does not exist: {path}")
    demand_ids: Set[str] = set()
    if path.suffix.lower() == ".jsonl":
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL derived demand row {line_number}: {exc}"
                ) from exc
            demand_id = _clean(row.get("competence_demand_id"))
            if demand_id:
                demand_ids.add(demand_id)
        if not demand_ids:
            raise ValueError(
                "derived demands JSONL file contains no competence_demand_id values"
            )
        return demand_ids

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("derived demands CSV is missing a header")
        if "competence_demand_id" not in reader.fieldnames:
            raise ValueError("derived demands CSV must contain competence_demand_id")
        for row in reader:
            demand_id = _clean(row.get("competence_demand_id"))
            if demand_id:
                demand_ids.add(demand_id)
    # An empty demand set is a valid scientific outcome: live acquisition
    # produced records but no legally retained semantic competence signals.
    # Downstream code emits not_computable hypotheses in this case.
    return demand_ids


def _load_registry_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"credential supply registry does not exist: {path}")
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("credential supply registry is missing a header")
        missing = [field for field in REGISTRY_FIELDS if field not in reader.fieldnames]
        if missing:
            raise ValueError(
                "credential supply registry missing required column(s): "
                f"{missing}"
            )
        return [dict(row) for row in reader]


def _parse_eqf_level(raw_level: Any, *, row_number: int) -> int:
    value = _clean(raw_level)
    if not value.isdigit():
        raise ValueError(f"registry row {row_number}: eqf_level must be an integer")
    level = int(value)
    if level < 4 or level > 7:
        raise ValueError(
            f"registry row {row_number}: eqf_level={level} is outside EQF 4-7 scope"
        )
    return level


def _validated_entry(row: Mapping[str, str], eqf_level: int) -> Dict[str, Any]:
    return {
        "credential_supply_id": _clean(row.get("credential_supply_id")),
        "programme_title": _clean(row.get("programme_title")),
        "awarding_institution": _clean(row.get("awarding_institution")),
        "country": _clean(row.get("country")),
        "programme_url": _clean(row.get("programme_url")),
        "source_type": _clean(row.get("source_type")),
        "source_access_date": _clean(row.get("source_access_date")),
        "eqf_level": eqf_level,
        "qualification_framework": _clean(row.get("qualification_framework")),
        "mapping_basis": _clean(row.get("mapping_basis")),
        "mapping_evidence": _clean(row.get("mapping_evidence")),
        "mapping_confidence": _clean(row.get("mapping_confidence")),
        "validated_by": _clean(row.get("validated_by")),
        "validation_date": _clean(row.get("validation_date")),
        "validation_evidence_ids": _clean(row.get("validation_evidence_ids")),
        "notes": _clean(row.get("notes")),
    }


def build_validated_supply_map(
    *,
    registry_path: Path,
    derived_demands_path: Path,
    output_path: Path,
    audit_output_path: Path,
    built_at_utc: str | None = None,
) -> Dict[str, Any]:
    """Validate the external registry and write the accepted H2 supply map."""
    demand_ids = load_derived_demand_ids(derived_demands_path)
    registry_rows = _load_registry_rows(registry_path)
    built_at = built_at_utc or _utc_now_iso()

    supply_by_demand: Dict[str, Dict[str, Any]] = {}
    validated_rows_by_demand: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    excluded_rows: List[Dict[str, Any]] = []

    # Empty demand set: no competence signals survived semantic filtering.
    # Registry cannot be validated against absent demands; emit not_computable.
    if not demand_ids:
        print(
            "[INFO] derived demands file contains no competence_demand_id values; "
            "writing not_computable supply map (no demands to validate against)",
            file=sys.stderr,
        )
    else:
        for index, row in enumerate(registry_rows, start=2):
            demand_id = _clean(row.get("competence_demand_id"))
            if not demand_id:
                raise ValueError(f"registry row {index}: competence_demand_id is required")
            if demand_id not in demand_ids:
                raise ValueError(
                    f"registry row {index}: unknown competence_demand_id {demand_id!r}"
                )
            eqf_level = _parse_eqf_level(row.get("eqf_level"), row_number=index)
            status = _clean(row.get("validation_status")).lower()
            if status not in _ALLOWED_VALIDATION_STATUSES:
                raise ValueError(
                    f"registry row {index}: unsupported validation_status {status!r}"
                )
            if status != "validated":
                excluded_rows.append(
                    {
                        "row_number": index,
                        "credential_supply_id": _clean(row.get("credential_supply_id")),
                        "competence_demand_id": demand_id,
                        "eqf_level": eqf_level,
                        "validation_status": status,
                        "reason": "not_explicitly_validated",
                    }
                )
                continue

            missing = [field for field in VALIDATED_REQUIRED_FIELDS if not _clean(row.get(field))]
            if missing:
                raise ValueError(
                    f"registry row {index}: validated mapping missing required field(s): "
                    f"{missing}"
                )
            if not bool(_split_pipe(row.get("validation_evidence_ids", ""))):
                raise ValueError(
                    f"registry row {index}: validated mapping must supply at least one "
                    "validation_evidence_id (field is blank or contains only separators)"
                )
            entry = _validated_entry(row, eqf_level)
            validated_rows_by_demand[demand_id].append(entry)

    if not validated_rows_by_demand:
        print(
            "[INFO] credential supply registry contains no explicitly validated mappings; "
            "writing not_computable supply map",
            file=sys.stderr,
        )

    for demand_id, rows in sorted(validated_rows_by_demand.items()):
        eqf_levels = sorted({int(row["eqf_level"]) for row in rows})
        supply_by_demand[demand_id] = {
            "validation_status": "validated",
            "eqf_levels": eqf_levels,
            "credential_supply_ids": sorted(
                {str(row["credential_supply_id"]) for row in rows}
            ),
            "programme_titles": sorted({str(row["programme_title"]) for row in rows}),
            "validation_evidence_ids": sorted(
                {
                    evidence_id
                    for row in rows
                    for evidence_id in _split_pipe(row.get("validation_evidence_ids"))
                    if evidence_id
                }
            ),
            "mapping_count": len(rows),
        }

    has_validated_supply = bool(supply_by_demand)
    output = {
        "schema_version": MAP_SCHEMA_VERSION,
        "validation_status": "validated" if has_validated_supply else "not_computable",
        "has_validated_supply": has_validated_supply,
        "unit_of_analysis": "competence_demand_id",
        "built_at_utc": built_at,
        "source_registry_path": _to_repo_relative_posix(registry_path),
        "derived_demands_path": _to_repo_relative_posix(derived_demands_path),
        "validated_supply_by_demand_id": supply_by_demand,
    }
    audit = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "built_at_utc": built_at,
        "registry_path": _to_repo_relative_posix(registry_path),
        "derived_demands_path": _to_repo_relative_posix(derived_demands_path),
        "total_registry_rows": len(registry_rows),
        "validated_mapping_rows": sum(len(rows) for rows in validated_rows_by_demand.values()),
        "validated_demand_count": len(validated_rows_by_demand),
        "excluded_row_count": len(excluded_rows),
        "excluded_rows": excluded_rows,
        "validated_rows_by_demand_id": dict(sorted(validated_rows_by_demand.items())),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    audit_output_path.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--derived-demands", default=str(DEFAULT_DERIVED_DEMANDS_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--audit-output", default=str(DEFAULT_AUDIT_OUTPUT_PATH))
    parser.add_argument("--built-at-utc", default=None)
    args = parser.parse_args(argv)

    try:
        output = build_validated_supply_map(
            registry_path=Path(args.registry),
            derived_demands_path=Path(args.derived_demands),
            output_path=Path(args.output),
            audit_output_path=Path(args.audit_output),
            built_at_utc=args.built_at_utc,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    summary = {
        "validated_demand_count": len(output["validated_supply_by_demand_id"]),
        "output": args.output,
        "audit_output": args.audit_output,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
