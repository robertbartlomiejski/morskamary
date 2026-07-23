<!--
  morskamary — Pull Request Template
  Aligned with docs/AGENT_WORKING_AGREEMENT.md § 3 (Canonical contribution contract)
-->

## Contribution declaration

<!-- Fill all fields below. PRs with empty fields will be flagged during review. -->

### Current branch / base SHA
<!-- Record the working branch and the base SHA reconciled before editing. -->


### Relevant open PRs / overlapping files
<!-- Note overlapping active PRs or confirm that none overlap the paths in scope. -->


### Objective
<!-- What does this PR accomplish? One sentence. -->


### Paths in scope
<!-- Which repository paths are intentionally in scope for this objective? -->


### Source basis
<!-- Which data, literature, or prior outputs does this change rely on? -->


### Authoritative scientific/configuration source
<!-- Which protocol/configuration governs this change (for example config/live_query_protocol.yml)? -->


### Axis logic
<!-- Which QMBD/TMBD axis (MARINE / MARITIME / OCEANIC / MULTI_AXIS) is affected and why? -->


### Expected artifact
<!-- Which output files, schemas, or capabilities change as a result? -->


### Acceptance criteria
<!-- What must be true for this fix/change to be considered complete? -->


### Validation commands
<!-- List the exact commands or checks that will be run for this PR. -->


### What changed, why, and which scientific aim it supports
<!-- Brief summary linking the change to a repository scientific aim. -->


---

## Sync & integration checklist

- [ ] `python scripts/sync_audit.py` passes locally (no drift detected)
- [ ] `python scripts/validate_generated_outputs.py` passes
- [ ] `python scripts/validate_research_source_outputs.py` passes
- [ ] `CHANGELOG.txt` updated for substantive tracked changes
- [ ] `MANIFEST_SOURCES.csv` regenerated and committed if data files changed
- [ ] No unresolved merge conflict markers
- [ ] Generated artifacts, manifests, and checksums remain complete where applicable

---

## Testing

### Negative regression coverage

- [ ] A regression test demonstrates the previous failure mode
- [ ] The relevant integration path is exercised

### Executed validation

- [ ] `python -m pytest tests/ -q` passes (all green)
- [ ] No new test failures introduced
- [ ] This PR body states exactly what was and was not validated
