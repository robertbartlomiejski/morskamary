# Content analysis protocol

## Analytical frame

The cumulative evidence database is treated as computational content analysis
with human-validation layers.

## Unit definitions

- **Collection unit**: workflow run, historical bundle, or manual source bundle
- **Observation unit**: evidence occurrence
- **Record unit**: unique evidence record
- **Coding unit**: evidence segment, competence phrase, or gap-linked excerpt
- **Analytical unit**: `sector x TMBD axis x competence/gap cluster`

## Coding families

Minimum coding families:

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
- policy/governance relevance
- methodological limitation

## Reliability and validity protocol

Required control layers:

- human-validation sample
- machine-human comparison sample
- duplicate detection
- restricted-content flagging
- provider-bias assessment
- gap-priority stability checks

Required metrics:

- Cohen kappa
- Krippendorff alpha
- precision
- recall
- F1
- missingness
- duplicate rate
- provider bias
- review-required rate

Recommended thresholds:

- Krippendorff alpha `>= 0.667` exploratory minimum
- Krippendorff alpha `>= 0.800` preferred publication threshold
- Cohen kappa `>= 0.60` minimum
- Cohen kappa `>= 0.75` preferred
- machine-human `F1 >= 0.80` for high-impact codes

If a code family falls below threshold, it must be marked as one of:

- exploratory
- requires human review
- not publication-grade yet

## Segment handling

Evidence segments should preserve:

- source occurrence reference,
- segment order,
- text scope,
- exact segment text,
- coding assignments and coder type,
- validation status.
