# QMBD Variable Operationalisation and Uncertainty Typology

This document defines uncertainty as a measurable design feature rather than a residual error bucket.

## 1. Why uncertainty must be operationalised

In this repository, uncertainty is not automatically non-significant. Some uncertain cases are analytically empty and should not count as evidence. Other uncertain cases are themselves important indicators of liminality, mediation, polysemy, or sector-conditioned meaning.

The task is therefore to distinguish:

- absence of retained semantic evidence,
- ambiguity in semantic evidence,
- boundary and mediator phenomena that require structured review.

## 2. Unit of analysis

Primary unit: retained sentence or equivalent evidence span from title, subject terms, abstract, or approved full-text fragment.

Secondary units:

- record,
- occurrence,
- fragment,
- semantic signal,
- candidate competence,
- validation decision.

Uncertainty must be attached first to the retained evidence span, then propagated cautiously upward.

## 3. Typology

### A. `no_signal`

Definition: no retained QMBD axis vocabulary or context rule is activated.

- Counts as positive axis evidence: no
- Retain in audit trail: yes
- Default review action: optional unless sampled for QA

### B. `ambiguous_context`

Definition: a term or phrase is present but the surrounding context does not justify a stable axis assignment.

- Counts as positive axis evidence: no
- Retain in audit trail: yes
- Default review action: review required

### C. `polysemic_term`

Definition: the same lexical item is used with materially different meanings across contexts.

- Counts as positive axis evidence: no, pending adjudication
- Retain in audit trail: yes
- Default review action: review required and dictionary refinement

### D. `boundary_threshold`

Definition: evidence sits at the edge of one or more axes or indicates transitional / liminal significance.

- Counts as positive axis evidence: not automatically
- Retain in audit trail: yes
- Default review action: review required

### E. `cross_axis_mediator`

Definition: the span links multiple axes through a mediating process, relation, or translation mechanism.

- Counts as positive axis evidence: only after review
- Retain in audit trail: yes
- Default review action: panel review for bridge logic

### F. `sector_dependent_meaning`

Definition: a term changes significance across one or more of the 12 sectors.

- Counts as positive axis evidence: sector-specific only after review
- Retain in audit trail: yes
- Default review action: vocabulary instrument update

### G. `discipline_dependent_meaning`

Definition: a term changes meaning across disciplinary contexts.

- Counts as positive axis evidence: discipline-specific only after review
- Retain in audit trail: yes
- Default review action: panel review and adjudication note

## 4. Variable -> indicator -> measure chain

| Layer | Construct element | Example |
|---|---|---|
| Variable | uncertainty_type | `cross_axis_mediator` |
| Indicator | overlap of retained axis vocabulary across evidence span | `hydrosocial governance` with water-governance and justice cues |
| Measure | coded typology + reviewer rating + adjudication note | `review_required`, typology code, 1-7 panel rating |

## 5. Liminal / mediator coding rules

The following must not be collapsed into generic no-match cases:

1. cross-axis overlap with retained vocabulary from more than one axis;
2. disciplinary terminology whose meaning is contested across sociology, governance, ecology, engineering, or policy;
3. sector-specific repurposing of broad terms such as resilience, transition, innovation, adaptation, or sustainability;
4. bridge terms that translate terrestrial and aquatic systems, especially in HYDRONIZATION and OCEANIC contexts.

## 6. Implication for future embeddings

Any future embedding classifier must predict not only axis membership but also uncertainty typology or review path eligibility. Otherwise it will remain too coarse for the measurement design.
