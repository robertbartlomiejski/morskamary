# Google Cloud Build — Optional Setup Guide

This document explains how to set up the optional Google Cloud Build mirror
for morskamary. GitHub Actions remains the primary CI; this is opt-in.

## Prerequisites

- Google Cloud account with billing enabled
- `gcloud` CLI installed and authenticated
- Terraform ≥ 1.3 (for infrastructure provisioning)
- Institutional API keys for research providers (optional; not needed for
  the offline build steps)

---

## Option A: gcloud CLI path (manual)

### 1. Authenticate and set project

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

### 2. Enable APIs

```bash
gcloud services enable \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  logging.googleapis.com \
  iam.googleapis.com \
  serviceusage.googleapis.com
```

### 3. Create secret containers

```bash
for secret in crossref-mailto elsevier-api-key scopus-api-key wos-api-key scival-api-key; do
  gcloud secrets create "$secret" \
    --replication-policy=user-managed \
    --locations=europe-west1 \
    --project=YOUR_PROJECT_ID
done
```

### 4. Grant Cloud Build access

```bash
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

for secret in crossref-mailto elsevier-api-key scopus-api-key wos-api-key scival-api-key; do
  gcloud secrets add-iam-policy-binding "$secret" \
    --member="serviceAccount:${CB_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project=YOUR_PROJECT_ID
done

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/logging.logWriter"
```

### 5. Populate secrets (via bootstrap script)

```bash
./scripts/bootstrap_research_secrets.sh --backend gcp \
  --project-id YOUR_PROJECT_ID
```

### 6. Submit a build

Offline (no live API calls):

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_LIVE_RESEARCH_API_TESTS=false
```

Full research run (live APIs):

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_LIVE_RESEARCH_API_TESTS=true,_PROVIDER_STRICT_MODE=true
```

---

## Option B: Terraform path

### 1. Provision infrastructure

```bash
cd infra/gcp-mirror
terraform init
terraform validate
terraform plan -var="project_id=YOUR_PROJECT_ID" -var="region=europe-west1"
terraform apply -var="project_id=YOUR_PROJECT_ID" -var="region=europe-west1"
terraform output secret_version_names
```

### 2. Populate secrets

```bash
cd ../../
./scripts/bootstrap_research_secrets.sh --backend gcp \
  --project-id YOUR_PROJECT_ID
```

### 3. Submit a build (same as above)

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_LIVE_RESEARCH_API_TESTS=false
```

---

## GitHub connection for Cloud Build triggers (optional)

Cloud Build can trigger automatically on GitHub pushes, but this requires
an OAuth consent step that **cannot be automated by Terraform**.

To set up a GitHub connection:
1. Go to Cloud Console → Cloud Build → Triggers → Manage Repositories
2. Click "Connect Repository" and follow the OAuth flow
3. After the connection is created, Terraform can reference it by name
   (set `github_connection_name` variable)

Until the connection is created via Console, Cloud Build triggers cannot be
provisioned by Terraform. Use `gcloud builds submit` for manual triggering.

---

## Safety notes

- Secret **values** are never stored in Terraform state.
- `prevent_destroy = true` on all secret resources prevents accidental deletion.
- Cloud Build SA has only `secretmanager.secretAccessor` on specific secrets.
- No `owner` or `editor` roles are granted to Cloud Build.
- Cloud Build logs do not print secret values (injected via `secretEnv`).
- Live proprietary API calls require explicit `_LIVE_RESEARCH_API_TESTS=true`.

---

## Verifying the setup

```bash
# Check secrets exist
gcloud secrets list --project=YOUR_PROJECT_ID

# Check Cloud Build SA has access
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID \
  --format='value(projectNumber)')
gcloud secrets get-iam-policy crossref-mailto --project=YOUR_PROJECT_ID

# Run a test build
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_LIVE_RESEARCH_API_TESTS=false
```
