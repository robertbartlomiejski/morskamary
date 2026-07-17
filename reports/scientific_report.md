# Scientific methodology audit and controlled evaluation plan

**Repository:** `robertbartlomiejski/morskamary`  
**Audited main commit:** `786586b5c27aae6f82daaede80c305500d9b83b2`  
**Report status:** implementation-level audit; not an empirical validation of a new live-provider run  
**Primary decision question:** Is a paid full contextual extraction layer likely to add enough scientific value beyond the repository's deterministic extraction pipeline to justify its cost?

## Executive finding

The repository already implements a strong **auditable research-data pipeline**: protocol-governed acquisition, provider and query provenance, stable evidence identities, DOI/title/source deduplication, novelty and repetition diagnostics, deterministic Layer 3 signal extraction, hypothesis-fragment ledgers, Layer 4 demand aggregation, Layer 5 hypothesis and credential outputs, current-run guards, checksums, reports, and release packaging.

The repository does **not** yet implement a full contextual extraction system. Its current semantic layer is deliberately deterministic and phrase-based. It can find declared phrases in retained evidence surfaces and preserve reproducible links from signals to evidence. It does not, by itself, reliably interpret long-range context, negation, causal direction, actor-role relations, implicit competence claims, rhetorical framing, or semantically equivalent expressions absent from the registries.

A paid contextual layer is therefore **potentially valuable**, but only as a controlled augmentation—not as a replacement for the existing pipeline. The recommended investment decision is:

> Fund a bounded benchmark pilot only. Purchase or scale a contextual extraction layer only when it demonstrates materially better human-validated extraction while preserving record-level evidence spans, deterministic identifiers, non-fabrication, hypothesis directionality, and the repository's release gates.

The current pipeline should remain the provenance, identity, governance, and publication backbone. A contextual model should produce candidate annotations that enter the same review-state machine and must never convert query intent into evidence.

## 1. Audited implementation

### 1.1 Layer 0: authoritative protocol

`config/live_query_protocol.yml` defines:

- six query families: `core_sector`, `competence_demand`, `emerging_demand`, `validation_eqf_translation`, `hypothesis_verification`, and `theory_translation`;
- temporal, provider-sort, sampling, sector, axis, expected-signal, and evidence-intent metadata;
- an authoritative H1–H3 registry with required axes, declared outcomes, indicator registries, theory registries, and required result fields.

`src/scientific_sources/live_query_protocol.py` parses the protocol into typed declarations and validates the six-family minimums, unique query IDs, hypothesis definitions, required axes, result fields, and legacy projection.

### 1.2 Layer 1: acquisition audit

The live workflow projects the rich protocol into the legacy exporter shape while separately passing the authoritative constraint ledger. The audit path records query/provider execution information and preserves canonical axis and count fields. This creates a reproducible acquisition trail even where a provider cannot apply every declared filter natively.

### 1.3 Layer 2: cumulative evidence

`src/scientific_sources/cumulative_scientific_database.py` creates stable evidence records and:

- normalizes DOI identities;
- falls back to normalized title and provider-scoped source identifiers;
- preserves first/latest run provenance;
- consolidates provider support;
- marks near-duplicate non-roots as `duplicate_only`;
- distinguishes new, repeated, metadata-updated, provider-enriched, semantic-enriched, duplicate-only, and review-required records;
- computes cross-run novelty and repetition diagnostics.

This is a major asset that a commercial extraction service would otherwise need to reproduce.

### 1.4 Layer 3: deterministic semantic extraction

The current classifier is explicitly versioned as a deterministic rule-based scanner. It evaluates retained evidence surfaces:

- title;
- subject terms;
- abstract, when retained;
- full text, when legally retained.

`source_query` remains provenance-only and does not provide positive evidence. Signals receive stable IDs, evidence hashes, evidence-surface labels, confidence scores, review status, and validity warnings.

The H1–H3 fragment ledger is also deterministic. A fragment is emitted only when:

1. the signal axis belongs to the hypothesis's required axes; and
2. the evidence text matches a phrase in the hypothesis indicator registry.

The ledger records the matched phrase, indicator family, optional theory-term family, evidence surface, signal ID, and evidence ID.

### 1.5 Layers 4–5 and hypothesis alignment

The implemented scientific contracts are:

| Hypothesis | Repository contract | Required axis relation | Current interpretation basis |
|---|---|---|---|
| H1 | Maritimisation Shift | **MARITIME vs OCEANIC** | signed Cohen's *d* on demand-strength scores, with matched H1 fragment count reported |
| H2 | Hydronization Lag | **HYDRONIZATION** | missing validated EQF 6–7 coverage at `competence_demand_id` level; generated candidate credentials are not validated supply |
| H3 | Omniocean Axis Translation / differential coverage | **MARINE and OCEANIC** | matched-fragment balance and evidence/signal overlap bridges |

This alignment must be preserved in every future extraction layer. In particular:

- H1 cannot be supported by a negative MARITIME–OCEANIC effect;
- H2 cannot infer validated supply from generated candidate translations;
- H3 must use MARINE/OCEANIC matched fragments and shared evidence or signal overlap, not generic axis counts.

## 2. What the repository already does well

### 2.1 Reproducibility

The existing system has deterministic serialization, stable identifiers, fixed classifier versions, sorted outputs, checksums, manifests, current-run identity checks, and negative-control tests. These are more important for scientific defensibility than adding a powerful model without an audit trail.

### 2.2 Evidence boundaries

The code distinguishes query intent from scientific evidence. This is a critical protection against circular confirmation: the terms used to retrieve a record cannot themselves prove that the retrieved record supports the hypothesis.

### 2.3 Conservative provenance

Signals and fragments are linked to evidence IDs and text hashes. Missing evidence is marked unavailable rather than replaced with a plausible but unrelated sector record. Candidate credentials and validated supply remain separate states.

### 2.4 Novelty and recurrence

The cumulative model separates repeated or duplicate evidence from scientific growth. This allows the project to distinguish corpus recurrence from genuinely new records, metadata, providers, or semantic identities.

## 3. Current semantic limitations

The deterministic layer is transparent and reproducible, but its scientific recall and interpretive depth are bounded by its registries.

### 3.1 Lexical dependence

A concept can be present without using a registered phrase. Synonyms, paraphrases, disciplinary jargon, multilingual variants, and indirect competence descriptions may be missed.

### 3.2 Limited contextual disambiguation

Phrase matching does not reliably distinguish:

- asserted need from historical description;
- current competence gap from a gap already resolved;
- recommendation from empirical finding;
- author claim from a cited or rejected claim;
- direct evidence from speculative discussion.

### 3.3 Negation and modality

The same phrase may appear in statements such as “no skills gap was identified,” “a gap may emerge,” or “earlier studies claimed a gap.” A lexical match alone cannot consistently encode these distinctions.

### 3.4 Relation extraction

The current pipeline does not fully model relations such as:

- actor → competence → sector → task;
- technology → displaced skill → emerging skill;
- governance level → responsibility → EQF outcome;
- evidence claim → hypothesis indicator → supporting or contradicting direction.

### 3.5 Document-level synthesis

Evidence may be distributed across multiple sentences or sections. A full contextual layer would need to demonstrate the ability to connect a method, population, result, limitation, and conclusion; a phrase scanner generally treats the retained text as a searchable surface rather than a structured argument. The benchmark should test whether a contextual layer can reliably perform this synthesis without fabricating connections.

### 3.6 Calibration remains empirical

The deterministic confidence score reflects evidence location and metadata richness. It is not a measured probability of scientific correctness. A contextual model's probability score would also require calibration against human coding.

## 4. What a paid full contextual layer must add

A paid layer is scientifically worthwhile only when it adds capabilities that the repository cannot obtain through modest registry expansion.

Required additions should include:

1. **Span-grounded extraction:** every extracted claim points to exact retained text spans and evidence IDs.
2. **Context classification:** assertion, negation, uncertainty, recommendation, background, result, and limitation.
3. **Relation extraction:** competence, actor, sector, task, technology, governance level, EQF implication, and hypothesis direction.
4. **Paraphrase recall:** detection of semantically equivalent formulations outside the phrase registry.
5. **Cross-sentence synthesis:** controlled linking of claims across nearby sentences or document sections.
6. **Contradiction handling:** separate support, contradiction, mixed evidence, and non-computable states.
7. **Structured H1–H3 outputs:** outputs must obey the repository's axis and direction contracts.
8. **Review-state integration:** model outputs begin as `candidate` or `review_required`, unless a pre-registered high-confidence rule is met.
9. **Version and prompt provenance:** model, prompt, schema, temperature, provider, and timestamp are recorded.
10. **Deterministic replay mode:** the same archived text and configuration should reproduce functionally equivalent structured output.

A service that returns only summaries, labels, or embeddings without evidence spans and reproducible structured output is not suitable for the scientific release path.

## 5. Controlled comparison design

### 5.1 Benchmark sample

Create a stratified benchmark of at least **300 evidence records**:

- all 12 canonical sectors;
- all four QMBD axes;
- all six query families;
- a mix of title-only, title-plus-subject, abstract, and full-text cases;
- repeated, duplicate, enriched, and new records;
- positive, negative, ambiguous, and no-signal controls.

**Sampling protocol (pre-registered):**

1. **Sampling frame:** All records in the cross-run evidence index with `is_candidate_for_layer4=true` as of a frozen snapshot date.
2. **Stratification:** Define primary strata by (sector × axis). For records appearing in multiple strata, assign to the stratum with the lowest current sample count to balance coverage.
3. **Allocation:** Minimum 2 records per stratum; remaining slots allocated proportional to stratum size in the frame, up to 300 total.
4. **Selection method:** Within each stratum, sort records by evidence_id (deterministic), then select every N-th record where N = floor(stratum_size / allocated_count). If fewer than allocated_count remain, take all.
5. **Reproducibility seed:** Use a fixed random seed (e.g., 20260717) for any tie-breaking or supplemental random sampling.
6. **Freezing:** Record evidence_id, text_hash (SHA-256 of retained title+abstract+subject), provider, and snapshot_date for each selected record.

The benchmark must be sampled from legally retained text with explicit permission for third-party transmission (see §5.1.1 below) and frozen by evidence ID and text hash before any system tuning begins.

#### 5.1.1 Third-party processing eligibility

Before any record is sent to a paid contextual extraction service, it must pass these hard licensing gates:

1. **Redistribution permission:** The record's licence explicitly permits redistribution of abstracts or full text (e.g., CC-BY, CC-0, publisher open-access terms), OR the vendor contract includes institutional text-mining rights that cover transmission for analysis.
2. **Vendor data handling:** The service contract must specify:
   - whether transmitted text is retained by the vendor;
   - whether retained text may be used for model training;
   - data residency requirements (e.g., EU-only processing for GDPR compliance);
   - deletion policy and timeline after contract termination.
3. **No institutional full-text without explicit rights:** Records accessed under institutional subscriptions (Scopus, Web of Science abstracts; paywalled full text) may NOT be transmitted unless the vendor contract explicitly permits it and the institutional licence includes text-mining redistribution.
4. **Local inference alternative:** If vendor terms are unacceptable, require local deployment of an open-weight model with no external transmission.

Any record that fails these gates is excluded from System C evaluation, even if it is legally retained for internal phrase-matching.

### 5.2 Human reference standard

Two trained coders independently annotate:

- competence signal type;
- exact supporting span;
- sector and axis;
- assertion/negation/modality;
- H1/H2/H3 indicator and direction;
- relation tuples;
- review status;
- whether the record is sufficient for an educational or credential inference.

Disagreements are adjudicated. Inter-coder agreement is reported before the adjudicated gold standard is used.

### 5.3 Systems compared

- **A — Current deterministic pipeline:** frozen repository classifier and registries.
- **B — Expanded deterministic registry:** modest manual registry improvement, to test whether cheaper rule maintenance closes the gap.
- **C — Paid contextual layer:** same frozen records and output schema.
- **D — Hybrid:** contextual candidates accepted only after deterministic constraints and provenance validation.

**Development/evaluation split to prevent leakage:**

1. **Development partition (150 records):** Used for System B registry tuning, System C prompt engineering, and System D hybrid-rule development. Gold labels are accessible during this phase.
2. **Evaluation partition (150 records, held out):** All systems (A, B, C, D) and prompts must be frozen before accessing this partition's gold labels. Reported metrics come only from the evaluation partition.
3. **Alternative:** If an external development corpus (e.g., 100 additional records from a prior run) is used for tuning, the full 300-record benchmark may serve as the evaluation set, but the external development set and all tuning decisions must be documented and frozen before evaluation begins.

No system configuration, registry entry, or prompt may be changed after evaluation-partition gold labels are first accessed.

### 5.4 Primary metrics

Report at record, signal, span, relation, and hypothesis levels:

- precision, recall, macro-F1, and class-specific F1;
- exact and partial span match;
- false evidence-link rate;
- negation/modality accuracy;
- relation-tuple F1;
- H1/H2/H3 direction agreement with adjudicated coding;
- calibration error for confidence scores;
- manual-review minutes per accepted signal;
- cost per adjudicated accepted signal;
- reproducibility across repeated runs.

### 5.5 Proposed acceptance thresholds

The thresholds below are decision gates, not claims about current performance. All gates apply to the evaluation partition only.

**Point estimates (computed from evaluation partition):**

- accepted-signal precision at least **0.90**;
- macro-F1 improvement over the current deterministic baseline at least **0.10**;
- recall improvement at least **0.15 absolute**, unless the expanded deterministic registry performs similarly;
- evidence-span presence **100%** for any output entering Layer 4–5;
- **fabricated evidence links exactly 0%** (hard rejection gate; see definition below);
- unsupported evidence links (non-fabricated) below **1%**;
- negation/modality accuracy at least **0.90**;
- H1/H2/H3 direction agreement at least **0.90**;
- reproducibility agreement at least **0.95** on frozen inputs;
- at least **30% reduction** in human adjudication time per accepted signal;
- cost remains below a pre-approved project budget ceiling.

**Uncertainty procedure (stratified bootstrap):**

1. Resample the evaluation partition 1,000 times with replacement, preserving stratum proportions.
2. Compute precision, recall, macro-F1, and other metrics on each bootstrap sample.
3. Report the 95% confidence interval (2.5th and 97.5th percentiles) for each metric.
4. **Lower-bound gate:** The **lower 95% confidence bound** (not the point estimate) must meet the precision (≥0.90), macro-F1 improvement (≥0.10), and recall improvement (≥0.15) thresholds for the contextual system to be recommended for adoption.

**Fabrication definition:**

- **Fabricated link:** An evidence_id, span, or citation that does not exist in the retained record text, or a paraphrased claim that materially contradicts the source.
- **Unsupported link (non-fabricated):** A claim that is not directly supported by the retained text but is a plausible inference or overgeneralization, without fabrication.

**Automatic rejection conditions:**

Failure on evidence grounding (span presence < 100%), hypothesis directionality (H1/H2/H3 agreement < 0.90), or fabrication (fabricated links > 0%) is an automatic rejection regardless of aggregate F1 or other metrics.

## 6. Cost-benefit decision matrix

### Keep the current deterministic layer only when

- corpus text remains mainly titles and sparse metadata;
- transparency and exact replay are more valuable than recall;
- the main task is monitoring recurrence and explicit competence terminology;
- human coding resources exist for the smaller ambiguous subset.

### Add a contextual pilot when

- abstracts or full text are retained for a material share of records;
- paraphrase, negation, relation, and cross-sentence errors materially affect H1–H3 conclusions;
- manual review is becoming the main cost;
- a vendor or model can return schema-valid, span-grounded outputs.

### Scale the paid layer only when

- the benchmark meets every hard evidence and hypothesis gate;
- improvement remains after comparison with an expanded deterministic registry;
- gains occur across sectors and axes rather than only in easy or English-language cases;
- the cost per accepted, human-validated signal is lower than the current review workflow;
- outputs can be archived and reproduced without vendor lock-in.

## 7. Recommended architecture

Use a **hybrid, evidence-first architecture**:

1. retain Layer 0 acquisition and Layer 1 audit unchanged;
2. retain Layer 2 identity, deduplication, provider provenance, and novelty unchanged;
3. run deterministic Layer 3 as the transparent baseline;
4. run the contextual model only on eligible retained evidence surfaces;
5. store contextual candidates in a separate versioned ledger;
6. require exact span and evidence ID for every candidate;
7. reconcile deterministic and contextual outputs into agreement, disagreement, and review queues;
8. allow only validated or rule-qualified outputs into Layer 4–5;
9. preserve the existing H1/H2/H3, gate, report, manifest, checksum, and package contracts.

This prevents a paid model from becoming the unreviewable source of truth.

## 8. Immediate recommendation

Do **not** purchase a broad “full contextual extraction” subscription solely on the promise of better summaries or larger context windows.

Proceed with a small, time-bounded pilot using the benchmark above. The repository is already sufficiently mature to evaluate the paid layer rigorously. Its strongest components—identity, provenance, novelty, hypothesis contracts, review states, and packaging—should be reused as the acceptance harness.

The likely value of a contextual layer is highest for:

- implicit competence demand;
- negation and uncertainty;
- actor–competence–task relations;
- hypothesis-support direction;
- cross-sentence evidence;
- richer learning-outcome candidates.

The likely value is lowest for:

- DOI identity and deduplication;
- provider/query provenance;
- novelty/repetition accounting;
- deterministic release construction;
- checksum and manifest governance.

Those lower-value functions are already implemented and should not be repurchased.

## 9. Reproducibility note

This report is a source-code and protocol audit at commit `786586b5c27aae6f82daaede80c305500d9b83b2`. It does not claim that current live-provider outputs contain a particular number of records, signals, fragments, demands, or supported hypotheses. Empirical counts must come from a named, current-run Layer 0–5 package with matching run ID, source SHA, gates, manifests, and checksums.
