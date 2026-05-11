# morskamary — Repository Overview

## What this repository is

`morskamary` is a **research infrastructure** for Blue Sociology — an applied extension
of maritime sociology for the EU Sustainable Blue Economy and "one ocean" governance.

Its primary function is to support **competence mapping and micro-credential design**
grounded in the Quadripartite Model of Blue Dynamics (QMBD), which extends the
original Tripartite Model of Blue Dynamics (TMBD):

| Axis | Code | Domain |
|---|---|---|
| Marine | M | Biophysical and ecological agency and constraints |
| Maritime | T | Techno-economic, infrastructural, labour, and institutional mediation |
| Oceanic | O | Planetary coupling, multi-level governance, hydrosocial subjectivity |
| Hydronization | H | Water-society co-constitution, wet-ontological reframing, and hydrosocial mediation |

Every **competence** and competence-derived analysis in the repository maps to
exactly one of these four axes. This is not optional — the QMBD framework is the
analytic spine of the entire project.

The QMBD extends the original Tripartite Model of Blue Dynamics (TMBD) with a
fourth axis, Hydronization, added following the Manus methodological review. All
existing TMBD logic is preserved and the new axis is additive only. See
`src/core.py` (`BlueDynamicsAxis` enum) for the canonical representation.

Literature records retrieved from providers (`LiteratureRecord`) are **not**
automatically classified by axis. Axis assignment for literature is applied
downstream during competence mapping and manuscript analysis. The automated
`AxisClassifier` assigns **exactly one** QMBD axis label per text fragment;
researchers may manually associate a record with more than one axis, but the
classifier itself is single-label. Do not assume that a literature record in the
repository has a pre-assigned axis.

Clarification on literature axis assignment: QMBD axis assignment is a downstream,
derived analytical step performed on extracted, deduplicated text fragments (not
on raw ingested bibliographic metadata). Fragment-level provenance hashing ensures
that the same DOI-linked sentence is counted only once in cumulative semantic
analysis.

The repository combines:

- **Domain models** — `Competence`, `MicroCredential`, `BlueDynamicsAxis`
  (see `src/core.py`)
- **Multi-provider bibliographic ingestion** — six provider adapters that normalise
  records into a single `LiteratureRecord` format (see `src/scientific_sources/`)
- **NLP reliability controls** — deduplication, confidence scoring, and
  cross-source triangulation (see `src/nlp_reliability/`)
- **Operational scripts** — deterministic manifest generation, sanitised CSV export,
  environment audits, and smoke tests (see `scripts/`)
- **Data governance** — explicit rules for raw inputs, derived outputs, and
  provenance traceability (see `DATA_GOVERNANCE.txt` and `CITATION.txt`)

---

## What this repository is not

| This is NOT | Why it matters |
|---|---|
| A public-facing API product | No SLA, rate-limiting, or uptime guarantee |
| A substitute for institutional database subscriptions | Proprietary providers (Scopus, WoS) are capability-gated; access requires your own credentials |
| A general-purpose literature database | Scope is confined to Blue Sociology, QMBD competences, and EU blue economy policy |
| A place to store full-text articles or abstracts | Publisher copyright prevents this; only bibliographic metadata fields are permitted |
| A validated machine-learning system | The repository's rule-based QMBD/TMBD axis classifier uses a deterministic map, not a trained model; reported accuracy reflects rule-label circularity in the current baseline |

---

## Intended audience

- **Research contributors** who add competences, literature records, or derived
  datasets — read this document and `DATA_GOVERNANCE.txt` first.
- **PhD students and collaborators** who use the outputs for manuscript writing —
  read `LLM_CONTEXT_INSTRUCTION.txt` and `CITATION.txt`.
- **Developers** who maintain or extend the provider architecture — read
  `docs/providers.md` and `docs/onboarding_new_provider.md`.
- **Reviewers and auditors** who assess compliance — read
  `docs/licensing_and_compliance.md`.

---

## How this repository is organised

```
src/                        Python package — domain models, provider adapters, NLP
scripts/                    Operational scripts (run standalone, not imported)
data/raw/                   Immutable source inputs — never overwrite
data/derived/               Reproducible outputs — generated from raw sources
docs/                       Human-readable contracts and governance documents
.github/workflows/          CI — enforces integrity rules automatically
outputs/                    Runtime export files — not committed to the repository
```

---

## CI and enforcement — Stage 0 baseline note

CI existed before this document was written. The following is an accurate
statement of the CI baseline as it stands:

**What CI currently enforces (hard fail):**

1. Unresolved merge conflict markers block merges.
2. Required governance files (`CITATION.txt`, `DATA_GOVERNANCE.txt`,
   `LLM_CONTEXT_INSTRUCTION.txt`, `CHANGELOG.txt`, `README.md`) must be present.
3. `MANIFEST_SOURCES.csv` must be reproducible — running `scripts/generate_manifest.py`
   must produce no diff against the committed file.
4. Pull requests that change `scripts/`, `data/`, or governance text files must also
   update `CHANGELOG.txt`.
5. The full test suite must pass on Python 3.10, 3.11, and 3.12.
6. The dependency graph snapshot is submitted to GitHub on every push to `main`.

**What CI does not yet enforce:**

- Licence acceptability rules for specific providers or data categories.
- Provider-specific metadata field constraints (those are currently documented in
  `docs/RESEARCH_SOURCE_GOVERNANCE.md` but not machine-checked).
- Research metadata schema conformance (schema design is a future stage).

This distinction is intentional. Integrity enforcement already exists and is frozen
as the baseline. Licence and content enforcement will be added only after the rules
are written down in plain English — which is the purpose of Stage 1 documentation.

---

## North star

> Transform morskamary into a research-grade, auditable, licence-safe infrastructure
> that supports long-term scientific use without retroactively breaking existing
> workflows.

Every document in `docs/` is subordinate to this aim.
