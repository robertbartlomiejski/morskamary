#!/usr/bin/env bash
# scripts/bootstrap_research_secrets.sh
#
# One-time secure setup for research API credentials.
# Reads values interactively (no echo) and stores them in the chosen backend:
#
#   --backend user-env    Export to current shell session (temporary)
#   --backend gcp         Upload to Google Secret Manager (persistent)
#   --backend github      Print gh CLI commands to set GitHub repository secrets
#
# Values are NEVER written to files or printed after entry.
# Secret names follow Issue #100 and cloudbuild.yaml conventions.
#
# Usage:
#   ./scripts/bootstrap_research_secrets.sh --backend user-env
#   ./scripts/bootstrap_research_secrets.sh --backend gcp --project-id PROJECT_ID
#   ./scripts/bootstrap_research_secrets.sh --backend github
#
# See docs/ONE_CLICK_RESEARCH_RUNBOOK.md for the full setup workflow.

set -euo pipefail

BACKEND=""
PROJECT_ID=""

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)
      BACKEND="$2"; shift 2 ;;
    --project-id)
      PROJECT_ID="$2"; shift 2 ;;
    -h|--help)
      head -30 "$0" | grep '^#' | sed 's/^# \?//'
      exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1 ;;
  esac
done

if [[ -z "$BACKEND" ]]; then
  echo "ERROR: --backend is required (user-env | gcp | github)" >&2
  exit 1
fi

if [[ "$BACKEND" == "gcp" && -z "$PROJECT_ID" ]]; then
  echo "ERROR: --project-id is required for --backend gcp" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Credential prompts
# ---------------------------------------------------------------------------

declare -A SECRET_NAMES
SECRET_NAMES=(
  [CROSSREF_MAILTO]="crossref-mailto"
  [ELSEVIER_API_KEY]="elsevier-api-key"
  [SCOPUS_API_KEY]="scopus-api-key"
  [WOS_API_KEY]="wos-api-key"
  [SCIVAL_API_KEY]="scival-api-key"
)

declare -A SECRET_LABELS
SECRET_LABELS=(
  [CROSSREF_MAILTO]="Crossref polite contact email (e.g. researcher@university.edu)"
  [ELSEVIER_API_KEY]="Elsevier platform API key"
  [SCOPUS_API_KEY]="Scopus-specific API key (may be same as Elsevier key)"
  [WOS_API_KEY]="Web of Science API key"
  [SCIVAL_API_KEY]="SciVal API key"
)

ENV_VARS=("CROSSREF_MAILTO" "ELSEVIER_API_KEY" "SCOPUS_API_KEY" "WOS_API_KEY" "SCIVAL_API_KEY")

echo ""
echo "=== morskamary Research API Bootstrap ==="
echo "Backend: $BACKEND"
echo ""
echo "Press ENTER to skip any credential you don't have yet."
echo "Values are read securely and never displayed."
echo ""

declare -A VALUES

for var in "${ENV_VARS[@]}"; do
  label="${SECRET_LABELS[$var]}"
  read -r -s -p "Enter ${label} [ENTER to skip]: " val
  echo ""
  VALUES[$var]="$val"
done

# ---------------------------------------------------------------------------
# Apply to chosen backend
# ---------------------------------------------------------------------------

echo ""

case "$BACKEND" in

  user-env)
    echo "Exporting to current shell environment..."
    echo ""
    echo "Add the following to your shell profile (~/.bashrc, ~/.zshrc, etc.)"
    echo "to make these persistent, or run this script again next session:"
    echo ""
    for var in "${ENV_VARS[@]}"; do
      val="${VALUES[$var]}"
      if [[ -n "$val" ]]; then
        export "$var"="$val"
        echo "  export $var=<set>"
      else
        echo "  export $var=  (skipped)"
      fi
    done
    echo ""
    echo "Current session: variables exported."
    echo "Note: these exports are session-only. Re-run for new sessions."
    ;;

  gcp)
    echo "Uploading to Google Secret Manager (project: $PROJECT_ID)..."
    echo ""
    for var in "${ENV_VARS[@]}"; do
      val="${VALUES[$var]}"
      secret_name="${SECRET_NAMES[$var]}"
      if [[ -n "$val" ]]; then
        echo -n "$val" | gcloud secrets versions add "$secret_name" \
          --project="$PROJECT_ID" \
          --data-file=- \
          2>&1 | grep -v "^$" || true
        echo "  ✓ $secret_name — version added"
      else
        echo "  ○ $secret_name — skipped (no value entered)"
      fi
    done
    echo ""
    echo "Done. Verify with:"
    echo "  gcloud secrets list --project=$PROJECT_ID"
    ;;

  github)
    echo "GitHub Actions secrets — run the following gh CLI commands:"
    echo "(Values must be entered interactively when prompted by gh)"
    echo ""
    for var in "${ENV_VARS[@]}"; do
      echo "  gh secret set $var"
    done
    echo ""
    echo "Or pipe from a variable (never commit the value):"
    echo "  echo 'YOUR_KEY' | gh secret set ELSEVIER_API_KEY"
    echo ""
    echo "Verify secrets are set:"
    echo "  gh secret list"
    ;;

  *)
    echo "ERROR: Unknown backend '$BACKEND'" >&2
    exit 1 ;;
esac

echo ""
echo "Next step: run scripts/check_research_env.py to verify:"
echo "  python scripts/check_research_env.py"
