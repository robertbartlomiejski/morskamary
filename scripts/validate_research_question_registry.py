#!/usr/bin/env python3
"""Validate the research-question registry and an optional accountability ledger."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources.research_question_registry import (  # noqa: E402
    DEFAULT_ACCOUNTABILITY_SCHEMA_PATH,
    DEFAULT_PROTOCOL_PATH,
    DEFAULT_REGISTRY_PATH,
    DEFAULT_REGISTRY_SCHEMA_PATH,
    ResearchQuestionRegistryError,
    load_accountability_ledger,
    load_research_question_registry,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Fail closed on invalid research-question registries and incomplete "
            "accountability ledgers."
        )
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_PATH)
    parser.add_argument(
        "--registry-schema",
        type=Path,
        default=DEFAULT_REGISTRY_SCHEMA_PATH,
    )
    parser.add_argument(
        "--accountability",
        type=Path,
        help="Optional YAML or JSON accountability ledger to validate.",
    )
    parser.add_argument(
        "--accountability-schema",
        type=Path,
        default=DEFAULT_ACCOUNTABILITY_SCHEMA_PATH,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run registry and optional ledger validation."""

    args = parse_args(argv)
    try:
        registry = load_research_question_registry(
            args.registry,
            protocol_path=args.protocol,
            schema_path=args.registry_schema,
        )
        print(
            "[OK] Research-question registry valid: "
            f"{len(registry.questions)} RQs, "
            f"{len(registry.extended_questions)} ETQs, "
            f"{len(registry.protocol.ordered_hypothesis_ids)} protocol hypotheses"
        )
        if args.accountability is not None:
            ledger = load_accountability_ledger(
                args.accountability,
                registry,
                schema_path=args.accountability_schema,
            )
            print(
                "[OK] Research-question accountability ledger valid: "
                f"{len(ledger.entries)} complete entries"
            )
    except ResearchQuestionRegistryError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
