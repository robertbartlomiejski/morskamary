"""Evidence-level sector/axis analysis with transparent screening boundaries.

This module intentionally keeps three different objects separate:

* observed evidence structure (one row per unique linked evidence identity),
* deterministic title-screening features (candidate realms and mechanisms), and
* human-validated demand, translation, and credential-supply outcomes.

The current cumulative database contains the first two objects only.  It must
not be used to claim workforce prevalence, validated performativity, or an
independently verified shortage of education and training supply.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

AXES = ("MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION")
AXIS_CODES: Mapping[str, str] = {
    "MARINE": "M",
    "MARITIME": "T",
    "OCEANIC": "O",
    "HYDRONIZATION": "H",
}
REALMS = ("ECONOMY", "TECHNOLOGY", "POLICY_GOVERNANCE", "CULTURE_LEARNING")

# These are deterministic screening groups, not validated performativity stages.
PERFORMATIVE_FEATURE_SIGNAL_TYPES: Mapping[str, frozenset[str]] = {
    "demand_articulation": frozenset(
        {
            "explicit_competence_demand",
            "implicit_competence_demand",
            "workforce_skill",
        }
    ),
    "learning_credential_translation": frozenset(
        {
            "education_training_signal",
            "learning_outcome_signal",
            "credential_translation_signal",
        }
    ),
    "technical_operational_capability": frozenset(
        {"digital_skill", "technical_skill", "safety_risk_skill"}
    ),
    "institutional_governance": frozenset(
        {"governance_skill", "policy_regulation_skill", "sustainability_skill"}
    ),
    "reflexive_cultural_capability": frozenset({"social_science_skill"}),
}

# Multi-label candidate-realm screen. Exact spans and human coding are still needed.
REALM_SIGNAL_TYPES: Mapping[str, frozenset[str]] = {
    "ECONOMY": frozenset(
        {
            "workforce_skill",
            "explicit_competence_demand",
            "implicit_competence_demand",
        }
    ),
    "TECHNOLOGY": frozenset({"digital_skill", "technical_skill", "safety_risk_skill"}),
    "POLICY_GOVERNANCE": frozenset(
        {"governance_skill", "policy_regulation_skill", "sustainability_skill"}
    ),
    "CULTURE_LEARNING": frozenset(
        {
            "social_science_skill",
            "education_training_signal",
            "learning_outcome_signal",
            "credential_translation_signal",
        }
    ),
}

ALLOWED_SEMANTIC_SCOPES = frozenset({"title", "subject_terms", "abstract", "full_text"})


class PerformativeDemandAnalysisError(RuntimeError):
    """Raised when evidence-level analytical invariants do not hold."""


def validate_evidence_identities(evidence: pd.DataFrame) -> None:
    """Fail closed on blank, null, or duplicated Layer-2 evidence identities.

    This must run before any ``set()``, merge, explode, or deduplication can
    conceal identity defects (see
    ``scripts/build_provider_sensitivity_analysis.py`` for the equivalent
    Layer-2 convention).
    """
    if "evidence_id" not in evidence.columns:
        raise PerformativeDemandAnalysisError(
            "evidence_records is missing the required evidence_id column"
        )
    raw_ids = evidence["evidence_id"]
    null_count = int(raw_ids.isna().sum())
    stripped = raw_ids.map(lambda value: str(value).strip() if pd.notna(value) else "")
    blank_count = int((stripped.eq("") & raw_ids.notna()).sum())
    if null_count or blank_count:
        raise PerformativeDemandAnalysisError(
            f"evidence_records contains {null_count} null and {blank_count} blank "
            "evidence_id values (Layer 2 structural violation)"
        )
    duplicate_ids = sorted(
        set(stripped[stripped.duplicated(keep=False)].tolist())
    )
    if duplicate_ids:
        raise PerformativeDemandAnalysisError(
            f"evidence_records contains {len(duplicate_ids)} duplicate evidence_id "
            "values (Layer 2 structural violation — deduplicate before performative "
            "demand analysis): " + ", ".join(duplicate_ids[:10])
        )


@dataclass(frozen=True)
class PerformativeDemandAnalysis:
    """Complete analysis tables and audit summary."""

    evidence_map: pd.DataFrame
    observed: pd.DataFrame
    expected: pd.DataFrame
    residuals: pd.DataFrame
    sector_axis_features: pd.DataFrame
    sector_axis_realms: pd.DataFrame
    axis_features: pd.DataFrame
    sector_profile: pd.DataFrame
    summary: dict[str, Any]


def split_pipe(value: object) -> list[str]:
    """Split a pipe-delimited database field without creating a ``nan`` ID."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    return [part.strip() for part in str(value).split("|") if part.strip()]


def _normalized_scope_set(values: Sequence[object]) -> frozenset[str]:
    """Normalize retained semantic scopes without manufacturing ``nan`` labels."""
    normalized: set[str] = set()
    for value in values:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        text = str(value).strip().lower()
        if text:
            normalized.add(text)
    return frozenset(normalized)


def _evidence_surface(frame: pd.DataFrame) -> str:
    """Return a deterministic union of retained semantic scopes for a frame."""
    scopes: set[str] = set()
    if "semantic_scopes" not in frame.columns:
        return ""
    for value in frame["semantic_scopes"].tolist():
        if isinstance(value, (frozenset, set, tuple, list)):
            scopes.update(str(item).strip() for item in value if str(item).strip())
    return "|".join(sorted(scopes))


def _linkage_dependence_audit(demands: pd.DataFrame) -> dict[str, Any]:
    """Quantify evidence-to-demand reuse to keep independence limits explicit."""
    links = demands[["evidence_ids"]].copy()
    links["evidence_id"] = links["evidence_ids"].map(split_pipe)
    links = links.explode("evidence_id")
    links = links.loc[links["evidence_id"].notna()]
    links = links.loc[links["evidence_id"].astype(str).str.strip().ne("")]
    if links.empty:
        return {
            "total_demand_link_rows": 0,
            "unique_linked_evidence_ids": 0,
            "duplicated_linked_evidence_ids": 0,
            "max_demand_links_per_evidence_id": 0,
            "mean_demand_links_per_evidence_id": 0.0,
            "independence_risk_flag": False,
        }
    counts = links.groupby("evidence_id").size()
    return {
        "total_demand_link_rows": int(len(links)),
        "unique_linked_evidence_ids": int(len(counts)),
        "duplicated_linked_evidence_ids": int((counts > 1).sum()),
        "max_demand_links_per_evidence_id": int(counts.max()),
        "mean_demand_links_per_evidence_id": float(counts.mean()),
        "independence_risk_flag": bool((counts > 1).any()),
    }


def build_unique_evidence_map(demands: pd.DataFrame) -> pd.DataFrame:
    """Return one sector/axis assignment per linked evidence identity.

    Demand rows are work packages, not independent observations.  An evidence
    identity may appear in several demand rows, so it is exploded and
    deduplicated before any sector/axis inference.
    """
    required = ("competence_demand_id", "sector", "axis_group", "evidence_ids")
    missing = set(required) - set(demands.columns)
    if missing:
        raise PerformativeDemandAnalysisError(
            "derived demands missing columns: " + ", ".join(sorted(missing))
        )

    links = demands[list(required)].copy()
    links["evidence_id"] = links["evidence_ids"].map(split_pipe)
    links = links.explode("evidence_id")
    links = links.loc[links["evidence_id"].notna()]
    links = links.loc[links["evidence_id"].astype(str).str.strip().ne("")]
    evidence_map = links[["evidence_id", "sector", "axis_group"]].drop_duplicates()

    sectors_per_id = evidence_map.groupby("evidence_id")["sector"].nunique()
    axes_per_id = evidence_map.groupby("evidence_id")["axis_group"].nunique()
    if (sectors_per_id > 1).any() or (axes_per_id > 1).any():
        raise PerformativeDemandAnalysisError(
            "an evidence identity maps to more than one exclusive sector or axis; "
            "use a validated multi-label evidence table instead"
        )
    return cast(
        pd.DataFrame,
        evidence_map.sort_values("evidence_id").reset_index(drop=True),
    )


def _adjust_holm(p_values: NDArray[np.float64]) -> NDArray[np.float64]:
    order = np.argsort(p_values)
    ranked = p_values[order]
    adjusted_ranked = np.maximum.accumulate(
        (len(ranked) - np.arange(len(ranked))) * ranked
    )
    adjusted_ranked = np.minimum(1.0, adjusted_ranked)
    adjusted = np.empty_like(adjusted_ranked)
    adjusted[order] = adjusted_ranked
    return cast(NDArray[np.float64], adjusted)


def _adjust_bh(p_values: NDArray[np.float64]) -> NDArray[np.float64]:
    order = np.argsort(p_values)
    ranked = p_values[order]
    adjusted_ranked = ranked * len(ranked) / (np.arange(len(ranked)) + 1)
    adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
    adjusted_ranked = np.minimum(1.0, adjusted_ranked)
    adjusted = np.empty_like(adjusted_ranked)
    adjusted[order] = adjusted_ranked
    return cast(NDArray[np.float64], adjusted)


def _bias_corrected_cramers_v(chi2: float, n: int, rows: int, cols: int) -> float:
    if n <= 1:
        return 0.0
    phi2 = chi2 / n
    phi2_corrected = max(0.0, phi2 - ((cols - 1) * (rows - 1)) / (n - 1))
    rows_corrected = rows - ((rows - 1) ** 2) / (n - 1)
    cols_corrected = cols - ((cols - 1) ** 2) / (n - 1)
    denominator = min(rows_corrected - 1, cols_corrected - 1)
    return math.sqrt(phi2_corrected / denominator) if denominator > 0 else 0.0


def _normalized_entropy(counts: np.ndarray) -> float:
    positive = counts[counts > 0]
    if len(positive) <= 1:
        return 0.0
    probabilities = positive / positive.sum()
    return float(-(probabilities * np.log(probabilities)).sum() / np.log(len(counts)))


def _permutation_chi2_p(
    row_codes: np.ndarray,
    col_codes: np.ndarray,
    expected: np.ndarray,
    observed_chi2: float,
    permutations: int,
    seed: int,
) -> tuple[float, int]:
    if permutations < 1:
        raise PerformativeDemandAnalysisError("permutations must be at least 1")
    random = np.random.default_rng(seed)
    exceedances = 0
    rows, columns = expected.shape
    for _ in range(permutations):
        permuted = random.permutation(col_codes)
        table = np.zeros((rows, columns), dtype=np.int64)
        np.add.at(table, (row_codes, permuted), 1)
        contributions = np.divide(
            (table - expected) ** 2,
            expected,
            out=np.zeros_like(expected),
            where=expected > 0,
        )
        statistic = float(contributions.sum())
        exceedances += int(statistic >= observed_chi2 - 1e-12)
    return ((exceedances + 1) / (permutations + 1), exceedances)


def _validate_inputs(
    demands: pd.DataFrame,
    evidence: pd.DataFrame,
    signals: pd.DataFrame,
    evidence_map: pd.DataFrame,
    sector_order: Sequence[str],
) -> None:
    validate_evidence_identities(evidence)
    if len(set(sector_order)) != len(sector_order):
        raise PerformativeDemandAnalysisError("sector order contains duplicates")
    unknown_sectors = set(evidence_map["sector"]) - set(sector_order)
    if unknown_sectors:
        raise PerformativeDemandAnalysisError(
            "linked evidence contains sectors absent from the protocol: "
            + ", ".join(sorted(unknown_sectors))
        )
    unknown_axes = set(evidence_map["axis_group"]) - set(AXES)
    if unknown_axes:
        raise PerformativeDemandAnalysisError(
            "linked evidence contains non-canonical axes: "
            + ", ".join(sorted(unknown_axes))
        )
    canonical_evidence_ids = set(evidence["evidence_id"].astype(str).str.strip())
    orphan_ids = set(evidence_map["evidence_id"]) - canonical_evidence_ids
    if orphan_ids:
        raise PerformativeDemandAnalysisError(
            f"{len(orphan_ids)} linked evidence identities are absent from evidence_records"
        )
    required_signal_columns = {
        "evidence_id",
        "sector",
        "axis_group",
        "signal_type",
        "semantic_scope",
        "manual_review_status",
    }
    missing_signal_columns = required_signal_columns - set(signals.columns)
    if missing_signal_columns:
        raise PerformativeDemandAnalysisError(
            "signals missing columns: " + ", ".join(sorted(missing_signal_columns))
        )
    if demands.empty or evidence_map.empty:
        raise PerformativeDemandAnalysisError("no linked demand evidence is available")


def _prepare_linked_signals_for_screening(
    signals: pd.DataFrame,
    evidence_map: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Normalize and gate screening signals with fail-closed validation status."""
    # Step 1: restrict screening to linked lineage and enforce sector/axis parity.
    linked_signals = signals.merge(
        evidence_map,
        on="evidence_id",
        how="inner",
        suffixes=("_signal", "_linked"),
    )
    if not (
        linked_signals["sector_signal"].eq(linked_signals["sector_linked"]).all()
        and linked_signals["axis_group_signal"]
        .eq(linked_signals["axis_group_linked"])
        .all()
    ):
        raise PerformativeDemandAnalysisError(
            "linked signal sector/axis assignments conflict with demand lineage"
        )
    linked_signals["manual_review_status"] = (
        linked_signals["manual_review_status"].astype(str).str.strip().str.lower()
    )
    linked_signals["semantic_scope"] = (
        linked_signals["semantic_scope"].astype(str).str.strip().str.lower()
    )
    # Step 2: enforce retained semantic-surface policy (never query/source_query).
    illegal_semantic_scopes = {
        scope
        for scope in set(linked_signals["semantic_scope"])
        if scope not in ALLOWED_SEMANTIC_SCOPES
    }
    if illegal_semantic_scopes:
        raise PerformativeDemandAnalysisError(
            "signals contain unsupported semantic_scope values: "
            + ", ".join(sorted(illegal_semantic_scopes))
        )
    rejected_signal_rows_excluded = int(
        linked_signals["manual_review_status"].eq("rejected").sum()
    )
    # Step 3: fail closed unless rows remain review_required screening candidates.
    linked_signals = linked_signals.loc[
        ~linked_signals["manual_review_status"].eq("rejected")
    ].copy()
    unsupported_review_statuses = set(linked_signals["manual_review_status"]) - {
        "review_required"
    }
    if unsupported_review_statuses:
        raise PerformativeDemandAnalysisError(
            "validated/manual review statuses require an accepted validation ledger; unsupported screening statuses: "
            + ", ".join(sorted(unsupported_review_statuses))
        )
    if linked_signals.empty:
        raise PerformativeDemandAnalysisError(
            "no non-rejected review_required signals remain for screening"
        )
    linked_signals = linked_signals.rename(
        columns={"sector_linked": "sector", "axis_group_linked": "axis_group"}
    )
    return linked_signals, rejected_signal_rows_excluded


def _signal_sets_by_linked_evidence(linked_signals: pd.DataFrame) -> pd.DataFrame:
    """Collapse to one row per linked evidence identity for corpus diagnostics.

    This removes repeated signal rows per evidence/sector/axis key, but it does
    not guarantee independent observations in a strict inferential sense.
    """
    signal_set_rows: list[dict[str, Any]] = []
    for group_key, group in linked_signals.groupby(
        ["evidence_id", "sector", "axis_group"], sort=False
    ):
        typed_group_key = cast(tuple[Any, Any, Any], group_key)
        evidence_key = str(typed_group_key[0])
        sector_key = str(typed_group_key[1])
        axis_group_key = str(typed_group_key[2])
        signal_set_rows.append(
            {
                "evidence_id": evidence_key,
                "sector": sector_key,
                "axis_group": axis_group_key,
                "signal_types": frozenset(
                    str(value) for value in group["signal_type"].tolist()
                ),
                "semantic_scopes": _normalized_scope_set(group["semantic_scope"].tolist()),
            }
        )
    return pd.DataFrame(signal_set_rows)


def build_performative_demand_analysis(
    demands: pd.DataFrame,
    evidence: pd.DataFrame,
    signals: pd.DataFrame,
    sector_labels: Mapping[str, str],
    *,
    permutations: int = 50_000,
    seed: int = 20_260_825,
) -> PerformativeDemandAnalysis:
    """Build corpus-structure tables and deterministic screening summaries.

    The sector-axis association is descriptive of the acquired/classified corpus.
    Permuting axis labels with fixed sector labels and fixed margins tests whether
    the observed table is more structured than random assignment within that corpus.
    It does not estimate population or workforce demand, and inferential statistics
    here are table diagnostics under curated design assumptions, not iid estimators.
    One linked evidence identity remains a curated corpus unit that may carry
    correlated signal context across screening pathways.
    """
    validate_evidence_identities(evidence)
    sector_order = list(sector_labels)
    linkage_dependence = _linkage_dependence_audit(demands)
    evidence_map = build_unique_evidence_map(demands)
    _validate_inputs(demands, evidence, signals, evidence_map, sector_order)

    observed = (
        evidence_map.groupby(["sector", "axis_group"])["evidence_id"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(index=sector_order, columns=AXES, fill_value=0)
    )
    observed_array = observed.to_numpy(dtype=float)
    total = int(observed_array.sum())
    if total <= 0:
        raise PerformativeDemandAnalysisError(
            "no observed evidence is available for inference"
        )
    row_totals = observed_array.sum(axis=1)
    column_totals = observed_array.sum(axis=0)
    expected_array = np.outer(row_totals, column_totals) / total
    expected = pd.DataFrame(expected_array, index=sector_order, columns=AXES)
    active_row_mask = row_totals > 0
    active_column_mask = column_totals > 0
    active_row_count = int(active_row_mask.sum())
    active_column_count = int(active_column_mask.sum())
    inferential_computable = active_row_count >= 2 and active_column_count >= 2
    # Sparse-cell diagnostics must describe the active inferential margins used
    # for chi-square, degrees of freedom, and permutation inference, not the
    # preserved full display matrix (which still keeps structural zero rows and
    # columns for descriptive sector x axis output).
    active_expected_array = expected_array[np.ix_(active_row_mask, active_column_mask)]
    chi2_contributions = np.divide(
        (observed_array - expected_array) ** 2,
        expected_array,
        out=np.zeros_like(expected_array),
        where=expected_array > 0,
    )
    chi2 = float(chi2_contributions.sum()) if inferential_computable else math.nan
    degrees_of_freedom = (
        (active_row_count - 1) * (active_column_count - 1)
        if inferential_computable
        else 0
    )
    row_proportions = row_totals / total
    column_proportions = column_totals / total
    residual_denominator = np.sqrt(
        expected_array
        * (1 - row_proportions[:, None])
        * (1 - column_proportions[None, :])
    )
    adjusted_residuals = np.divide(
        observed_array - expected_array,
        residual_denominator,
        out=np.full_like(expected_array, np.nan),
        where=residual_denominator > 0,
    )
    valid_residual_mask = np.isfinite(adjusted_residuals) & (expected_array > 0)
    cell_p = np.full(adjusted_residuals.shape, np.nan, dtype=float)
    holm_p = np.full(adjusted_residuals.shape, np.nan, dtype=float)
    bh_p = np.full(adjusted_residuals.shape, np.nan, dtype=float)
    if valid_residual_mask.any():
        valid_p = np.array(
            [
                math.erfc(abs(value) / math.sqrt(2))
                for value in adjusted_residuals[valid_residual_mask]
            ]
        )
        cell_p[valid_residual_mask] = valid_p
        holm_p[valid_residual_mask] = _adjust_holm(valid_p)
        bh_p[valid_residual_mask] = _adjust_bh(valid_p)
    row_codes = pd.Categorical(evidence_map["sector"], categories=sector_order).codes
    column_codes = pd.Categorical(evidence_map["axis_group"], categories=AXES).codes
    # Permutation/residual outputs are corpus-structure diagnostics, not prevalence.
    if inferential_computable:
        permutation_p, permutation_exceedances = _permutation_chi2_p(
            row_codes, column_codes, expected_array, chi2, permutations, seed
        )
        corrected_v = _bias_corrected_cramers_v(
            chi2, total, active_row_count, active_column_count
        )
    else:
        permutation_p, permutation_exceedances, corrected_v = math.nan, 0, math.nan

    residual_rows: list[dict[str, Any]] = []
    for row_index, sector in enumerate(sector_order):
        for column_index, axis in enumerate(AXES):
            observed_count = int(observed_array[row_index, column_index])
            residual_rows.append(
                {
                    "sector": sector,
                    "sector_label": sector_labels[sector],
                    "axis_group": axis,
                    "axis_code": AXIS_CODES[axis],
                    "observed_evidence_count": observed_count,
                    "expected_evidence_count": float(
                        expected_array[row_index, column_index]
                    ),
                    "adjusted_standardized_residual": float(
                        adjusted_residuals[row_index, column_index]
                    ),
                    "raw_cell_p": float(cell_p[row_index, column_index]),
                    "holm_p": float(holm_p[row_index, column_index]),
                    "bh_p": float(bh_p[row_index, column_index]),
                    "holm_significant_0_05": bool(
                        np.isfinite(holm_p[row_index, column_index])
                        and holm_p[row_index, column_index] < 0.05
                    ),
                    "bh_significant_0_05": bool(
                        np.isfinite(bh_p[row_index, column_index])
                        and bh_p[row_index, column_index] < 0.05
                    ),
                    "cell_status": (
                        "empty_current_linked_corpus"
                        if observed_count == 0
                        else "observed_linked_evidence"
                    ),
                }
            )
    residuals = pd.DataFrame(residual_rows)

    linked_signals, rejected_signal_rows_excluded = _prepare_linked_signals_for_screening(
        signals, evidence_map
    )
    signal_sets = _signal_sets_by_linked_evidence(linked_signals)
    all_linked = evidence_map.merge(
        signal_sets, on=["evidence_id", "sector", "axis_group"], how="left"
    )
    normalized_signal_types = pd.Series(
        [
            value if isinstance(value, frozenset) else frozenset()
            for value in all_linked["signal_types"].tolist()
        ],
        index=all_linked.index,
        dtype=object,
    )
    all_linked["signal_types"] = normalized_signal_types
    normalized_semantic_scopes = pd.Series(
        [
            value if isinstance(value, frozenset) else frozenset()
            for value in all_linked["semantic_scopes"].tolist()
        ],
        index=all_linked.index,
        dtype=object,
    )
    all_linked["semantic_scopes"] = normalized_semantic_scopes
    all_linked["signal_type_richness"] = all_linked["signal_types"].map(len)
    for feature, members in PERFORMATIVE_FEATURE_SIGNAL_TYPES.items():
        all_linked[feature] = [
            bool(values & members) for values in all_linked["signal_types"].tolist()
        ]
    for realm, members in REALM_SIGNAL_TYPES.items():
        all_linked[f"realm_{realm}"] = [
            bool(values & members) for values in all_linked["signal_types"].tolist()
        ]
    # Deterministic multi-label realm crosswalk for screening triage only.
    realm_columns = [f"realm_{realm}" for realm in REALMS]
    all_linked["realm_count"] = all_linked[realm_columns].sum(axis=1)
    screening_linked = all_linked.loc[all_linked["signal_type_richness"].gt(0)].copy()
    screening_linked_total = int(len(screening_linked))
    if (screening_linked["realm_count"] == 0).any():
        raise PerformativeDemandAnalysisError(
            "at least one non-rejected linked evidence identity has no candidate realm mapping"
        )

    sector_axis_feature_rows: list[dict[str, Any]] = []
    sector_axis_realm_rows: list[dict[str, Any]] = []
    for sector in sector_order:
        for axis in AXES:
            group = screening_linked.loc[
                screening_linked["sector"].eq(sector)
                & screening_linked["axis_group"].eq(axis)
            ]
            demand_group = demands.loc[
                demands["sector"].eq(sector) & demands["axis_group"].eq(axis)
            ]
            signal_union: set[str] = set()
            for values in group["signal_types"]:
                signal_union.update(values)
            evidence_surface = _evidence_surface(group)
            feature_row: dict[str, Any] = {
                "sector": sector,
                "sector_label": sector_labels[sector],
                "axis_group": axis,
                "axis_code": AXIS_CODES[axis],
                "evidence_surface": evidence_surface,
                "unique_evidence_count": int(len(group)),
                "derived_demand_count": int(len(demand_group)),
                "distinct_signal_type_count": len(signal_union),
                "mean_signal_type_richness": (
                    float(group["signal_type_richness"].mean())
                    if len(group)
                    else math.nan
                ),
                "median_signal_type_richness": (
                    float(group["signal_type_richness"].median())
                    if len(group)
                    else math.nan
                ),
                "validated_demand_count": 0,
                "validated_translation_count": 0,
                "validated_supply_count": math.nan,
                "supply_gap_status": "not_computable_no_independent_supply",
                "screening_validation_state": "screening_only_not_validated",
                "evidence_status": (
                    "screening_not_human_validated"
                    if len(group)
                    else "empty_current_linked_corpus"
                ),
                "analysis_scope": "deterministic_screening_only_not_validated",
            }
            for feature in PERFORMATIVE_FEATURE_SIGNAL_TYPES:
                hits = int(group[feature].sum()) if len(group) else 0
                feature_row[f"{feature}_count"] = hits
                feature_row[f"{feature}_share"] = (
                    hits / len(group) if len(group) else math.nan
                )
            sector_axis_feature_rows.append(feature_row)

            for realm in REALMS:
                realm_mask = group[f"realm_{realm}"]
                candidate_count = int(realm_mask.sum()) if len(group) else 0
                fractional_weight = (
                    float((realm_mask / group["realm_count"]).sum())
                    if len(group)
                    else 0.0
                )
                sector_axis_realm_rows.append(
                    {
                        "sector": sector,
                        "sector_label": sector_labels[sector],
                        "axis_group": axis,
                        "axis_code": AXIS_CODES[axis],
                        "evidence_surface": evidence_surface,
                        "realm": realm,
                        "candidate_evidence_count": candidate_count,
                        "fractional_candidate_weight": fractional_weight,
                        "validated_demand_count": 0,
                        "validated_translation_count": 0,
                        "validated_supply_count": math.nan,
                        "screening_validation_state": "screening_only_not_validated",
                        "coding_status": "deterministic_screening_not_human_validated",
                        "analysis_scope": "deterministic_screening_only_not_validated",
                        "zero_interpretation": (
                            "not_observed_in_current_screening_run"
                            if candidate_count == 0
                            else "candidate_for_exact_text_review_not_validated"
                        ),
                    }
                )
    sector_axis_features = pd.DataFrame(sector_axis_feature_rows)
    sector_axis_realms = pd.DataFrame(sector_axis_realm_rows)

    axis_feature_rows: list[dict[str, Any]] = []
    for axis in AXES:
        group = screening_linked.loc[screening_linked["axis_group"].eq(axis)]
        evidence_surface = _evidence_surface(group)
        for feature in PERFORMATIVE_FEATURE_SIGNAL_TYPES:
            hits = int(group[feature].sum())
            axis_feature_rows.append(
                {
                    "axis_group": axis,
                    "axis_code": AXIS_CODES[axis],
                    "evidence_surface": evidence_surface,
                    "feature": feature,
                    "evidence_with_feature": hits,
                    "axis_evidence_total": int(len(group)),
                    "feature_share": hits / len(group) if len(group) else math.nan,
                    "status": "screening_not_validated_performativity",
                }
            )
    axis_features = pd.DataFrame(axis_feature_rows)

    sector_rows: list[dict[str, Any]] = []
    for sector in sector_order:
        group = screening_linked.loc[screening_linked["sector"].eq(sector)]
        linked_group = evidence_map.loc[evidence_map["sector"].eq(sector)]
        axis_counts = np.array(
            [int(group["axis_group"].eq(axis).sum()) for axis in AXES],
            dtype=float,
        )
        demand_group = demands.loc[demands["sector"].eq(sector)]
        dominant_axis = AXES[int(axis_counts.argmax())] if axis_counts.sum() else None
        row: dict[str, Any] = {
            "sector": sector,
            "sector_label": sector_labels[sector],
            "linked_evidence_count": int(linked_group["evidence_id"].nunique()),
            "screening_eligible_linked_evidence_count": int(len(group)),
            "derived_demand_count": int(len(demand_group)),
            "axes_observed": int((axis_counts > 0).sum()),
            "empty_axis_cells": int((axis_counts == 0).sum()),
            "dominant_axis": dominant_axis,
            "dominant_axis_code": (
                AXIS_CODES[dominant_axis] if dominant_axis is not None else None
            ),
            "dominant_axis_share": (
                float(axis_counts.max() / axis_counts.sum())
                if axis_counts.sum()
                else math.nan
            ),
            "normalized_axis_entropy": _normalized_entropy(axis_counts),
            "mean_signal_type_richness": (
                float(group["signal_type_richness"].mean()) if len(group) else math.nan
            ),
            "candidate_realms_observed": int(
                sum(bool(group[column].any()) for column in realm_columns)
            ),
            "validated_translation_events": 0,
            "independent_validated_supply_available": False,
            "shortage_claim_status": "not_computable",
            "screening_validation_state": "screening_only_not_validated",
            "analysis_scope": "deterministic_screening_profile_not_validated",
        }
        for feature in PERFORMATIVE_FEATURE_SIGNAL_TYPES:
            row[f"{feature}_count"] = int(group[feature].sum())
            row[f"{feature}_share"] = (
                float(group[feature].mean()) if len(group) else math.nan
            )
        sector_rows.append(row)
    sector_profile = pd.DataFrame(sector_rows)

    summary: dict[str, Any] = {
        "evidence_records": int(len(evidence)),
        "derived_demands": int(len(demands)),
        "linked_evidence": int(evidence_map["evidence_id"].nunique()),
        "linked_signal_rows": int(len(linked_signals)),
        "linked_evidence_with_signals": int(signal_sets["evidence_id"].nunique()),
        "sector_axis_independence": {
            "unit": "unique linked evidence identity",
            "n": total,
            "linkage_dependence_audit": linkage_dependence,
            "unit_independence_note": (
                "deduplicated evidence IDs avoid duplicated demand rows, but this "
                "curated corpus is not an iid sample and may retain correlated "
                "screening context"
            ),
            "inferential_table_use": (
                "descriptive_corpus_structure_diagnostic_only_not_population_inference"
            ),
            "rows": len(sector_order),
            "columns": len(AXES),
            "active_rows_for_inference": active_row_count,
            "active_columns_for_inference": active_column_count,
            "inferential_status": (
                "computed_on_nonzero_margins"
                if inferential_computable
                else "not_computable_insufficient_nonzero_margins"
            ),
            "degrees_of_freedom": degrees_of_freedom,
            "pearson_chi_square": chi2,
            "permutation_method": (
                f"{permutations:,} unrestricted axis-label permutations with fixed "
                "sector labels and fixed axis margins"
            ),
            "permutation_interpretation": (
                "small p-values indicate non-random corpus structure under the "
                "curated design, not external prevalence or causal demand effects"
            ),
            "permutation_seed": seed,
            "permutations": permutations,
            "permutation_exceedances": permutation_exceedances,
            "permutation_p": permutation_p,
            "bias_corrected_cramers_v": corrected_v,
            "expected_cells_below_5": int((active_expected_array < 5).sum()),
            "expected_cells_below_5_share": (
                float((active_expected_array < 5).mean())
                if active_expected_array.size
                else math.nan
            ),
            "expected_cells_below_1": int((active_expected_array < 1).sum()),
            "expected_cells_below_1_share": (
                float((active_expected_array < 1).mean())
                if active_expected_array.size
                else math.nan
            ),
            "minimum_expected_count": (
                float(active_expected_array.min())
                if active_expected_array.size
                else math.nan
            ),
            "sparse_cell_diagnostic_scope": (
                "active_inferential_margins_only_not_full_display_matrix"
            ),
            "observed_zero_cells": int((observed_array == 0).sum()),
            "holm_significant_cells": int(np.nansum(holm_p < 0.05)),
            "bh_significant_cells": int(np.nansum(bh_p < 0.05)),
            "interpretation_boundary": (
                "association describes the acquired/classified corpus and is "
                "confounded by retrieval/classification design; it is not "
                "workforce prevalence or causal sector demand"
            ),
        },
        "screening_feature_boundary": {
            "all_title_level": (
                _normalized_scope_set(linked_signals["semantic_scope"].tolist())
                == frozenset({"title"})
            ),
            "observed_semantic_scopes": sorted(
                _normalized_scope_set(linked_signals["semantic_scope"].tolist())
            ),
            "screening_scope_policy": (
                "screening accepts retained title/subject_terms/abstract/full_text "
                "surfaces; all_title_level is only a corpus-condition flag for the "
                "current run"
            ),
            "title_only_interpretation": (
                "title_only_screening_condition"
                if _normalized_scope_set(linked_signals["semantic_scope"].tolist())
                == frozenset({"title"})
                else "mixed_semantic_surfaces_screening_condition"
            ),
            "rejected_signal_rows_excluded": rejected_signal_rows_excluded,
            "all_review_required": bool(
                linked_signals["manual_review_status"].eq("review_required").all()
            ),
            "validated_demand_events": 0,
            "validated_translation_events": 0,
            "independently_validated_supply_rows": 0,
            "performative_stage_conclusion": (
                "not computable until exact text spans and two-coder decisions exist"
            ),
        },
        "realm_screening_audit": {
            "binary_candidate_count": int(
                sector_axis_realms["candidate_evidence_count"].sum()
            ),
            "fractional_candidate_weight": float(
                sector_axis_realms["fractional_candidate_weight"].sum()
            ),
            "fractional_weight_expected": screening_linked_total,
            "status": "multi-label screening; fractional weights prevent double count",
            "mapping_basis": (
                "deterministic signal-type to realm crosswalk for screening triage; "
                "conceptual overlap remains and requires exact-span validation"
            ),
            "overlap_audit": {
                "multi_realm_evidence_count": int(
                    screening_linked["realm_count"].gt(1).sum()
                ),
                "multi_realm_evidence_share": (
                    float(screening_linked["realm_count"].gt(1).mean())
                    if screening_linked_total
                    else 0.0
                ),
                "max_candidate_realms_per_evidence": int(
                    screening_linked["realm_count"].max()
                )
                if screening_linked_total
                else 0,
            },
            "robustness_boundary": (
                "realm assignment is deterministic screening triage with allowed "
                "multi-realm overlap; it is not a validated exclusive coding frame"
            ),
        },
    }
    return PerformativeDemandAnalysis(
        evidence_map=evidence_map,
        observed=observed,
        expected=expected,
        residuals=residuals,
        sector_axis_features=sector_axis_features,
        sector_axis_realms=sector_axis_realms,
        axis_features=axis_features,
        sector_profile=sector_profile,
        summary=summary,
    )
