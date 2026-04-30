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

from src.scientific_sources.models import LiteratureRecord, SourceEvidence
from src.scientific_sources.source_registry import SourceRegistry


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
    deduped: List[LiteratureRecord] = []
    stats = {"doi_duplicates": 0, "title_duplicates": 0}

    for rec in records:
        # DOI dedup (if DOI is present)
        if rec.doi:
            doi_key = rec.doi.strip().lower()
            if doi_key in seen_dois:
                stats["doi_duplicates"] += 1
                continue
            seen_dois.add(doi_key)
            seen_titles.add(normalize_title(rec.title))
            deduped.append(rec)
        else:
            # Title dedup (if no DOI)
            norm_title = normalize_title(rec.title)
            if norm_title in seen_titles:
                stats["title_duplicates"] += 1
                continue
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


def export_records_json(records: List[LiteratureRecord], output_path: Path) -> None:
    """Export records as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [rec.to_dict() for rec in records]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported {len(records)} records to {output_path}")


def export_records_csv(records: List[LiteratureRecord], output_path: Path) -> None:
    """Export records as CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        # Write empty CSV with headers
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "title",
                    "authors",
                    "year",
                    "doi",
                    "source_id",
                    "provider",
                    "journal",
                    "url",
                    "source_query",
                    "retrieval_timestamp",
                ],
            )
            writer.writeheader()
        print(f"Exported 0 records to {output_path}")
        return

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "title",
                "authors",
                "year",
                "doi",
                "source_id",
                "provider",
                "journal",
                "url",
                "source_query",
                "retrieval_timestamp",
            ],
        )
        writer.writeheader()
        for rec in records:
            writer.writerow(
                {
                    "title": rec.title,
                    "authors": rec.authors,
                    "year": rec.year,
                    "doi": rec.doi,
                    "source_id": rec.source_id,
                    "provider": rec.provider,
                    "journal": rec.journal,
                    "url": rec.url,
                    "source_query": rec.source_query,
                    "retrieval_timestamp": rec.retrieval_timestamp,
                }
            )
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

    # Parse providers
    provider_list = [p.strip() for p in args.providers.split(",") if p.strip()]

    # Parse offline mode
    offline = args.offline.lower() in ("true", "1", "yes")

    # Load query file
    query_file_path = Path(args.query_file)
    if not query_file_path.exists():
        print(f"Error: Query file not found: {query_file_path}", file=sys.stderr)
        return 1

    with open(query_file_path, "r", encoding="utf-8") as f:
        query_config = yaml.safe_load(f)

    query_groups = query_config.get("query_groups", {})
    if not query_groups:
        print("Error: No query_groups found in query file", file=sys.stderr)
        return 1

    # Initialize registry
    registry = SourceRegistry()

    # Provider names in the same order SourceRegistry.search() uses.
    registry_provider_order = [cap.name for cap in registry.list_capabilities()]
    if provider_list:
        queried_providers = [
            name for name in registry_provider_order if name in provider_list
        ]
        if not queried_providers:
            queried_providers = list(provider_list)
    else:
        queried_providers = registry_provider_order

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
            f"Fetching records for {len(query_groups)} sectors with providers: {provider_list}"
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
                        queried_providers[i]
                        if i < len(queried_providers)
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
