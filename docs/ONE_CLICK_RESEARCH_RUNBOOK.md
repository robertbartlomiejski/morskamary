# One-Click Research API Runbook

> **Implementation status** (April 2026)
> - ✅ **Crossref** — fully implemented (open API, no key required)
> - 🔧 **Elsevier / Scopus / Web of Science / SciVal** — provider stubs (Phase 2)
>   These providers are capability-gated: the architecture and IAM are in place,
>   but live proprietary API calls are not yet implemented. Stubs return structured
>   "not configured" results without crashing.

This document describes the complete workflow for setting up and running the
morskamary research API integration from scratch — from credential bootstrap
to full analysis with Cloud Build mirror.

## Overview

```
First-time setup (once)        Everyday use (one command)
─────────────────────────      ─────────────────────────
1. Clone repository            ./scripts/run_research_api_full.sh --live
2. pip install -e .[dev]
3. Bootstrap secrets
4. (Optional) Terraform infra
```

## Prerequisites

- Python ≥ 3.9
- Git
- (Optional) `gcloud` CLI for Google Cloud mirror
- (Optional) `gh` CLI for GitHub Actions secrets
- (Optional) Terraform ≥ 1.3 for infrastructure provisioning

---

## First-time local setup

### 1. Clone and install

```bash
git clone https://github.com/robertbartlomiejski/morskamary.git
cd morskamary
python -m pip install --upgrade pip
python -m pip install -e .[dev]
python -m pytest tests/ -v   # verify: expect all tests to pass
```

### 2. Bootstrap research API secrets (local session)

```bash
./scripts/bootstrap_research_secrets.sh --backend dotenv
source .env                  # load into current terminal session
```

The script will prompt for each credential interactively (input is hidden).
Press ENTER to skip any credential you do not have yet.

The credentials are written to a `.env` file (gitignored) that you must
**`source`** to load into your current terminal. Unlike `export` in a child
shell, this approach persists the values in your current session.

**Windows / PowerShell:**
```powershell
.\scripts\bootstrap_research_secrets.ps1 -Backend DotEnv
. .\.env.ps1      # dot-source to load into current session
```

To make credentials persistent across sessions, add to your shell profile:

```bash
# ~/.bashrc or ~/.zshrc
[ -f /path/to/morskamary/.env ] && source /path/to/morskamary/.env
```

### 3. Verify environment

```bash
python scripts/check_research_env.py
```

### 4. Run offline smoke test (no API keys required)

```bash
python scripts/smoke_scientific_bridge.py --offline
```

---

## Everyday local full research run

```bash
./scripts/run_research_api_full.sh --live
```

This single command:
1. Checks Python version
2. Installs/updates the package
3. Runs `check_research_env.py`
4. Runs the offline smoke test
5. Runs the live API smoke test (for configured providers)
6. Runs `run_full_analysis.py`
7. Exports provider capabilities to `outputs/research_source_capabilities.json`
8. Validates research source outputs
9. Prints a summary of configured providers and output file paths

Without `--live`, live API calls are skipped (safe for offline use).

---

## First-time Google Cloud setup (optional mirror)

### 1. Authenticate

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

### 2. Provision infrastructure

```bash
cd infra/gcp-mirror
terraform init
terraform validate
terraform plan -var="project_id=YOUR_PROJECT_ID" -var="region=europe-west1"
terraform apply -var="project_id=YOUR_PROJECT_ID" -var="region=europe-west1"
terraform output secret_version_names   # note the paths for cloudbuild.yaml
cd ../..
```

### 3. Bootstrap secrets into Google Secret Manager

```bash
./scripts/bootstrap_research_secrets.sh --backend gcp \
  --project-id YOUR_PROJECT_ID
```

### 4. Verify secrets

```bash
gcloud secrets list --project=YOUR_PROJECT_ID
gcloud secrets versions list crossref-mailto --project=YOUR_PROJECT_ID
```

---

## Everyday Cloud Build remote run

**Cloud Build comes in two config files:**

| File | When to use |
|---|---|
| `cloudbuild.yaml` | Offline — no secrets required, no live API calls |
| `cloudbuild.live.yaml` | Live — requires Secret Manager secrets populated |

### Offline (no secrets required)

```bash
# Bash
./scripts/run_cloudbuild_research_full.sh --offline

# PowerShell
.\scripts\run_cloudbuild_research_full.ps1 -Offline

# Or directly
gcloud builds submit --config cloudbuild.yaml
```

### Full live research run (Crossref live; proprietary providers are stubs pending Phase 2)

```bash
# Bash
./scripts/run_cloudbuild_research_full.sh --live

# PowerShell
.\scripts\run_cloudbuild_research_full.ps1 -Live

# Or directly
gcloud builds submit --config cloudbuild.live.yaml
```

The wrapper scripts check gcloud authentication, project, Cloud Build API
availability, and (for live mode) secret version presence before submitting.

The Cloud Build run URL and log location are printed by `gcloud builds submit`.

---

## GitHub Actions secrets (optional)

To enable live API tests in GitHub Actions:

```bash
gh secret set CROSSREF_MAILTO
gh secret set ELSEVIER_API_KEY
gh secret set SCOPUS_API_KEY
gh secret set WOS_API_KEY
gh secret set SCIVAL_API_KEY
```

Verify:

```bash
gh secret list
```

The `.github/workflows/research-api-smoke.yml` workflow runs on
`workflow_dispatch` only and requires `LIVE_RESEARCH_API_TESTS=true` to
make live API calls.

---

## Generated output files

| File | Description |
|---|---|
| `outputs/research_source_capabilities.json` | Provider capability snapshot |
| `outputs/research_api_smoke_report.json` | Smoke test results |
| `outputs/literature_source_coverage.csv` | Literature coverage by provider |
| `outputs/literature_provider_overlap.csv` | DOI overlap across providers |
| `outputs/low_confidence_literature_review.json` | Records needing manual review |

---

## Safety checklist

- [ ] No API keys committed to the repository
- [ ] `config/research_sources.local.yml` is in `.gitignore`
- [ ] `.env` and `.secrets/` are in `.gitignore`
- [ ] OAuth JSON files are NOT in the repository
- [ ] Terraform secret versions are NOT in Terraform state
- [ ] Cloud Build logs do not print secret values
- [ ] Live API tests are disabled by default in GitHub Actions

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `ModuleNotFoundError: src.scientific_sources` | Run `pip install -e .` from repo root |
| `gcloud: command not found` | Install Google Cloud SDK |
| `Secret Manager secret not found` | Run `terraform apply` first, then bootstrap |
| `LIVE_RESEARCH_API_TESTS=true` but no live results | Check provider key is set and valid |
| All providers show "not configured" except Crossref | Run bootstrap script |
