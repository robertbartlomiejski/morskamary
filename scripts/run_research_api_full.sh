#!/usr/bin/env bash
# scripts/run_research_api_full.sh
#
# One-command full research run for morskamary.
#
# Steps:
#   1. Check Python version
#   2. Install / update package
#   3. Check research environment
#   4. Offline smoke test
#   5. Optional live API tests (pass --live or set LIVE_RESEARCH_API_TESTS=true)
#   6. Export live research records (live mode)
#   7. Full analysis (static or live-enriched mode)
#   8. Export provider capabilities
#   9. Validate research source outputs
#  10. Print summary
#
# Usage:
#   ./scripts/run_research_api_full.sh --mode quick
#   ./scripts/run_research_api_full.sh --mode full-static
#   ./scripts/run_research_api_full.sh --mode full-live
#   ./scripts/run_research_api_full.sh --live     # backward-compatible alias for --mode full-live
#
# See docs/ONE_CLICK_RESEARCH_RUNBOOK.md for the full workflow.

set -euo pipefail

MODE="full-static"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --mode requires a value (quick|full-static|full-live)"
        echo "Usage: ./scripts/run_research_api_full.sh [--mode quick|full-static|full-live] [--live]"
        exit 1
      fi
      MODE="$2"
      shift 2
      ;;
    --mode=*)
      MODE="${1#*=}"
      shift
      ;;
    --live)
      MODE="full-live"
      shift
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: ./scripts/run_research_api_full.sh [--mode quick|full-static|full-live] [--live]"
      exit 1
      ;;
  esac
done

if [[ "${LIVE_RESEARCH_API_TESTS:-false}" == "true" && "$MODE" != "full-live" ]]; then
  MODE="full-live"
fi

if [[ "$MODE" != "quick" && "$MODE" != "full-static" && "$MODE" != "full-live" ]]; then
  echo "Invalid mode: $MODE"
  echo "Expected one of: quick, full-static, full-live"
  exit 1
fi

LIVE="false"
if [[ "$MODE" == "full-live" ]]; then
  LIVE="true"
fi

echo "============================================="
echo "  morskamary — Full Research Run"
echo "  Mode: $MODE"
echo "  Live API: $LIVE"
echo "============================================="
echo ""

# Step 1: Python version check
echo "--- Step 1: Python version ---"
python --version || python3 --version
PYTHON=$(command -v python || command -v python3)

# Step 2: Install/update package
echo ""
echo "--- Step 2: Install dependencies ---"
$PYTHON -m pip install --upgrade pip --quiet
$PYTHON -m pip install -e .[dev] --quiet
echo "Package installed."

# Step 3: Provider diagnostics
echo ""
echo "--- Step 3: Provider capability diagnostics ---"
$PYTHON scripts/audit_research_api_config.py
$PYTHON scripts/export_research_source_capabilities.py

# Step 4: Environment check
echo ""
echo "--- Step 4: Environment check ---"
$PYTHON scripts/check_research_env.py

# Quick mode: deterministic static analysis + core validation only.
if [[ "$MODE" == "quick" ]]; then
  echo ""
  echo "--- QUICK MODE: static analysis and consistency gates ---"
  $PYTHON run_full_analysis.py --analysis-input-mode static
  $PYTHON scripts/validate_generated_outputs.py
  $PYTHON scripts/validate_research_source_outputs.py
  echo ""
  echo "Quick mode complete."
  exit 0
fi

# Step 5: Offline smoke test (always for full modes)
echo ""
echo "--- Step 5: Offline smoke test ---"
$PYTHON scripts/smoke_scientific_bridge.py --offline

# Step 6: Live API smoke (optional)
if [[ "$LIVE" == "true" ]]; then
  echo ""
  echo "--- Step 6: Live API smoke test ---"
  LIVE_RESEARCH_API_TESTS=true $PYTHON scripts/smoke_scientific_bridge.py \
    --live-if-secrets-present
else
  echo ""
  echo "--- Step 6: Live API smoke test --- SKIPPED (use --mode full-live)"
fi

# Step 7: Export live research records (optional)
echo ""
if [[ "$LIVE" == "true" ]]; then
  echo "--- Step 7: Export live research records ---"
  $PYTHON scripts/export_live_research_records.py \
    --providers "crossref,scopus,wos,scival,microsoft_graph" \
    --query-file config/research_queries.yml \
    --max-results-per-query 30 \
    --output-dir outputs/research_sources \
    --offline false
else
  echo "--- Step 7: Export live research records --- SKIPPED (offline mode)"
fi

# Step 8: Full analysis
echo ""
echo "--- Step 8: Full analysis ---"
if [[ "$LIVE" == "true" ]]; then
  $PYTHON run_full_analysis.py \
    --analysis-input-mode live-enriched \
    --live-records-path outputs/research_sources/live_records_triangulated.json
else
  $PYTHON run_full_analysis.py --analysis-input-mode static
fi
$PYTHON scripts/validate_generated_outputs.py

# Step 9: Export capabilities
echo ""
echo "--- Step 9: Export provider capabilities ---"
$PYTHON scripts/export_research_source_capabilities.py

# Step 10: Validate research outputs
echo ""
echo "--- Step 10: Validate research source outputs ---"
$PYTHON scripts/validate_research_source_outputs.py

# Step 11: Summary
echo ""
echo "============================================="
echo "  Run complete."
echo ""
echo "  Configured providers:"
$PYTHON scripts/audit_research_api_config.py 2>&1 | grep -E "(✓|✗)" | head -10
echo ""
echo "  Output files:"
ls -1 outputs/*.json outputs/*.csv outputs/*.html 2>/dev/null | head -15 || true
echo ""
echo "  Next steps:"
if [[ "$MODE" != "full-live" ]]; then
  echo "  - Run full live mode for provider-enriched analysis:"
  echo "    ./scripts/run_research_api_full.sh --mode full-live"
fi
echo "  - Run Cloud Build mirror:"
echo "    gcloud builds submit --config cloudbuild.yaml"
echo "============================================="
