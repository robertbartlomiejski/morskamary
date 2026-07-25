# Live-enriched statistical analysis plan for main-branch outputs

**Repository:** `robertbartlomiejski/morskamary`  
**Main branch head used for this document:** `17655608d984b9614d84166d14f07dab613475a4`  
**Document status:** repository-grounded statistical analysis plan and report-materialisation contract; **not** an empirical substitute for a successful new live-provider run  

## 1. Objective

Prepare the cumulative evidence database for descriptive, inferential, reliability-oriented, and reproducible analysis across Excel, Statistica, PS IMAGO/SPSS, Python, and R, while preserving the repository's provenance, novelty, hypothesis, and release-governance contracts.

## 2. Source basis and governing contract

This plan is grounded in the current `main` implementation and must be interpreted together with:

- `docs/STATISTICAL_REPORT_METHODOLOGY.md`
- `.github/workflows/full-live-analysis.yml`
- `scripts/build_statistical_research_report.py`
- `reports/scientific_report.md`

The critical scientific limitation remains in force: the current Layer 4-5 pipeline is suitable for auditable cumulative analysis and deterministic diagnostic statistics, but it must **not** be described as completed professor-level scientific-statistical validation until the heuristic coverage model is replaced by evidence-based credential coverage and richer inferential tests.

## 3. Canonical versus analytical outputs

### 3.1 Canonical outputs

Canonical outputs are the provenance-preserving, normalized, audit-first artifacts that remain authoritative for traceability and deterministic reconstruction:

- `outputs/cumulative_database/evidence_records.csv`
- `outputs/cumulative_database/evidence_records.jsonl`
- `outputs/cumulative_database/competence_demand_signals.csv`
- `outputs/cumulative_database/competence_demand_signals.jsonl`
- `outputs/cumulative_database/derived_competence_demands.csv`
- `outputs/cumulative_database/derived_competence_demands.jsonl`
- `outputs/cumulative_database/sector_axis_gap_model.csv`
- `outputs/cumulative_database/credential_translation_eqf4_7.csv`
- `outputs/cumulative_database/learning_outcomes.csv`
- `outputs/cumulative_database/layer4_manifest.json`
- `outputs/cumulative_database/layer5_manifest.json`
- `outputs/cumulative_database/run_novelty_metrics.json`
- `outputs/cumulative_database/novelty_gate_report.json`
- JSONL audit records and Layer 1 run-audit outputs under `outputs/live_runs/<run_id>/`

### 3.2 Analytical outputs

Analytical outputs are software-oriented views derived from the canonical layer for statistical packages and reproducible notebooks/scripts. The following flattened views are planned and should remain explicitly derived rather than treated as provenance roots:

- `analysis_view_record_level.csv`
- `analysis_view_occurrence_level.csv`
- `analysis_view_sector_axis_gap_level.csv`
- `analysis_view_provider_sector_level.csv`
- `analysis_view_credential_level.csv`

## 4. Planned release outputs

The release target for a successful full live-enriched run should include:

- CSV UTF-8 tables
- XLSX workbook with one sheet per table
- optional SPSS/PS IMAGO `.sav` files with variable labels and value labels
- JSONL canonical audit records
- checksum manifest
- single release ZIP package

Where `.sav` export dependencies are unavailable, CSV plus value-label tables remain the mandatory fallback rather than a reason to suppress release.

## 5. Current workflow-grounded live report materialisation contract

The `Full Live-Enriched Analysis` workflow on `main` is the authoritative materialisation path for the empirical report package. In its current contract, a successful run should build at least the following report-facing artifacts:

### 5.1 Report artifacts

- `reports/morskamary_statistical_report.html`
- `reports/morskamary_statistical_report.pdf` when PDF rendering dependencies are available
- `reports/morskamary_methodological_audit.html`

### 5.2 Statistical and package artifacts

- `outputs/layer4_statistics/`
- `outputs/release_packages/morskamary_live_cumulative_latest.zip`
- current-run Layer 1-5 outputs under `outputs/live_runs/`, `outputs/cumulative_database/`, and `outputs/run_archive/`

### 5.3 Important interpretation rule

`scripts/build_statistical_research_report.py` formats precomputed Layer 2-5 outputs into human-readable reports. It does **not** recompute scientific results. Therefore, the statistical report is only as valid as the current run's underlying cumulative database, novelty metrics, Layer 4 indices, Layer 5 hypothesis outputs, and release guards.

## 6. Variable treatment standard

### 6.1 Categorical variables

- store as numeric-coded wherever export target software benefits from coded categorical input
- retain paired label dictionaries and value-label lookup tables
- preserve canonical text columns where required for provenance and reviewability

### 6.2 Ordinal variables

- use explicit ordered code scales
- document ordering semantics in labels/metadata tables
- avoid silent coercion to nominal when order matters analytically

### 6.3 Continuous variables

- store as numeric
- attach unit notes or score-construction notes where applicable
- keep deterministic formula documentation for all derived indices

### 6.4 Restricted or missing values

- retain the row
- apply reserved missing-value codes rather than deleting observations
- distinguish structural absence, unavailable evidence, not computable, and review-required conditions wherever analytically meaningful

## 7. Planned analyses

The cumulative database and its analytical views are intended to support the following families of analysis:

1. descriptive statistics by run, sector, provider, and axis
2. cross-tabulations (`sector × axis`, `provider × sector`, `source_type × quality_status`)
3. missingness analysis
4. duplicate-rate analysis
5. provider-diversity and provider-bias analysis
6. live/manual/historical source comparison
7. trend analysis across runs
8. gap-priority stability analysis
9. cluster/profile analysis for competence and gap patterns
10. machine-human agreement analysis
11. credential-generation-rate analysis

## 8. Repository-grounded measurement notes

### 8.1 Demand-strength score

The mandated Layer 4 formula remains:

```text
demand_strength_score =
    0.30 * normalized_unique_doi_count
  + 0.20 * provider_diversity_score
  + 0.20 * temporal_recency_score
  + 0.15 * query_diversity_score
  + 0.15 * semantic_confidence_mean
```

Weights are fixed and sum to `1.00` by contract.

### 8.2 Growth-eligible reliability rule

Statistical growth and derived-demand aggregation must be calculated only from evidence rows with `record_novelty_status` in the growth-eligible set:

- `new_record`
- `updated_metadata`
- `provider_enriched`
- `semantic_enriched`

`duplicate_only` rows must remain excluded from novelty growth so that reruns, package bumps, and repeated metadata cannot inflate scientific-growth interpretation.

### 8.3 Axis contract

QMBD axis identity remains four-part and canonical:

- `MARINE (M)`
- `MARITIME (T)`
- `OCEANIC (O)`
- `HYDRONIZATION (H)`

Any analytical export that collapses, renames, or drops one of these four axes violates the current scientific contract.

## 9. Hypothesis-facing analysis constraints

The current implementation-level report contract expects executable Layer 5 outputs for the declared hypotheses:

- `H1` — Maritimisation Shift
- `H2` — Hydronization Lag
- `H3` — Omniocean Axis Translation / differential coverage

These remain preliminary diagnostic tests rather than final inferential validation. They may be reported as `supported`, `partially_supported`, `not_supported`, or `not_computable`, and small-cell instability warnings must be preserved rather than hidden.

## 10. Software-specific notes

### 10.1 Excel

Primary uses:

- inspection
- filtering
- pivoting
- teaching-friendly descriptive work
- manual QA of categorical/value-label integrity

### 10.2 Statistica

Primary uses:

- CSV/XLSX import with numeric category codes
- contingency tables and classification-oriented diagnostics
- exploratory profile analysis

### 10.3 PS IMAGO / SPSS

Primary uses:

- `.sav` import when available
- variable labels and value labels
- reproducible descriptive and inferential procedures in GUI-oriented teaching and review environments

Fallback remains CSV plus separate variable-label/value-label tables.

### 10.4 Python / R

Primary uses:

- reproducible scripts and notebooks
- reliability diagnostics
- inferential extensions
- clustering/profile work
- agreement analysis
- publication-grade tables and figure generation

Normalized tables remain the authoritative ingest surface; flattened views are convenience layers.

## 11. Required analytical views and recommended grains

### 11.1 `analysis_view_record_level.csv`

One row per cumulative evidence record. Recommended fields include:

- `evidence_id`
- `first_run_id`
- `latest_run_id`
- `record_novelty_status`
- `provider_primary`
- `providers_seen_count`
- `query_families_seen_count`
- `year`
- `source_type`
- `doi_present`
- `title_present`
- `abstract_present`
- `citation_count`
- `record_origin`

### 11.2 `analysis_view_occurrence_level.csv`

One row per signal occurrence or evidence-signal pairing. Recommended fields include:

- `signal_id`
- `evidence_id`
- `sector`
- `axis_group`
- `axis_code`
- `competence_label`
- `signal_type`
- `confidence_score`
- `matched_hypothesis_ids`
- `review_status`
- `validity_warning`

### 11.3 `analysis_view_sector_axis_gap_level.csv`

One row per `sector × axis` cell. Recommended fields include:

- `sector`
- `axis_group`
- `static_baseline_available_count`
- `live_literature_demand_count`
- `validated_demand_count`
- `uncovered_demand_count`
- `gap_ratio`
- `gap_priority`
- `validity_warning`

### 11.4 `analysis_view_provider_sector_level.csv`

One row per `provider × sector` analytical cell. Recommended fields include:

- `provider`
- `sector`
- `records_contributed`
- `unique_doi_count`
- `growth_eligible_count`
- `duplicate_only_count`
- `provider_share`
- `provider_bias_flag`

### 11.5 `analysis_view_credential_level.csv`

One row per generated or validated credential row. Recommended fields include:

- `credential_id`
- `competence_demand_id`
- `sector`
- `axis_group`
- `eqf_level`
- `coverage_status`
- `confidence_score`
- `ects`
- `validated_supply_flag`
- `candidate_translation_flag`

## 12. Reliability, bias, and validity checks to retain in analysis outputs

Analytical exports and downstream reports should preserve, not erase, the repository's known threats and guardrails, especially:

- provider concentration and Crossref dominance
- Scopus zero-contribution situations despite health success
- WoS credential/entitlement failures
- static-baseline contamination
- query-design bias
- metadata-only limitations
- absence-of-abstract limitations
- duplicate-run inflation risk
- small-cell statistical instability
- advanced-method skipped states when dependencies are unavailable

## 13. What this document does and does not claim

### 13.1 This document does claim

- the repository has a defined, auditable, workflow-grounded plan for statistical output generation
- the current `main` branch contains an explicit live-analysis workflow and report-building path
- the cumulative database can be prepared for multi-software analysis without breaking provenance contracts

### 13.2 This document does not claim

- that a new successful empirical full live-enriched run has been executed on the current `main` head
- that `main` currently stores the generated `reports/` and `outputs/` artifacts from such a run
- that current heuristic credential coverage should be interpreted as final validated educational supply coverage
- that current H1-H3 diagnostics are already sufficient as final professor-level inferential validation

## 14. Operational note for main-branch report generation

To materialise the empirical live-enriched report on `main`, the repository's `Full Live-Enriched Analysis` workflow must complete successfully for the current head with valid provider access and output generation. The authoritative user-facing report artifacts are the workflow-generated HTML/PDF and package outputs, not this planning document.

Until such a run is executed successfully for the current head, this file should be treated as the **execution-ready statistical analysis plan and report contract**, not as the completed empirical report itself.
