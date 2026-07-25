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

Runs are comparable only when their fingerprint matches on protocol version, query-ID hash, classifier version, provider profile, sampling mode, logical pages, rows per page, time-window contract, and sort-strategy contract.

Default provisional saturation thresholds are:

- new unique DOI growth below 5%;
- new semantic-signal growth below 5%;
- maximum sector-axis share delta below 0.05;
- absolute H1 Cohen d delta below 0.10;
- H3 balance delta below 0.05 with stable bridge status;
- all of the above for two consecutive comparable transitions.

The output status is one of:

- `insufficient_comparable_runs`;
- `continue_sampling`;
- `provisional_saturation`.

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
