# Cross-run evidence codebook

## Purpose

This codebook defines the cumulative evidence entities emitted by the dynamic-mode,
manual-ledger, and historical-revalidation workflow surfaces. It is the mechanism
document for the Draft Code PR; large artifact publication remains a separate,
policy-governed Data PR decision under `DATA_GOVERNANCE.txt`.

## Publication boundary

- **Code PR**: code, schemas, docs, tests, small fixtures, and governance updates.
- **Optional Data PR**: selected `outputs/manual_sources/*`,
  `outputs/run_archive/cross_run_evidence_*`, checksums, reports, and release notes
  only after storage, retention, and licensing decisions are made.

## Entity definitions

### `runs`

Run-level observations from archived methodological executions.

| Variable | Type | Meaning | Source artifact |
| --- | --- | --- | --- |
| `run_id` | string | Stable run archive identifier | `outputs/run_archive/cumulative_runs_index.csv` |
| `run_path` | string | Relative archive path | `outputs/run_archive/cumulative_runs_index.csv` |
| `timestamp_utc` | string | Archive index timestamp for the run row | `outputs/run_archive/cumulative_runs_index.csv` |
| `analysis_input_mode` | string | Runtime mode used by the generator (`live-enriched` or recovery `static`) | `outputs/cumulative_qmbd_records.json` metadata; archived manifest |
| `is_static_recovery_mode` | boolean | Whether the run used the static recovery hatch | `outputs/cumulative_qmbd_records.json` metadata; archived manifest |
| `static_recovery_reason` | string | Human/audit explanation for a static recovery run | `outputs/cumulative_qmbd_records.json` metadata; archived manifest |
| `provider_set` | string | Requested or inferred provider set recorded for the run | `outputs/cumulative_qmbd_records.json` metadata; archived manifest |
| `commit_sha` | string | Git commit associated with the generated run | `outputs/cumulative_qmbd_records.json` metadata; archived manifest |
| `github_run_id` | string | GitHub Actions run identifier when available | `outputs/cumulative_qmbd_records.json` metadata; archived manifest |
| `analysis_timestamp_utc` | string | Generator timestamp recorded in cumulative metadata | archived manifest |

### `source_bundles`

Historical or manual input packages treated as a bounded ingest unit.

| Variable | Type | Meaning | Source artifact |
| --- | --- | --- | --- |
| `bundle_id` | string | Deterministic ID for one historical bundle | `outputs/manual_sources/historical_compatibility.csv` |
| `source_path` | string | Original local ZIP/folder path | `outputs/manual_sources/historical_compatibility.csv` |
| `extracted_dir` | string | Extraction workspace used for validation | `outputs/manual_sources/historical_compatibility.csv` |
| `status` | string | Compatibility state (`compatible`, `incompatible`, `invalid`, `missing`) | `outputs/manual_sources/historical_compatibility.csv` |
| `reason` | string | Machine-readable reason for the status | `outputs/manual_sources/historical_compatibility.csv` |

### `evidence_records`

Canonicalized evidence records emitted from live records, triangulated live records,
or cumulative QMBD records.

| Variable | Type | Meaning | Source artifact |
| --- | --- | --- | --- |
| `canonical_record_id` | string | Deterministic historical/manual record key | `outputs/manual_sources/historical_cumulative_records.jsonl` |
| `doi` | string | DOI when present | `outputs/manual_sources/historical_cumulative_records.jsonl`; cross-run tables |
| `source_id` | string | Provider or local source identifier | same |
| `title` | string | Evidence title or document label | same |
| `record_origin` | string | Origin label such as `STATIC_BASELINE`, `LIVE_API`, `manual_supporting_source` | same |
| `axis_name` | string | TMBD axis label when available | same |

### `evidence_occurrences`

One row per observation of an evidence record within a run or the manual ledger.

| Variable | Type | Meaning | Source artifact |
| --- | --- | --- | --- |
| `dataset` | string | Dataset lane (`live_records`, `live_records_triangulated`, `cumulative_qmbd_records`, `manual_supporting_sources`) | `outputs/run_archive/cross_run_evidence_occurrences.csv` |
| `record_index` | integer | Position within the dataset | `outputs/run_archive/cross_run_evidence_occurrences.csv` |
| `dedupe_value` | string | Canonicalized value used for longitudinal grouping | `outputs/run_archive/cross_run_evidence_occurrences.csv` |
| `dedupe_field_used` | string | Field that supplied the dedupe value (`doi`, `source_id`, `title`) | `outputs/run_archive/cross_run_evidence_occurrences.csv` |

### `gap_clusters`

Evidence-first analytical gaps derived from the demand/supply model.

| Variable | Type | Meaning | Source artifact |
| --- | --- | --- | --- |
| `sector` | string | Blue economy sector | `outputs/gaps_detailed.json`; `outputs/gap_priority_ranking.csv` |
| `axis_name` | string | TMBD axis of the missing demand | same |
| `gap_ratio` | number | Sector gap ratio at cluster level | `outputs/gaps_detailed.json` |
| `priority_score` | number | Weighted priority score for the missing cluster | `outputs/gap_priority_ranking.csv` |

### `dynamic_credentials`

Generated credential proposals or review-required placeholders linked to evidence.

| Variable | Type | Meaning | Source artifact |
| --- | --- | --- | --- |
| `id` | string | Credential identifier | `outputs/credentials_dynamic_database.json`; `outputs/credentials_database.json` |
| `sector` | string | Target sector | same |
| `eqf_level` | integer | Target EQF level | same |
| `evidence_clusters` | array/string | Gap-cluster evidence basis for generation | `outputs/credentials_dynamic_database.json` |
| `review_required` | boolean/state | Whether the credential remains an evidence gap placeholder | `outputs/credentials_generation_rationale.json` |

### `manual_sources`

Append-only locally ingested supporting documents.

| Variable | Type | Meaning | Source artifact |
| --- | --- | --- | --- |
| `source_id` | string | Stable manual document identifier (`manual_src_<sha16>`) | `outputs/manual_sources/manual_sources_ledger.jsonl` |
| `ingested_at_utc` | string | Ingest timestamp | `outputs/manual_sources/manual_sources_ledger.jsonl` |
| `source_kind` | string | `manual_document` or `zip_member_document` | `outputs/manual_sources/manual_sources_ledger.jsonl` |
| `sha256` | string | Payload checksum | `outputs/manual_sources/manual_sources_ledger.jsonl` |
| `archive_sha256` | string | Parent ZIP checksum when applicable | `outputs/manual_sources/manual_sources_ledger.jsonl` |
| `stored_path` | string | Local copied artifact path when copy mode is enabled | `outputs/manual_sources/manual_sources_ledger.jsonl` |

### `historical_revalidation`

Batch-level ingest and recount summary for historical bundles.

| Variable | Type | Meaning | Source artifact |
| --- | --- | --- | --- |
| `inputs_total` | integer | Number of requested historical inputs | `outputs/manual_sources/historical_revalidation_report.json` |
| `compatible_bundles` | integer | Bundles accepted into recounting | same |
| `incompatible_bundles` | integer | Bundles rejected for missing required files | same |
| `records_scanned` | integer | Historical rows examined | same |
| `records_inserted` | integer | New rows appended to `historical_cumulative_records.jsonl` | same |
| `records_skipped_duplicates` | integer | Rows skipped due to prior ingest | same |

## Notes

- `outputs/cumulative_qmbd_records.json` stayed at 466 in earlier static-only runs
  because deterministic regeneration kept rewriting the same 15 baseline plus 451
  literature-derived records.
- The cumulative mechanism separates **observation** from **publication**: the code
  PR establishes reproducible capture and audit fields first, while a later Data PR
  can decide which corpora, indexes, or checksums are publishable under storage and
  licensing constraints.
