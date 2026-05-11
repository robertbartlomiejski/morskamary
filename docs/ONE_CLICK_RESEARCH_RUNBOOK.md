# One-Click Research API Runbook

> **Implementation status** (April 2026)
> - ✅ **Crossref** — fully implemented (open API, no key required)
> - ✅ **Elsevier / Scopus / Web of Science / SciVal** — live proprietary integrations
>   implemented with capability-gated behavior (missing/invalid credentials do not crash).
> - 🔧 **Google Drive / Microsoft Graph** — provider stubs (Phase 2)

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
python scripts/check_research_api_health.py --output outputs/research_api_health.json
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
6. Exports live records to `outputs/research_sources/live_records.json` (live mode)
7. Runs `run_full_analysis.py` in `live-enriched` mode when `--live` is used
8. Exports provider capabilities to `outputs/research_source_capabilities.json`
9. Validates research source outputs
10. Prints a summary of configured providers and output file paths

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

### Full live research run (Crossref + Scopus + WoS + SciVal live; workspace providers pending Phase 2)

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

## Preflight credential health statuses

`scripts/check_research_api_health.py` returns one of:

- `missing` — credential not provided.
- `present-but-invalid` — key present but rejected/unauthorized.
- `rate-limited` — provider throttled request.
- `ok` — authenticated probe succeeded.

Use `--require-valid` in CI/live runs to fail fast on invalid or throttled
credentials before long-running export workflows.

### Troubleshooting revoked/cancelled credentials

If status is `present-but-invalid`:

1. Confirm the account/subscription is still active in provider admin.
2. Regenerate or un-revoke API key/token.
3. Update local `.env` / GitHub Actions secret / Secret Manager value.
4. Re-run `python scripts/check_research_api_health.py --require-valid`.

---

## Exporting live research records

Export structured literature metadata from Crossref and other configured providers:

```bash
# Offline test (no network calls)
python scripts/export_live_research_records.py \
  --providers crossref \
  --query-file config/research_queries.yml \
  --max-results-per-query 50 \
  --output-dir outputs/research_sources \
  --offline true

# Live export (Crossref requires no API key; proprietary providers may require credentials)
python scripts/export_live_research_records.py \
  --providers crossref \
  --query-file config/research_queries.yml \
  --max-results-per-query 50 \
  --output-dir outputs/research_sources \
  --offline false
```

**What it does:**
- Fetches records for 12 canonical blue economy sectors (defined in `config/research_queries.yml`)
- Deduplicates by DOI first, then by normalized title
- Tracks full provenance (provider, query, timestamp, endpoint, confidence)
- Does NOT store abstracts or full text (licence compliance)

**Generated outputs:**
- `outputs/research_sources/live_records.json` — all deduplicated records
- `outputs/research_sources/live_records.csv` — CSV export
- `outputs/research_sources/crossref_records.json` — Crossref-only subset
- `outputs/research_sources/live_provenance.json` — provenance metadata
- `outputs/research_sources/live_source_coverage.csv` — coverage by sector/provider
- `outputs/research_sources/low_confidence_live_records.json` — records with confidence < 0.8

---

## Generated output files

| File | Description |
|---|---|
| `outputs/research_source_capabilities.json` | Provider capability snapshot |
| `outputs/research_api_smoke_report.json` | Smoke test results |
| `outputs/literature_source_coverage.csv` | Literature coverage by provider |
| `outputs/literature_provider_overlap.csv` | DOI overlap across providers |
| `outputs/low_confidence_literature_review.json` | Records needing manual review |
| `outputs/research_sources/live_records.json` | Live research records (all providers) |
| `outputs/research_sources/live_records.csv` | Live research records (CSV) |
| `outputs/research_sources/crossref_records.json` | Crossref-only records |
| `outputs/research_sources/live_provenance.json` | Provenance metadata for live records |
| `outputs/research_sources/live_source_coverage.csv` | Coverage by sector and provider |
| `outputs/research_sources/low_confidence_live_records.json` | Low-confidence records for manual review |

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

---

## How to obtain provider credentials

### Crossref

No signup is required. Use an institutional email address as `CROSSREF_MAILTO`.
This enables polite API use.

Source:
https://www.crossref.org/documentation/retrieve-metadata/rest-api/

### Elsevier / Scopus

Use the Elsevier Developer Portal. Create or sign in to an Elsevier Developer account, create an API key, and check whether your institutional subscription and IP entitlement allow Scopus access.

Environment variables:
- `ELSEVIER_API_KEY`
- `SCOPUS_API_KEY`

If one Elsevier key covers Scopus for your institution, set `ELSEVIER_API_KEY` first and skip `SCOPUS_API_KEY` unless a separate key is issued.

Source:
https://dev.elsevier.com/tecdoc_api_authentication.html

### SciVal

SciVal API access requires SciVal entitlement for academic or public-sector users. Use the Elsevier Developer Portal and confirm that your institution has SciVal access.

Environment variable:
- `SCIVAL_API_KEY`

Source:
https://dev.elsevier.com/scival_apis.html

### Web of Science

Use the Clarivate Developer Portal. Sign up, register an application, subscribe to the relevant Web of Science API, and wait for immediate or administrative approval where required.

Environment variable:
- `WOS_API_KEY`

Source:
https://developer.clarivate.com/

### Google Drive

The repository expects a local path to an OAuth client credentials JSON file, not a pasted API key.

Environment variable:
- `GOOGLE_DRIVE_OAUTH_CREDENTIALS`

Example:
`C:\Users\Pracownik\.secrets\google-drive-oauth.json`

Do not commit the OAuth JSON file.

### Microsoft Graph

Use Microsoft Entra / Azure App Registration. Collect:

- `MICROSOFT_TENANT_ID`
- `MICROSOFT_CLIENT_ID`
- `MICROSOFT_CLIENT_SECRET`

Do not commit client secrets.
