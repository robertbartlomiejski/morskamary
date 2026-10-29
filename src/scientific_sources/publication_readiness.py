"""Shared reporting/packaging rules; never recompute hypothesis results."""

from collections.abc import Mapping, Sequence
import math
from typing import Any


def current_run_identity(payloads: Sequence[object]) -> tuple[str, list[str]]:
    """Require a nonempty string run ID from every required input."""
    values = [
        payload.get("current_run_id") if isinstance(payload, Mapping) else None
        for payload in payloads
    ]
    if not values or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        return "", ["current_run_id_mismatch_or_missing"]
    run_ids = {str(value).strip() for value in values}
    if len(run_ids) != 1:
        return "", ["current_run_id_mismatch_or_missing"]
    return next(iter(run_ids)), []


def _positive_count(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False


def derive_claim_boundary(hypotheses: Mapping[str, Any]) -> dict[str, bool]:
    """Mirror source-backed supply/bridge flags and retain conservative claims."""
    h2 = hypotheses.get("H2", {})
    h3 = hypotheses.get("H3", {})
    bridge_count = (
        h3.get("validated_semantic_bridge_count", 0)
        if isinstance(h3, Mapping) else 0
    )
    return {
        "validated_supply_available": bool(
            isinstance(h2, Mapping)
            and (
                h2.get("validated_supply_available") is True
                or (
                    h2.get("validated_supply_map_provided") is True
                    and _positive_count(h2.get("validated_covered_demand_count"))
                )
            )
        ),
        "objective_competence_gap_established": False,
        "generated_credentials_are_supply": False,
        "h3_translation_validated": bool(
            isinstance(h3, Mapping)
            and _positive_count(bridge_count)
            and h3.get("validation_status") == "validated"
        ),
    }


def aggregate_readiness(
    hypotheses: Mapping[str, str], *, pdf_available: bool, blockers: Sequence[str]
) -> dict[str, Any]:
    """Derive aggregate qualification from declared outcomes and artifacts."""
    reasons = {
        "H2": "H2_not_computable_no_independently_validated_supply",
        "H3": "H3_not_computable_no_validated_semantic_bridges",
    }
    degraded = [
        reasons.get(hypothesis_id, f"{hypothesis_id}_not_computable")
        for hypothesis_id, status in hypotheses.items()
        if status == "not_computable"
    ]
    scientific_status = (
        "screening_only_with_noncomputable_components"
        if degraded else "qualified_for_declared_results"
    )
    if not pdf_available:
        degraded.append("pdf_omitted")
    return {
        "engineering_status": "fail" if blockers else "pass",
        "scientific_status": scientific_status,
        "publication_status": (
            "blocked" if blockers else "degraded" if degraded else "candidate"
        ),
        "degraded_components": sorted(degraded),
    }
