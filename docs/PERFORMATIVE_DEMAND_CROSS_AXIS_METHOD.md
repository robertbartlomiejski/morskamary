# Performative demand cross-axis method

## Decision

Use **unique linked evidence identities** as the independent unit for the
sector × axis table. Do not use derived-demand rows as observations because one
evidence identity can support several demand work packages. The current table
therefore has 978 observations, 12 sectors, four canonical axes, and all 48
cells—including zeros.

This choice removes duplicate work-package inflation, but it does not make the
dataset an iid sample. A linked evidence identity can still carry correlated
screening context across multiple signals.

The method separates four objects that answer different questions:

1. **Observed evidence structure** — where the acquired and classified texts sit.
2. **Title-screening features** — which candidate mechanism and realm labels are
   present and should be reviewed.
3. **Validated demand and translation** — exact text spans accepted by two coders.
4. **Validated supply** — independent credential evidence that can support a
   shortage claim.

Only objects 1 and 2 are populated in the current cumulative database.

## Complete conceptual table

The complete design is sector × axis × realm:

- 12 protocol sectors;
- `MARINE`, `MARITIME`, `OCEANIC`, and `HYDRONIZATION`;
- `ECONOMY`, `TECHNOLOGY`, `POLICY_GOVERNANCE`, and `CULTURE_LEARNING`.

This creates 192 explicit cells. A zero means “not observed in the current
screening run,” not “the competence does not exist.” Realm screening is
multi-label. Each evidence identity receives fractional weight
`1 / number_of_candidate_realms` so the 192-cell fractional total returns to
the 978 independent evidence identities.

## Sector-axis statistics

The analysis reports:

- exact observed and expected counts;
- adjusted standardized residuals;
- raw, Holm-adjusted, and Benjamini-Hochberg-adjusted cell p-values;
- Pearson chi-square as a table diagnostic;
- a deterministic 50,000-permutation p-value with fixed margins;
- bias-corrected Cramer's V;
- the number of expected cells below five and below one;
- all observed zero cells.

The test describes structure in the acquired/classified corpus. Sector and axis
were part of retrieval and classification, so a strong association is expected.
Small p-values or large residuals indicate non-random corpus structure under
this design; they are not workforce prevalence estimates or causal
sector-demand effects.

## Candidate performative-feature screen

Existing screening signal types (from retained `semantic_scope` values) are
grouped into five review queues:

| Feature | Signal types | Meaning now |
|---|---|---|
| Demand articulation | explicit/implicit competence demand, workforce skill | Candidate statement of need |
| Learning/credential translation | education/training, learning outcome, credential translation | Candidate movement into learning or credentials |
| Technical/operational capability | digital, technical, safety/risk | Candidate operational capability |
| Institutional governance | governance, policy/regulation, sustainability | Candidate institutional mechanism |
| Reflexive/cultural capability | social-science skill | Candidate reflexive or cultural capability |

These features are deterministic screening results, not validated
performativity. The current package allows retained title/subject-term/abstract/full-text
surfaces but still requires `review_required` status and exact-span validation
before any performativity claim.

## Human-validation grain for the next run

The validation ledger should add one row per exact text unit with:

- `text_unit_id`, `evidence_id`, `run_id`, provider, query ID, and source URL;
- text tier, exact span, actor/actant, capability/action, object, modality, context;
- multi-label axes and realms;
- demand presence: absent, implicit, explicit;
- performativity stage: mention, assertion, prescription, enactment,
  institutionalization;
- bridge type: none, direct, mediated;
- source axis, target axis, direction span, mediator span, and outcome span;
- coder 1, coder 2, confidence, reasons, and adjudication.

Strong performativity requires validated enactment or institutionalization.
Translation requires source and target spans, direction, a mediator, and an
outcome. A qualification-supply shortage additionally requires independently
validated registry evidence. Candidate credential rows cannot validate
themselves.

## Reproduction

Run:

```bash
python scripts/build_performative_demand_cross_axis_analysis.py
```

The package is written to `outputs/performative_demand_cross_axis/`.

## How to read the files

- `sector_axis_observed.csv`, `sector_axis_expected.csv`, `sector_axis_residuals.csv`:
  descriptive corpus-structure diagnostics only.
- `sector_axis_screening_features.csv`, `sector_axis_realm_screening.csv`,
  `axis_screening_feature_shares.csv`, `sector_screening_profile.csv`:
  deterministic screening outputs only; not validated demand, translation, or
  supply evidence.
- `external_comparison_coastal_tourism_axis_realm_case.csv`: external
  comparison-only aggregate; not retained repository evidence.
- `statistics_summary.json`, `validity_threats.json`, `value_labels.json`,
  `hypothesis_outcomes.json`, `package_schema.json`, `package_manifest.json`:
  governance and interpretation-boundary metadata that must be read with tables.

## Review reconciliation: output identity and provenance

All axis-bearing publication tables retain both the canonical `axis_group` and its non-inferred display `axis_code` (`M`, `T`, `O`, `H`). Screening rows carry the actual retained `evidence_surface` derived from `semantic_scope`; they are not assumed to be title-only. The supplied 21-fragment coastal-tourism 4 × 4 recoding remains comparison data, explicitly marked `citation_needed`, because no retained citable source for that aggregate exists in the repository. It is not repository evidence and cannot establish validated translation or performativity.

## PR #270 follow-up governance contract

This publication directory is a deterministic screening package, not a validated supply-gap package. `sector_screening_profile.csv` replaces the misleading deficit-profile name. Rejected semantic signals are excluded from positive screening aggregates; any reviewed state other than `review_required` fails closed until an accepted validation ledger is ingested.

`linked_evidence_sector_axis_lineage.csv` preserves exact evidence-identity lineage. `package_manifest.json`, `validity_threats.json`, `value_labels.json`, and `hypothesis_outcomes.json` provide machine-readable governance. H1–H3 retain the authoritative protocol definitions and are emitted as `not_computable` where this package lacks the required evidence. Full Analysis regenerates this package only from the retained cumulative snapshot; it performs no live acquisition.
