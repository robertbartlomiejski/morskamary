"""Shared reporting/packaging rules; never recompute hypothesis results."""

from collections.abc import Mapping, Sequence
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
