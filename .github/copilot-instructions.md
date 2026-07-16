# GitHub Copilot instructions for morskamary

## Mission and authority

Treat this repository as a publication-oriented Blue Sociology research infrastructure, not a demo project. Preserve the complete chain:

theory -> research question/hypothesis -> construct -> variable -> indicator -> measure -> source -> method -> result -> interpretation -> contribution.

Read `docs/AGENT_WORKING_AGREEMENT.md` before changing scientific logic. Repository evidence and executable configuration outrank prose summaries and prior agent claims.

## Canonical axis contract

The current analytical contract has four stable axis identities:

| Canonical name | Display code | Meaning |
|---|---:|---|
| `MARINE` | `M` | biophysical, ecological and more-than-human agency or constraints |
| `MARITIME` | `T` | labour, technology, infrastructure, economy and institutional mediation |
| `OCEANIC` | `O` | planetary coupling, transboundary governance and hydrosocial responsibility |
| `HYDRONIZATION` | `H` | water-mediated transformation, hydro-social relations and translation across terrestrial/aquatic systems |

Do not reduce the four-axis QMBD contract to the legacy three-axis TMBD description. Store canonical names and display codes in separate fields. Never infer the number or names of hypotheses from the number of axes: load all declared hypothesis identifiers and definitions from the authoritative protocol/configuration and serialize every declared result, including `not_computable`.

## Scientific evidence rules

- Query text expresses retrieval intent; it is not empirical evidence.
- `source_query` may support provenance, query binding, diversity and bias diagnostics only. It must never create a competence signal, hypothesis fragment, novelty event, demand score or gap finding.
- Positive semantic evidence may come only from legally retained evidence text: title, subject terms, abstract or full text.
- Separate evidence, inference, hypothesis outcome, interpretation and recommendation in reports.
- Do not invent citations, authors, policy titles, empirical findings, competence labels or learning outcomes. Use `[citation needed]` until evidence is available.
- Candidate credential translations are proposals for review, not externally validated credential coverage.
- Unsupported, weak, negative or non-significant hypotheses are valid outcomes. Structural defects are pipeline failures.

## Layer 0-5 data contract

1. Layer 0: authoritative versioned query/theory/hypothesis protocol and deterministic provider projection.
2. Layer 1: immutable run-level acquisition evidence, raw indexes, provider health and query execution logs.
3. Layer 2: normalized canonical evidence plus append-only occurrence/provenance tables.
4. Layer 3: stable, classifier-versioned semantic signals and hypothesis fragments.
5. Layer 4: derived competence demands and statistics with fixed analysis timestamps.
6. Layer 5: sector-axis gaps, hypothesis outcomes and EQF 4-7 candidate translations.

Never overwrite historical occurrences. Build deterministic materialized views from immutable run history. Canonical identity, occurrence identity and semantic-signal identity are different entities and must remain separate.

## Required validity gates

Fail non-zero before report/package publication for:

- authoritative protocol/projection mismatch;
- missing required fields or declared hypothesis output;
- static-baseline contamination of live evidence;
- healthy requested provider with zero contribution when strict contribution gating is enabled;
- query-only semantic matches;
- unstable cross-run novelty identity;
- missing package artifact, invalid schema, manifest or checksum;
- absolute local/runner paths or secrets in public artifacts.

Report provider failure, throttling, invalid credentials and zero contribution separately. Never replace real live-provider validation with fixtures. Fixtures are permitted only for deterministic unit/integration tests and must be labelled as fixtures.

## Engineering and provenance

- Normal analysis is `live-enriched`. Static mode is recovery-only and requires `ALLOW_STATIC_RECOVERY_MODE=true` plus an explicit reason.
- Use repository-relative POSIX paths in persisted metadata. Redact out-of-repository paths.
- Keep logs ASCII-safe with `[INFO]`, `[OK]`, `[WARN]` and `[ERROR]`.
- Use Python supported by `pyproject.toml`; run tools as `python -m ...`.
- No secret, token, browser cookie, OAuth state or credential may be committed, printed or placed in an artifact.
- Update tests, schemas, documentation, `CHANGELOG.txt` and generated-governance manifests when their contracts change.
- Preserve unrelated user changes and generated archives. Do not regenerate or commit large outputs unless the task explicitly requires it.

## Agent work discipline

Use one canonical branch and one PR per coherent objective. Before editing, reconcile the current base SHA, open PRs and overlapping paths. Do not start a parallel implementation of active PR work. State objective, source basis, axis logic, expected artifact, acceptance criteria and validation commands in the PR.

Minimum validation for code changes:

```bash
python -m flake8 src scripts tests run_full_analysis.py main.py
python -m mypy src scripts run_full_analysis.py main.py
python -m pytest tests/ -v
python scripts/validate_generated_outputs.py
python scripts/validate_run_archive_integrity.py --archive-root outputs/run_archive --require-present
```

Run only the subset relevant to documentation/configuration-only changes, and report exactly what was and was not executed.
