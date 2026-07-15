# Live cumulative scientific database (PR-190 Layers 2 and 3)

## Scope

This document describes the *live cumulative scientific database* produced by
`scripts/build_cumulative_scientific_database.py` on top of the PR-190 Layer 0
and Layer 1 evidence pipeline. It is intentionally a strict consumer of Layer
0-1 outputs — it never modifies, weakens, or replaces them.

The bundle is a deterministic, provenance-traceable snapshot suitable for
downstream cross-run analysis, gap detection, and competence-demand review. In
PR-190 Stage A-C this Layer 2-3 substrate now feeds the downstream Layer 4-5
scaffold, novelty gates, statistical report, and browser-downloadable ZIP
package. Those downstream outputs are intentionally labelled as scaffolded /
preliminary where they use deterministic heuristics rather than professor-level
validated coverage modelling.

## Layer stack context

| Layer | Owner | Purpose |
| --- | --- | --- |
| Layer 0 | `config/live_query_protocol.yml` | Frozen registry of 12 sectors × 10 queries × 6 families |
| Layer 1 | `scripts/build_live_run_audit.py` | Per-run raw acquisition audit bundle at `outputs/live_runs/<run_id>/` |
| Layer 2 | `scripts/build_cumulative_scientific_database.py` | Cumulative evidence records (this document) |
| Layer 3 | `scripts/build_cumulative_scientific_database.py` | Deterministic semantic competence-demand signals (this document) |
| Layer 4 | `scripts/build_layer4_5_scientific_analysis.py` | Derived demand statistics and diagnostic indices |
| Layer 5 | `scripts/build_layer4_5_scientific_analysis.py` | Sector-axis gap scaffold, EQF 4-7 candidate translation, and learning outcomes |

Layers 2 and 3 are packaged together because both derive from the same
deduplicated evidence backbone, share the same manifest, and must be
consistently reproducible from the same inputs.

## Bundle layout

The builder writes the following files under
`outputs/cumulative_database/`:

```
cumulative_database_manifest.json
_checksums.sha256
evidence_records.csv
evidence_records.jsonl
competence_demand_signals.csv
competence_demand_signals.jsonl
run_novelty_metrics.csv
run_novelty_metrics.json
```

The manifest records the schema version, classifier version, deterministic
`built_at_utc` timestamp, input roots, workflow context, and per-file byte
sizes. `_checksums.sha256` records SHA-256 digests of every emitted file
using chunked 1 MB reads for reproducibility across large runs.

## Evidence records (Layer 2)

Each row in `evidence_records.{csv,jsonl}` represents one deduplicated
scientific work observed across all runs contributing to the bundle.

### Columns

1. `evidence_id`
2. `canonical_doi`
3. `canonical_title`
4. `normalized_title_hash`
5. `first_seen_run_id`
6. `latest_seen_run_id`
7. `first_seen_at_utc`
8. `latest_seen_at_utc`
9. `providers_seen`
10. `provider_count`
11. `query_ids_seen`
12. `query_families_seen`
13. `sector_candidates`
14. `axis_candidates`
15. `year`
16. `journal`
17. `citation_count`
18. `record_novelty_status`
19. `record_recurrence_count`
20. `jaccard_group_id`
21. `validity_warning`

### Deduplication priority

The deduplicator groups observations in this fixed order:

1. **Canonical DOI** — the DOI is normalized (lowercased, `https://doi.org/`
   prefix stripped, whitespace collapsed).
2. **Normalized title hash** — Unicode-normalized, lowercased, punctuation
   stripped, whitespace collapsed, then SHA-256 hashed. Applied only when
   the DOI is missing.
3. **Provider source_id** — provider-scoped fallback identifier such as
   `crossref:xyz`, applied only when both DOI and title are missing.

After primary deduplication, a Jaccard-similarity pass groups near-duplicate
titles (threshold 0.85) using union-find over token sets. The resulting
`jaccard_group_id` is deterministic and shared across all rows in a group.

### `record_novelty_status`

Allowed values:

| Status | Meaning |
| --- | --- |
| `new_record` | First observed in the current run |
| `repeated_record` | Also present in prior runs, no meaningful change |
| `updated_metadata` | Prior record but core metadata changed (e.g., year, journal) |
| `provider_enriched` | Prior record now attested by an additional provider |
| `semantic_enriched` | Prior record now yields Layer 3 signals it did not before |
| `duplicate_only` | Row exists solely because of a Jaccard group merge |
| `review_required` | Deduplication produced ambiguous results and needs manual review |

`record_recurrence_count` is the raw number of run-scoped observations that
map to this record.

### `validity_warning`

`metadata_only_limitation` is stamped whenever the record has neither an
abstract nor structured subject terms — i.e., when semantic scanning must
operate solely on the title. This warning is propagated into
any Layer 3 signals derived from that record so downstream consumers can
distinguish weak from strong evidence.


## Raw payload provenance note

`outputs/live_runs/<run_id>/raw/raw_api_payloads/` preserves the exporter-level
raw payload envelopes captured by `scripts/export_live_research_records.py`.
These files are not guaranteed to be byte-for-byte provider HTTP responses for
every source: depending on provider capability and cache path they may be
provider-normalized raw rows wrapped by the exporter with query/run metadata.
Reviewers should therefore treat them as the auditable acquisition envelope, not
as a legal substitute for re-querying proprietary provider APIs.

## Evidence-strength note

Layer 3 semantic competence-demand signals are metadata-derived unless an
abstract or legally available full-text field is present in the source record.
When only title or subject terms are available, the signal carries
`metadata_only_limitation` / `review_required` warnings and must not be
interpreted as full-text evidence. `source_query` is retained for provenance
tracking only and never contributes to positive semantic matching or
confidence scoring. Query intent is not scientific evidence; matched semantic
fragments are evidence candidates.

## Competence-demand signals (Layer 3)

Each row in `competence_demand_signals.{csv,jsonl}` is one deterministic
semantic hit against the metadata available for an evidence record in the
current run. The scanner is intentionally rule-based (no LLM, no external
services) and reproducible.

### Columns

1. `signal_id`
2. `evidence_id`
3. `run_id`
4. `sector`
5. `axis_group`
6. `axis_code`
7. `query_id`
8. `query_family`
9. `semantic_scope`
10. `signal_type`
11. `competence_label`
12. `competence_description`
13. `demand_phrase`
14. `learning_outcome_candidate`
15. `evidence_text_scope`
16. `evidence_text_hash`
17. `confidence_score`
18. `classifier_version`
19. `manual_review_status`
20. `validity_warning`

### Allowed `signal_type` vocabulary

- `explicit_competence_demand`
- `implicit_competence_demand`
- `workforce_skill`
- `technical_skill`
- `governance_skill`
- `social_science_skill`
- `sustainability_skill`
- `digital_skill`
- `safety_risk_skill`
- `policy_regulation_skill`
- `education_training_signal`
- `learning_outcome_signal`
- `credential_translation_signal`

Each `_SignalPattern` in the scanner maps a fixed set of surface phrases to
one canonical `signal_type` and a stable `competence_label` /
`competence_description`. The pattern registry is frozen and iterated in
deterministic order, so the same inputs always yield the same signals.

### `axis_group` and `axis_code`

Signals inherit the TMBD axis of the evidence record's sector-candidate
mapping. Codes follow the `BlueDynamicsAxis` enum:

| Code | Group |
| --- | --- |
| `M` | Marine |
| `T` | Maritime |
| `O` | Oceanic |
| `H` | Hydronization |

When multiple axes are attested, `axis_group` uses the union label and
`axis_code` uses the first canonical code in registry order.

### Confidence scoring

The scorer sums additive weights per matched evidence scope:

- title match: `+0.55`
- subject term match: `+0.20`
- abstract match: `+0.20`
- full-text match: `+0.25`

`source_query` is excluded from positive matching and awards no points.
`metadata_only_limitation` subtracts `-0.10`. The final score is clamped to
the interval `[0.05, 0.95]`. Signals below the acceptance threshold `0.50`
are stamped `manual_review_status='review_required'`; signals at or above
the threshold with sufficient evidence support are stamped `auto_accepted`.

### Query binding

The scanner attempts to bind each signal to a Layer 0 query in the
following order:

1. Layer 1 `raw_acquisition_index.csv` where `protocol_binding == 'bound'`
   (preferred; carries the full sector × family × query context).
2. Fallback text-match against the Layer 0 `live_query_protocol.yml` registry
   when Layer 1 is absent or the record was acquired outside the protocol.

If no binding is available, the signal is still emitted but `query_id` and
`query_family` are recorded as empty strings and the manual review status is
promoted to `review_required`.

## Run novelty metrics

`run_novelty_metrics.{csv,json}` records at least the following fields:

- `current_run_id`
- `previous_run_id`
- `new_unique_doi_count`
- `repeated_doi_count`
- `updated_metadata_count`
- `provider_enriched_count`
- `semantic_new_signal_count`
- `semantic_enriched_count`
- `duplicate_only_count`
- `review_required_count`
- `jaccard_similarity_with_previous_run`
- `computed_at_utc`

These metrics support cross-run novelty tracking and pipeline observability
without requiring downstream statistical software.

## CLI usage

```bash
python scripts/build_cumulative_scientific_database.py \
  --current-run outputs \
  --archive-root outputs/run_archive \
  --live-runs-root outputs/live_runs \
  --query-protocol config/live_query_protocol.yml \
  --output-dir outputs/cumulative_database \
  --current-run-id "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" \
  --emit-summary
```

Arguments:

- `--current-run` — directory containing the current run's outputs; must
  contain `research_sources/live_records.json`.
- `--output-dir` — directory into which the bundle files are written.
- `--archive-root` — root for cross-run history (`cumulative_runs_index.csv`
  and `runs/<run_id>/research_sources/live_records.json`).
- `--live-runs-root` — root for Layer 1 raw acquisition bundles.
- `--query-protocol` — path to the Layer 0 registry.
- `--current-run-id` — deterministic identifier for the current run, must
  match the value used by `scripts/archive_run_outputs.py` and
  `scripts/build_live_run_audit.py`.
- `--built-at-utc` — optional ISO-8601 timestamp to freeze into the manifest
  for reproducible bundles.
- `--emit-summary` — print a one-line JSON summary to stdout on success.

Missing optional inputs degrade gracefully: absent `--archive-root` limits
the run to the current run only, absent `--live-runs-root` disables Layer 1
protocol binding, and absent `--query-protocol` disables Layer 0 fallback
binding.

## Workflow integration

The builder is invoked in `.github/workflows/full-live-analysis.yml`
immediately after `scripts/validate_run_archive_integrity.py` succeeds. The
`outputs/cumulative_database/` directory is uploaded as part of the
`live-enriched-analysis-outputs` artifact and staged in the `commit-outputs`
job when repository policy allows.

## Determinism and reproducibility guarantees

- All JSON files use `sort_keys=True`, `ensure_ascii=False`, and a trailing
  newline.
- All CSV files use `lineterminator="\n"` and pre-sort rows by a stable key.
- SHA-256 checksums are computed with chunked 1 MB reads.
- Two invocations against the same inputs produce byte-identical outputs.
- The semantic scanner has no non-deterministic branches, no time-dependent
  logic, and no external network calls.

## Non-goals

- Building the final publication-grade statistical report.
- Producing release ZIPs, versioned dataset packages, or Zenodo deposits.
- Rewriting or replacing Layer 0 / Layer 1 outputs.
- Introducing LLM-based inference or non-deterministic classifiers.

Downstream releases must continue to use the versioned pipeline documented in
`docs/CUMULATIVE_DATABASE_METHODOLOGY.md`.
