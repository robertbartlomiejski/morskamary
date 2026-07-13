---
applyTo: "main.py,scripts/**/*.py,src/**/*.py,run_full_analysis.py,.github/workflows/**/*.yml,config/**/*.yml"
---

# Scientific pipeline implementation instructions

Before modifying an acquisition, semantic, statistical, hypothesis or packaging stage, trace its inputs and outputs across Layers 0-5 and identify the unit of analysis.

- Treat `config/live_query_protocol.yml` as authoritative when present. Any legacy `config/research_queries.yml` representation must be a deterministic, tested projection.
- Preserve raw occurrences and provider payload indexes per run. Deduplicate only into a separate canonical evidence view.
- Exclude query text from positive semantic classification.
- Define stable identifiers from normalized evidence content plus classifier/schema version; reprocessing identical evidence must not count as novelty.
- Use a fixed, injectable analysis timestamp for recency calculations.
- Keep `MARINE/M`, `MARITIME/T`, `OCEANIC/O` and `HYDRONIZATION/H` as name/code pairs.
- Load hypothesis declarations from configuration. Serialize every declared hypothesis with status, sample sizes, effect/direction, evidence counts, interpretation and warnings; use `not_computable` rather than omission.
- Distinguish scientific outcomes from structural validation. Non-support is a result; missing/reproducibility/schema/provenance failures block publication.
- A provider health result of `ok` does not prove contribution. Record requested, attempted, returned, accepted, deduplicated and semantically contributing counts by provider.
- Do not allow static baseline availability to become live literature demand.
- Candidate EQF 4-7 credentials remain `candidate` or `review_required` unless external validation evidence is present.
- Require manifests, checksums, schemas, variable/value labels and a validity-threat register in release packages.
- Add regression tests for scientific invariants and negative controls, especially query-only records, identical reruns, zero-contribution providers and static contamination.
