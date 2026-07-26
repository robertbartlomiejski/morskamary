# Live Replication Infrastructure

This note records the executable contract for controlled live-enriched scientific replications after the OpenAlex and stability infrastructure patch.

## Scientific run contract

A run classified as scientific `live-enriched` acquisition must use the authoritative protocol in `config/live_query_protocol.yml` and its generated executable projection. The exporter now fails before provider setup when the projection is incomplete or malformed.

The pre-acquisition assertion verifies:

- exactly 120 query IDs;
- exact query-ID equality between protocol and projection;
- all 12 canonical sectors;
- exactly 10 protocol queries per sector;
- query-family counts equal the authoritative protocol;
- no missing, duplicate, dropped, or extra query IDs.

PR validation and local development should keep using offline fixtures and mocks. A failed protocol assertion performs zero provider API calls.

## Protocol pagination

The protocol-defined sampling depth is three logical pages of 50 records per query/provider. Logical pages are the scientific sampling unit. Provider physical requests may differ.

The workflow therefore defaults `max_results_per_query` to 150. Relative to the
old 50-record ceiling, operators should budget for up to three times as many
retrieval positions per query/provider. Actual requests, returned records, and
provider charges can be lower because providers paginate differently, queries
overlap, and some result sets contain fewer than 150 records. PR and CI tests
use fixtures and do not spend live provider quota.

Implemented provider behavior:

- Crossref uses cursor-based paging and records page cursor markers.
- Scopus composes each 50-row logical page from provider-compliant 25-row physical requests.
- OpenAlex uses cursor paging with deterministic date sorting where requested.

The exporter writes `provider_pagination_diagnostics.json` and extends `query_execution_log.csv` with logical-page and physical-request counts. A replayed first page cannot be reported as three pages.

## Canonical provider profile

The canonical low-cost three-provider profile is now:

`crossref,scopus,openalex`

Web of Science remains optional when credentials exist. OpenAlex improves acquisition-provider diversity but must not be described as upstream bibliographic independence from Crossref-related DOI metadata infrastructures.

The protected workflow applies `--require-configured` to the requested profile.
Selecting Scopus, Web of Science, or another credential-dependent provider
without its required configuration therefore fails before acquisition. Web of
Science is not part of the canonical profile: its Starter free trial is limited
to 50 requests per day, which cannot execute this repository's complete
120-query, three-page protocol in one controlled run.

OpenAIRE is a possible future European repository and funding-provenance
enrichment source. Its Graph API supports publication-year filtering and
structured offset/cursor paging, but morskamary has no OpenAIRE provider adapter.
It must not be included in current provider counts, sensitivity subsets, or
comparability fingerprints until an adapter and deterministic fixtures exist.

## Static baseline interpretation

`outputs/gaps_summary.csv` compares literature-derived candidate competence
units with the 15-competence University of Szczecin project baseline available
to the pipeline. It does not represent a census of qualifications, programmes,
or workforce supply across the 12 sectors.

Consequently, its `Missing` and `Gap %` fields are project-baseline coverage
diagnostics. They must not be reported as national, European, or real-world
qualification deficits. The current tracked output contains 2,548 candidate
units absent from 2,728 required units (93.4%); 1,818 of those are OCEANIC
(71.35%). Historical figures such as 16,929 missing, 13,583 OCEANIC, or
98.8-99.1% sector gaps are not the current repository result and must not be
carried into a manuscript without a run-specific archived source.

Actual educational shortage claims require the externally validated
programme-to-demand supply mapping described below. Until that evidence exists,
the defensible conclusion is baseline undercoverage and validation need, not a
measured labour-market or qualification shortage.

## H2 validated supply

H2 uses an external, demand-level credential/programme supply map. Generated candidate credential translations are not validated supply.

The registry template is:

`data/validated/credential_supply_registry.csv`

The builder is:

`scripts/build_validated_credential_supply_map.py`

The builder accepts only rows with `validation_status=validated`, checks that every `competence_demand_id` exists in current derived demands, validates EQF 4-7 scope, requires source and reviewer provenance, and writes an auditable companion JSON. Candidate-only registries fail closed and must not be passed to Layer 4-5.

Until an explicitly validated map exists, H2 remains `not_computable`.

## Provider sensitivity

`scripts/build_provider_sensitivity_analysis.py` computes provider-sensitivity diagnostics from persisted artifacts only. It performs no API acquisition.

Default subsets are:

- all canonical providers: Crossref + Scopus + OpenAlex;
- direct Crossref-excluded: Scopus + OpenAlex;
- Scopus only;
- OpenAlex only.

The Crossref-excluded subset is deliberately not named Crossref-independent because OpenAlex can contain upstream metadata from overlapping DOI infrastructures.

## Run stability and saturation

`scripts/build_run_stability_report.py` computes comparability and saturation diagnostics across run directories.

Runs are comparable only when their fingerprint matches on protocol version, provider set, classifier version, requested and contributing provider profiles, logical pages, rows per page, time-window contract, sampling-strategy contract, and sort-strategy contract.

Default provisional saturation thresholds are:

- DOI Jaccard similarity above the configured threshold (default `0.90`);
- new DOI ratio below the configured diminishing-return threshold (default `0.05`);
- axis-stability score above the configured threshold (default `0.95`);
- the same comparable transition thresholds sustained for two consecutive transitions to claim provisional saturation, and three to claim saturation.

The output status is one of:

- `not_assessable`;
- `not_saturated`;
- `provisional_saturation`.
- `saturated`.

Lack of saturation is not a pipeline failure. It is a scientific stopping diagnostic.

## Archive finalization order

The controlled workflow finalizes a run only after the demand model, externally
validated H2 supply mapping, provider-sensitivity analysis, and strict novelty
gates have succeeded. It then creates the immutable run archive and immediately
validates its manifest and checksums.

The cross-run stability report follows archive validation because it must read
the newly indexed current run together with prior archives. Stability is an
informational sampling-stopping diagnostic, not a structural validity gate. It
remains in `outputs/cumulative_database/run_stability_report.json`, while the
immutable per-run archive contains the evidence, H2 audit, and provider
sensitivity artifacts that existed at finalization.

## Controlled post-merge run

The protected live-research environment should run the full-depth profile with:

- all 120 queries;
- three logical pages;
- 50 logical rows per page;
- `crossref,scopus,openalex`;
- live mode;
- require live records;
- strict provenance;
- immutable archive;
- no automatic direct push of scientific outputs to main.
