# ABRP governed gold-corpus codebook

## Purpose

This contract defines the first machine-governed Human Capability Recoding / Action-Bearing Relational Proposition (ABRP) annotation surface for MOR-15A. It does not alter the existing aggregate screening results and does not make H2 or H3 computable.

## Empirical unit

Minimal ABRP:

`ACTOR must ACTION OBJECT because TRANSFORMATION changes AFFECTED_RELATION.`

Extended ABRP may additionally record an intended effect and conditions/qualifiers.

The fail-closed rule is normative for validation:

**No exact action span -> no validated human capability.**

A title, topic, sector label, QMBD target or broad demand label may guide sampling, but may not supply a missing action.

## Blind coding

Phase `A_BLIND` keeps sector, QMBD axis, axis fit and candidate-capability fields empty. It records `axis_hidden_phase_A=true` and `axis_revealed_phase_B=false`.

Phase `B_REVEALED` may reveal sector and QMBD only after Phase A. It preserves `axis_hidden_phase_A=true` and sets `axis_revealed_phase_B=true`. The revealed axis may assess fit; it must never determine the action verb.

## Controlled vocabularies

Semantic completeness:
- `complete_action_proposition`
- `partial_action_proposition`
- `meta_signal`
- `underspecified`
- `non_capability`

Capability content gate:
- `PASS`
- `PARTIAL`
- `FAIL_META`
- `FAIL_INSUFFICIENT`
- `REJECT`

Ocean relationality:
- `constitutive`
- `conditioning`
- `incidental`
- `unclear`

Statement polarity explicitly distinguishes `deficit` from `negated_need` so statements such as “lacks digital skills” are not silently treated as absence of demand.

## Gold status

`is_gold=true` is permitted only in an `adjudicated_gold` corpus and only after `agreed` or `resolved` adjudication. Seed and coder surfaces are not gold.

The Pilot-v7 baseline manifest preserves only the known aggregate counts. Its 24 case-level evidence IDs are not present in the current repository and must not be invented.

## Reliability

Independent coder surfaces and adjudication are separate empirical objects. The schema supports later calculation of percent agreement, Gwet AC1 / Cohen kappa where appropriate, Krippendorff alpha, exact-span overlap/IoU and a disagreement ledger. Reliability computation is outside this first schema PR.

## Governance

Changes to the governed schema, gold-corpus records or ABRP review templates must occur through a pull request. The repository includes an approval workflow requiring at least one non-author `APPROVED` review anchored to the current PR head when protected gold-corpus paths change.

Canonical `main` currently has no GitHub ruleset making that status check mandatory. The workflow is therefore an auditable control, not yet an unbypassable merge gate; repository administration must make the check required before this can be described as enforced branch policy.
