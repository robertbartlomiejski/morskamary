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

Keep the repository-level JSON minimal:

```json
{
  "inputs": [],
  "servers": {}
}
```

GitHub and Playwright MCP servers are already enabled by default. MCP tools execute autonomously, so add a custom server only for a documented use case, with an explicit read-only `tools` allowlist. Never use `"*"` for an authenticated scientific database server.

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

Recommended Actions variables during PR #193 hardening:

- `ALLOW_BOT_COMMITS=false`
- `LIVE_OUTPUTS_AUTOCOMMIT=false`

Enable either only after the controlled two-run validation passes and branch/ruleset protection is confirmed.

## Actions and branch protection

1. Keep **Actions -> General -> Workflow permissions** at read-only by default.
2. Keep `.github/workflows/copilot-setup-steps.yml` at `contents: read` only. The `contents: write` exception applies exclusively to a separately controlled output-publishing job.
3. Create a `live-research` environment with required reviewer approval. An environment protects a job only after that job declares `environment: live-research`; creating it alone does not gate the current live workflows. Wire the environment and move provider secrets on the canonical workflow-owning branch (currently draft PR #191 for `full-live-analysis.yml`) before claiming reviewer-gated live acquisition. Do not modify that overlapping Layer 0-5 workflow from PR #193.
4. Protect `main`: require PRs, conversation resolution, a current branch, and the stable CI/governance checks observed on a successful PR.
5. Do not require a scheduled/manual live workflow as a PR check.
6. Use exactly one CodeQL setup. If an advanced `.github/workflows/codeql*.yml` exists, do not also enable default CodeQL setup.
7. Keep output auto-commit disabled until a bot branch + PR publication flow replaces direct pushes to `main`.

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
