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
#   6. Full analysis
#   7. Export provider capabilities
#   8. Validate research source outputs
#   9. Print summary
#
# Usage:
#   ./scripts/run_research_api_full.sh            # offline only
#   ./scripts/run_research_api_full.sh --live     # enable live API calls
#   LIVE_RESEARCH_API_TESTS=true ./scripts/run_research_api_full.sh
#
# See docs/ONE_CLICK_RESEARCH_RUNBOOK.md for the full workflow.

set -euo pipefail

LIVE="false"
if [[ "${1:-}" == "--live" ]] || [[ "${LIVE_RESEARCH_API_TESTS:-false}" == "true" ]]; then
  LIVE="true"
fi

echo "============================================="
echo "  morskamary — Full Research Run"
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

# Step 3: Environment check
echo ""
echo "--- Step 3: Environment check ---"
$PYTHON scripts/check_research_env.py

# Step 4: Offline smoke test (always)
echo ""
echo "--- Step 4: Offline smoke test ---"
$PYTHON scripts/smoke_scientific_bridge.py --offline

# Step 5: Live API smoke (optional)
if [[ "$LIVE" == "true" ]]; then
  echo ""
  echo "--- Step 5: Live API smoke test ---"
  LIVE_RESEARCH_API_TESTS=true $PYTHON scripts/smoke_scientific_bridge.py \
    --live-if-secrets-present
else
  echo ""
  echo "--- Step 5: Live API smoke test --- SKIPPED (pass --live to enable)"
fi

# Step 6: Full analysis
echo ""
echo "--- Step 6: Full analysis ---"
$PYTHON run_full_analysis.py
$PYTHON scripts/validate_generated_outputs.py

# Step 7: Export capabilities
echo ""
echo "--- Step 7: Export provider capabilities ---"
$PYTHON scripts/export_research_source_capabilities.py

# Step 8: Validate research outputs
echo ""
echo "--- Step 8: Validate research source outputs ---"
$PYTHON scripts/validate_research_source_outputs.py

# Step 9: Summary
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
if [[ "$LIVE" != "true" ]]; then
  echo "  - Run with --live to enable live API calls"
  echo "    ./scripts/run_research_api_full.sh --live"
fi
echo "  - Run Cloud Build mirror:"
echo "    gcloud builds submit --config cloudbuild.yaml"
echo "============================================="
