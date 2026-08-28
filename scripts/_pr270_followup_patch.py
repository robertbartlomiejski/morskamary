from __future__ import annotations

from pathlib import Path
import re
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, block: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + block.strip() + "\n", encoding="utf-8")


def patch_analysis() -> None:
    path = "src/scientific_sources/performative_demand_analysis.py"
    replace_once(path, '''    observed_array = observed.to_numpy(dtype=float)\n    total = int(observed_array.sum())\n    row_totals = observed_array.sum(axis=1)\n    column_totals = observed_array.sum(axis=0)\n    expected_array = np.outer(row_totals, column_totals) / total\n    expected = pd.DataFrame(expected_array, index=sector_order, columns=AXES)\n\n    chi2_contributions = np.divide(\n        (observed_array - expected_array) ** 2,\n        expected_array,\n        out=np.zeros_like(expected_array),\n        where=expected_array > 0,\n    )\n    chi2 = float(chi2_contributions.sum())\n    degrees_of_freedom = (len(sector_order) - 1) * (len(AXES) - 1)\n    row_proportions = row_totals / total\n    column_proportions = column_totals / total\n    residual_denominator = np.sqrt(\n        expected_array\n        * (1 - row_proportions[:, None])\n        * (1 - column_proportions[None, :])\n    )\n    adjusted_residuals = np.divide(\n        observed_array - expected_array,\n        residual_denominator,\n        out=np.zeros_like(expected_array),\n        where=residual_denominator > 0,\n    )\n    cell_p = np.array(\n        [math.erfc(abs(value) / math.sqrt(2)) for value in adjusted_residuals.ravel()]\n    )\n    holm_p = _adjust_holm(cell_p).reshape(adjusted_residuals.shape)\n    bh_p = _adjust_bh(cell_p).reshape(adjusted_residuals.shape)\n\n    row_codes = pd.Categorical(evidence_map["sector"], categories=sector_order).codes\n    column_codes = pd.Categorical(evidence_map["axis_group"], categories=AXES).codes\n    permutation_p, permutation_exceedances = _permutation_chi2_p(\n        row_codes,\n        column_codes,\n        expected_array,\n        chi2,\n        permutations,\n        seed,\n    )\n    corrected_v = _bias_corrected_cramers_v(chi2, total, len(sector_order), len(AXES))\n''', '''    observed_array = observed.to_numpy(dtype=float)\n    total = int(observed_array.sum())\n    if total <= 0:\n        raise PerformativeDemandAnalysisError("no observed evidence is available for inference")\n    row_totals = observed_array.sum(axis=1)\n    column_totals = observed_array.sum(axis=0)\n    expected_array = np.outer(row_totals, column_totals) / total\n    expected = pd.DataFrame(expected_array, index=sector_order, columns=AXES)\n    active_row_mask = row_totals > 0\n    active_column_mask = column_totals > 0\n    active_row_count = int(active_row_mask.sum())\n    active_column_count = int(active_column_mask.sum())\n    inferential_computable = active_row_count >= 2 and active_column_count >= 2\n    chi2_contributions = np.divide(\n        (observed_array - expected_array) ** 2, expected_array,\n        out=np.zeros_like(expected_array), where=expected_array > 0,\n    )\n    chi2 = float(chi2_contributions.sum()) if inferential_computable else math.nan\n    degrees_of_freedom = ((active_row_count - 1) * (active_column_count - 1) if inferential_computable else 0)\n    row_proportions = row_totals / total\n    column_proportions = column_totals / total\n    residual_denominator = np.sqrt(\n        expected_array * (1 - row_proportions[:, None]) * (1 - column_proportions[None, :])\n    )\n    adjusted_residuals = np.divide(\n        observed_array - expected_array, residual_denominator,\n        out=np.full_like(expected_array, np.nan), where=residual_denominator > 0,\n    )\n    valid_residual_mask = np.isfinite(adjusted_residuals) & (expected_array > 0)\n    cell_p = np.full(adjusted_residuals.shape, np.nan, dtype=float)\n    holm_p = np.full(adjusted_residuals.shape, np.nan, dtype=float)\n    bh_p = np.full(adjusted_residuals.shape, np.nan, dtype=float)\n    if valid_residual_mask.any():\n        valid_p = np.array([math.erfc(abs(value) / math.sqrt(2)) for value in adjusted_residuals[valid_residual_mask]])\n        cell_p[valid_residual_mask] = valid_p\n        holm_p[valid_residual_mask] = _adjust_holm(valid_p)\n        bh_p[valid_residual_mask] = _adjust_bh(valid_p)\n    row_codes = pd.Categorical(evidence_map["sector"], categories=sector_order).codes\n    column_codes = pd.Categorical(evidence_map["axis_group"], categories=AXES).codes\n    if inferential_computable:\n        permutation_p, permutation_exceedances = _permutation_chi2_p(\n            row_codes, column_codes, expected_array, chi2, permutations, seed\n        )\n        corrected_v = _bias_corrected_cramers_v(chi2, total, active_row_count, active_column_count)\n    else:\n        permutation_p, permutation_exceedances, corrected_v = math.nan, 0, math.nan\n''')
    replace_once(path, '''                    "raw_cell_p": float(\n                        cell_p.reshape(adjusted_residuals.shape)[\n                            row_index, column_index\n                        ]\n                    ),\n''', '''                    "raw_cell_p": float(cell_p[row_index, column_index]),\n''')
    replace_once(path, '''                    "holm_significant_0_05": bool(\n                        holm_p[row_index, column_index] < 0.05\n                    ),\n                    "bh_significant_0_05": bool(bh_p[row_index, column_index] < 0.05),\n''', '''                    "holm_significant_0_05": bool(np.isfinite(holm_p[row_index, column_index]) and holm_p[row_index, column_index] < 0.05),\n                    "bh_significant_0_05": bool(np.isfinite(bh_p[row_index, column_index]) and bh_p[row_index, column_index] < 0.05),\n''')
    replace_once(path, '''    linked_signals = linked_signals.rename(\n        columns={"sector_linked": "sector", "axis_group_linked": "axis_group"}\n    )\n''', '''    linked_signals["manual_review_status"] = linked_signals["manual_review_status"].astype(str).str.strip().str.lower()\n    rejected_signal_rows_excluded = int(linked_signals["manual_review_status"].eq("rejected").sum())\n    linked_signals = linked_signals.loc[~linked_signals["manual_review_status"].eq("rejected")].copy()\n    unsupported_review_statuses = set(linked_signals["manual_review_status"]) - {"review_required"}\n    if unsupported_review_statuses:\n        raise PerformativeDemandAnalysisError(\n            "validated/manual review statuses require an accepted validation ledger; unsupported screening statuses: "\n            + ", ".join(sorted(unsupported_review_statuses))\n        )\n    if linked_signals.empty:\n        raise PerformativeDemandAnalysisError("no non-rejected review_required signals remain for screening")\n    linked_signals = linked_signals.rename(\n        columns={"sector_linked": "sector", "axis_group_linked": "axis_group"}\n    )\n''')
    replace_once(path, '''    all_linked["realm_count"] = all_linked[realm_columns].sum(axis=1)\n    if (all_linked["realm_count"] == 0).any():\n        raise PerformativeDemandAnalysisError(\n            "at least one linked evidence identity has no candidate realm mapping"\n        )\n\n    sector_axis_feature_rows''', '''    all_linked["realm_count"] = all_linked[realm_columns].sum(axis=1)\n    screening_linked = all_linked.loc[all_linked["signal_type_richness"].gt(0)].copy()\n    if (screening_linked["realm_count"] == 0).any():\n        raise PerformativeDemandAnalysisError(\n            "at least one non-rejected linked evidence identity has no candidate realm mapping"\n        )\n\n    sector_axis_feature_rows''')
    replace_once(path, '''            group = all_linked.loc[\n                all_linked["sector"].eq(sector) & all_linked["axis_group"].eq(axis)\n            ]\n''', '''            group = screening_linked.loc[\n                screening_linked["sector"].eq(sector) & screening_linked["axis_group"].eq(axis)\n            ]\n''')
    replace_once(path, '        group = all_linked.loc[all_linked["axis_group"].eq(axis)]\n', '        group = screening_linked.loc[screening_linked["axis_group"].eq(axis)]\n')
    replace_once(path, '        group = all_linked.loc[all_linked["sector"].eq(sector)]\n', '        group = screening_linked.loc[screening_linked["sector"].eq(sector)]\n')
    replace_once(path, '''            "rows": len(sector_order),\n            "columns": len(AXES),\n            "degrees_of_freedom": degrees_of_freedom,\n''', '''            "rows": len(sector_order),\n            "columns": len(AXES),\n            "active_rows_for_inference": active_row_count,\n            "active_columns_for_inference": active_column_count,\n            "inferential_status": ("computed_on_nonzero_margins" if inferential_computable else "not_computable_insufficient_nonzero_margins"),\n            "degrees_of_freedom": degrees_of_freedom,\n''')
    replace_once(path, '''            "holm_significant_cells": int((holm_p < 0.05).sum()),\n            "bh_significant_cells": int((bh_p < 0.05).sum()),\n''', '''            "holm_significant_cells": int(np.nansum(holm_p < 0.05)),\n            "bh_significant_cells": int(np.nansum(bh_p < 0.05)),\n''')
    replace_once(path, '''        "screening_feature_boundary": {\n            "all_title_level": bool(linked_signals["semantic_scope"].eq("title").all()),\n''', '''        "screening_feature_boundary": {\n            "all_title_level": (_normalized_scope_set(linked_signals["semantic_scope"].tolist()) == frozenset({"title"})),\n            "rejected_signal_rows_excluded": rejected_signal_rows_excluded,\n''')


def patch_builder() -> None:
    path = "scripts/build_performative_demand_cross_axis_analysis.py"
    replace_once(path, "import argparse\nimport json\nimport sys\n", "import argparse\nimport hashlib\nimport json\nimport sys\n")
    replace_once(path, "from typing import Sequence, cast\n", "from typing import Any, Mapping, Sequence, cast\n")
    marker = "\ndef main(argv: Sequence[str] | None = None) -> int:\n"
    block = dedent('''
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


    def _source_provenance(database: Path, frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
        manifest_path = database / "cumulative_database_manifest.json"
        if not manifest_path.exists():
            raise RuntimeError("cumulative database manifest is required for analysis provenance")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_names = ["derived_competence_demands.csv", "evidence_records.csv", "competence_demand_signals.csv"]
        observed: dict[str, dict[str, str]] = {}
        for table_name, frame in frames.items():
            for field in ("current_run_id", "run_id", "classifier_version"):
                if field not in frame.columns:
                    continue
                values = {str(v).strip() for v in frame[field].dropna().tolist() if str(v).strip()}
                if len(values) > 1:
                    raise RuntimeError(f"{table_name} mixes multiple {field} values: {sorted(values)}")
                if values:
                    observed.setdefault(field, {})[table_name] = next(iter(values))
        for field, by_table in observed.items():
            values = set(by_table.values())
            if len(values) > 1:
                raise RuntimeError(f"input tables disagree on {field}: {sorted(values)}")
            manifest_value = str(manifest.get(field, "")).strip()
            if manifest_value and manifest_value not in values:
                raise RuntimeError(f"cumulative manifest {field} conflicts with table lineage")
        return {
            "cumulative_manifest_schema_version": manifest.get("schema_version"),
            "cumulative_manifest_generated_at_utc": manifest.get("generated_at_utc"),
            "cumulative_manifest_generated_by": manifest.get("generated_by"),
            "cumulative_manifest_status": manifest.get("status"),
            "qmbd_assignment_methodology": manifest.get("qmbd_assignment_methodology"),
            "evidence_map_exact_rows": manifest.get("evidence_map_exact_rows"),
            "demand_profile_rows": manifest.get("demand_profile_rows"),
            "joined_evidence_id_count": manifest.get("joined_evidence_id_count"),
            "records_in_database": manifest.get("records_in_database"),
            "source_file_sha256": {name: _sha256(database / name) for name in source_names},
            "run_classifier_identity": {
                "status": "verified_from_available_fields" if observed else "not_exposed_in_frozen_snapshot",
                "observed_fields": observed,
                "current_run_id": manifest.get("current_run_id"),
                "classifier_version": manifest.get("classifier_version"),
            },
        }


    def _hypothesis_outcomes(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
        reasons = {
            "H1": "this evidence-structure package does not recompute demand_strength_score effect sizes",
            "H2": "independently validated EQF 6-7 supply is unavailable in this package",
            "H3": "validated semantic translation bridges are unavailable in this package",
        }
        rows = []
        for hypothesis_id, config in protocol.get("hypotheses", {}).items():
            result_fields = {str(field): None for field in config.get("required_result_fields", [])}
            result_fields["hypothesis_id"] = hypothesis_id
            result_fields["hypothesis_label"] = config.get("label")
            result_fields["interpretation"] = reasons.get(hypothesis_id, "required evidence is outside this package")
            rows.append({
                "hypothesis_id": hypothesis_id,
                "hypothesis_label": config.get("label"),
                "definition": config.get("definition"),
                "test": config.get("test"),
                "direction": config.get("direction"),
                "required_axes": config.get("required_axes", []),
                "declared_outcomes": config.get("declared_outcomes", []),
                "status": "not_computable",
                "result_fields": result_fields,
                "warning": reasons.get(hypothesis_id, "required evidence is outside this package"),
            })
        return rows


    def _write_governance_artifacts(output: Path, protocol: Mapping[str, Any], source_provenance: Mapping[str, Any]) -> None:
        (output / "validity_threats.json").write_text(json.dumps({
            "claim_boundary": [
                "association describes the acquired/classified corpus, not population prevalence",
                "screening signal is not a validated competence demand",
                "co-occurrence is not a directional translation bridge",
                "translation is not validated performativity",
                "demand is not independently validated supply or a supply gap",
                "coastal-tourism comparison is not retained repository evidence",
            ],
            "known_design_threats": [
                "retrieval/classification design confounds prevalence interpretation",
                "semantic signals require exact-span human validation",
                "multi-label screening is not an independent-event design",
            ],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "value_labels.json").write_text(json.dumps({
            "axis_group_to_axis_code": AXIS_CODES,
            "review_status_contract": {
                "review_required": "eligible for deterministic screening only",
                "rejected": "excluded from positive screening aggregates",
                "other": "fail closed until accepted validation ledger is ingested",
            },
            "zero_interpretation": "not observed in declared screening state, not absent in reality",
            "supply_gap_status": "not_computable_no_independent_supply",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (output / "hypothesis_outcomes.json").write_text(json.dumps(_hypothesis_outcomes(protocol), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        files = {}
        for artifact in sorted(output.iterdir()):
            if artifact.is_file() and artifact.name != "package_manifest.json":
                files[artifact.name] = {"sha256": _sha256(artifact), "bytes": artifact.stat().st_size}
        (output / "package_manifest.json").write_text(json.dumps({
            "package_schema_version": "1.0",
            "generated_by": "scripts/build_performative_demand_cross_axis_analysis.py",
            "protocol_version": protocol.get("protocol_version"),
            "source_provenance": source_provenance,
            "files": files,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
''')
    replace_once(path, marker, "\n" + block + marker)
    replace_once(path, '''    signals = pd.read_csv(database / "competence_demand_signals.csv")\n\n    analysis = build_performative_demand_analysis(\n''', '''    signals = pd.read_csv(database / "competence_demand_signals.csv")\n    source_provenance = _source_provenance(database, {"demands": demands, "evidence": evidence, "signals": signals})\n\n    analysis = build_performative_demand_analysis(\n''')
    replace_once(path, '''    output = args.output_dir\n    output.mkdir(parents=True, exist_ok=True)\n''', '''    output = args.output_dir\n    output.mkdir(parents=True, exist_ok=True)\n    legacy_profile = output / "sector_deficit_profile.csv"\n    if legacy_profile.exists():\n        legacy_profile.unlink()\n''')
    replace_once(path, '''    analysis.sector_profile.to_csv(output / "sector_deficit_profile.csv", index=False)\n''', '''    analysis.sector_profile.to_csv(output / "sector_screening_profile.csv", index=False)\n    lineage = analysis.evidence_map.copy()\n    lineage["axis_code"] = lineage["axis_group"].map(AXIS_CODES)\n    lineage = lineage[["evidence_id", "sector", "axis_group", "axis_code"]]\n    lineage.sort_values(["evidence_id", "sector", "axis_group"]).to_csv(output / "linked_evidence_sector_axis_lineage.csv", index=False)\n''')
    replace_once(path, '''    (output / "statistics_summary.json").write_text(\n        json.dumps(analysis.summary, indent=2, sort_keys=True) + "\\n",\n        encoding="utf-8",\n    )\n    print(json.dumps(analysis.summary, indent=2, sort_keys=True))\n''', '''    summary = dict(analysis.summary)\n    summary["source_provenance"] = source_provenance\n    (output / "statistics_summary.json").write_text(\n        json.dumps(summary, indent=2, sort_keys=True) + "\\n", encoding="utf-8"\n    )\n    _write_governance_artifacts(output, protocol, source_provenance)\n    print(json.dumps(summary, indent=2, sort_keys=True))\n''')


def patch_validator() -> None:
    path = "scripts/validate_generated_outputs.py"
    replace_once(path, "import json\nimport re\n", "import hashlib\nimport json\nimport os\nimport re\n")
    replace_once(path, '''        "sector_deficit_profile.csv": {"sector", "dominant_axis", "dominant_axis_code"},\n''', '''        "sector_screening_profile.csv": {"sector", "dominant_axis", "dominant_axis_code"},\n        "linked_evidence_sector_axis_lineage.csv": {"evidence_id", "sector", "axis_group", "axis_code"},\n''')
    replace_once(path, '''    expected_names = set(schemas) | {"statistics_summary.json"}\n''', '''    expected_names = set(schemas) | {"statistics_summary.json", "hypothesis_outcomes.json", "validity_threats.json", "value_labels.json", "package_manifest.json"}\n''')
    replace_once(path, '''    summary_path = output_dir / "statistics_summary.json"\n    require_file(summary_path)\n''', '''    summary_path = output_dir / "statistics_summary.json"\n    require_file(summary_path)\n    if (output_dir / "sector_deficit_profile.csv").exists():\n        fail("legacy sector_deficit_profile.csv must not be published as a supply-gap claim")\n    manifest_path = output_dir / "package_manifest.json"\n    hypothesis_path = output_dir / "hypothesis_outcomes.json"\n    require_file(manifest_path)\n    require_file(hypothesis_path)\n    if manifest_path.exists():\n        package_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))\n        manifest_files = package_manifest.get("files", {})\n        expected_manifest_files = expected_names - {"package_manifest.json"}\n        if not isinstance(manifest_files, dict) or set(manifest_files) != expected_manifest_files:\n            fail("package_manifest.json file set does not match governed artifacts")\n        elif isinstance(manifest_files, dict):\n            for name, metadata in manifest_files.items():\n                artifact = output_dir / name\n                if artifact.exists():\n                    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()\n                    if not isinstance(metadata, dict) or metadata.get("sha256") != digest:\n                        fail(f"package manifest checksum mismatch: {name}")\n    if hypothesis_path.exists():\n        rows_h = json.loads(hypothesis_path.read_text(encoding="utf-8"))\n        if {row.get("hypothesis_id") for row in rows_h if isinstance(row, dict)} != {"H1", "H2", "H3"}:\n            fail("hypothesis_outcomes.json must serialize H1, H2, and H3")\n''')
    replace_once(path, '''        completed = subprocess.run(\n            [sys.executable, str(builder), "--output-dir", tmp],\n''', '''        database_dir = Path(os.environ.get("MORSKAMARY_CUMULATIVE_DATABASE_DIR", str(OUTPUTS_DIR / "cumulative_database")))\n        completed = subprocess.run(\n            [sys.executable, str(builder), "--database-dir", str(database_dir), "--output-dir", tmp],\n''')


def patch_full_analysis_workflow() -> None:
    path = ".github/workflows/full-analysis.yml"
    replace_once(path, '''      STATIC_RECOVERY_REASON: "Full Analysis CI reproducibility check"\n''', '''      STATIC_RECOVERY_REASON: "Full Analysis CI reproducibility check"\n      MORSKAMARY_CUMULATIVE_DATABASE_DIR: ${{ runner.temp }}/full-analysis-retained-inputs/cumulative_database\n''')
    replace_once(path, '''            "literature_integration.html"\n            "report_index.html"\n''', '''            "literature_integration.html"\n            "performative_demand_cross_axis"\n            "report_index.html"\n''')
    replace_once(path, '''          for relative_path in "${generated_paths[@]}"; do\n''', '''          if [[ ! -d "outputs/cumulative_database" ]]; then\n            echo "Missing retained cumulative database required by performative-demand analysis"\n            exit 1\n          fi\n          cp -R "outputs/cumulative_database" "$RETAINED_INPUT_ROOT/cumulative_database"\n          for relative_path in "${generated_paths[@]}"; do\n''')
    replace_once(path, '''      - name: Verify output artifacts\n''', '''      - name: Regenerate performative-demand package from retained cumulative database\n        run: >-\n          python scripts/build_performative_demand_cross_axis_analysis.py\n          --database-dir "$MORSKAMARY_CUMULATIVE_DATABASE_DIR"\n\n      - name: Verify output artifacts\n''')
    replace_once(path, '''          python run_full_analysis.py --analysis-input-mode static\n          cp -R outputs/. "$STATIC_COMPARE_ROOT/"\n''', '''          python run_full_analysis.py --analysis-input-mode static\n          python scripts/build_performative_demand_cross_axis_analysis.py --database-dir "$MORSKAMARY_CUMULATIVE_DATABASE_DIR"\n          cp -R outputs/. "$STATIC_COMPARE_ROOT/"\n''')
    replace_once(path, '''          python run_full_analysis.py --analysis-input-mode static\n          python scripts/compare_generated_outputs.py \\\n''', '''          python run_full_analysis.py --analysis-input-mode static\n          python scripts/build_performative_demand_cross_axis_analysis.py --database-dir "$MORSKAMARY_CUMULATIVE_DATABASE_DIR"\n          python scripts/compare_generated_outputs.py \\\n''')


def patch_tests() -> None:
    path = "tests/test_performative_demand_analysis.py"
    replace_once(path, "import pandas as pd\n", "import pandas as pd\nimport pytest\n")
    replace_once(path, '''    REALMS,\n    build_performative_demand_analysis,\n''', '''    REALMS,\n    PerformativeDemandAnalysisError,\n    build_performative_demand_analysis,\n''')
    append_once(path, "def test_rejected_signals_are_excluded_fail_closed", dedent('''
    def test_rejected_signals_are_excluded_fail_closed() -> None:
        demands, evidence, signals = _frames()
        rejected = signals.iloc[[0]].copy()
        rejected["signal_type"] = "digital_skill"
        rejected["manual_review_status"] = "rejected"
        signals = pd.concat([signals, rejected], ignore_index=True)
        analysis = build_performative_demand_analysis(demands, evidence, signals, {"sector_a": "Sector A", "sector_b": "Sector B"}, permutations=9, seed=42)
        row = analysis.sector_axis_features.loc[analysis.sector_axis_features["sector"].eq("sector_a") & analysis.sector_axis_features["axis_group"].eq("MARINE")].iloc[0]
        assert row["technical_operational_capability_count"] == 1
        assert analysis.summary["screening_feature_boundary"]["rejected_signal_rows_excluded"] == 1


    def test_non_screening_review_status_requires_validation_ledger() -> None:
        demands, evidence, signals = _frames()
        signals.loc[0, "manual_review_status"] = "manually_reviewed"
        with pytest.raises(PerformativeDemandAnalysisError, match="validation ledger"):
            build_performative_demand_analysis(demands, evidence, signals, {"sector_a": "Sector A", "sector_b": "Sector B"}, permutations=9, seed=42)


    def test_title_level_audit_uses_normalized_scopes() -> None:
        demands, evidence, signals = _frames()
        signals.loc[0, "semantic_scope"] = " Title "
        signals.loc[1, "semantic_scope"] = "TITLE"
        analysis = build_performative_demand_analysis(demands, evidence, signals, {"sector_a": "Sector A", "sector_b": "Sector B"}, permutations=9, seed=42)
        assert analysis.summary["screening_feature_boundary"]["all_title_level"] is True


    def test_zero_margin_dimensions_are_excluded_from_inference() -> None:
        demands, evidence, signals = _frames()
        analysis = build_performative_demand_analysis(demands, evidence, signals, {"sector_a": "Sector A", "sector_b": "Sector B"}, permutations=9, seed=42)
        inference = analysis.summary["sector_axis_independence"]
        assert inference["active_rows_for_inference"] == 2
        assert inference["active_columns_for_inference"] == 2
        assert inference["degrees_of_freedom"] == 1
        assert inference["inferential_status"] == "computed_on_nonzero_margins"
    '''))


def patch_docs() -> None:
    append_once("docs/PERFORMATIVE_DEMAND_CROSS_AXIS_METHOD.md", "## PR #270 follow-up governance contract", '''## PR #270 follow-up governance contract

This publication directory is a deterministic screening package, not a validated supply-gap package. `sector_screening_profile.csv` replaces the misleading deficit-profile name. Rejected semantic signals are excluded from positive screening aggregates; any reviewed state other than `review_required` fails closed until an accepted validation ledger is ingested.

`linked_evidence_sector_axis_lineage.csv` preserves exact evidence-identity lineage. `package_manifest.json`, `validity_threats.json`, `value_labels.json`, and `hypothesis_outcomes.json` provide machine-readable governance. H1–H3 retain the authoritative protocol definitions and are emitted as `not_computable` where this package lacks the required evidence. Full Analysis regenerates this package only from the retained cumulative snapshot; it performs no live acquisition.''')
    append_once("CHANGELOG.txt", "PR #270 follow-up completion hardening", '''PR #270 follow-up completion hardening
- Regenerate performative-demand outputs inside Full Analysis from the retained cumulative snapshot.
- Exclude rejected review signals and fail closed on unsupported reviewed statuses.
- Add evidence lineage, source provenance, checksums, validity threats, value labels, and H1–H3 outcomes.
- Rename the screening profile to avoid implying an independently validated supply deficit.
- Restrict inferential dimensions to non-zero margins while retaining all zero cells descriptively.''')


def main() -> None:
    patch_analysis()
    patch_builder()
    patch_validator()
    patch_full_analysis_workflow()
    patch_tests()
    patch_docs()


if __name__ == "__main__":
    main()
