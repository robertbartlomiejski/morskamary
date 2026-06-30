#!/usr/bin/env python3
"""
Smoke test for the scientific bridge and provider architecture.

Modes:
  --offline               Run only mocked/offline tests (default, no network).
  --live-if-secrets-present  Run live API calls for providers that are configured
                              and LIVE_RESEARCH_API_TESTS=true.

Usage:
    python scripts/smoke_scientific_bridge.py --offline
    LIVE_RESEARCH_API_TESTS=true python scripts/smoke_scientific_bridge.py \\
        --live-if-secrets-present

Exit codes:
    0  All checks passed.
    1  One or more checks failed.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.scientific_sources.source_registry import SourceRegistry  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def _result_line(label: str, status: str, detail: str = "") -> None:
    marker = {"PASS": "✓", "FAIL": "✗", "SKIP": "○"}.get(status, "?")
    suffix = f" — {detail}" if detail else ""
    print(f"  [{marker}] {label}{suffix}")


def run_offline_checks() -> list:
    """Run checks that require no network access."""
    failures = []
    registry = SourceRegistry()

    # 1. Registry lists all expected providers
    caps = registry.capabilities_dict()
    expected = {
        "crossref",
        "scopus",
        "wos",
        "scival",
        "google_drive",
        "microsoft_graph",
    }
    missing = expected - set(caps.keys())
    if missing:
        _result_line("Registry contains all providers", FAIL, f"missing: {missing}")
        failures.append("missing providers")
    else:
        _result_line("Registry contains all providers", PASS)

    # 2. Crossref is always configured
    if caps.get("crossref", {}).get("configured"):
        _result_line("Crossref always configured", PASS)
    else:
        _result_line("Crossref always configured", FAIL)
        failures.append("Crossref not configured")

    # 3. Unconfigured providers return warnings, not errors
    for name in ("scopus", "wos", "scival"):
        if not caps.get(name, {}).get("configured"):
            results = registry.search("test", max_results=1, providers=[name])
            has_warnings = any(r.warnings for r in results)
            has_errors = any(r.errors for r in results)
            if has_warnings and not has_errors:
                _result_line(f"{name} returns structured warning", PASS)
            elif has_errors:
                _result_line(f"{name} raises error instead of warning", FAIL)
                failures.append(f"{name} error")
            else:
                _result_line(f"{name} returns no warning (unexpected)", FAIL)
                failures.append(f"{name} no warning")

    # 4. Capabilities dict is JSON-serialisable
    try:
        json.dumps(caps)
        _result_line("Capabilities dict is JSON-serialisable", PASS)
    except TypeError as exc:
        _result_line("Capabilities dict is JSON-serialisable", FAIL, str(exc))
        failures.append("json serialise")

    # 5. Bridge MCP tool list works
    try:
        import scientific_bridge as sb

        bridge = sb.ScientificBridge()
        resp = bridge.handle_request({"method": "tools/list"})
        if not isinstance(resp, dict):
            raise ValueError("tools/list response must be a dictionary")
        tools = resp.get("tools", [])
        if not isinstance(tools, list):
            raise ValueError("tools/list response must contain a list under 'tools'")
        tool_names = {t["name"] for t in tools if isinstance(t, dict) and "name" in t}
        required_tools = {
            "fetch_scientific_proofs",
            "verify_citation",
            "list_research_source_capabilities",
            "search_open_metadata",
            "verify_doi",
        }
        missing_tools = required_tools - tool_names
        if missing_tools:
            _result_line("MCP tool list", FAIL, f"missing: {missing_tools}")
            failures.append("missing tools")
        else:
            _result_line("MCP tool list", PASS, f"{len(tool_names)} tools")
    except Exception as exc:
        _result_line("MCP tool list", FAIL, str(exc))
        failures.append("bridge error")

    # 6. Missing topic returns structured error, not exception
    try:
        bridge = __import__("scientific_bridge").ScientificBridge()
        resp = bridge.handle_fetch_scientific_proofs({})
        text = resp["content"][0]["text"]
        if "required" in text.lower():
            _result_line("Missing topic returns structured error", PASS)
        else:
            _result_line("Missing topic returns unexpected response", FAIL, text[:80])
            failures.append("missing topic error")
    except Exception as exc:
        _result_line("Missing topic raises exception", FAIL, str(exc))
        failures.append("exception on missing topic")

    return failures


def run_live_checks() -> list:
    """Run live API checks for configured providers."""
    failures = []
    registry = SourceRegistry()
    caps = registry.list_capabilities()

    for cap in caps:
        if not cap.live_test_allowed:
            _result_line(f"Live: {cap.provider}", SKIP, "not configured or not enabled")
            continue
        try:
            results = registry.search(
                "blue economy", max_results=2, providers=[cap.name]
            )
            records = registry.flat_records(results)
            errs = [e for r in results for e in r.errors]
            if errs:
                _result_line(f"Live: {cap.provider}", FAIL, errs[0][:80])
                failures.append(f"live {cap.name}")
            elif records:
                _result_line(
                    f"Live: {cap.provider}", PASS, f"{len(records)} record(s) returned"
                )
            else:
                _result_line(
                    f"Live: {cap.provider}",
                    SKIP,
                    "no records (may be normal for stub providers)",
                )
        except Exception as exc:
            _result_line(f"Live: {cap.provider}", FAIL, str(exc))
            failures.append(f"live exception {cap.name}")

    return failures


def main() -> int:
    """Run smoke checks based on CLI arguments."""
    args = sys.argv[1:]
    live_mode = "--live-if-secrets-present" in args

    print("=== Scientific Bridge Smoke Test ===\n")
    print("Offline checks:")
    failures = run_offline_checks()

    if live_mode:
        print("\nLive checks (LIVE_RESEARCH_API_TESTS must be 'true'):")
        failures.extend(run_live_checks())

    print(f"\n{'─' * 40}")
    if failures:
        print(f"FAILED: {len(failures)} check(s) failed.")
        for f in failures:
            print(f"  - {f}")
        return 1
    else:
        print("All smoke checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
