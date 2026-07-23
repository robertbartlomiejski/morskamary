# Agent Working Agreement — morskamary

This checklist is the shared operating contract for all contributors (human and AI)
to keep work aligned with repository purpose and scientific aims.

## 1) Shared mission lock

- [ ] Treat morskamary as an evidence-driven Blue Sociology research/tooling repository.
- [ ] Keep scientific purpose primary: QMBD/TMBD-grounded analysis, policy relevance, reproducible outputs.

## 2) Non-negotiable scientific rules

- [ ] Use repository evidence only for substantive claims; otherwise mark `[citation needed]`.
- [ ] Apply the quote-then-reason pattern for new conceptual claims.
- [ ] Classify competences and outputs by QMBD axis and sector relevance.

## 3) Canonical contribution contract

Every substantive contribution must state:

- [ ] Objective
- [ ] Source basis
- [ ] Axis logic
- [ ] Expected artifact
- [ ] What changed, why, and which scientific aim it supports

## 4) Task-start declaration

Before editing any path:

- [ ] Read `.github/copilot-instructions.md`, this agreement, `config/live_query_protocol.yml`, the nearest `AGENTS.md`, and applicable `.github/instructions/*.instructions.md`.
- [ ] Record the current branch and base SHA.
- [ ] Check relevant open PRs and overlapping files.
- [ ] Declare paths in scope, authoritative scientific/configuration sources, acceptance criteria, and validation commands.
- [ ] Use one branch and one draft PR per coherent objective; never push directly to `main`.

## 5) Single operating pipeline

- [ ] Ingestion/provenance
- [ ] Classification/mapping
- [ ] Analysis outputs
- [ ] Validation/governance checks

No side workflow should bypass provenance, validation, or changelog governance.

## 6) One-command operating modes

Use:

- `./scripts/run_research_api_full.sh --mode quick`
- `./scripts/run_research_api_full.sh --mode full-static`
- `./scripts/run_research_api_full.sh --mode full-live`

PowerShell equivalents are supported via `scripts/run_research_api_full.ps1`.

## 7) Scientific consistency gates (must pass)

- [ ] `python scripts/validate_generated_outputs.py`
- [ ] `python scripts/validate_research_source_outputs.py`
- [ ] Deterministic manifests and changelog governance checks in CI

## 8) Usability and diagnostics

- [ ] Start each run with provider capability diagnostics.
- [ ] Keep errors actionable: what failed, why, and exact next command.
- [ ] If blocked, report the exact blocker, affected file/workflow, evidence, safest next action, and the command or setting the maintainer should use.

## 9) Micro-credential quality baseline

Each credential must retain required fields:

- title, learner profile, workload/ECTS, EQF level
- learning outcomes, assessment method
- prerequisites and stackability rules

## 10) Governance and reproducibility alignment

- [ ] Respect FAIR/CARE and repository traceability rules.
- [ ] Update `CHANGELOG.txt` for substantive tracked changes.
- [ ] Regenerate `MANIFEST_SOURCES.csv` for new, removed, or renamed files.
- [ ] Never print secrets or `.env` contents; secret checks may report only present, absent, invalid, rate-limited, or configured.

## 11) Collaboration cadence

- [ ] Work incrementally: plan → implementation → validation → evidence review.
- [ ] Verify alignment to scientific aims at each checkpoint before expanding scope.
- [ ] A fix is incomplete until a negative regression test, the relevant integration path, and generated artifacts/manifests/checksums are all covered and the PR reports exactly what was and was not validated.
