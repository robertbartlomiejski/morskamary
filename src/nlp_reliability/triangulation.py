"""
Provider triangulation and overlap matrix for the NLP reliability module.

Computes how many records are found by multiple providers so that analysts
can identify corroborating evidence and single-source claims.

The overlap matrix is Crossref × Scopus × WoS × SciVal (and other providers
registered in the SourceRegistry).
"""

from __future__ import annotations

from typing import Dict, List

from src.scientific_sources.models import LiteratureRecord, ProviderResult


def build_provider_overlap_matrix(
    results: List[ProviderResult],
) -> Dict[str, object]:
    """
    Build a provider overlap matrix from a list of ProviderResult objects.

    Compares DOIs across providers to identify records found by multiple
    providers (corroborating evidence) vs. single-source records.

    Args:
        results: Results from multiple providers (from SourceRegistry.search).

    Returns:
        Dictionary with:
        - provider_doi_sets: DOIs found by each provider
        - overlap_pairs: pairs of providers sharing DOIs
        - multi_source_dois: DOIs found by 2+ providers
        - single_source_dois: DOIs found by exactly one provider
        - total_unique_dois: count of unique DOIs across all providers
    """
    provider_doi_sets: Dict[str, set] = {}

    for result in results:
        for rec in result.records:
            if not rec.doi:
                continue
            prov = rec.provider
            if prov not in provider_doi_sets:
                provider_doi_sets[prov] = set()
            provider_doi_sets[prov].add(rec.doi)

    all_dois: Dict[str, int] = {}
    for dois in provider_doi_sets.values():
        for doi in dois:
            all_dois[doi] = all_dois.get(doi, 0) + 1

    multi_source = [doi for doi, count in all_dois.items() if count >= 2]
    single_source = [doi for doi, count in all_dois.items() if count == 1]

    # Build pairwise overlap
    providers = list(provider_doi_sets.keys())
    overlap_pairs: Dict[str, int] = {}
    for i in range(len(providers)):
        for j in range(i + 1, len(providers)):
            pa, pb = providers[i], providers[j]
            shared = len(provider_doi_sets[pa] & provider_doi_sets[pb])
            if shared > 0:
                overlap_pairs[f"{pa} × {pb}"] = shared

    return {
        "provider_doi_sets": {
            prov: sorted(dois) for prov, dois in provider_doi_sets.items()
        },
        "overlap_pairs": overlap_pairs,
        "multi_source_dois": sorted(multi_source),
        "single_source_dois": sorted(single_source),
        "total_unique_dois": len(all_dois),
    }


def format_overlap_matrix_text(
    results: List[ProviderResult],
) -> str:
    """
    Return a human-readable text summary of the provider overlap matrix.

    Args:
        results: Results from multiple providers.

    Returns:
        Multi-line text summary suitable for console output or a report.
    """
    matrix = build_provider_overlap_matrix(results)
    lines = ["=== Provider Overlap Matrix ==="]
    lines.append(f"Total unique DOIs: {matrix['total_unique_dois']}")
    lines.append(
        f"Multi-source DOIs (corroborated): {len(matrix['multi_source_dois'])}"
    )
    lines.append(
        f"Single-source DOIs (unverified): {len(matrix['single_source_dois'])}"
    )
    if matrix["overlap_pairs"]:
        lines.append("\nPairwise overlap:")
        for pair, count in sorted(matrix["overlap_pairs"].items()):
            lines.append(f"  {pair}: {count} shared DOI(s)")
    else:
        lines.append("\nNo pairwise overlap found (single-provider retrieval).")
    return "\n".join(lines)
