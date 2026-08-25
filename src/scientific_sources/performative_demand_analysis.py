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
    "TECHNOLOGY": frozenset(
        {"digital_skill", "technical_skill", "safety_risk_skill"}
    ),
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


class PerformativeDemandAnalysisError(RuntimeError):
    """Raised when evidence-level analytical invariants do not hold."""


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
    phi2_corrected = max(
        0.0, phi2 - ((cols - 1) * (rows - 1)) / (n - 1)
    )
    rows_corrected = rows - ((rows - 1) ** 2) / (n - 1)
    cols_corrected = cols - ((cols - 1) ** 2) / (n - 1)
    denominator = min(rows_corrected - 1, cols_corrected - 1)
    return math.sqrt(phi2_corrected / denominator) if denominator > 0 else 0.0


def _normalized_entropy(counts: np.ndarray) -> float:
    positive = counts[counts > 0]
    if len(positive) <= 1:
        return 0.0
    probabilities = positive / positive.sum()
    return float(
        -(probabilities * np.log(probabilities)).sum() / np.log(len(counts))
    )


def _wilson_interval(
    successes: int,
    total: int,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    if total == 0:
        return (math.nan, math.nan)
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        (proportion * (1 - proportion) + z * z / (4 * total)) / total
    ) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


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
    orphan_ids = set(evidence_map["evidence_id"]) - set(evidence["evidence_id"])
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


def build_performative_demand_analysis(
    demands: pd.DataFrame,
    evidence: pd.DataFrame,
    signals: pd.DataFrame,
    sector_labels: Mapping[str, str],
    *,
    permutations: int = 50_000,
    seed: int = 20_260_825,
) -> PerformativeDemandAnalysis:
    """Build complete sector-axis tables and candidate screening summaries.

    The sector-axis association is descriptive of the acquired and classified
    corpus.  Permuting axis labels with fixed sector labels and fixed margins
    tests whether the observed table is more structured than random assignment
    within that corpus.  It does not estimate population or workforce demand.
    """
    sector_order = list(sector_labels)
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
    row_totals = observed_array.sum(axis=1)
    column_totals = observed_array.sum(axis=0)
    expected_array = np.outer(row_totals, column_totals) / total
    expected = pd.DataFrame(expected_array, index=sector_order, columns=AXES)

    chi2_contributions = np.divide(
        (observed_array - expected_array) ** 2,
        expected_array,
        out=np.zeros_like(expected_array),
        where=expected_array > 0,
    )
    chi2 = float(chi2_contributions.sum())
    degrees_of_freedom = (len(sector_order) - 1) * (len(AXES) - 1)
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
        out=np.zeros_like(expected_array),
        where=residual_denominator > 0,
    )
    cell_p = np.array(
        [math.erfc(abs(value) / math.sqrt(2)) for value in adjusted_residuals.ravel()]
    )
    holm_p = _adjust_holm(cell_p).reshape(adjusted_residuals.shape)
    bh_p = _adjust_bh(cell_p).reshape(adjusted_residuals.shape)

    row_codes = pd.Categorical(
        evidence_map["sector"], categories=sector_order
    ).codes
    column_codes = pd.Categorical(
        evidence_map["axis_group"], categories=AXES
    ).codes
    permutation_p, permutation_exceedances = _permutation_chi2_p(
        row_codes,
        column_codes,
        expected_array,
        chi2,
        permutations,
        seed,
    )
    corrected_v = _bias_corrected_cramers_v(
        chi2, total, len(sector_order), len(AXES)
    )

    residual_rows: list[dict[str, Any]] = []
    for row_index, sector in enumerate(sector_order):
        for column_index, axis in enumerate(AXES):
            observed_count = int(observed_array[row_index, column_index])
            residual_rows.append(
                {
                    "sector": sector,
                    "sector_label": sector_labels[sector],
                    "axis_group": axis,
                    "observed_evidence_count": observed_count,
                    "expected_evidence_count": float(
                        expected_array[row_index, column_index]
                    ),
                    "adjusted_standardized_residual": float(
                        adjusted_residuals[row_index, column_index]
                    ),
                    "raw_cell_p": float(
                        cell_p.reshape(adjusted_residuals.shape)[
                            row_index, column_index
                        ]
                    ),
                    "holm_p": float(holm_p[row_index, column_index]),
                    "bh_p": float(bh_p[row_index, column_index]),
                    "holm_significant_0_05": bool(
                        holm_p[row_index, column_index] < 0.05
                    ),
                    "bh_significant_0_05": bool(
                        bh_p[row_index, column_index] < 0.05
                    ),
                    "cell_status": (
                        "empty_current_linked_corpus"
                        if observed_count == 0
                        else "observed_screening_evidence"
                    ),
                }
            )
    residuals = pd.DataFrame(residual_rows)

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
    linked_signals = linked_signals.rename(
        columns={"sector_linked": "sector", "axis_group_linked": "axis_group"}
    )
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
            }
        )
    signal_sets = pd.DataFrame(signal_set_rows)
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
    all_linked["signal_type_richness"] = all_linked["signal_types"].map(len)
    for feature, members in PERFORMATIVE_FEATURE_SIGNAL_TYPES.items():
        all_linked[feature] = [
            bool(values & members)
            for values in all_linked["signal_types"].tolist()
        ]
    for realm, members in REALM_SIGNAL_TYPES.items():
        all_linked[f"realm_{realm}"] = [
            bool(values & members)
            for values in all_linked["signal_types"].tolist()
        ]
    realm_columns = [f"realm_{realm}" for realm in REALMS]
    all_linked["realm_count"] = all_linked[realm_columns].sum(axis=1)
    if (all_linked["realm_count"] == 0).any():
        raise PerformativeDemandAnalysisError(
            "at least one linked evidence identity has no candidate realm mapping"
        )

    sector_axis_feature_rows: list[dict[str, Any]] = []
    sector_axis_realm_rows: list[dict[str, Any]] = []
    for sector in sector_order:
        for axis in AXES:
            group = all_linked.loc[
                all_linked["sector"].eq(sector)
                & all_linked["axis_group"].eq(axis)
            ]
            demand_group = demands.loc[
                demands["sector"].eq(sector) & demands["axis_group"].eq(axis)
            ]
            signal_union: set[str] = set()
            for values in group["signal_types"]:
                signal_union.update(values)
            feature_row: dict[str, Any] = {
                "sector": sector,
                "sector_label": sector_labels[sector],
                "axis_group": axis,
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
                "evidence_status": (
                    "screening_only_title_level"
                    if len(group)
                    else "empty_current_linked_corpus"
                ),
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
                        "realm": realm,
                        "candidate_evidence_count": candidate_count,
                        "fractional_candidate_weight": fractional_weight,
                        "validated_demand_count": 0,
                        "validated_translation_count": 0,
                        "validated_supply_count": math.nan,
                        "coding_status": (
                            "deterministic_title_screening_not_human_validated"
                        ),
                        "zero_interpretation": (
                            "not_observed_in_current_screening_run"
                            if candidate_count == 0
                            else "candidate_for_text_review"
                        ),
                    }
                )
    sector_axis_features = pd.DataFrame(sector_axis_feature_rows)
    sector_axis_realms = pd.DataFrame(sector_axis_realm_rows)

    axis_feature_rows: list[dict[str, Any]] = []
    for axis in AXES:
        group = all_linked.loc[all_linked["axis_group"].eq(axis)]
        for feature in PERFORMATIVE_FEATURE_SIGNAL_TYPES:
            hits = int(group[feature].sum())
            lower, upper = _wilson_interval(hits, len(group))
            axis_feature_rows.append(
                {
                    "axis_group": axis,
                    "feature": feature,
                    "evidence_with_feature": hits,
                    "axis_evidence_total": int(len(group)),
                    "feature_share": hits / len(group) if len(group) else math.nan,
                    "wilson_95_lower": lower,
                    "wilson_95_upper": upper,
                    "status": "title_screening_not_validated_performativity",
                }
            )
    axis_features = pd.DataFrame(axis_feature_rows)

    sector_rows: list[dict[str, Any]] = []
    for sector in sector_order:
        group = all_linked.loc[all_linked["sector"].eq(sector)]
        axis_counts = np.array(
            [int(group["axis_group"].eq(axis).sum()) for axis in AXES],
            dtype=float,
        )
        demand_group = demands.loc[demands["sector"].eq(sector)]
        row: dict[str, Any] = {
            "sector": sector,
            "sector_label": sector_labels[sector],
            "linked_evidence_count": int(len(group)),
            "derived_demand_count": int(len(demand_group)),
            "axes_observed": int((axis_counts > 0).sum()),
            "empty_axis_cells": int((axis_counts == 0).sum()),
            "dominant_axis": (
                AXES[int(axis_counts.argmax())] if axis_counts.sum() else None
            ),
            "dominant_axis_share": (
                float(axis_counts.max() / axis_counts.sum())
                if axis_counts.sum()
                else math.nan
            ),
            "normalized_axis_entropy": _normalized_entropy(axis_counts),
            "mean_signal_type_richness": (
                float(group["signal_type_richness"].mean())
                if len(group)
                else math.nan
            ),
            "candidate_realms_observed": int(
                sum(bool(group[column].any()) for column in realm_columns)
            ),
            "validated_translation_events": 0,
            "independent_validated_supply_available": False,
            "shortage_claim_status": "not_computable",
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
            "rows": len(sector_order),
            "columns": len(AXES),
            "degrees_of_freedom": degrees_of_freedom,
            "pearson_chi_square": chi2,
            "permutation_method": (
                f"{permutations:,} unrestricted axis-label permutations with fixed "
                "sector labels and fixed axis margins"
            ),
            "permutation_seed": seed,
            "permutations": permutations,
            "permutation_exceedances": permutation_exceedances,
            "permutation_p": permutation_p,
            "bias_corrected_cramers_v": corrected_v,
            "expected_cells_below_5": int((expected_array < 5).sum()),
            "expected_cells_below_5_share": float((expected_array < 5).mean()),
            "expected_cells_below_1": int((expected_array < 1).sum()),
            "expected_cells_below_1_share": float((expected_array < 1).mean()),
            "minimum_expected_count": float(expected_array.min()),
            "observed_zero_cells": int((observed_array == 0).sum()),
            "holm_significant_cells": int((holm_p < 0.05).sum()),
            "bh_significant_cells": int((bh_p < 0.05).sum()),
            "interpretation_boundary": (
                "association describes the acquired/classified corpus and is "
                "confounded by retrieval/classification design; it is not "
                "workforce prevalence or causal sector demand"
            ),
        },
        "screening_feature_boundary": {
            "all_title_level": bool(
                linked_signals["semantic_scope"].eq("title").all()
            ),
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
            "fractional_weight_expected": total,
            "status": "multi-label title screening; fractional weights prevent double count",
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
