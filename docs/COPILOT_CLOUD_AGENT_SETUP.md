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

Enable either only after the controlled two-run validation passes and branch/ruleset protection is confirmed.

## Actions and branch protection

1. Keep **Actions -> General -> Workflow permissions** at read-only by default.
2. Keep `.github/workflows/copilot-setup-steps.yml` at `contents: read` only. The `contents: write` exception applies exclusively to a separately controlled output-publishing job.
3. Keep a `live-research` environment with required reviewer approval. An environment protects a job only after that job declares `environment: live-research`; the current canonical live workflows already do so and must continue to.
4. Protect `main`: require PRs, conversation resolution, a current branch, and the stable CI/governance checks observed on a successful PR.
5. Do not require a scheduled/manual live workflow as a PR check.
6. Use exactly one CodeQL setup. If an advanced `.github/workflows/codeql*.yml` exists, do not also enable default CodeQL setup.
7. Keep output auto-commit disabled until a bot branch + PR publication flow replaces direct pushes to `main`.

## Current workflow state to preserve

- `/home/runner/work/morskamary/morskamary/.github/workflows/full-live-analysis.yml`
  - runs under `live-research`
  - keeps `commit_outputs` default `false`
  - keeps publication behind `ALLOW_BOT_COMMITS` and `LIVE_OUTPUTS_AUTOCOMMIT`
  - captures one `ANALYSIS_TIMESTAMP_UTC`
  - passes that timestamp into Layer 4/5
  - passes the current-run raw acquisition index into the release package
- `/home/runner/work/morskamary/morskamary/.github/workflows/export-research-records.yml` runs under `live-research`
- `/home/runner/work/morskamary/morskamary/.github/workflows/research-api-smoke.yml` runs under `live-research`
- `/home/runner/work/morskamary/morskamary/.github/workflows/codeql.yml` is the repo-managed CodeQL workflow with stable checks `Analyze (actions)` and `Analyze (python)`
- `/home/runner/work/morskamary/morskamary/.github/workflows/copilot-setup-steps.yml` keeps `contents: read`

## Operator closure checklist for issue #198 and PR #208

### 1. Advance PR #208 immediately

- [ ] Update PR #208 body or comment to state that no repository code delta is required because current `main` already contains the timestamp and Gate A alias fixes.
- [ ] Record that the remaining work is operator-side GitHub configuration and controlled live validation, not a repository patch.
- [ ] Keep PR #208 draft unless it is being used only as an audit log; if it is audit-only with no file changes, close it after posting the final audit summary.

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
- [ ] Deployment branches are restricted to `main` and `claude/pr-190-build-live-cumulative-database`.
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

### 7. Controlled live validation gate for the former PR #191 line of work

Do this only after ordinary checks are green and review state is clean.

- [ ] Dispatch Run 1 from `claude/pr-190-build-live-cumulative-database`.
- [ ] Use the same documented protocol and settings intended for controlled validation.
- [ ] Set `commit_outputs=false`.
- [ ] Review Run 1 for provider health, query execution and filter audit, accepted/deduplicated/contributing counts, Layer 0-5 artifacts, archive integrity, package checksums, and no static-baseline contamination.
- [ ] Dispatch Run 2 with identical documented inputs.
- [ ] Again set `commit_outputs=false`.
- [ ] Produce and retain a machine-readable Run 1 vs Run 2 comparison.
- [ ] Produce and retain a validity-threat register.
- [ ] Confirm stable signal recurrence and zero-new novelty where appropriate.
- [ ] Confirm duplicate recurrence separation and provider enrichment behavior.
- [ ] Confirm no secret leakage and no prohibited raw proprietary payload retention.

### 8. Publication-path gate

- [ ] Keep `ALLOW_BOT_COMMITS=false`.
- [ ] Keep `LIVE_OUTPUTS_AUTOCOMMIT=false`.
- [ ] Do not enable either variable unless the controlled two-run validation is accepted.
- [ ] When publication is eventually enabled, require bot publication through a `bot/live-research/...` branch plus PR.
- [ ] If that bot PR does not trigger CI automatically, explicitly trigger or rerun CI before review.

### 9. Decision point for issue #198

Close #198 only when all of the following are true:

- [ ] Sections A-F are confirmed in GitHub settings.
- [ ] The repo-managed CodeQL setup is the only active CodeQL path.
- [ ] The `main` ruleset uses stable ordinary CI and CodeQL checks.
- [ ] Controlled Run 1 and Run 2 completed with `commit_outputs=false`.
- [ ] Run comparison and validity-threat register exist and were reviewed.
- [ ] No remaining conversation-resolution or branch-current blockers remain on the relevant PR path.
- [ ] A maintainer records the closure comment summarizing settings confirmed, protected environment confirmed, required check names locked, controlled validation completed, and whether publication variables remain disabled or are explicitly approved for later enablement.

### 10. Best next operator action

- [ ] Post a maintainer comment on PR #208 saying the repository already contains the required code-side fixes and that the remaining tasks are the manual GitHub settings audit, `main` ruleset finalization, and controlled two-run live validation needed to close #198.

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
