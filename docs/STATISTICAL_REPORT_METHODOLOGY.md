# Statistical Report Methodology (PR-190 Layer 4-5)

Reference documentation for the live cumulative Blue Economy competence
demand analysis pipeline (Layers 4 and 5). This file explains every
formula, index, hypothesis, and classification rule used by
`src/scientific_sources/derived_competence_analysis.py` and the CLI
scripts under `scripts/`. PR-190 Stage A-C wires a full pipeline scaffold;
it must not be described as a completed professor-level scientific-statistical
validation until the follow-up work replaces the heuristic coverage model with
evidence-based credential coverage and richer inferential tests.

## 1. Layers at a glance

| Layer | Purpose                                                | Primary output                                        |
|-------|--------------------------------------------------------|-------------------------------------------------------|
| 0     | Query protocol registry                                | `config/live_query_protocol.yml`                      |
| 1     | Raw provider acquisition                               | `outputs/live_runs/<run_id>/raw/`                     |
| 2     | Deduplicated cumulative evidence records               | `evidence_records.{csv,jsonl}`                        |
| 3     | Semantic competence-demand signals                     | `competence_demand_signals.{csv,jsonl}`               |
| 4     | Derived competence demand + statistical indices        | `derived_competence_demands.{csv,jsonl}` + statistics |
| 5     | Sector gap model + EQF 4-7 credential translation      | `sector_axis_gap_model.csv` + credentials + outcomes  |

## 2. Mandated demand-strength formula

```
demand_strength_score =
    0.30 * normalized_unique_doi_count
  + 0.20 * provider_diversity_score
  + 0.20 * temporal_recency_score
  + 0.15 * query_diversity_score
  + 0.15 * semantic_confidence_mean
```

Weights are fixed and sum to 1.00 by construction (see the test
`test_demand_strength_weights_sum_to_one`). The formula is embedded
verbatim in `build_layer4()` as an inline comment so downstream reviewers
can audit it without re-reading this file.

Component definitions:

* `normalized_unique_doi_count = min(1.0, unique_doi_count / 10.0)` — a
  reference of 10 unique DOIs is the saturation point.
* `provider_diversity_score` — number of distinct providers observed for
  the label divided by the maximum providers observed in the run.
* `temporal_recency_score` — recency function derived from
  `latest_seen_at_utc` using an exponential decay (see `_recency_score`).
* `query_diversity_score` — number of distinct query families divided by
  the maximum query family count for the run.
* `semantic_confidence_mean` — arithmetic mean of `confidence_score` on
  the underlying signals.

## 3. Growth-eligible reliability rule

Growth indexes and derived-demand aggregation are computed **only** on
evidence rows with `record_novelty_status` in
`GROWTH_ELIGIBLE_STATUSES`:

* `new_record`
* `updated_metadata`
* `provider_enriched`
* `semantic_enriched`

`duplicate_only` records are **excluded** from novelty growth so that
package version bumps and re-runs cannot inflate the corpus size.

## 4. Classification vocabularies

* `ALLOWED_DEMAND_STATUS = {high_demand, medium_demand, low_demand,
  review_required, duplicate_artifact, provider_bias_warning}`
* Hypothesis `interpretation` ∈ `{supported, partially_supported,
  not_supported, not_computable}`.
* QMBD axes: `MARINE (M)`, `MARITIME (T)`, `OCEANIC (O)`,
  `HYDRONIZATION (H)`.

## 5. Global indices

| Index                              | Definition (informal)                                                            |
|------------------------------------|----------------------------------------------------------------------------------|
| Blue Capability Gap Index          | Weighted uncovered-demand share across all sector×axis cells.                    |
| QMBD Skewness Index                | Concentration of demand across the four QMBD axes (Herfindahl-style).            |
| Micro-Credential Coverage Index    | Ratio of validated demands with at least one EQF 4-7 credential row.             |
| Provider Diversity Index           | 1.0 minus the max-provider share of records.                                     |
| Query Diversity Index              | 1.0 minus the max query-family share.                                            |
| Temporal Recency Index             | Mean per-record recency score.                                                    |
| Cross-Sector Recurrence Index      | Mean number of sectors per competence label / 12.                                |

## 6. Hypotheses

* **H1 — Maritimisation Shift**: Cohen's d on `demand_strength_score`
  between MARITIME and OCEANIC axes. Interpretation:
  `supported` when d ≥ 0.5, `partially_supported` at 0.2–0.5,
  `not_supported` otherwise, `not_computable` when either group is empty.
* **H2 — Hydronization Lag**: ratio of HYDRONIZATION demands lacking a
  credential row at EQF 6-7. `supported` when ratio ≥ 0.5,
  `partially_supported` at 0.25–0.5, `not_supported` otherwise,
  `not_computable` when no HYDRONIZATION signals are present.

Both hypotheses attach a `validity_warning = small_cell_stability`
whenever the sample size falls below the reliable threshold (n < 5).
CI **must not** fail on `not_supported` or `not_computable`. These are
preliminary diagnostic tests, not final inferential validation; follow-up work
should add sector × axis correspondence analysis and sentence-fragment
association models for hydronization lag.

## 7. Multivariate induction

`multivariate_induction_results.json` includes:

* frequency counts, contingency tables, standardized residuals;
* chi-square and Cramer's V (numpy fallback, no scipy dependency);
* provider-set Jaccard between axis groups.

Advanced methods (CA, PCA, K-means, hierarchical clustering) are marked
`method_status: "skipped"` with a clear reason when scipy/sklearn are
unavailable. This is a deterministic behaviour, not a silent failure.

## 8. EQF 4-7 credential translation

For each derived demand, credential rows are generated as **candidate** EQF
translations per matching EQF level using keyword mapping. Unless a future run
passes a validated `existing_credential_coverage` map, these rows are generated
candidate credential translations, not empirically validated coverage against
the existing 48-credential network.


* EQF 4 — operational skills (execute, operate, monitor).
* EQF 5 — technician / supervisory skills.
* EQF 6 — bachelor-level analytical or engineering skills.
* EQF 7 — master / governance / research skills.

The mapping is defined in `EQF_KEYWORD_MAP` and applied deterministically
to `competence_label`, `competence_description`, and axis metadata. Learning
outcome statements now include a Bloom-style action phrase, EQF level, evidence
ID, demand ID, and confidence score so reviewers can trace each candidate back
to Layer 2-4 evidence.

## 9. Static-baseline separation

`sector_axis_gap_model.csv` exposes `static_baseline_available_count` as
a distinct column. Live availability signals are NEVER written to this
column. Live-run acquisition CSVs must not contain records with
`record_origin ∈ {static_baseline, baseline}` — Gate D fails the run if
they do (see `scripts/compute_live_novelty_metrics.py`).

## 10. Reproducibility

Every CSV/JSONL is written with `newline=""`, `lineterminator="\n"`,
`sort_keys=True`, and pre-sorted rows. Package ZIPs use a fixed
`ZipInfo(date_time=(1980,1,1,0,0,0))` so archive member timestamps are stable.
For byte-identical package rebuilds, call
`scripts/build_live_cumulative_release_package.py --generated-at-utc <ISO8601>`
so README, citation, and manifest timestamps are also frozen.
