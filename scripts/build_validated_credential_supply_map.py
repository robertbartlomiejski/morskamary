#!/usr/bin/env python3
"""Build a preliminary H2 credential supply registry map for HYDRONIZATION."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
DEFAULT_DEMAND_SIGNALS_PATH = (
    REPO_ROOT / "outputs" / "cumulative_database" / "competence_demand_signals.jsonl"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs"
OUTPUT_FILENAME = "h2_credential_supply_map.json"
HYPOTHESIS_ID = "H2"
HYPOTHESIS_LABEL = "Hydronization Lag"
HYDRONIZATION = "HYDRONIZATION"
ALLOWED_PRELIMINARY_STATUSES = {"validated", "review_required"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "and",
    "candidate",
    "certificate",
    "competence",
    "course",
    "credential",
    "demand",
    "diploma",
    "for",
    "graduate",
    "in",
    "learning",
    "manual",
    "master",
    "msc",
    "of",
    "operations",
    "placeholder",
    "program",
    "required",
    "review",
    "skill",
    "the",
    "to",
    "validation",
}


@dataclass(frozen=True)
class RegistryEntry:
    credential_id: str
    credential_name: str
    eqf_level: int
    issuing_body: str
    country_iso: str
    axis_coverage: tuple[str, ...]
    validation_status: str
    source_url: str
    notes: str

    @property
    def searchable_tokens(self) -> set[str]:
        return _search_tokens(
            " ".join(
                [
                    self.credential_name,
                    self.issuing_body,
                    self.notes,
                    " ".join(self.axis_coverage),
                ]
            )
        )


@dataclass(frozen=True)
class DemandSignal:
    signal_id: str
    axis_group: str
    sector: str
    competence_label: str
    competence_description: str
    demand_phrase: str
    learning_outcome_candidate: str

    @property
    def searchable_tokens(self) -> set[str]:
        return _search_tokens(
            " ".join(
                [
                    self.sector,
                    self.competence_label,
                    self.competence_description,
                    self.demand_phrase,
                    self.learning_outcome_candidate,
                ]
            )
        )


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _repo_relative_posix(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _parse_axis_coverage(raw_value: str) -> tuple[str, ...]:
    axes = [token.strip().upper() for token in str(raw_value or "").split("|")]
    return tuple(axis for axis in axes if axis)


def _search_tokens(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        for token in _TOKEN_RE.findall(str(part or "").lower()):
            if len(token) < 4:
                continue
            if token in _STOPWORDS:
                continue
            tokens.add(token)
    return tokens


def load_registry(path: Path) -> List[RegistryEntry]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: List[RegistryEntry] = []
        for row in reader:
            rows.append(
                RegistryEntry(
                    credential_id=str(row.get("credential_id", "")).strip(),
                    credential_name=str(row.get("credential_name", "")).strip(),
                    eqf_level=int(str(row.get("eqf_level", "")).strip() or 0),
                    issuing_body=str(row.get("issuing_body", "")).strip(),
                    country_iso=str(row.get("country_iso", "")).strip(),
                    axis_coverage=_parse_axis_coverage(row.get("axis_coverage", "")),
                    validation_status=str(
                        row.get("validation_status", "")
                    ).strip().lower(),
                    source_url=str(row.get("source_url", "")).strip(),
                    notes=str(row.get("notes", "")).strip(),
                )
            )
    return rows


def load_demand_signals(path: Path) -> List[DemandSignal]:
    if not path.is_file():
        return []
    signals: Dict[str, DemandSignal] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        signal = DemandSignal(
            signal_id=str(payload.get("signal_id", "")).strip(),
            axis_group=str(payload.get("axis_group", "")).strip().upper(),
            sector=str(payload.get("sector", "")).strip(),
            competence_label=str(payload.get("competence_label", "")).strip(),
            competence_description=str(
                payload.get("competence_description", "")
            ).strip(),
            demand_phrase=str(payload.get("demand_phrase", "")).strip(),
            learning_outcome_candidate=str(
                payload.get("learning_outcome_candidate", "")
            ).strip(),
        )
        if signal.signal_id:
            signals[signal.signal_id] = signal
    return list(signals.values())


def _status_distribution(entries: Iterable[RegistryEntry]) -> Dict[str, int]:
    distribution = {"review_required": 0, "validated": 0, "rejected": 0}
    for entry in entries:
        if entry.validation_status not in distribution:
            distribution[entry.validation_status] = 0
        distribution[entry.validation_status] += 1
    return distribution


def _entry_matches_demand(entry: RegistryEntry, demand: DemandSignal) -> bool:
    if demand.axis_group not in entry.axis_coverage:
        return False
    demand_tokens = demand.searchable_tokens
    if not demand_tokens:
        return True
    overlap = demand_tokens & entry.searchable_tokens
    if len(overlap) >= 2:
        return True
    demand_phrase_tokens = _search_tokens(demand.demand_phrase)
    return bool(demand_phrase_tokens & entry.searchable_tokens)


def _count_matches(
    demands: Sequence[DemandSignal], entries: Sequence[RegistryEntry]
) -> Mapping[str, List[str]]:
    matched: Dict[str, List[str]] = {}
    for demand in demands:
        credential_ids = [
            entry.credential_id
            for entry in entries
            if _entry_matches_demand(entry, demand)
        ]
        if credential_ids:
            matched[demand.signal_id] = sorted(credential_ids)
    return matched


def _interpretation_from_ratio(missing_ratio: float) -> str:
    if missing_ratio > 0.5:
        return "supported"
    if missing_ratio >= 0.25:
        return "partially_supported"
    return "not_supported"


def compute_h2_supply_map(
    *,
    registry_entries: Sequence[RegistryEntry],
    demand_signals: Sequence[DemandSignal],
    eqf_min: int = 6,
    eqf_max: int = 7,
    registry_path: Path | None = None,
    demand_signals_path: Path | None = None,
) -> Dict[str, Any]:
    hydronization_demands = [
        demand for demand in demand_signals if demand.axis_group == HYDRONIZATION
    ]
    status_distribution = _status_distribution(registry_entries)
    eqf_window_entries = [
        entry for entry in registry_entries if eqf_min <= entry.eqf_level <= eqf_max
    ]
    hydronization_eqf_entries = [
        entry for entry in eqf_window_entries if HYDRONIZATION in entry.axis_coverage
    ]
    validated_entries = [
        entry
        for entry in hydronization_eqf_entries
        if entry.validation_status == "validated"
    ]
    preliminary_entries = [
        entry
        for entry in hydronization_eqf_entries
        if entry.validation_status in ALLOWED_PRELIMINARY_STATUSES
    ]

    preliminary_matches = _count_matches(hydronization_demands, preliminary_entries)
    validated_matches = _count_matches(hydronization_demands, validated_entries)

    hydronization_demand_count = len(hydronization_demands)
    validated_covered_demand_count = len(validated_matches)
    validated_missing_demand_count = max(
        hydronization_demand_count - validated_covered_demand_count, 0
    )
    preliminary_covered_demand_count = len(preliminary_matches)
    preliminary_missing_demand_count = max(
        hydronization_demand_count - preliminary_covered_demand_count, 0
    )

    missing_ratio = (
        round(validated_missing_demand_count / hydronization_demand_count, 6)
        if hydronization_demand_count
        else None
    )
    preliminary_missing_ratio = (
        round(preliminary_missing_demand_count / hydronization_demand_count, 6)
        if hydronization_demand_count
        else None
    )

    if not validated_entries:
        interpretation = "not_computable"
        interpretation_note = (
            "All registry entries are review_required; H2 result is preliminary until "
            "human validation."
        )
    elif missing_ratio is None:
        interpretation = "not_computable"
        interpretation_note = "No HYDRONIZATION demand signals were available for H2."
    else:
        interpretation = _interpretation_from_ratio(missing_ratio)
        interpretation_note = (
            "Interpretation is computed only from explicitly validated EQF "
            f"{eqf_min}-{eqf_max} credential entries."
        )

    payload: Dict[str, Any] = {
        "hypothesis_id": HYPOTHESIS_ID,
        "hypothesis_label": HYPOTHESIS_LABEL,
        "timestamp_utc": _timestamp_utc(),
        "registry_path": _repo_relative_posix(registry_path or DEFAULT_REGISTRY_PATH),
        "demand_signals_path": _repo_relative_posix(
            demand_signals_path or DEFAULT_DEMAND_SIGNALS_PATH
        ),
        "registry_entries_total": len(registry_entries),
        "registry_entries_eqf_6_7": len(eqf_window_entries),
        "registry_entries_hydronization_eqf_6_7": len(hydronization_eqf_entries),
        "hydronization_demand_count": hydronization_demand_count,
        "validated_covered_demand_count": validated_covered_demand_count,
        "validated_missing_demand_count": validated_missing_demand_count,
        "missing_ratio": missing_ratio,
        "interpretation": interpretation,
        "interpretation_note": interpretation_note,
        "validation_status_distribution": status_distribution,
        "preliminary_covered_demand_count": preliminary_covered_demand_count,
        "preliminary_missing_demand_count": preliminary_missing_demand_count,
        "preliminary_missing_ratio": preliminary_missing_ratio,
        "validated_entries_hydronization_eqf_6_7": len(validated_entries),
        "eligible_preliminary_statuses": sorted(ALLOWED_PRELIMINARY_STATUSES),
        "mapping_method": (
            "Axis-constrained lexical overlap between HYDRONIZATION demand-signal "
            "text and candidate credential registry metadata."
        ),
    }
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry-path",
        default=str(DEFAULT_REGISTRY_PATH),
        help="Path to credential_supply_registry.csv.",
    )
    parser.add_argument(
        "--demand-signals",
        default=str(DEFAULT_DEMAND_SIGNALS_PATH),
        help="Path to competence_demand_signals.jsonl.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for h2_credential_supply_map.json.",
    )
    parser.add_argument(
        "--eqf-min",
        type=int,
        default=6,
        help="Minimum EQF level to include in coverage calculations.",
    )
    parser.add_argument(
        "--eqf-max",
        type=int,
        default=7,
        help="Maximum EQF level to include in coverage calculations.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry_path = Path(args.registry_path)
    demand_signals_path = Path(args.demand_signals)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    registry_entries = load_registry(registry_path)
    demand_signals = load_demand_signals(demand_signals_path)
    payload = compute_h2_supply_map(
        registry_entries=registry_entries,
        demand_signals=demand_signals,
        eqf_min=args.eqf_min,
        eqf_max=args.eqf_max,
        registry_path=registry_path,
        demand_signals_path=demand_signals_path,
    )

    output_path = output_dir / OUTPUT_FILENAME
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output_path": _repo_relative_posix(output_path),
                "interpretation": payload["interpretation"],
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
