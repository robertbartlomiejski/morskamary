#!/usr/bin/env python3
"""
Export research source capabilities to outputs/research_source_capabilities.json.

This script is safe to run without any API keys configured.
Crossref is always listed as configured; proprietary providers show as
not-configured without crashing.

Usage:
    python scripts/export_research_source_capabilities.py

Output:
    outputs/research_source_capabilities.json
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.scientific_sources.source_registry import SourceRegistry  # noqa: E402


def main() -> int:
    """Export provider capabilities to JSON."""
    registry = SourceRegistry()
    caps = registry.capabilities_dict()

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Provider capability snapshot. Values reflect runtime environment. "
            "Re-run after configuring additional provider credentials."
        ),
        "providers": caps,
    }

    out_dir = os.path.join(os.path.dirname(__file__), "..", "outputs")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "research_source_capabilities.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Exported provider capabilities to {out_path}")
    configured = sum(1 for v in caps.values() if v["configured"])
    print(f"  {configured}/{len(caps)} providers configured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
