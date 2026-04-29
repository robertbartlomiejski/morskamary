# Research API CI/CD Setup

This document describes how to set up the optional research API integration
for morskamary, including GitHub Actions secrets, environment variables, and
provider configuration.

## Architecture

```
morskamary (Python-first, GitHub Actions primary)
     │
     ├── src/scientific_sources/   ← Provider architecture
     │     ├── crossref.py         ← Always configured (open API)
     │     ├── elsevier_scopus.py  ← Gated on ELSEVIER_API_KEY / SCOPUS_API_KEY
     │     ├── web_of_science.py   ← Gated on WOS_API_KEY
     │     ├── scival.py           ← Gated on SCIVAL_API_KEY
     │     ├── google_drive.py     ← Gated on GOOGLE_DRIVE_OAUTH_CREDENTIALS
     │     └── microsoft_graph.py  ← Gated on MICROSOFT_TENANT_ID etc.
     │
     ├── scientific_bridge.py      ← MCP server (thin adapter over providers)
     │
     ├── .github/workflows/
     │     ├── ci.yml              ← Primary CI (no API keys needed)
     │     ├── full-analysis.yml   ← Full analysis (no API keys needed)
     │     └── research-api-smoke.yml  ← Optional: workflow_dispatch only
     │
     └── infra/gcp-mirror/         ← Optional Cloud Build mirror (Terraform)
```

## Environment variables

| Variable | Provider | Required |
|---|---|---|
| `CROSSREF_MAILTO` | Crossref | Optional (improves rate limits) |
| `ELSEVIER_API_KEY` | Elsevier / Scopus | Institutional |
| `SCOPUS_API_KEY` | Scopus | Institutional |
| `WOS_API_KEY` | Web of Science | Institutional |
| `SCIVAL_API_KEY` | SciVal | Institutional |
| `GOOGLE_DRIVE_OAUTH_CREDENTIALS` | Google Drive | Local OAuth JSON path |
| `MICROSOFT_TENANT_ID` | Microsoft Graph | Azure app registration |
| `MICROSOFT_CLIENT_ID` | Microsoft Graph | Azure app registration |
| `MICROSOFT_CLIENT_SECRET` | Microsoft Graph | Azure app registration |
| `LIVE_RESEARCH_API_TESTS` | All | Set `true` to enable live calls |
| `GCP_PROJECT_ID` | Cloud Build | GCP project for mirror |

## Local setup

See `docs/ONE_CLICK_RESEARCH_RUNBOOK.md` for the complete step-by-step guide.

Quick start:

```bash
pip install -e .[dev]
./scripts/bootstrap_research_secrets.sh --backend dotenv
python scripts/check_research_env.py
python scripts/smoke_scientific_bridge.py --offline
```

The legacy `user-env` alias still works, but `dotenv` is the canonical backend name for the supported `./scripts/bootstrap_research_secrets.sh` workflow.

## GitHub Actions setup

1. Go to repository Settings → Secrets and Variables → Actions
2. Add repository secrets for each provider key you have
3. Trigger the research API smoke workflow manually:
   - Actions → Research API Smoke → Run workflow

Or use the GitHub CLI:

```bash
gh secret set CROSSREF_MAILTO
gh secret set ELSEVIER_API_KEY
gh secret set SCOPUS_API_KEY
gh secret set WOS_API_KEY
gh secret set SCIVAL_API_KEY
```

## Google Secret Manager setup

After running `terraform apply` in `infra/gcp-mirror/`:

```bash
./scripts/bootstrap_research_secrets.sh --backend gcp \
  --project-id YOUR_PROJECT_ID
```

## Safety rules

1. Never commit API keys, OAuth JSON, or tokens to the repository.
2. Never put secrets in cloudbuild.yaml directly — use `availableSecrets`.
3. Never run `gcloud secrets versions add` with a value in a shell command
   (use `--data-file=-` to read from stdin).
4. Store only permitted bibliographic metadata, not restricted database payloads.
5. Live API tests must be explicitly enabled (`LIVE_RESEARCH_API_TESTS=true`).
6. GitHub Actions primary CI must pass without any external API keys.
