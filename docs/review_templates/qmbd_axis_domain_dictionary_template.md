# QMBD Axis-Domain Dictionary Template

**Status:** Reviewable vocabulary scaffold. This is an instrument for validating evidence indicators, not a hidden classifier truth source.

## Governance rules

1. Each entry must state whether it is:
   - evidential indicator,
   - contextual modifier,
   - ambiguous term requiring review,
   - excluded query/provenance term.
2. Query text alone must never create a positive semantic signal.
3. Terms must be traceable to theory, retained evidence, or reviewer justification.
4. Ambiguous terms must stay review-required until adjudicated.

## Fields

| Field | Description |
|---|---|
| dictionary_version | Version of this vocabulary instrument |
| axis_group | MARINE / MARITIME / OCEANIC / HYDRONIZATION |
| domain | Broad research or occupational domain |
| discipline | Disciplinary context |
| sector | Blue Economy sector |
| specialised_vocabulary | Candidate term or phrase |
| indicator_role | evidential_indicator / contextual_modifier / ambiguous / excluded |
| evidence_scope | title / abstract / sentence / subject_terms |
| uncertainty_typology | no_signal / ambiguous_context / polysemic_term / boundary_threshold / cross_axis_mediator / sector_dependent_meaning / discipline_dependent_meaning |
| review_status | proposed / reviewed / accepted / rejected |
| reviewer_note | Quote-then-reason justification |

## Example rows

| dictionary_version | axis_group | domain | discipline | sector | specialised_vocabulary | indicator_role | evidence_scope | uncertainty_typology | review_status | reviewer_note |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.1.0 | HYDRONIZATION | water governance | sociology | coastal_tourism | hydrosocial | evidential_indicator | abstract | cross_axis_mediator | proposed | [citation needed] |
| 0.1.0 | OCEANIC | governance | political science | maritime_transport | resilience | ambiguous | title | sector_dependent_meaning | proposed | Broad governance term; requires contextual review. |
