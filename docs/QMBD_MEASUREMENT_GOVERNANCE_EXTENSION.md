# QMBD Measurement Governance Extension

This extension strengthens measurement governance without overstating empirical validity.

## Purpose

This repository must prefer explicit uncertainty over silent fallback, preserve separation between literature-derived demand and external validation, and prepare a review-ready governance layer before any future classifier modernization.

## Why the older fallback was a real weakness

The previous free-text axis classifier defaulted unmatched records to `OCEANIC`. That design hid a measurement failure by converting "no retained evidence for an axis assignment" into "governance evidence exists". This was not conservative. It was biased.

The problem is not that real weaknesses were identified. The problem is when a pipeline disguises those weaknesses as substantive results.

## Why some proposed fixes could overstate empirical validity

The risk is not in ambition. The risk is in claiming stronger evidence than the design currently supports.

### 1. Embeddings without a validated contract

Embeddings or softmax scores can be useful, but without:

- a labeled gold set,
- calibration and threshold studies,
- a versioned classifier contract,
- a fail-closed review path,

they produce opaque probabilities that may look scientific while remaining unvalidated for this theory/model.

### 2. Arbitrary score fusion

Combining literature demand with external labor-market data through a fixed weighted score can falsely imply that the resulting scalar has construct validity. If those data sources measure different constructs, the fused score is not automatically more valid. It can become less interpretable.

### 3. Overconfident econometric language

Inferential tests can support or fail to support a pattern. They do not prove a theory. If observational units, missingness, dependence, and population identity are not stabilized first, statistical significance can overstate certainty.

## Governance-safe principles implemented or prepared here

1. No biased fallback defaults.
2. Explicit uncertainty for no-match or low-confidence states.
3. Literature-derived demand remains distinct from validated external supply.
4. Human review is standardized before any future canonical expansion.
5. Vocabulary assets are versioned as reviewable instruments, not as hidden model internals.
6. Uncertainty is treated as a measurable typology, not a single residual bucket.

## Required future conditions before any embedding-based extension

Any future contextual embedding classifier must include:

1. a labeled gold set with adjudication rules;
2. a calibration protocol with reported thresholds;
3. a versioned classifier specification and changelog;
4. a fail-closed `UNCLASSIFIED` / `review_required` branch;
5. preserved evidence spans and reviewer-auditable rationale;
6. non-publication of model outputs as validated facts without panel review.

Until those conditions are met, embeddings may be explored as experimental Layer 3 signals only.

## Separation rule: literature demand vs external validation

- Literature-derived demand may indicate salience, recurrence, novelty, or thematic concentration.
- External validated supply may indicate existing credential or occupational coverage.
- These are different constructs and must not be fused by default into one score.

Where both exist, they should be reported side by side and linked through explicit provenance.

## Reviewer panel safeguard

The repository now includes a standardized reviewer questionnaire template aligned to:

- profession,
- sector,
- discipline,
- education,
- domain,
- axis,
- realm.

This is a preparedness instrument for future expert-panel validation, not proof that validation has already occurred.

## Variable-operationalisation extension

This extension now prepares:

- an uncertainty typology for liminal, mediator, sector-dependent, and discipline-dependent cases;
- a gold review set template for adjudicating boundary cases;
- a vocabulary instrument scaffold for sector-domain-axis validation.

These additions are designed to support serious university-level measurement design before any future embedding classifier is treated as analytically consequential.
