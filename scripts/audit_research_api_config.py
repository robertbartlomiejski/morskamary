#!/usr/bin/env python3
"""
Research API configuration audit script.

Checks which scientific source providers are configured by inspecting
environment variables and prints a capability dashboard.

Usage:
    python scripts/audit_research_api_config.py

Exit codes:
    0  At least one provider (Crossref) is configured.
    1  Unexpected error during audit.

This script never prints secret values — only presence/absence.
"""

import os
import sys

# Allow import from repo root when run as script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.scientific_sources.source_registry import SourceRegistry  # noqa: E402


def main() -> int:
    """Run the capability audit and print a dashboard."""
    registry = SourceRegistry()
    caps = registry.list_capabilities()

    print("=== Research Source Capability Dashboard ===\n")

    configured_count = 0
    for cap in caps:
        status = "✓ CONFIGURED" if cap.configured else "✗ not configured"
        live = " [live OK]" if cap.live_test_allowed else ""
        print(f"  {cap.provider:<40} {status}{live}")
        if cap.requires_secret and not cap.configured:
            env_hint = {
                "scopus": "ELSEVIER_API_KEY or SCOPUS_API_KEY",
                "wos": "WOS_API_KEY",
                "scival": "SCIVAL_API_KEY",
                "google_drive": "GOOGLE_DRIVE_OAUTH_CREDENTIALS",
                "microsoft_graph": (
                    "MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID, "
                    "MICROSOFT_CLIENT_SECRET (+ MICROSOFT_GRAPH_SITE_ID or "
                    "MICROSOFT_GRAPH_DRIVE_ID for search scope)"
                ),
            }.get(cap.name, "provider-specific credential")
            print(f"    → Set {env_hint} to enable")
        if cap.configured:
            configured_count += 1

    print(f"\nConfigured: {configured_count}/{len(caps)} providers")
    live_ok = any(c.live_test_allowed for c in caps)
    live_flag = os.getenv("LIVE_RESEARCH_API_TESTS", "false")
    print(f"Live API tests: {'enabled' if live_ok else 'disabled'} "
          f"(LIVE_RESEARCH_API_TESTS={live_flag})")

    print("\nTo run the bootstrap script:")
    print("  ./scripts/bootstrap_research_secrets.sh --backend dotenv")
    print("  .\\scripts\\bootstrap_research_secrets.ps1 -Backend DotEnv")
    print("  ./scripts/bootstrap_research_secrets.sh --backend gcp "
          "--project-id YOUR_PROJECT_ID")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
