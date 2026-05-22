<!--
  morskamary — Pull Request Template
  Aligned with docs/AGENT_WORKING_AGREEMENT.md § 3 (Canonical contribution contract)
-->

## Contribution declaration

<!-- Fill all five fields below. PRs with empty fields will be flagged during review. -->

### Objective
<!-- What does this PR accomplish? One sentence. -->


### Source basis
<!-- Which data, literature, or prior outputs does this change rely on? -->


### Axis logic
<!-- Which QMBD/TMBD axis (MARINE / MARITIME / OCEANIC / MULTI_AXIS) is affected and why? -->


### Expected artifact
<!-- Which output files, schemas, or capabilities change as a result? -->


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

---

## Testing

- [ ] `python -m pytest tests/ -q` passes (all green)
- [ ] No new test failures introduced
