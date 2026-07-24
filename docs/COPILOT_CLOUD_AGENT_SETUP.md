# Copilot cloud agent and scientific automation setup

This document separates code-generation authority from live-research authority. Copilot may edit and validate code in an ephemeral environment. Live provider acquisition remains a controlled GitHub Actions operation with separate secrets and human approval.

## Repository settings

Open **Settings -> Copilot -> Cloud agent** and use:

| Setting | Value | Rationale |
|---|---|---|
| Enable firewall | On | Limits code/data exfiltration paths |
| Recommended allowlist | On | Allows supported package registries and browser dependencies |
| Custom allowlist | Empty initially | Add only a host demonstrated by a failed, reviewed task |
| Require approval for workflow runs | On | Agent code cannot use Actions/secrets before maintainer review |
| Allow automations | On | Permits scheduled maintenance after rules are established |
| Only users with write access may trigger automations | On | Reduces prompt-injection exposure |
| CodeQL validation | On | Security validation |
| Copilot code review | On | Second-pass code-quality review |
| Secret scanning | On | Detects committed credentials |
| Dependency vulnerability checks | On | Checks newly introduced dependencies |

Do not disable the firewall merely to make a provider request succeed. Provider APIs belong in controlled Actions jobs, not the agent development sandbox.

## MCP configuration

Keep the GitHub Copilot cloud agent repository-level JSON minimal:

```json
{
  "mcpServers": {}
}
```

This is GitHub Copilot's repository MCP schema. Do not copy the VS Code workspace `.vscode/mcp.json` shape (`inputs` + `servers`) into this setting. GitHub and Playwright MCP servers are already enabled by default. MCP tools execute autonomously, so add a custom server only for a documented use case, with an explicit read-only `tools` allowlist. Never use `"*"` for an authenticated scientific database server.

Do not configure Scopus, Web of Science, SciVal, Microsoft Graph, Google Drive or OpenAI credentials as Copilot Agents secrets merely to run the live pipeline. If a future read-only MCP server is approved, use a dedicated least-privilege credential prefixed `COPILOT_MCP_`, never the production Actions credential.

## Secrets and variables

Create live-provider credentials under **Settings -> Secrets and variables -> Actions**, not **Agents**:

- `CROSSREF_MAILTO`
- `ELSEVIER_API_KEY` / `SCOPUS_API_KEY` as required by the adapter
- `WOS_API_KEY`
- `SCIVAL_API_KEY`
- `MICROSOFT_TENANT_ID`
- `MICROSOFT_CLIENT_ID`
- `MICROSOFT_CLIENT_SECRET`

Never paste secret values into issues, PRs, prompts, logs, screenshots, committed files or Playwright storage state.

Recommended Actions variables during the controlled live-validation period:

- `ALLOW_BOT_COMMITS=false`
- `LIVE_OUTPUTS_AUTOCOMMIT=false`

Enable `ALLOW_BOT_COMMITS` only after the controlled two-run validation passes and branch/ruleset protection is confirmed. `LIVE_OUTPUTS_AUTOCOMMIT` additionally gates scheduled publication and should remain `false` until a scheduled publication cadence is explicitly approved.

## Actions and branch protection

1. Keep **Actions -> General -> Workflow permissions** at read-only by default.
2. Keep `.github/workflows/copilot-setup-steps.yml` at `contents: read` only. The `contents: write` exception applies exclusively to a separately controlled output-publishing job.
3. Keep a `live-research` environment with required reviewer approval. An environment protects a job only after that job declares `environment: live-research`; the current canonical live workflows already do so and must continue to.
4. Protect `main`: require PRs, conversation resolution, a current branch, and the stable CI/governance checks observed on a successful PR.
5. Do not require a scheduled/manual live workflow as a PR check.
6. Use exactly one CodeQL setup. If an advanced `.github/workflows/codeql*.yml` exists, do not also enable default CodeQL setup.
7. Keep output auto-commit disabled until a bot branch + PR publication flow replaces direct pushes to `main`.

## Current workflow state to preserve

- `.github/workflows/full-live-analysis.yml`
  - runs under `live-research`
  - keeps `commit_outputs` default `false`
  - gates manual-dispatch publication behind `ALLOW_BOT_COMMITS=true` and `commit_outputs=true`
  - gates scheduled publication behind `ALLOW_BOT_COMMITS=true` and `LIVE_OUTPUTS_AUTOCOMMIT=true`
  - captures one `ANALYSIS_TIMESTAMP_UTC`
  - passes that timestamp into Layer 4/5
  - passes the current-run raw acquisition index into the release package
- `.github/workflows/export-research-records.yml` runs under `live-research`
- `.github/workflows/research-api-smoke.yml` runs under `live-research`
- `.github/workflows/codeql.yml` is the repo-managed CodeQL workflow with stable checks `Analyze (actions)` and `Analyze (python)`
- `.github/workflows/copilot-setup-steps.yml` keeps `contents: read`

## Operator closure checklist for issue #198 and PR #208

### 1. Advance PR #208 immediately

- [ ] Update PR #208 body or comment to acknowledge that this PR adds governance-documentation changes (operator runbook and CHANGELOG entry); there is no production-code delta required because current `main` already contains the timestamp and Gate A alias fixes.
- [ ] Record that the remaining work is operator-side GitHub configuration and controlled live validation, not a repository code patch.
- [ ] If PR #208 is audit-only and the documentation additions are not needed, revert the file changes and close the PR after posting the final audit summary.

### 2. Reconfirm sections A-E in repository settings

- [ ] Copilot cloud agent firewall is On.
- [ ] Recommended allowlist is On.
- [ ] Custom allowlist is empty.
- [ ] Workflow-run approval is On.
- [ ] Automations are allowed.
- [ ] Only users with write access may trigger automations.
- [ ] Validation tools are On: CodeQL, Copilot code review, secret scanning, dependency vulnerability checks.
- [ ] Repository MCP JSON is still `{"mcpServers": {}}`.
- [ ] Actions variables remain disabled:
  - [ ] `ALLOW_BOT_COMMITS=false`
  - [ ] `LIVE_OUTPUTS_AUTOCOMMIT=false`

### 3. Reconfirm protected environment `live-research`

- [ ] Environment `live-research` exists.
- [ ] Required reviewer is the repository owner or maintainer.
- [ ] Self-review prevention is configured without creating an impossible gate for a sole maintainer.
- [ ] Deployment branches are restricted to `main` only. (The `claude/pr-190-build-live-cumulative-database` branch was only needed during the PR #191 controlled validation period and has since been merged and deleted.)
- [ ] Provider credentials exist only in the `live-research` environment, not as repository-level Actions secrets.
- [ ] No provider credentials exist in Copilot Agent secrets, MCP config, PR text, logs, or artifacts.

### 4. Reconfirm workflows that must stay environment-gated

- [ ] `Full Live-Enriched Analysis` uses `environment: live-research`.
- [ ] `Export Live Research Records` uses `environment: live-research`.
- [ ] `Research API Smoke` uses `environment: live-research`.
- [ ] `Copilot Setup Steps` remains read-only and does not receive production provider credentials.

### 5. Reconfirm CodeQL single-setup policy

- [ ] GitHub Default CodeQL setup is disabled for the repository.
- [ ] No organization policy is forcing default setup back on.
- [ ] Only the repo-managed workflow is active.
- [ ] Stable CodeQL required-check names are:
  - [ ] `Analyze (actions)`
  - [ ] `Analyze (python)`

### 6. Finalize the `main` ruleset

- [ ] Require pull request.
- [ ] Require at least one approval.
- [ ] Require conversation resolution.
- [ ] Require branch to be up to date before merge.
- [ ] Block force pushes.
- [ ] Block branch deletion.
- [ ] Do not require scheduled or manual live workflows as normal PR checks.
- [ ] Add the stable ordinary required checks from CI:
  - [ ] `conflict-marker-check`
  - [ ] `governance-and-repro`
  - [ ] `quick-mode-gate`
  - [ ] `static-quality`
  - [ ] all `test-suite` matrix checks that appear on reviewed PRs
- [ ] Add required CodeQL checks:
  - [ ] `Analyze (actions)`
  - [ ] `Analyze (python)`

### 7. Controlled live validation gate

Do this only after ordinary checks are green and review state is clean.

**Known limitations to account for before dispatching:**

- **Run 1 archive handoff**: With `commit_outputs=false`, Run 1 uploads its updated `outputs/run_archive` as an artifact but does not commit it. Run 2 dispatched from a fresh checkout will compare against the older committed archive baseline, not Run 1's output. To get a valid Run 1 vs Run 2 recurrence comparison you must either commit Run 1's archive before dispatching Run 2, or download the Run 1 artifact and supply it as a prior-archive input to Run 2.
- **Strict gate vs zero-novelty**: `compute_live_novelty_metrics.py --strict` Gate B fails when both new-DOI and semantic-new-signal counts are zero. A truly identical repeat run will produce zero new novelty and therefore fail Gate B under `--strict`. This is the expected outcome for a recurrence confirmation; document the Gate B failure as expected, or run Run 2 outside the strict publication gate for the purpose of comparing outputs.
- **Analysis timestamp**: Each dispatch unconditionally captures a new `ANALYSIS_TIMESTAMP_UTC`, which feeds temporal-recency scores, demand-strength classifications, and hypothesis results. To compare Run 1 and Run 2 artifacts on evidence behavior rather than elapsed time, supply Run 1's timestamp as a fixed input to Run 2.
- **Raw provider payloads**: `outputs/research_sources/raw_api_payloads` and `outputs/live_runs/.../raw/raw_api_payloads` may contain fields whose license prohibits redistribution. The `git reset` in the publish step prevents commit but does not remove the 30-day artifact upload. Ensure the workflow or a pre-upload step strips prohibited fields before uploading all of `outputs/`.

- [ ] Dispatch Run 1 from `main` (verified current SHA).
- [ ] Use the same documented protocol and settings intended for controlled validation.
- [ ] Set `commit_outputs=false`.
- [ ] Review Run 1 for provider health, query execution and filter audit, accepted/deduplicated/contributing counts, Layer 0-5 artifacts, archive integrity, package checksums, and no static-baseline contamination.
- [ ] Confirm no prohibited raw proprietary payload fields are present in the uploaded artifacts.
- [ ] Before dispatching Run 2, ensure Run 1's archive is available as the prior-archive baseline (commit it to the branch, or supply it as an artifact input). Record Run 1's `ANALYSIS_TIMESTAMP_UTC` for use in Run 2.
- [ ] Dispatch Run 2 from the same `main` revision with identical documented inputs and `commit_outputs=false`.
- [ ] Supply Run 1's `ANALYSIS_TIMESTAMP_UTC` and archive as inputs so the comparison reflects evidence behavior, not elapsed time.
- [ ] Expect and document Gate B failure on zero-novelty as the correct recurrence outcome rather than treating it as a blocking error.
- [ ] Produce and retain a machine-readable Run 1 vs Run 2 comparison.
- [ ] Produce and retain a validity-threat register.
- [ ] Confirm stable signal recurrence and zero-new novelty where appropriate.
- [ ] Confirm duplicate recurrence separation and provider enrichment behavior.
- [ ] Confirm no secret leakage and no prohibited raw proprietary payload retention.

### 8. Publication-path gate

Publication gates differ between manual dispatch and scheduled runs:

- **Manual dispatch**: publication runs when `ALLOW_BOT_COMMITS=true` AND `commit_outputs=true` (the `workflow_dispatch` input).
- **Scheduled run**: publication runs when `ALLOW_BOT_COMMITS=true` AND `LIVE_OUTPUTS_AUTOCOMMIT=true`. Setting only `ALLOW_BOT_COMMITS=true` without `LIVE_OUTPUTS_AUTOCOMMIT=true` does **not** enable scheduled publication. Conversely, leaving `LIVE_OUTPUTS_AUTOCOMMIT=false` does not disable manual dispatch publication when `commit_outputs=true` is explicitly passed.

- [ ] Keep `ALLOW_BOT_COMMITS=false`.
- [ ] Keep `LIVE_OUTPUTS_AUTOCOMMIT=false`.
- [ ] Do not enable either variable unless the controlled two-run validation is accepted.
- [ ] Before enabling bot commits, verify that **Settings → Actions → General → Allow GitHub Actions to create and approve pull requests** is enabled; without it, `gh pr create` will fail and leave an orphan branch.
- [ ] When publication is eventually enabled, require bot publication through a `bot/live-research/...` branch plus PR.
- [ ] If that bot PR does not trigger CI automatically, explicitly trigger or rerun CI before review.

### 9. Issue #198 closure — audit record

Issue #198 was closed as completed on 2026-07-23. All sections A–G were confirmed:

- [x] **A** — Copilot cloud agent settings (firewall, allowlists, approval, automations, MCP).
- [x] **B** — Actions variables disabled (`ALLOW_BOT_COMMITS=false`, `LIVE_OUTPUTS_AUTOCOMMIT=false`).
- [x] **C** — Protected `live-research` environment with required reviewer, restricted deployment branches, and provider credentials in environment only.
- [x] **D** — CodeQL single-setup: default setup disabled, repo-managed `Analyze (actions)` and `Analyze (python)` pass.
- [x] **E** — Actions permissions: default read-only, bot-PR publication path defined, workflow-run approval enabled.
- [x] **F** — `main` ruleset: PR required, approval, conversation resolution, branch current, stable CI and CodeQL checks, force-push blocked.
- [x] **G** — Controlled two-run live validation (Run 1 and Run 2 on `claude/pr-190-build-live-cumulative-database`, `commit_outputs=false`): provider health, Layer 0–5 artifacts, archive integrity, recurrence and novelty, duplicate separation, no static-baseline contamination, no secret leakage.

If future changes require re-opening any of the above items, track them in a new issue rather than reopening #198.

### 10. Best next operator action

- [ ] Post a maintainer comment on PR #208 confirming that issue #198 is closed and this runbook records the completed audit state.

## Agent task contract

Every delegated implementation must specify:

- canonical branch and base SHA;
- objective and paths in scope;
- authoritative protocol/configuration;
- theoretical/axis and unit-of-analysis contract;
- acceptance criteria and negative controls;
- commands to validate;
- prohibition on fixtures as evidence of live-provider success;
- exact blocker reporting for credentials, firewall or network access.

Use one canonical branch and one PR per coherent objective. Before editing any path, reconcile the current base SHA, open PRs and overlapping paths. Do not start a parallel Layer 0-5 implementation while another is active.

## Windows local workstation

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
winget install --id Python.Python.3.11 -e

gh auth login --web --git-protocol https
git clone https://github.com/robertbartlomiejski/morskamary.git
Set-Location morskamary
gh repo set-default robertbartlomiejski/morskamary

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest tests/ -q
git remote -v
```

Use Git Credential Manager or `gh auth login`; do not put a personal access token in a remote URL. For normal work, branch from updated `main`, push one branch, and open a draft PR.

## Playwright authentication state

The supplied `playwright_setup.py` captures cookies and local storage. Do not use it for GitHub, Scopus, Web of Science, SciVal, Microsoft or Google accounts in this repository. Browser storage state is a bearer credential and must never enter `outputs/`, Actions artifacts or Git history. Prefer OAuth/API credentials stored in the appropriate secret store.
