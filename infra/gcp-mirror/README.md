# infra/gcp-mirror/README.md

# GCP Mirror — Terraform Scaffold

Optional Google Cloud Build mirror for morskamary CI.

**Normal GitHub Actions CI works without this.** This module is opt-in.

## What this creates

| Resource | Purpose |
|---|---|
| `google_project_service` | Enable required GCP APIs |
| `google_secret_manager_secret` × 5 | Empty containers for research API keys |
| `google_secret_manager_secret_iam_member` × 5 | Cloud Build can read each secret |
| `google_project_iam_member` | Cloud Build can write logs |

Secrets created (empty containers only — values injected by bootstrap script):

- `crossref-mailto`
- `elsevier-api-key`
- `scopus-api-key`
- `wos-api-key`
- `scival-api-key`

## Usage

```bash
cd infra/gcp-mirror
terraform init
terraform validate
terraform plan -var="project_id=YOUR_PROJECT_ID" -var="region=europe-west1"
terraform apply -var="project_id=YOUR_PROJECT_ID" -var="region=europe-west1"
terraform output secret_version_names
```

## After apply — populate secrets

```bash
cd ../../
./scripts/bootstrap_research_secrets.sh --backend gcp --project-id YOUR_PROJECT_ID
```

## Safety

- Secret **values** are never stored in Terraform state.
- `prevent_destroy = true` protects secrets from accidental `terraform destroy`.
- Cloud Build SA has only `secretmanager.secretAccessor` on specific secrets.
- No `owner` or `editor` roles are granted.

See `docs/GOOGLE_CLOUD_BUILD_OPTIONAL_SETUP.md` for the full setup guide.
