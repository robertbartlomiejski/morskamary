# MORSKAMARY — Live-Enriched Readiness Audit
**Date:** 2026-11-08. **Canonical baseline:** `504318bd27813553b0840d96d62b3c29eed19c13`.

**Decision:** G0 PARTIAL GO (prior exact-SHA CI passed, dedicated hardening not dispatched). G1 API smoke NOT AUTHORIZED/UNVERIFIED. G2 exploratory live NO-GO FOR EXECUTION until selected-provider preflight, protection and budget guarantees are resolved.

**Execution:** No real provider API call, no mutation of main, no change of publication statuses, no archive regeneration.

## Validated basis
- Existing exact-SHA CI tests ran successfully on Python 3.10, 3.11, 3.12 with flake8/mypy, Full Analysis, Research Pipeline and CodeQL.
- `hardening_dry_run` is isolated from provider-calling `live-analysis` in `full-live-analysis.yml`.
- `research-api-smoke.yml` always invokes provider health checks even when `live_api_tests=false`. Therefore, **never dispatch that workflow under a strict zero-API authorization**.
- `check_budget_ceiling.py` checks `logical_pages_attempted` only after acquisition, so it cannot alone prevent physical HTTP overspend or retry fees.
- The current workflow explicitly declares `environment: live-research`, but actual current reviewer rules and secret values could not be read via the available GitHub connection.
- `main protected=false` and protection API returned 403; this does not establish live-research environment configuration.
- The Research API Smoke workflow lacks explicit `OPENALEX_API_KEY` propagation despite its presence in Full Live.

## Acquisition budget
The authoritative protocol contains **120 query definitions in 12 sectors and six families** (see source-derived query codebook). Sampling is **3 pages × 50 rows**, across default **Crossref, Scopus and OpenAlex**. Nominal **360 logical pages per provider; 1,080 for all three**; maximal pre-dedup rows **54,000**, not distinct evidence.

OpenAlex price illustration: **$0.36** for 360 search calls at the published **$1/1,000 searches** rate, conditional on exactly one billable search per logical page and no retries. Current free-key budget is published as $1/day; remaining credits not inspected. Scopus Search nominal quota 20,000/7 days → 360 logical pages need approximately 720 physical calls at 25 records per HTTP query, or 3.6% of the generic weekly quota, not proof of any entitlement or remaining balance. Crossref public/polite pool is unbilled REST metadata but must obey returned rate limits. Monetary total **UNKNOWN**, not approved.

## Physical HTTP envelope: more precise than the logical-page budget (2026-11-11 review)

A source-backed review of the three adapter implementations establishes that **1080 logical pages are not 1080 physical requests**. Scopus uses `_SCOPUS_MAX_COUNT=25`; therefore each logical 50-row page may require two physical `urlopen` calls. Crossref allows up to four attempts per page and OpenAlex up to three attempts per page (counting initial attempts). For full 120-query, three-page, three-provider execution:

| Provider | Logical pages | Physical calls if all logical pages run, no retry | Adapter-attempt upper scenario |
| --- | ---: | ---: | ---: |
| Crossref | 360 | 360 | 1440 |
| Scopus | 360 | 720 | 720 |
| OpenAlex | 360 | 360 | 1080 |
| TOTAL | 1080 | **1440** | **3240** |

These are static projections, **not measured traffic, guaranteed upper limits, or a billable quote**. Actual volumes can be lower due to early termination/errors; HTTP redirects and independent health probes are excluded. For OpenAlex, retry-saturation could result in ~1080 search calls or nominal **$1.08** at $1/1000, potentially above the published $1/day free-key allowance.

**P1 still open:** `scripts/check_budget_ceiling.py` executes post-acquisition and `prepare_live_acquisition_plan.py` limits logical shape, neither establishes an atomic per-request physical/currency cap across provider adapters. Keep G2 NO-GO until an enforceable pre-request counter (including retries) or a separately versioned, approved bounded pilot is tested.

Sources: `src/scientific_sources/crossref.py`, `src/scientific_sources/elsevier_scopus.py`, `src/scientific_sources/openalex.py` at research-code SHA `504318bd...`.

## Scientific meaning
`protocol_query_codebook.csv` records declared retrieval intent, not semantic signals or validated demands. `sector_axis_query_counts.csv` records **query target distribution**, not an empirical QMBD result. H1 requires real evidence and a comparable method; H2 needs independently validated educational supply; H3 needs independently verified cross-axis bridge relations. Preserve `not_computable` where appropriate. Historical archive, source and codebook files must not be retroactively modified.

## Next actions (STOP before API)
1. Owner confirms current `live-research` protected environment reviewer rules/branch restrictions and non-secret credential presence.
2. Authorized maintainer dispatches **only** `Full Live-Enriched Analysis` with `execution_mode=hardening_dry_run`; capture exact ref, SHA and run URL. The available connector cannot dispatch new workflow runs.
3. Prepare small reviewed code PR to make `research-api-smoke` truly offline under false input, align OpenAlex key wiring, and enforce pre-request physical/financial budget (or separately versioned reduced query pilot).
4. Approve bounded provider smoke **as a separate action**. No provider call is made here.
5. Reassess G1/G2 GO only after corresponding actual evidence is attached.

Primary ledger: https://github.com/robertbartlomiejski/morskamary/issues/291
Linear: https://linear.app/morskamary/issue/MOR-23
