# Cross-run evidence codebook

## Purpose

This codebook defines the publication-grade cumulative evidence database for
`morskamary`. It is designed for:

- normalized audit storage in JSONL and relational tables,
- flattened analytical views for Excel, Statistica, PS IMAGO/SPSS, Python, and R,
- later versioned dataset-package publication outside this Draft Code PR.

This Draft Code PR ships the **mechanism** only: schemas, codebook, validation
logic, tests, and documentation. Large empirical artifacts remain out of scope.

## Publication boundary

- **Code PR**: code, validators, schemas, codebook, methodology docs, release
  policy, tests, and small deterministic fixtures.
- **Optional Data Release / Data PR later**: selected cumulative empirical
  exports, checksums, release notes, validation reports, and downloadable
  versioned dataset packages.

## Statistical export design

The cumulative database is designed to export as:

- `CSV` UTF-8 tables for universal tabular interchange,
- one `XLSX` workbook with one sheet per table for Excel and manual review,
- optional `SPSS/PS IMAGO .sav` files with variable labels, value labels, and
  missing-value codes where exporter dependencies are available,
- canonical `JSONL` audit records for append-only provenance review,
- checksum manifests (`.sha256`) for package verification.

The normalized tables are the canonical model. Flattened views are secondary
analysis products for statistical packages.

## Standard missing-value codes

All categorical numeric code fields reserve the following values:

| Code | Label | Meaning |
| --- | --- | --- |
| `-99` | Unknown | Expected value exists conceptually but is unknown |
| `-98` | Not extracted | Source exists but the variable was not extracted |
| `-97` | Not applicable | Variable does not apply to the row |
| `-96` | Restricted | Value exists but cannot be redistributed |
| `-95` | Validation error | Value failed validation or decoding |

## SPSS / Statistica conventions

For every categorical variable, define:

- a numeric `*_code` field,
- a string `*_label` field,
- value labels,
- missing-value codes,
- measurement level,
- allowed values.

Example:

| Variable | Measurement | Example |
| --- | --- | --- |
| `sector_code` | nominal | `1` |
| `sector_label` | nominal display label | `Blue Biotech` |
| `qmbd_axis_code` | nominal | `3` |
| `qmbd_axis_label` | nominal display label | `Oceanic` |

## Canonical normalized tables

### `runs`

One row per archived or local analytical run.

**Primary key**: `run_pk`

Core variables:

- `run_id`
- `run_path`
- `timestamp_utc`
- `analysis_input_mode_code`, `analysis_input_mode_label`
- `is_static_recovery_mode_code`, `is_static_recovery_mode_label`
- `workflow_event_code`, `workflow_event_label`
- `provider_set`
- `commit_sha`
- `github_run_id`

### `source_bundles`

One row per historical ZIP/folder or manual ingest bundle.

**Primary key**: `bundle_pk`

Core variables:

- `run_pk`
- `bundle_id`
- `bundle_type_code`, `bundle_type_label`
- `compatibility_status_code`, `compatibility_status_label`
- `source_path`
- `extracted_dir`
- `bundle_sha256`

### `artifacts`

One row per emitted file artifact tracked for release or validation.

**Primary key**: `artifact_pk`

Core variables:

- `run_pk`
- `artifact_role_code`, `artifact_role_label`
- `format_code`, `format_label`
- `relative_path`
- `sha256`
- `size_bytes`

### `providers`

One row per provider configuration or observed provider lane.

**Primary key**: `provider_pk`

Core variables:

- `provider_code`
- `provider_label`
- `provider_family_code`, `provider_family_label`
- `provider_status_code`, `provider_status_label`

### `queries`

One row per query definition or executed query variant.

**Primary key**: `query_pk`

Core variables:

- `run_pk`
- `query_id`
- `query_text`
- `query_status_code`, `query_status_label`
- `provider_code`, `provider_label`

### `evidence_records`

One row per unique evidence record regardless of how many times it appears.

**Primary key**: `record_pk`

Core variables:

- `canonical_record_id`
- `preferred_identifier`
- `source_type_code`, `source_type_label`
- `qmbd_axis_code`, `qmbd_axis_label`
- `record_origin_code`, `record_origin_label`
- `title`
- `doi`
- `source_id`

### `evidence_occurrences`

One row per appearance of an evidence record in a run, bundle, or manual ledger.

**Primary key**: `occurrence_pk`

Core variables:

- `record_pk`
- `run_pk`
- `bundle_pk`
- `dataset_code`, `dataset_label`
- `provider_code`, `provider_label`
- `occurrence_type_code`, `occurrence_type_label`
- `timestamp_utc`

### `evidence_segments`

One row per coding unit extracted from an occurrence.

**Primary key**: `segment_pk`

Core variables:

- `occurrence_pk`
- `segment_unit_code`, `segment_unit_label`
- `text_scope_code`, `text_scope_label`
- `segment_text`
- `segment_order`

### `codebook_codes`

One row per code-family member used in manual or machine coding.

**Primary key**: `code_pk`

Core variables:

- `code_family_code`, `code_family_label`
- `code_value_code`, `code_value_label`
- `code_description`

### `coding_assignments`

One row per machine or human coding decision applied to a segment.

**Primary key**: `assignment_pk`

Core variables:

- `segment_pk`
- `code_family_code`, `code_family_label`
- `code_value_code`, `code_value_label`
- `coder_type_code`, `coder_type_label`
- `validation_status_code`, `validation_status_label`
- `confidence_score`

### `reliability_metrics`

One row per reliability/validity metric observation.

**Primary key**: `reliability_pk`

Core variables:

- `run_pk`
- `code_family_code`, `code_family_label`
- `metric_code`, `metric_label`
- `sample_type_code`, `sample_type_label`
- `metric_value`
- `threshold_value`
- `status_code`, `status_label`

### `demand_supply_units`

One row per demand or supply unit used in the gap model.

**Primary key**: `unit_pk`

Core variables:

- `run_pk`
- `unit_type_code`, `unit_type_label`
- `sector_code`, `sector_label`
- `qmbd_axis_code`, `qmbd_axis_label`
- `verification_status_code`, `verification_status_label`

### `gap_clusters`

One row per sector-axis-cluster gap observation.

**Primary key**: `gap_cluster_pk`

Core variables:

- `run_pk`
- `sector_code`, `sector_label`
- `qmbd_axis_code`, `qmbd_axis_label`
- `priority_tier_code`, `priority_tier_label`
- `review_required_code`, `review_required_label`
- `gap_ratio`
- `priority_score`

### `coverage_matches`

One row per demand-to-supply or demand-to-evidence coverage match.

**Primary key**: `coverage_match_pk`

Core variables:

- `run_pk`
- `record_pk`
- `unit_pk`
- `coverage_method_code`, `coverage_method_label`
- `match_status_code`, `match_status_label`
- `similarity_score`

### `dynamic_credentials`

One row per generated or review-required dynamic credential outcome.

**Primary key**: `credential_pk`

Core variables:

- `run_pk`
- `credential_id`
- `sector_code`, `sector_label`
- `eqf_level_code`, `eqf_level_label`
- `credential_status_code`, `credential_status_label`
- `supply_origin_code`, `supply_origin_label`
- `supply_verification_status_code`, `supply_verification_status_label`
- `review_required_code`, `review_required_label`

### `manual_sources`

This logical table is materialized from the append-only manual-source ledger and
feeds cumulative cross-run occurrence counting without requiring large binary
payloads in Git.

### `historical_revalidation`

This logical table captures bundle-level recount, compatibility, and duplicate
handling outcomes produced by historical-output revalidation.

### `data_quality_indicators`

One row per quality-control metric for a run or release.

**Primary key**: `indicator_pk`

Core variables:

- `run_pk`
- `indicator_family_code`, `indicator_family_label`
- `indicator_code`, `indicator_label`
- `status_code`, `status_label`
- `indicator_value`
- `notes`

## Flattened analysis views

These are secondary analytical exports for SPSS/Statistica/Excel:

### `analysis_view_record_level.csv`

One row per unique evidence record with major categorical labels/codes and
aggregate occurrence counts.

### `analysis_view_occurrence_level.csv`

One row per evidence occurrence with run, provider, dataset, and sector/axis
context.

### `analysis_view_sector_axis_gap_level.csv`

One row per `sector x axis x gap cluster` observation for gap statistics and
priority analyses.

### `analysis_view_provider_sector_level.csv`

One row per `provider x sector x run` summary for source-diversity and provider
bias analysis.

### `analysis_view_credential_level.csv`

One row per dynamic credential output for EQF, review status, and evidence basis
analysis.

## Content-analysis coding families

Minimum code families:

- sector
- TMBD/QMBD axis
- provider/source type
- demand/supply status
- competence domain
- gap type
- coverage method
- EQF level
- evidence quality
- review status
- CARE/community sensitivity
- policy/governance relevance
- methodological limitation

## Reliability and validity controls

Required publication-oriented controls:

- human-validation sample
- machine-human comparison sample
- Cohen kappa
- Krippendorff alpha
- precision
- recall
- F1
- missingness
- duplicate rate
- provider bias
- gap-priority stability
- review-required rate

## Longitudinal interpretation note

`outputs/cumulative_qmbd_records.json` stayed at **466** in earlier static-only
runs because repeated static regeneration produced the same **15 baseline + 451
literature-derived** records. The cumulative-ledger design changes the unit of
analysis from a replaced latest snapshot to comparable observations across
manual, historical, live, and future workflow evidence.
