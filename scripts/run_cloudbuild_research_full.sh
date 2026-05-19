#!/usr/bin/env bash
# scripts/run_cloudbuild_research_full.sh
#
# One-command Cloud Build wrapper for morskamary.
# Checks gcloud authentication, project, Cloud Build API, and (for live mode)
# Secret Manager version presence before submitting the right build config.
#
# Usage:
#   ./scripts/run_cloudbuild_research_full.sh --offline             # no secrets required
#   ./scripts/run_cloudbuild_research_full.sh --live                # requires secrets
#   ./scripts/run_cloudbuild_research_full.sh --live --no-source    # faster (no upload)
#
# For the Windows / PowerShell equivalent, see:
#   scripts/run_cloudbuild_research_full.ps1
#
# See docs/GOOGLE_CLOUD_BUILD_OPTIONAL_SETUP.md for full setup instructions.

set -euo pipefail

LIVE="false"
NO_SOURCE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live)    LIVE="true"; shift ;;
    --offline) LIVE="false"; shift ;;
    --no-source) NO_SOURCE="true"; shift ;;
    -h|--help)
      head -35 "$0" | grep '^#' | sed 's/^# \?//'
      exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1 ;;
  esac
done

echo "============================================="
echo "  morskamary — Cloud Build Wrapper"
echo "  Mode: $([ "$LIVE" = "true" ] && echo "LIVE (cloudbuild.live.yaml)" || echo "offline (cloudbuild.yaml)")"
echo "============================================="
echo ""

# ---------------------------------------------------------------------------
# Step 1: Check gcloud is installed
# ---------------------------------------------------------------------------

if ! command -v gcloud &>/dev/null; then
  echo "ERROR: gcloud CLI not found. Install Google Cloud SDK:" >&2
  echo "  https://cloud.google.com/sdk/docs/install" >&2
  exit 1
fi
echo "✓ gcloud CLI found: $(gcloud version --format='value(Google Cloud SDK)' 2>/dev/null || echo 'version unknown')"

# ---------------------------------------------------------------------------
# Step 2: Check authentication
# ---------------------------------------------------------------------------

if ! gcloud auth print-access-token &>/dev/null; then
  echo "ERROR: Not authenticated with gcloud. Run:" >&2
  echo "  gcloud auth login" >&2
  echo "  gcloud auth application-default login" >&2
  exit 1
fi
echo "✓ gcloud authenticated"

# ---------------------------------------------------------------------------
# Step 3: Detect project
# ---------------------------------------------------------------------------

PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: No GCP project set. Run:" >&2
  echo "  gcloud config set project YOUR_PROJECT_ID" >&2
  echo "  # or: export GCP_PROJECT_ID=YOUR_PROJECT_ID" >&2
  exit 1
fi
echo "✓ Project: $PROJECT_ID"

# ---------------------------------------------------------------------------
# Step 4: Check Cloud Build API is enabled
# ---------------------------------------------------------------------------

if ! gcloud services list --project="$PROJECT_ID" --filter="name:cloudbuild.googleapis.com" \
     --format='value(name)' 2>/dev/null | grep -q 'cloudbuild'; then
  echo "ERROR: Cloud Build API not enabled for project $PROJECT_ID." >&2
  echo "  Enable with: gcloud services enable cloudbuild.googleapis.com --project=$PROJECT_ID" >&2
  echo "  Or run: terraform apply in infra/gcp-mirror/" >&2
  exit 1
fi
echo "✓ Cloud Build API enabled"

# ---------------------------------------------------------------------------
# Step 5 (live only): Check that Secret Manager secrets have at least one version
# ---------------------------------------------------------------------------

SECRETS=("crossref-mailto" "elsevier-api-key" "scopus-api-key" "wos-api-key" "scival-api-key")

if [[ "$LIVE" == "true" ]]; then
  echo ""
  echo "Checking Secret Manager versions (required for cloudbuild.live.yaml)..."
  missing_secrets=()
  for secret in "${SECRETS[@]}"; do
    version_count=$(gcloud secrets versions list "$secret" \
      --project="$PROJECT_ID" \
      --filter="state=ENABLED" \
      --format='value(name)' 2>/dev/null | wc -l || echo "0")
    if [[ "$version_count" -gt 0 ]]; then
      echo "  ✓ $secret — has version(s)"
    else
      echo "  ✗ $secret — NO enabled version found"
      missing_secrets+=("$secret")
    fi
  done

  if [[ ${#missing_secrets[@]} -gt 0 ]]; then
    echo ""
    echo "ERROR: The following secrets have no enabled versions:" >&2
    for s in "${missing_secrets[@]}"; do
      echo "  - $s" >&2
    done
    echo ""
    echo "Add secret versions with:" >&2
    echo "  ./scripts/bootstrap_research_secrets.sh --backend gcp --project-id $PROJECT_ID" >&2
    exit 1
  fi
  echo "✓ All secret versions present"
fi

# ---------------------------------------------------------------------------
# Step 6: Select build config and submit
# ---------------------------------------------------------------------------

if [[ "$LIVE" == "true" ]]; then
  CONFIG="cloudbuild.live.yaml"
else
  CONFIG="cloudbuild.yaml"
fi

echo ""
echo "Submitting build with config: $CONFIG"
echo "Project: $PROJECT_ID"
if [[ "$NO_SOURCE" == "true" ]]; then
  echo "Note: --no-source flag set; Cloud Build will use the workspace without uploading source."
  echo ""
  gcloud builds submit \
    --config="$CONFIG" \
    --project="$PROJECT_ID" \
    --no-source
else
  echo ""
  gcloud builds submit \
    --config="$CONFIG" \
    --project="$PROJECT_ID"
fi

echo ""
echo "Cloud Build complete. Check logs above for results."
