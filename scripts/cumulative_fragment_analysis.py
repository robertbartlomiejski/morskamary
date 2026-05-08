#!/usr/bin/env python3
"""
Cumulative fragment-level semantic analysis (derived, append-only).

This script enforces fragment-level provenance for downstream TMBD analysis:
- `LiteratureRecord` objects are raw bibliographic metadata and do not carry an axis.
- Axis assignment happens downstream on extracted text fragments/sentences.
- Each fragment is deduplicated via a stable hash so it is counted only once across runs.

Outputs (derived):
- `data/derived/cumulative_semantic_analysis.json` (stateful cumulative store)
- `data/derived/cumulative_semantic_analysis_fragments.csv` (flattened view)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.axis_classifier import AxisClassifier  # noqa: E402

DERIVED_DIR = REPO_ROOT / "data" / "derived"
DEFAULT_STATE_PATH = DERIVED_DIR / "cumulative_semantic_analysis.json"
DEFAULT_CSV_PATH = DERIVED_DIR / "cumulative_semantic_analysis_fragments.csv"

SCHEMA_VERSION = 1
EMERGENT_DOMAINS = ("ECONOMY", "TECHNOLOGY", "POLITICS", "CULTURE")


@dataclass(frozen=True)
class FragmentInput:
    """Normalized input for a single text fragment."""

    doi: str
    text: str


def utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compute_fragment_id(doi: str, exact_sentence_string: str) -> str:
    """
    Compute a stable fragment provenance hash.

    The ID is defined as `sha256(f"{doi}|||{text}")` where:
    - `doi` is stripped; missing DOI is replaced with `[CITATION_REQUIRED]`
    - `text` is stripped and lowercased to prevent formatting-only duplicates
    """
    safe_doi = doi.strip() if doi and doi.strip() else "[CITATION_REQUIRED]"
    safe_text = exact_sentence_string.strip().lower()
    combined = f"{safe_doi}|||{safe_text}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _as_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def normalize_fragment_record(record: Mapping[str, Any]) -> Optional[FragmentInput]:
    """Normalize a raw record into a FragmentInput; return None when unusable."""
    doi = ""
    for key in ("doi", "DOI", "source_doi"):
        if key in record:
            doi = _as_str(record.get(key, ""))
            break

    text = ""
    for key in ("text", "sentence", "fragment", "original_fragment"):
        if key in record:
            text = _as_str(record.get(key, ""))
            break

    text = text.strip()
    if not text:
        return None

    return FragmentInput(doi=doi.strip(), text=text)


def load_fragments(input_path: Path) -> List[FragmentInput]:
    """Load fragments from JSON/JSONL/CSV into normalized FragmentInput objects."""
    if not input_path.exists():
        raise FileNotFoundError(str(input_path))

    suffix = input_path.suffix.lower()
    fragments: List[FragmentInput] = []

    if suffix == ".jsonl":
        with input_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                if isinstance(raw, dict):
                    normalized = normalize_fragment_record(raw)
                    if normalized:
                        fragments.append(normalized)
        return fragments

    if suffix == ".csv":
        with input_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                normalized = normalize_fragment_record(row)
                if normalized:
                    fragments.append(normalized)
        return fragments

    if suffix == ".json":
        with input_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                normalized = normalize_fragment_record(item)
                if normalized:
                    fragments.append(normalized)
            return fragments

        raise ValueError(
            "JSON input must be a list of objects with `doi` and `text`/`sentence`."
        )

    raise ValueError("Unsupported input format; use .json, .jsonl, or .csv")


def load_state(path: Path) -> Dict[str, Any]:
    """Load cumulative state, returning a valid empty state if missing/corrupt."""
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": utc_now_iso(),
            "fragments": {},
            "runs": [],
        }

    with path.open("r", encoding="utf-8") as f:
        try:
            loaded = json.load(f)
        except json.JSONDecodeError:
            loaded = {}

    fragments = loaded.get("fragments", {})
    runs = loaded.get("runs", [])
    if not isinstance(fragments, dict):
        fragments = {}
    if not isinstance(runs, list):
        runs = []

    return {
        "schema_version": int(
            loaded.get("schema_version", SCHEMA_VERSION) or SCHEMA_VERSION
        ),
        "generated_at": utc_now_iso(),
        "fragments": fragments,
        "runs": runs,
    }


def qmbd_label_from_text(text: str) -> str:
    """
    Variant 1 label for cumulative tracking.

    The repository's canonical axis model is TMBD (Marine/Maritime/Oceanic) via
    `src.axis_classifier.AxisClassifier`. This function preserves that output and
    adds two non-canonical labels used only for fragment-level provenance tracking:
    `HYDRONIZATION` and `UNCLASSIFIED`.
    """
    normalized = text.lower()
    if any(
        term in normalized
        for term in ("hydrosocial", "wet ontology", "estuary", "river")
    ):
        return "HYDRONIZATION"
    if not normalized.strip():
        return "UNCLASSIFIED"
    return AxisClassifier().classify_axis(text).name


def emergent_discovery(text: str) -> Dict[str, Any]:
    """Variant 2 (open discovery) contextual signals without forcing an axis."""
    normalized = text.lower()

    domains: List[str] = []
    if any(
        kw in normalized
        for kw in ("market", "investment", "trade", "finance", "business")
    ):
        domains.append("ECONOMY")
    if any(
        kw in normalized
        for kw in ("ai", "robotics", "sensor", "data space", "infrastructure")
    ):
        domains.append("TECHNOLOGY")
    if any(
        kw in normalized
        for kw in ("policy", "regulation", "msp", "treaty", "governance")
    ):
        domains.append("POLITICS")
    if any(
        kw in normalized
        for kw in ("heritage", "identity", "literacy", "culture", "coastal")
    ):
        domains.append("CULTURE")

    gap_terms = [
        kw for kw in ("gap", "lack", "barrier", "challenge", "need") if kw in normalized
    ]
    skill_terms = [
        kw
        for kw in (
            "skill",
            "competence",
            "capacity",
            "training",
            "education",
            "literacy",
            "knowledge",
        )
        if kw in normalized
    ]

    return {
        "emerged_domains": [d for d in EMERGENT_DOMAINS if d in domains],
        "skill_terms": skill_terms,
        "gap_terms": gap_terms,
        "raw_text": text,
    }


def update_state(
    state: MutableMapping[str, Any],
    fragments: Iterable[FragmentInput],
    *,
    input_path: Path,
) -> Dict[str, int]:
    """Merge new fragments into the cumulative state without double-counting."""
    store: Dict[str, Any] = state.setdefault("fragments", {})
    if not isinstance(store, dict):
        store = {}
        state["fragments"] = store

    classifier = AxisClassifier()
    added = 0
    skipped = 0

    for fragment in fragments:
        fragment_id = compute_fragment_id(fragment.doi, fragment.text)
        if fragment_id in store:
            skipped += 1
            continue

        strict_axis = classifier.classify_axis(fragment.text)
        store[fragment_id] = {
            "fragment_id": fragment_id,
            "doi": fragment.doi.strip() or "[CITATION_REQUIRED]",
            "text": fragment.text,
            "added_at": utc_now_iso(),
            "variant_1": {
                "tmbd_axis": strict_axis.name,
                "tmbd_code": strict_axis.value,
                "qmbd_label": qmbd_label_from_text(fragment.text),
            },
            "variant_2": emergent_discovery(fragment.text),
        }
        added += 1

    if input_path.is_absolute():
        try:
            input_display = input_path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            input_display = input_path.as_posix()
    else:
        input_display = input_path.as_posix()

    run_record = {
        "ran_at": utc_now_iso(),
        "input": input_display,
        "added": added,
        "skipped_duplicates": skipped,
    }
    runs = state.setdefault("runs", [])
    if isinstance(runs, list):
        runs.append(run_record)

    state["generated_at"] = utc_now_iso()
    return {"added": added, "skipped": skipped}


def compute_frequencies(state: Mapping[str, Any]) -> Dict[str, Dict[str, int]]:
    """Compute simple frequencies across all stored fragments."""
    fragments = state.get("fragments", {})
    if not isinstance(fragments, dict):
        return {"variant_1_tmbd": {}, "variant_1_qmbd": {}, "variant_2_domains": {}}

    tmbd: Dict[str, int] = {}
    qmbd: Dict[str, int] = {}
    domains: Dict[str, int] = {}

    for item in fragments.values():
        if not isinstance(item, dict):
            continue
        v1 = item.get("variant_1", {})
        if isinstance(v1, dict):
            axis = _as_str(v1.get("tmbd_axis", "")).strip()
            if axis:
                tmbd[axis] = tmbd.get(axis, 0) + 1
            label = _as_str(v1.get("qmbd_label", "")).strip()
            if label:
                qmbd[label] = qmbd.get(label, 0) + 1
        v2 = item.get("variant_2", {})
        if isinstance(v2, dict):
            for domain in v2.get("emerged_domains", []) or []:
                d = _as_str(domain).strip()
                if d:
                    domains[d] = domains.get(d, 0) + 1

    return {
        "variant_1_tmbd": tmbd,
        "variant_1_qmbd": qmbd,
        "variant_2_domains": domains,
    }


def write_state(state: Mapping[str, Any], path: Path) -> None:
    """Write state JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, sort_keys=True)


def write_fragments_csv(state: Mapping[str, Any], path: Path) -> None:
    """Write a flattened fragments CSV."""
    fragments = state.get("fragments", {})
    if not isinstance(fragments, dict):
        fragments = {}

    rows: List[Dict[str, str]] = []
    for fragment_id, record in fragments.items():
        if not isinstance(record, dict):
            continue
        v1 = (
            record.get("variant_1", {})
            if isinstance(record.get("variant_1"), dict)
            else {}
        )
        v2 = (
            record.get("variant_2", {})
            if isinstance(record.get("variant_2"), dict)
            else {}
        )
        rows.append(
            {
                "fragment_id": _as_str(fragment_id),
                "doi": _as_str(record.get("doi", "")),
                "text": _as_str(record.get("text", "")),
                "added_at": _as_str(record.get("added_at", "")),
                "tmbd_axis": _as_str(v1.get("tmbd_axis", "")),
                "tmbd_code": _as_str(v1.get("tmbd_code", "")),
                "qmbd_label": _as_str(v1.get("qmbd_label", "")),
                "emerged_domains": ",".join(
                    [_as_str(d) for d in (v2.get("emerged_domains") or [])]
                ),
                "skill_terms": ",".join(
                    [_as_str(d) for d in (v2.get("skill_terms") or [])]
                ),
                "gap_terms": ",".join(
                    [_as_str(d) for d in (v2.get("gap_terms") or [])]
                ),
            }
        )

    rows.sort(key=lambda r: (r["doi"], r["fragment_id"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "fragment_id",
                "doi",
                "text",
                "added_at",
                "tmbd_axis",
                "tmbd_code",
                "qmbd_label",
                "emerged_domains",
                "skill_terms",
                "gap_terms",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cumulative fragment-level semantic analysis (append-only derived state)."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to fragments (.json list, .jsonl, or .csv with doi/text fields).",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="Path to cumulative JSON state (default: data/derived/cumulative_semantic_analysis.json).",
    )
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help="Path to flattened fragments CSV.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    state_path: Path = args.state_path
    csv_path: Path = args.csv_path
    input_path: Path = args.input

    fragments = load_fragments(input_path)
    state = load_state(state_path)
    stats = update_state(state, fragments, input_path=input_path)

    state["frequencies"] = compute_frequencies(state)
    write_state(state, state_path)
    write_fragments_csv(state, csv_path)

    print(
        "Cumulative update complete:",
        f"added={stats['added']},",
        f"skipped_duplicates={stats['skipped']},",
        f"total_fragments={len(state.get('fragments', {}))}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
