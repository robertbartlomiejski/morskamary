#!/usr/bin/env python3
"""
Research environment check script.

Inspects the current environment and prints a summary of:
- Python version
- Installed package status
- Provider configuration (presence/absence of API keys)
- LIVE_RESEARCH_API_TESTS flag

Does NOT print secret values — only presence/absence.

Usage:
    python scripts/check_research_env.py
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def check_python_version() -> bool:
    """Verify Python version is at least 3.9."""
    major, minor = sys.version_info[:2]
    ok = (major, minor) >= (3, 9)
    status = "OK" if ok else "FAIL (need >= 3.9)"
    print(f"  Python version: {major}.{minor} — {status}")
    return ok


def check_package_installed(name: str) -> bool:
    """Check if a Python package is importable."""
    try:
        importlib.import_module(name)
        print(f"  Package {name:<30} installed")
        return True
    except ImportError:
        print(f"  Package {name:<30} MISSING (run: pip install -e .[dev])")
        return False


def check_env_var(name: str, label: str) -> bool:
    """Check if an environment variable is set (does not print value)."""
    val = os.getenv(name, "")
    if val:
        print(f"  {label:<40} SET")
        return True
    else:
        print(f"  {label:<40} not set")
        return False


def main() -> int:
    """Run all environment checks and print a summary."""
    print("=== Research Environment Check ===\n")

    all_ok = True

    # Python version
    print("Python:")
    if not check_python_version():
        all_ok = False

    # Core packages
    print("\nCore packages:")
    for pkg in ["pandas", "numpy", "pytest", "yaml"]:
        real = "pyyaml" if pkg == "yaml" else pkg
        check_package_installed(real if real != "pyyaml" else "yaml")

    # Provider environment variables
    print("\nProvider credentials (presence only — values not shown):")
    envs = [
        ("CROSSREF_MAILTO", "Crossref polite email"),
        ("ELSEVIER_API_KEY", "Elsevier API key"),
        ("SCOPUS_API_KEY", "Scopus API key"),
        ("WOS_API_KEY", "Web of Science API key"),
        ("SCIVAL_API_KEY", "SciVal API key"),
        ("GOOGLE_DRIVE_OAUTH_CREDENTIALS", "Google Drive OAuth path"),
        ("MICROSOFT_TENANT_ID", "Microsoft Tenant ID"),
        ("MICROSOFT_CLIENT_ID", "Microsoft Client ID"),
        ("MICROSOFT_CLIENT_SECRET", "Microsoft Client Secret"),
        ("GCP_PROJECT_ID", "GCP Project ID"),
    ]
    for env, label in envs:
        check_env_var(env, label)

    # Live test flag
    print("\nLive test configuration:")
    live = os.getenv("LIVE_RESEARCH_API_TESTS", "false")
    print(f"  LIVE_RESEARCH_API_TESTS = {live}")
    if live.lower() == "true":
        print("  → Live API calls ENABLED")
    else:
        print("  → Live API calls disabled (set LIVE_RESEARCH_API_TESTS=true to enable)")

    # Provider registry status
    print("\nProvider registry status:")
    try:
        from src.scientific_sources.source_registry import SourceRegistry

        registry = SourceRegistry()
        for cap in registry.list_capabilities():
            status = "configured" if cap.configured else "not configured"
            print(f"  {cap.provider:<40} {status}")
    except Exception as exc:
        print(f"  ERROR loading registry: {exc}")
        all_ok = False

    print()
    if all_ok:
        print("Environment check complete. Core dependencies OK.")
    else:
        print("Environment check found issues. Review above output.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
