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

## 4) Single operating pipeline

- [ ] Ingestion/provenance
- [ ] Classification/mapping
- [ ] Analysis outputs
- [ ] Validation/governance checks

No side workflow should bypass provenance, validation, or changelog governance.

## 5) One-command operating modes

Use:

- `./scripts/run_research_api_full.sh --mode quick`
- `./scripts/run_research_api_full.sh --mode full-static`
- `./scripts/run_research_api_full.sh --mode full-live`

PowerShell equivalents are supported via `scripts/run_research_api_full.ps1`.

## 6) Scientific consistency gates (must pass)

- [ ] `python scripts/validate_generated_outputs.py`
- [ ] `python scripts/validate_research_source_outputs.py`
- [ ] Deterministic manifests and changelog governance checks in CI

## 7) Usability and diagnostics

- [ ] Start each run with provider capability diagnostics.
- [ ] Keep errors actionable: what failed, why, and exact next command.

## 8) Micro-credential quality baseline

Each credential must retain required fields:

- title, learner profile, workload/ECTS, EQF level
- learning outcomes, assessment method
- prerequisites and stackability rules

## 9) Governance and reproducibility alignment

- [ ] Respect FAIR/CARE and repository traceability rules.
- [ ] Update `CHANGELOG.txt` for substantive tracked changes.

## 10) Collaboration cadence

- [ ] Work incrementally: plan → implementation → validation → evidence review.
- [ ] Verify alignment to scientific aims at each checkpoint before expanding scope.
