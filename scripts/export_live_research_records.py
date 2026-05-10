#!/usr/bin/env python3
"""
Export live research records from configured providers.

Fetches literature metadata from Crossref and other configured providers
based on query groups defined in config/research_queries.yml.

Outputs:
  - outputs/research_sources/live_records.json (all records, all providers)
  - outputs/research_sources/live_records.csv (flattened CSV)
  - outputs/research_sources/crossref_records.json (Crossref-only records)
  - outputs/research_sources/live_provenance.json (provenance metadata)
  - outputs/research_sources/live_source_coverage.csv (coverage by sector/provider)
  - outputs/research_sources/low_confidence_live_records.json (records with confidence < 0.8)

Features:
  - Deduplicates by DOI first, then by normalized title
  - Includes full provenance tracking (provider, query, timestamp, endpoint, DOI)
  - Does not store abstracts or full text (licence compliance)
  - Supports offline mode for testing (no network calls)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources.models import (  # noqa: E402
    LiteratureRecord,
    SourceEvidence,
)
from src.scientific_sources.source_registry import SourceRegistry  # noqa: E402


def normalize_title(title: str) -> str:
    """
    Normalize a title for deduplication.

    Lowercases, removes punctuation, and collapses whitespace.
    """
    title_lower = title.lower()
    # Remove punctuation and special characters
    title_clean = re.sub(r"[^\w\s]", "", title_lower)
    # Collapse whitespace
    title_normalized = re.sub(r"\s+", " ", title_clean).strip()
    return title_normalized


def deduplicate_records(
    records: List[LiteratureRecord],
) -> Tuple[List[LiteratureRecord], Dict[str, int]]:
    """
    Deduplicate records by DOI first, then by normalized title.

    Args:
        records: List of LiteratureRecord objects.

    Returns:
        Tuple of (deduplicated_records, dedup_stats).
    """
    seen_dois: Set[str] = set()
    seen_titles: Set[str] = set()
    # Maps norm_title → index in `deduped` for records accepted without a DOI.
    # When a DOI-bearing record for the same title arrives later we upgrade the
    # slot in-place so the DOI record wins (DOI-first policy).
    nondoi_title_idx: Dict[str, int] = {}
    deduped: List[LiteratureRecord] = []
    stats = {"doi_duplicates": 0, "title_duplicates": 0}

    for rec in records:
        norm_title = normalize_title(rec.title)
        if rec.doi:
            doi_key = rec.doi.strip().lower()
            if doi_key in seen_dois:
                stats["doi_duplicates"] += 1
                continue
            # A no-DOI record with the same title was accepted earlier: upgrade
            # it with this DOI-bearing record so the DOI version wins.
            if norm_title in nondoi_title_idx:
                deduped[nondoi_title_idx.pop(norm_title)] = rec
                seen_dois.add(doi_key)
                # Count as a title duplicate: the incoming record was matched
                # by title (not DOI) against a previously accepted no-DOI slot.
                stats["title_duplicates"] += 1
                continue
            # Distinct DOIs identify distinct papers even if titles happen to
            # match, so keep the record regardless of seen_titles.
            seen_dois.add(doi_key)
            seen_titles.add(norm_title)
            deduped.append(rec)
        else:
            # No DOI: skip if an accepted record (DOI or no-DOI) shares this title.
            if norm_title in seen_titles:
                stats["title_duplicates"] += 1
                continue
            idx = len(deduped)
            nondoi_title_idx[norm_title] = idx
            seen_titles.add(norm_title)
            deduped.append(rec)

    return deduped, stats


def build_coverage_report(
    all_results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Build a coverage report showing records per sector and provider.

    Args:
        all_results: List of dicts with keys: sector, query, provider, record_count

    Returns:
        List of coverage rows with sector, provider, query, record_count
    """
    coverage: List[Dict[str, Any]] = []
    for item in all_results:
        coverage.append(
            {
                "sector": item["sector"],
                "provider": item["provider"],
                "query": item["query"],
                "record_count": item["record_count"],
            }
        )
    return coverage


def _to_stage1_compliant_dict(rec: LiteratureRecord) -> Dict[str, Any]:
    """
    Return a compliance-filtered dictionary for a single LiteratureRecord.

    Only the fields explicitly listed in docs/licensing_and_compliance.md
    ("What you are always allowed to store") are included.  Fields that may
    carry restricted content under institutional-provider licences are
    intentionally excluded here, even when they are present on the model:

    - ``citation_count`` is omitted: Web of Science and SciVal counts are
      restricted by institutional licence (docs/licensing_and_compliance.md,
      Category 2 — Institutional providers, and Category 3 — SciVal).
    - ``abstract_available`` / ``abstract_stored`` are omitted from the
      serialised output: their boolean values are internal provenance flags
      only; exporting them would imply an abstract is accessible, which could
      create a misleading impression for third parties reusing this dataset.
      (docs/licensing_and_compliance.md — "What you are never allowed to
      store": Full abstract text.)

    Fields retained and their docs/licensing_and_compliance.md basis:
    - title, authors, year, doi    → "Bibliographic fact; not copyright-protected"
    - journal                       → "Bibliographic fact"
    - url                           → "Pointer, not content"
    - subject_terms                 → "Aggregated classification, not full text"
    - provider                      → "Source provider name — Internal metadata"
    - source_id, source_query,
      retrieval_timestamp           → "Internal metadata generated by this repository"
    - licence_note                  → "Internal metadata generated by this repository"
    """
    # Stage 1 — bibliographic-metadata-only fields
    # (docs/licensing_and_compliance.md: "What you are always allowed to store")
    return {
        "title": rec.title,
        "authors": rec.authors,
        "year": rec.year,
        "doi": rec.doi,
        "source_id": rec.source_id,
        "provider": rec.provider,
        "journal": rec.journal,
        "url": rec.url,
        "subject_terms": rec.subject_terms,
        "source_query": rec.source_query,
        "retrieval_timestamp": rec.retrieval_timestamp,
        "licence_note": rec.licence_note,
    }


def _serialize_subject_terms_for_csv(subject_terms: Any) -> str:
    """Serialize subject_terms to a pipe-delimited scalar for CSV export.

    For string input we still split and re-join to normalize stray whitespace
    around delimiters, so both ``"a|b"`` and ``"a | b"`` produce ``"a|b"``.
    """
    if isinstance(subject_terms, str):
        terms = [t.strip() for t in subject_terms.split("|") if t.strip()]
        return "|".join(terms)
    if isinstance(subject_terms, list):
        return "|".join(str(t).strip() for t in subject_terms if str(t).strip())
    return ""


# Stage 1 governance: CSV columns are the bibliographic-metadata-only subset
# permitted for all providers, including institutional ones. subject_terms is
# serialized as a pipe-delimited scalar to preserve it in a flat CSV schema.
# (docs/licensing_and_compliance.md — Category 1/2/3 constraints.)
STAGE1_CSV_FIELDS: List[str] = [
    "title",
    "authors",
    "year",
    "doi",
    "source_id",
    "provider",
    "journal",
    "url",
    "subject_terms",
    "source_query",
    "retrieval_timestamp",
    "licence_note",
]


def export_records_json(records: List[LiteratureRecord], output_path: Path) -> None:
    """Export records as JSON using Stage 1 compliance filtering.

    Uses ``_to_stage1_compliant_dict`` to ensure only bibliographic metadata
    fields permitted by docs/licensing_and_compliance.md are written to disk.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Stage 1 governance: serialize only permitted bibliographic fields.
    # Full-text, abstract content, and institution-restricted analytics are
    # never written here (docs/licensing_and_compliance.md — Category 1/2/3).
    data = [_to_stage1_compliant_dict(rec) for rec in records]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported {len(records)} records to {output_path}")


def export_records_csv(records: List[LiteratureRecord], output_path: Path) -> None:
    """Export records as CSV using Stage 1 compliance filtering.

    Column set is deliberately limited to the fields in ``STAGE1_CSV_FIELDS``
    which are safe to commit and redistribute under all provider licence
    categories (docs/licensing_and_compliance.md — "What you are always
    allowed to store").

    Excluded fields (citation_count, abstract_available, abstract_stored) are
    omitted here for the same reasons documented in
    ``_to_stage1_compliant_dict``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        # Write empty CSV with headers only
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=STAGE1_CSV_FIELDS)
            writer.writeheader()
        print(f"Exported 0 records to {output_path}")
        return

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STAGE1_CSV_FIELDS)
        writer.writeheader()
        for rec in records:
            compliant = _to_stage1_compliant_dict(rec)
            row = {k: compliant[k] for k in STAGE1_CSV_FIELDS}
            row["subject_terms"] = _serialize_subject_terms_for_csv(
                compliant.get("subject_terms", [])
            )
            writer.writerow(row)
    print(f"Exported {len(records)} records to {output_path}")


def export_provenance_json(
    provenance: List[SourceEvidence], output_path: Path
) -> None:
    """Export provenance as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [p.to_dict() for p in provenance]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported {len(provenance)} provenance entries to {output_path}")


def export_coverage_csv(coverage: List[Dict[str, Any]], output_path: Path) -> None:
    """Export coverage report as CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not coverage:
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["sector", "provider", "query", "record_count"]
            )
            writer.writeheader()
        print(f"Exported 0 coverage rows to {output_path}")
        return

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["sector", "provider", "query", "record_count"]
        )
        writer.writeheader()
        for row in coverage:
            writer.writerow(row)
    print(f"Exported {len(coverage)} coverage rows to {output_path}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Export live research records from configured providers"
    )
    parser.add_argument(
        "--providers",
        default="crossref",
        help="Comma-separated list of provider names (default: crossref)",
    )
    parser.add_argument(
        "--query-file",
        default="config/research_queries.yml",
        help="Path to YAML file with query groups",
    )
    parser.add_argument(
        "--max-results-per-query",
        type=int,
        default=50,
        help="Maximum results per query (default: 50)",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/research_sources",
        help="Output directory for exported files",
    )
    parser.add_argument(
        "--offline",
        default="false",
        help="Offline mode: skip network calls (default: false)",
    )

    args = parser.parse_args()

    # Parse providers — normalize to lowercase and drop empty tokens so that
    # case variants like "Crossref" match the registry's canonical names and
    # an accidental empty string (e.g. --providers "") produces a clear error.
    provider_list = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    if not provider_list:
        print(
            "Error: --providers must not be empty. "
            "Specify one or more provider names (e.g. crossref).",
            file=sys.stderr,
        )
        return 1

    # Parse offline mode
    offline = args.offline.lower() in ("true", "1", "yes")

    # Load query file
    query_file_path = Path(args.query_file)
    if not query_file_path.exists():
        print(f"Error: Query file not found: {query_file_path}", file=sys.stderr)
        return 1

    with open(query_file_path, "r", encoding="utf-8") as f:
        query_config = yaml.safe_load(f)

    if not isinstance(query_config, dict):
        print(
            f"Error: Query file is empty or not a valid YAML mapping: {query_file_path}",
            file=sys.stderr,
        )
        return 1

    query_groups = query_config.get("query_groups", {})
    if not query_groups:
        print("Error: No query_groups found in query file", file=sys.stderr)
        return 1

    # Initialize registry
    registry = SourceRegistry()

    # Validate that every requested provider name is known to the registry.
    known_names: Set[str] = {cap.name for cap in registry.list_capabilities()}
    unknown = [p for p in provider_list if p not in known_names]
    if unknown:
        print(
            f"Error: Unknown provider(s): {unknown}. "
            f"Valid names are: {sorted(known_names)}",
            file=sys.stderr,
        )
        return 1

    # Derive the ordered list of provider names as the registry will return them.
    # registry.search() filters _providers by name membership in provider_list but
    # preserves the registry's internal order — NOT the order of provider_list itself.
    ordered_provider_names: List[str] = [
        cap.name
        for cap in registry.list_capabilities()
        if cap.name in provider_list
    ]

    # Storage for all results
    all_records: List[LiteratureRecord] = []
    all_provenance: List[SourceEvidence] = []
    all_coverage_items: List[Dict[str, Any]] = []

    # Offline mode: skip all queries
    if offline:
        print("Offline mode enabled. Skipping all network calls.")
    else:
        # Execute queries
        print(
            f"Fetching records for {len(query_groups)} sectors with providers: {ordered_provider_names}"
        )
        for sector_key, sector_data in query_groups.items():
            sector_label = sector_data.get("label", sector_key)
            queries = sector_data.get("queries", [])
            print(f"\nSector: {sector_label} ({len(queries)} queries)")

            for query in queries:
                print(f"  Query: {query}")
                results = registry.search(
                    query, max_results=args.max_results_per_query, providers=provider_list
                )

                for i, result in enumerate(results):
                    provider_name = (
                        ordered_provider_names[i]
                        if i < len(ordered_provider_names)
                        else (
                            result.records[0].provider
                            if result.records
                            else (
                                result.provenance[0].source_provider
                                if result.provenance
                                else "unknown"
                            )
                        )
                    )
                    if result.errors:
                        print(f"    Errors: {result.errors}", file=sys.stderr)
                    if result.warnings:
                        print(f"    Warnings: {result.warnings}")

                    all_coverage_items.append(
                        {
                            "sector": sector_label,
                            "provider": provider_name,
                            "query": query,
                            "record_count": len(result.records),
                        }
                    )

                    all_records.extend(result.records)
                    all_provenance.extend(result.provenance)

                    print(f"    Fetched {len(result.records)} records")

    # Deduplicate
    print(f"\nDeduplicating {len(all_records)} records...")
    deduped_records, dedup_stats = deduplicate_records(all_records)
    print(
        f"Deduplicated: {len(deduped_records)} unique records "
        f"(removed {dedup_stats['doi_duplicates']} DOI duplicates, "
        f"{dedup_stats['title_duplicates']} title duplicates)"
    )

    # Filter by provider for provider-specific exports
    crossref_records = [r for r in deduped_records if r.provider == "Crossref"]

    # Filter low-confidence records
    low_confidence_record_ids: Set[str] = {
        p.record_id for p in all_provenance if p.confidence_score < 0.8
    }
    low_confidence_records = [
        r for r in deduped_records if r.source_id in low_confidence_record_ids
    ]

    # Build coverage report
    coverage = build_coverage_report(all_coverage_items)

    # Export outputs
    output_dir = Path(args.output_dir)
    print(f"\nExporting to {output_dir}/...")

    export_records_json(deduped_records, output_dir / "live_records.json")
    export_records_csv(deduped_records, output_dir / "live_records.csv")
    export_records_json(crossref_records, output_dir / "crossref_records.json")
    export_provenance_json(all_provenance, output_dir / "live_provenance.json")
    export_coverage_csv(coverage, output_dir / "live_source_coverage.csv")
    export_records_json(
        low_confidence_records, output_dir / "low_confidence_live_records.json"
    )

    print("\nExport complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
