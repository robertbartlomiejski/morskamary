from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected exactly one match, found {count}: {old[:100]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_analysis() -> None:
    path = "src/scientific_sources/performative_demand_analysis.py"
    replace_once(
        path,
        'AXES = ("MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION")\nREALMS = ("ECONOMY", "TECHNOLOGY", "POLICY_GOVERNANCE", "CULTURE_LEARNING")',
        dedent(
            '''\
            AXES = ("MARINE", "MARITIME", "OCEANIC", "HYDRONIZATION")
            AXIS_CODES: Mapping[str, str] = {
                "MARINE": "M",
                "MARITIME": "T",
                "OCEANIC": "O",
                "HYDRONIZATION": "H",
            }
            REALMS = ("ECONOMY", "TECHNOLOGY", "POLICY_GOVERNANCE", "CULTURE_LEARNING")'''
        ),
    )
    replace_once(
        path,
        "def build_unique_evidence_map(demands: pd.DataFrame) -> pd.DataFrame:\n",
        dedent(
            '''\
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
                        scopes.update(
                            str(item).strip() for item in value if str(item).strip()
                        )
                return "|".join(sorted(scopes))


            def build_unique_evidence_map(demands: pd.DataFrame) -> pd.DataFrame:
            '''
        ),
    )
    replace_once(
        path,
        '                    "axis_group": axis,\n                    "observed_evidence_count": observed_count,',
        '                    "axis_group": axis,\n                    "axis_code": AXIS_CODES[axis],\n                    "observed_evidence_count": observed_count,',
    )
    replace_once(
        path,
        dedent(
            '''\
                            "signal_types": frozenset(
                                str(value) for value in group["signal_type"].tolist()
                            ),
            '''
        ),
        dedent(
            '''\
                            "signal_types": frozenset(
                                str(value) for value in group["signal_type"].tolist()
                            ),
                            "semantic_scopes": _normalized_scope_set(
                                group["semantic_scope"].tolist()
                            ),
            '''
        ),
    )
    replace_once(
        path,
        '    all_linked["signal_types"] = normalized_signal_types\n    all_linked["signal_type_richness"] = all_linked["signal_types"].map(len)',
        dedent(
            '''\
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
                all_linked["signal_type_richness"] = all_linked["signal_types"].map(len)'''
        ),
    )
    replace_once(
        path,
        dedent(
            '''\
                        signal_union: set[str] = set()
                        for values in group["signal_types"]:
                            signal_union.update(values)
                        feature_row: dict[str, Any] = {
            '''
        ),
        dedent(
            '''\
                        signal_union: set[str] = set()
                        for values in group["signal_types"]:
                            signal_union.update(values)
                        evidence_surface = _evidence_surface(group)
                        feature_row: dict[str, Any] = {
            '''
        ),
    )
    replace_once(
        path,
        '                "axis_group": axis,\n                "unique_evidence_count": int(len(group)),',
        '                "axis_group": axis,\n                "axis_code": AXIS_CODES[axis],\n                "evidence_surface": evidence_surface,\n                "unique_evidence_count": int(len(group)),',
    )
    replace_once(
        path,
        dedent(
            '''\
                            "evidence_status": (
                                "screening_only_title_level"
                                if len(group)
                                else "empty_current_linked_corpus"
                            ),'''
        ),
        dedent(
            '''\
                            "evidence_status": (
                                "screening_not_human_validated"
                                if len(group)
                                else "empty_current_linked_corpus"
                            ),'''
        ),
    )
    replace_once(
        path,
        '                        "axis_group": axis,\n                        "realm": realm,',
        '                        "axis_group": axis,\n                        "axis_code": AXIS_CODES[axis],\n                        "evidence_surface": evidence_surface,\n                        "realm": realm,',
    )
    replace_once(
        path,
        dedent(
            '''\
                                    "coding_status": (
                                        "deterministic_title_screening_not_human_validated"
                                    ),'''
        ),
        '                        "coding_status": "deterministic_screening_not_human_validated",',
    )
    replace_once(
        path,
        dedent(
            '''\
                for axis in AXES:
                    group = all_linked.loc[all_linked["axis_group"].eq(axis)]
                    for feature in PERFORMATIVE_FEATURE_SIGNAL_TYPES:
            '''
        ),
        dedent(
            '''\
                for axis in AXES:
                    group = all_linked.loc[all_linked["axis_group"].eq(axis)]
                    evidence_surface = _evidence_surface(group)
                    for feature in PERFORMATIVE_FEATURE_SIGNAL_TYPES:
            '''
        ),
    )
    replace_once(
        path,
        '                    "axis_group": axis,\n                    "feature": feature,',
        '                    "axis_group": axis,\n                    "axis_code": AXIS_CODES[axis],\n                    "evidence_surface": evidence_surface,\n                    "feature": feature,',
    )
    replace_once(
        path,
        '                    "status": "title_screening_not_validated_performativity",',
        '                    "status": "screening_not_validated_performativity",',
    )
    replace_once(
        path,
        '        demand_group = demands.loc[demands["sector"].eq(sector)]\n        row: dict[str, Any] = {',
        '        demand_group = demands.loc[demands["sector"].eq(sector)]\n        dominant_axis = AXES[int(axis_counts.argmax())] if axis_counts.sum() else None\n        row: dict[str, Any] = {',
    )
    replace_once(
        path,
        dedent(
            '''\
                        "dominant_axis": (
                            AXES[int(axis_counts.argmax())] if axis_counts.sum() else None
                        ),'''
        ),
        dedent(
            '''\
                        "dominant_axis": dominant_axis,
                        "dominant_axis_code": (
                            AXIS_CODES[dominant_axis] if dominant_axis is not None else None
                        ),'''
        ),
    )
    replace_once(
        path,
        '            "status": "multi-label title screening; fractional weights prevent double count",',
        '            "status": "multi-label screening; fractional weights prevent double count",',
    )


def patch_builder() -> None:
    path = "scripts/build_performative_demand_cross_axis_analysis.py"
    replace_once(path, "    AXES,\n    REALMS,", "    AXES,\n    AXIS_CODES,\n    REALMS,")
    replace_once(
        path,
        '                    "axis_group": axis,\n                    "realm": realm,',
        '                    "axis_group": axis,\n                    "axis_code": AXIS_CODES[axis],\n                    "realm": realm,',
    )
    replace_once(
        path,
        dedent(
            '''\
                                "manual_validation_status": "not_started",
                                "source_note": (
                                    "aggregate realm recoding supplied in the empirical brief; "
                                    "repository H3 rows contain no realm field"
                                ),'''
        ),
        dedent(
            '''\
                                "manual_validation_status": "not_started",
                                "citation_needed": True,
                                "source_status": "comparison_data_not_repository_evidence",
                                "source_note": (
                                    "aggregate realm recoding supplied outside retained repository "
                                    "evidence; no retained citable source is available"
                                ),'''
        ),
    )
    replace_once(
        path,
        dedent(
            '''\
                    matrix.rename_axis(index="sector", columns="axis_group").stack(
                        future_stack=True
                    ),'''
        ),
        '        matrix.rename_axis(index="sector", columns="axis_group").stack(),',
    )
    replace_once(
        path,
        dedent(
            '''\
                long_series.name = value_name
                long = long_series.reset_index()
                long.to_csv(path, index=False)
            '''
        ),
        dedent(
            '''\
                long_series.name = value_name
                long = long_series.reset_index()
                long["axis_code"] = long["axis_group"].map(AXIS_CODES)
                if long["axis_code"].isna().any():
                    raise RuntimeError("matrix contains a non-canonical axis without axis_code")
                long = long[["sector", "axis_group", "axis_code", value_name]]
                long.to_csv(path, index=False)
            '''
        ),
    )


def patch_validator() -> None:
    path = "scripts/validate_generated_outputs.py"
    replace_once(
        path,
        "import re\nimport sys\n",
        "import re\nimport subprocess\nimport sys\nimport tempfile\n",
    )
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    marker = (
        "# ---------------------------------------------------------------------------\n"
        "# Main\n"
        "# ---------------------------------------------------------------------------\n"
    )
    if text.count(marker) != 1:
        raise RuntimeError("validate_generated_outputs.py: Main marker not unique")
    block = dedent(
        '''\

        def check_performative_demand_outputs() -> None:
            """Validate PR #270 scientific artifacts by schema and deterministic rebuild."""
            print("\\n[performative_demand_cross_axis/]")
            output_dir = OUTPUTS_DIR / "performative_demand_cross_axis"
            builder = REPO_ROOT / "scripts" / "build_performative_demand_cross_axis_analysis.py"
            schemas: dict[str, set[str]] = {
                "sector_axis_observed.csv": {"sector", "axis_group", "axis_code", "observed_evidence_count"},
                "sector_axis_expected.csv": {"sector", "axis_group", "axis_code", "expected_evidence_count"},
                "sector_axis_residuals.csv": {"sector", "axis_group", "axis_code", "observed_evidence_count"},
                "sector_axis_screening_features.csv": {"sector", "axis_group", "axis_code", "evidence_surface"},
                "sector_axis_realm_screening.csv": {"sector", "axis_group", "axis_code", "evidence_surface", "realm"},
                "axis_screening_feature_shares.csv": {"axis_group", "axis_code", "evidence_surface", "feature"},
                "sector_deficit_profile.csv": {"sector", "dominant_axis", "dominant_axis_code"},
                "coastal_tourism_axis_realm_case.csv": {"sector", "axis_group", "axis_code", "realm", "citation_needed", "source_status"},
            }
            axis_codes = {
                "MARINE": "M",
                "MARITIME": "T",
                "OCEANIC": "O",
                "HYDRONIZATION": "H",
            }
            expected_names = set(schemas) | {"statistics_summary.json"}
            if not output_dir.exists():
                fail(f"Performative-demand output directory missing: {output_dir}")
                return
            local_errors_before = len(ERRORS)
            for name, required_columns in schemas.items():
                artifact = output_dir / name
                if not require_file(artifact):
                    continue
                with artifact.open(newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    fieldnames = set(reader.fieldnames or [])
                    missing = required_columns - fieldnames
                    if missing:
                        fail(f"{name}: missing required columns {sorted(missing)}")
                        continue
                    rows = list(reader)
                for row_index, row in enumerate(rows, 2):
                    axis = str(row.get("axis_group", "")).strip()
                    if axis and axis in axis_codes and row.get("axis_code") != axis_codes[axis]:
                        fail(
                            f"{name}:{row_index}: axis_code {row.get('axis_code')!r} "
                            f"does not match canonical {axis_codes[axis]!r} for {axis}"
                        )
                        break
                if name == "coastal_tourism_axis_realm_case.csv":
                    if any(
                        str(row.get("citation_needed", "")).lower() != "true"
                        for row in rows
                    ):
                        fail(
                            f"{name}: every supplied aggregate row must remain "
                            "citation_needed=true"
                        )
                    if any(
                        row.get("source_status")
                        != "comparison_data_not_repository_evidence"
                        for row in rows
                    ):
                        fail(
                            f"{name}: supplied aggregate rows must be labelled "
                            "comparison data"
                        )

            summary_path = output_dir / "statistics_summary.json"
            require_file(summary_path)
            if len(ERRORS) != local_errors_before:
                return

            with tempfile.TemporaryDirectory(prefix="morskamary-performative-") as tmp:
                completed = subprocess.run(
                    [sys.executable, str(builder), "--output-dir", tmp],
                    cwd=REPO_ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                if completed.returncode != 0:
                    fail(
                        "Performative-demand deterministic regeneration failed: "
                        + completed.stdout[-2000:]
                    )
                    return
                regenerated = Path(tmp)
                for name in sorted(expected_names):
                    committed = output_dir / name
                    rebuilt = regenerated / name
                    if not rebuilt.exists():
                        fail(f"Deterministic rebuild did not emit required artifact: {name}")
                        continue
                    if committed.read_bytes() != rebuilt.read_bytes():
                        fail(f"Performative-demand artifact is stale/non-deterministic: {name}")
                if len(ERRORS) == local_errors_before:
                    ok(
                        "Performative-demand schemas and deterministic regeneration "
                        "match committed artifacts"
                    )


        '''
    )
    target.write_text(text.replace(marker, block + marker, 1), encoding="utf-8")
    replace_once(
        path,
        "    check_dynamic_outputs(dynamic_credentials, rationale, pathways)\n"
        "    check_no_absolute_local_paths(OUTPUTS_DIR)",
        "    check_dynamic_outputs(dynamic_credentials, rationale, pathways)\n"
        "    check_performative_demand_outputs()\n"
        "    check_no_absolute_local_paths(OUTPUTS_DIR)",
    )


def patch_tests() -> None:
    path = "tests/test_performative_demand_analysis.py"
    replace_once(path, "    AXES,\n    REALMS,", "    AXES,\n    AXIS_CODES,\n    REALMS,")
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if "test_axis_codes_are_explicit_in_analysis_tables" in text:
        return
    extra = dedent(
        '''\


        def test_axis_codes_are_explicit_in_analysis_tables() -> None:
            demands, evidence, signals = _frames()
            analysis = build_performative_demand_analysis(
                demands,
                evidence,
                signals,
                {"sector_a": "Sector A", "sector_b": "Sector B"},
                permutations=9,
                seed=42,
            )
            for frame in (
                analysis.residuals,
                analysis.sector_axis_features,
                analysis.sector_axis_realms,
                analysis.axis_features,
            ):
                assert "axis_code" in frame.columns
                assert all(
                    row.axis_code == AXIS_CODES[row.axis_group]
                    for row in frame.itertuples(index=False)
                )
            assert "dominant_axis_code" in analysis.sector_profile.columns
            assert all(
                row.dominant_axis_code == AXIS_CODES[row.dominant_axis]
                for row in analysis.sector_profile.itertuples(index=False)
                if row.dominant_axis is not None
            )


        def test_screening_surface_tracks_retained_semantic_scope() -> None:
            demands, evidence, signals = _frames()
            signals.loc[signals["evidence_id"].eq("E-1"), "semantic_scope"] = "abstract"
            analysis = build_performative_demand_analysis(
                demands,
                evidence,
                signals,
                {"sector_a": "Sector A", "sector_b": "Sector B"},
                permutations=9,
                seed=42,
            )
            row = analysis.sector_axis_features.loc[
                analysis.sector_axis_features["sector"].eq("sector_a")
                & analysis.sector_axis_features["axis_group"].eq("MARINE")
            ].iloc[0]
            assert row["evidence_surface"] == "abstract|title"
            assert row["evidence_status"] == "screening_not_human_validated"


        def test_builder_is_pandas_15_compatible_and_tourism_is_uncited_comparison() -> None:
            import inspect

            from scripts.build_performative_demand_cross_axis_analysis import (
                _tourism_case_table,
                _write_long_matrix,
            )

            assert "future_stack" not in inspect.getsource(_write_long_matrix)
            tourism = _tourism_case_table()
            assert tourism["citation_needed"].all()
            assert set(tourism["source_status"]) == {
                "comparison_data_not_repository_evidence"
            }
            assert all(
                row.axis_code == AXIS_CODES[row.axis_group]
                for row in tourism.itertuples(index=False)
            )
        '''
    )
    target.write_text(text.rstrip() + extra + "\n", encoding="utf-8")


def patch_docs() -> None:
    path = ROOT / "docs/PERFORMATIVE_DEMAND_CROSS_AXIS_METHOD.md"
    text = path.read_text(encoding="utf-8")
    heading = "## Review reconciliation: output identity and provenance"
    if heading not in text:
        note = dedent(
            '''\


            ## Review reconciliation: output identity and provenance

            All axis-bearing publication tables retain both the canonical `axis_group` and its non-inferred display `axis_code` (`M`, `T`, `O`, `H`). Screening rows carry the actual retained `evidence_surface` derived from `semantic_scope`; they are not assumed to be title-only. The supplied 21-fragment coastal-tourism 4 × 4 recoding remains comparison data, explicitly marked `citation_needed`, because no retained citable source for that aggregate exists in the repository. It is not repository evidence and cannot establish validated translation or performativity.
            '''
        )
        path.write_text(text.rstrip() + note, encoding="utf-8")

    changelog = ROOT / "CHANGELOG.txt"
    text = changelog.read_text(encoding="utf-8")
    entry = (
        "PR #270 review reconciliation: pandas>=1.5 compatibility; canonical "
        "axis_code; evidence-surface provenance; tourism citation boundary; "
        "deterministic generated-output validation.\n"
    )
    if entry not in text:
        changelog.write_text(entry + text, encoding="utf-8")


def main() -> None:
    patch_analysis()
    patch_builder()
    patch_validator()
    patch_tests()
    patch_docs()


if __name__ == "__main__":
    main()
