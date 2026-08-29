from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{path}: start marker not found: {start!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{path}: end marker not found: {end!r}")
    target.write_text(
        text[:start_index] + replacement + text[end_index:],
        encoding="utf-8",
        newline="\n",
    )


def append_once(path: str, marker: str, block: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + block.strip() + "\n", encoding="utf-8", newline="\n")


def patch_analysis() -> None:
    path = "src/scientific_sources/performative_demand_analysis.py"
    replace_once(
        path,
        'REALMS = ("ECONOMY", "TECHNOLOGY", "POLICY_GOVERNANCE", "CULTURE_LEARNING")\n',
        'REALMS = ("ECONOMY", "TECHNOLOGY", "POLICY_GOVERNANCE", "CULTURE_LEARNING")\n'
        'QUERY_ONLY_SCOPES = frozenset({"query", "source_query", "query_text", "source_query_text", "retrieval_query"})\n',
    )
    replace_once(
        path,
        '''    if linked_signals.empty:\n        raise PerformativeDemandAnalysisError(\n            "no non-rejected review_required signals remain for screening"\n        )\n    linked_signals = linked_signals.rename(\n''',
        '''    if linked_signals.empty:\n        raise PerformativeDemandAnalysisError(\n            "no non-rejected review_required signals remain for screening"\n        )\n    query_only_scopes = (\n        _normalized_scope_set(linked_signals["semantic_scope"].tolist())\n        & QUERY_ONLY_SCOPES\n    )\n    if query_only_scopes:\n        raise PerformativeDemandAnalysisError(\n            "query-only semantic scopes cannot contribute positive empirical screening signals: "\n            + ", ".join(sorted(query_only_scopes))\n        )\n    linked_signals = linked_signals.rename(\n''',
    )
    replace_once(
        path,
        '            "fractional_weight_expected": total,\n',
        '            "fractional_weight_expected": int(len(screening_linked)),\n',
    )


def patch_builder() -> None:
    path = "scripts/build_performative_demand_cross_axis_analysis.py"
    replace_once(path, "import json\n", "import json\nimport math\n")
    replace_once(
        path,
        '''    long = long[["sector", "axis_group", "axis_code", value_name]]\n    long.to_csv(path, index=False)\n\n\ndef _sha256(path: Path) -> str:\n    return hashlib.sha256(path.read_bytes()).hexdigest()\n\n\n''',
        '''    long = long[["sector", "axis_group", "axis_code", value_name]]\n    _write_csv(long, path)\n\n\ndef _sha256(path: Path) -> str:\n    return hashlib.sha256(path.read_bytes()).hexdigest()\n\n\ndef _write_text_lf(path: Path, text: str) -> None:\n    with path.open("w", encoding="utf-8", newline="\\n") as handle:\n        handle.write(text)\n\n\ndef _json_safe(value: Any) -> Any:\n    if isinstance(value, float) and not math.isfinite(value):\n        return None\n    if isinstance(value, dict):\n        return {str(key): _json_safe(item) for key, item in value.items()}\n    if isinstance(value, (list, tuple)):\n        return [_json_safe(item) for item in value]\n    return value\n\n\ndef _write_json(path: Path, payload: Any) -> None:\n    text = json.dumps(\n        _json_safe(payload),\n        indent=2,\n        sort_keys=True,\n        allow_nan=False,\n    ) + "\\n"\n    _write_text_lf(path, text)\n\n\ndef _write_csv(frame: pd.DataFrame, path: Path) -> None:\n    frame.to_csv(path, index=False, lineterminator="\\n")\n\n\n''',
    )
    source_provenance = dedent('''
    def _required_text(mapping: Mapping[str, Any], key: str, label: str) -> str:
        value = str(mapping.get(key, "")).strip()
        if not value:
            raise RuntimeError(f"{label} missing required field {key}")
        return value


    def _source_provenance(
        database: Path, frames: Mapping[str, pd.DataFrame]
    ) -> dict[str, Any]:
        manifest_path = database / "cumulative_database_manifest.json"
        layer4_path = database / "layer4_manifest.json"
        readiness_path = database / "layer_readiness_report.json"
        for required in (manifest_path, layer4_path, readiness_path):
            if not required.exists():
                raise RuntimeError(f"required provenance artifact is missing: {required.name}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        layer4 = json.loads(layer4_path.read_text(encoding="utf-8"))
        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))

        current_run_id = _required_text(manifest, "current_run_id", "cumulative manifest")
        classifier_version = _required_text(
            manifest, "classifier_version", "cumulative manifest"
        )
        if _required_text(layer4, "current_run_id", "Layer-4 manifest") != current_run_id:
            raise RuntimeError("Layer-4 current_run_id conflicts with cumulative manifest")
        if (
            _required_text(layer4, "classifier_version", "Layer-4 manifest")
            != classifier_version
        ):
            raise RuntimeError("Layer-4 classifier_version conflicts with cumulative manifest")

        observed: dict[str, dict[str, str]] = {}
        for table_name, frame in frames.items():
            run_values: set[str] = set()
            for source_field in ("current_run_id", "run_id"):
                if source_field not in frame.columns:
                    continue
                values = {
                    str(value).strip()
                    for value in frame[source_field].dropna().tolist()
                    if str(value).strip()
                }
                if len(values) > 1:
                    raise RuntimeError(
                        f"{table_name} mixes multiple {source_field} values: {sorted(values)}"
                    )
                run_values.update(values)
            if len(run_values) > 1:
                raise RuntimeError(
                    f"{table_name} has conflicting run identifier aliases: {sorted(run_values)}"
                )
            if run_values:
                observed.setdefault("current_run_id", {})[table_name] = next(
                    iter(run_values)
                )
            if "classifier_version" in frame.columns:
                classifier_values = {
                    str(value).strip()
                    for value in frame["classifier_version"].dropna().tolist()
                    if str(value).strip()
                }
                if len(classifier_values) > 1:
                    raise RuntimeError(
                        f"{table_name} mixes multiple classifier_version values: {sorted(classifier_values)}"
                    )
                if classifier_values:
                    observed.setdefault("classifier_version", {})[table_name] = next(
                        iter(classifier_values)
                    )

        for table_name, value in observed.get("current_run_id", {}).items():
            if value != current_run_id:
                raise RuntimeError(
                    f"{table_name} run identity {value!r} conflicts with cumulative current_run_id {current_run_id!r}"
                )
        for table_name, value in observed.get("classifier_version", {}).items():
            if value != classifier_version:
                raise RuntimeError(
                    f"{table_name} classifier_version {value!r} conflicts with cumulative classifier_version {classifier_version!r}"
                )

        counts = manifest.get("counts")
        if not isinstance(counts, dict):
            raise RuntimeError("cumulative manifest counts must be an object")
        manifest_evidence_count = int(counts.get("evidence_records", -1))
        manifest_signal_count = int(counts.get("competence_demand_signals", -1))
        layer4_demand_count = int(layer4.get("derived_demand_count", -1))
        if manifest_evidence_count != len(frames["evidence"]):
            raise RuntimeError("cumulative manifest evidence_records count conflicts with evidence table")
        if manifest_signal_count != len(frames["signals"]):
            raise RuntimeError("cumulative manifest competence_demand_signals count conflicts with signals table")
        if layer4_demand_count != len(frames["demands"]):
            raise RuntimeError("Layer-4 derived_demand_count conflicts with demand table")

        readiness_layers = readiness.get("layers")
        if not isinstance(readiness_layers, list) or not readiness_layers:
            raise RuntimeError("layer readiness report contains no declared layers")
        if any(not bool(layer.get("schema_valid")) for layer in readiness_layers):
            raise RuntimeError("layer readiness report contains an invalid schema state")
        if any(not bool(layer.get("usable_for_layer4")) for layer in readiness_layers):
            raise RuntimeError("layer readiness report contains a layer unusable for Layer 4")

        source_names = [
            "derived_competence_demands.csv",
            "evidence_records.csv",
            "competence_demand_signals.csv",
            "cumulative_database_manifest.json",
            "layer4_manifest.json",
            "layer_readiness_report.json",
        ]
        return {
            "cumulative_manifest": {
                "schema_version": _required_text(manifest, "schema_version", "cumulative manifest"),
                "built_at_utc": _required_text(manifest, "built_at_utc", "cumulative manifest"),
                "current_run_id": current_run_id,
                "classifier_version": classifier_version,
                "evidence_record_count": manifest_evidence_count,
                "competence_demand_signal_count": manifest_signal_count,
                "workflow_context": manifest.get("workflow_context", {}),
            },
            "layer4_manifest": {
                "schema_version": _required_text(layer4, "schema_version", "Layer-4 manifest"),
                "built_at_utc": _required_text(layer4, "built_at_utc", "Layer-4 manifest"),
                "current_run_id": current_run_id,
                "classifier_version": classifier_version,
                "derived_demand_count": layer4_demand_count,
                "demand_strength_formula": _required_text(
                    layer4, "demand_strength_formula", "Layer-4 manifest"
                ),
            },
            "layer_readiness": {
                "schema_version": _required_text(readiness, "schema_version", "layer readiness report"),
                "generated_at_utc": _required_text(
                    readiness, "generated_at_utc", "layer readiness report"
                ),
                "declared_layer_count": len(readiness_layers),
                "all_schema_valid": True,
                "all_usable_for_layer4": True,
            },
            "qmbd_assignment_methodology": {
                "package_method": (
                    "axis_group is inherited from Layer-4 derived_competence_demands "
                    "through exact evidence_id linkage; this package performs no axis reclassification"
                ),
                "lineage_source": "derived_competence_demands.csv:evidence_ids,sector,axis_group",
            },
            "source_file_sha256": {
                name: _sha256(database / name) for name in source_names
            },
            "run_classifier_identity": {
                "status": "verified",
                "current_run_id": current_run_id,
                "classifier_version": classifier_version,
                "observed_fields": observed,
            },
        }


    ''')
    replace_between(path, "def _source_provenance(\n", "def _hypothesis_outcomes(", source_provenance)

    schema_and_governance = dedent('''
    def _csv_field_type(series: pd.Series) -> str:
        if pd.api.types.is_bool_dtype(series.dtype):
            return "boolean"
        if pd.api.types.is_integer_dtype(series.dtype):
            return "integer"
        if pd.api.types.is_numeric_dtype(series.dtype):
            return "number"
        return "string"


    def _build_package_schema(output: Path) -> dict[str, Any]:
        csv_names = [
            "sector_axis_observed.csv",
            "sector_axis_expected.csv",
            "sector_axis_residuals.csv",
            "sector_axis_screening_features.csv",
            "sector_axis_realm_screening.csv",
            "axis_screening_feature_shares.csv",
            "sector_screening_profile.csv",
            "linked_evidence_sector_axis_lineage.csv",
            "coastal_tourism_axis_realm_case.csv",
        ]
        primary_keys = {
            "sector_axis_observed.csv": ["sector", "axis_group"],
            "sector_axis_expected.csv": ["sector", "axis_group"],
            "sector_axis_residuals.csv": ["sector", "axis_group"],
            "sector_axis_screening_features.csv": ["sector", "axis_group"],
            "sector_axis_realm_screening.csv": ["sector", "axis_group", "realm"],
            "axis_screening_feature_shares.csv": ["axis_group", "feature"],
            "sector_screening_profile.csv": ["sector"],
            "linked_evidence_sector_axis_lineage.csv": ["evidence_id", "sector", "axis_group"],
            "coastal_tourism_axis_realm_case.csv": ["sector", "axis_group", "realm"],
        }
        controlled_values: dict[str, list[Any]] = {
            "axis_group": list(AXES),
            "axis_code": list(AXIS_CODES.values()),
            "realm": list(REALMS),
            "citation_needed": [True],
            "source_status": ["comparison_data_not_repository_evidence"],
            "manual_validation_status": ["not_started"],
            "supply_gap_status": ["not_computable_no_independent_supply"],
            "shortage_claim_status": ["not_computable"],
            "coding_status": ["deterministic_screening_not_human_validated"],
        }
        tabular: dict[str, Any] = {}
        for name in csv_names:
            frame = pd.read_csv(output / name)
            fields = []
            for column in frame.columns:
                field: dict[str, Any] = {
                    "name": str(column),
                    "type": _csv_field_type(frame[column]),
                }
                if column in controlled_values:
                    field["constraints"] = {"enum": controlled_values[column]}
                fields.append(field)
            tabular[name] = {
                "format": "csv",
                "encoding": "utf-8",
                "line_ending": "LF",
                "primary_key": primary_keys[name],
                "fields": fields,
            }
        return {
            "schema_version": "1.0",
            "profile": "morskamary-tabular-package-schema",
            "tabular_artifacts": tabular,
            "json_artifacts": {
                "statistics_summary.json": {"type": "object"},
                "hypothesis_outcomes.json": {"type": "array"},
                "validity_threats.json": {"type": "object"},
                "value_labels.json": {"type": "object"},
                "package_manifest.json": {"type": "object"},
            },
        }


    def _write_governance_artifacts(
        output: Path, protocol: Mapping[str, Any], source_provenance: Mapping[str, Any]
    ) -> None:
        _write_json(
            output / "validity_threats.json",
            {
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
            },
        )
        _write_json(
            output / "value_labels.json",
            {
                "axis_group_to_axis_code": AXIS_CODES,
                "review_status_contract": {
                    "review_required": "eligible for deterministic screening only",
                    "rejected": "excluded from positive screening aggregates",
                    "other": "fail closed until accepted validation ledger is ingested",
                },
                "query_only_scope_contract": (
                    "query/source-query text is provenance only and cannot contribute a positive empirical signal"
                ),
                "zero_interpretation": "not observed in declared screening state, not absent in reality",
                "supply_gap_status": "not_computable_no_independent_supply",
            },
        )
        _write_json(output / "hypothesis_outcomes.json", _hypothesis_outcomes(protocol))
        _write_json(output / "package_schema.json", _build_package_schema(output))
        files = {}
        for artifact in sorted(output.iterdir()):
            if artifact.is_file() and artifact.name != "package_manifest.json":
                files[artifact.name] = {
                    "sha256": _sha256(artifact),
                    "bytes": artifact.stat().st_size,
                }
        _write_json(
            output / "package_manifest.json",
            {
                "package_schema_version": "1.0",
                "generated_by": "scripts/build_performative_demand_cross_axis_analysis.py",
                "protocol_version": protocol.get("protocol_version"),
                "source_provenance": source_provenance,
                "files": files,
            },
        )


    ''')
    replace_between(path, "def _write_governance_artifacts(\n", "def main(", schema_and_governance)

    replace_once(
        path,
        '''    analysis = build_performative_demand_analysis(\n        demands,\n        evidence,\n        signals,\n        sector_labels,\n        permutations=args.permutations,\n        seed=args.seed,\n    )\n    output = args.output_dir\n''',
        '''    analysis = build_performative_demand_analysis(\n        demands,\n        evidence,\n        signals,\n        sector_labels,\n        permutations=args.permutations,\n        seed=args.seed,\n    )\n    source_provenance["package_coverage"] = {\n        "evidence_records_loaded": int(len(evidence)),\n        "derived_demands_loaded": int(len(demands)),\n        "linked_evidence_identity_count": int(analysis.evidence_map["evidence_id"].nunique()),\n        "evidence_map_exact_rows": int(len(analysis.evidence_map)),\n    }\n    output = args.output_dir\n''',
    )
    replace_once(
        path,
        '''    analysis.residuals.to_csv(output / "sector_axis_residuals.csv", index=False)\n    analysis.sector_axis_features.to_csv(\n        output / "sector_axis_screening_features.csv", index=False\n    )\n    analysis.sector_axis_realms.to_csv(\n        output / "sector_axis_realm_screening.csv", index=False\n    )\n    analysis.axis_features.to_csv(\n        output / "axis_screening_feature_shares.csv", index=False\n    )\n    analysis.sector_profile.to_csv(output / "sector_screening_profile.csv", index=False)\n''',
        '''    _write_csv(analysis.residuals, output / "sector_axis_residuals.csv")\n    _write_csv(\n        analysis.sector_axis_features, output / "sector_axis_screening_features.csv"\n    )\n    _write_csv(\n        analysis.sector_axis_realms, output / "sector_axis_realm_screening.csv"\n    )\n    _write_csv(analysis.axis_features, output / "axis_screening_feature_shares.csv")\n    _write_csv(analysis.sector_profile, output / "sector_screening_profile.csv")\n''',
    )
    replace_once(
        path,
        '''    lineage.sort_values(["evidence_id", "sector", "axis_group"]).to_csv(\n        output / "linked_evidence_sector_axis_lineage.csv", index=False\n    )\n    _tourism_case_table().to_csv(\n        output / "coastal_tourism_axis_realm_case.csv", index=False\n    )\n''',
        '''    _write_csv(\n        lineage.sort_values(["evidence_id", "sector", "axis_group"]),\n        output / "linked_evidence_sector_axis_lineage.csv",\n    )\n    _write_csv(\n        _tourism_case_table(), output / "coastal_tourism_axis_realm_case.csv"\n    )\n''',
    )
    replace_once(
        path,
        '''    (output / "statistics_summary.json").write_text(\n        json.dumps(summary, indent=2, sort_keys=True) + "\\n", encoding="utf-8"\n    )\n''',
        '''    _write_json(output / "statistics_summary.json", summary)\n''',
    )


def patch_validator() -> None:
    path = "scripts/validate_generated_outputs.py"
    replace_once(path, "import tempfile\n", "import tempfile\n\nimport yaml  # type: ignore[import-untyped]\n")
    replace_once(
        path,
        '''        "package_manifest.json",\n    }\n''',
        '''        "package_manifest.json",\n        "package_schema.json",\n    }\n''',
    )
    replace_once(
        path,
        '''    manifest_path = output_dir / "package_manifest.json"\n    hypothesis_path = output_dir / "hypothesis_outcomes.json"\n    require_file(manifest_path)\n    require_file(hypothesis_path)\n''',
        '''    manifest_path = output_dir / "package_manifest.json"\n    schema_path = output_dir / "package_schema.json"\n    hypothesis_path = output_dir / "hypothesis_outcomes.json"\n    require_file(manifest_path)\n    require_file(schema_path)\n    require_file(hypothesis_path)\n\n    def load_strict_json(path: Path) -> object:\n        def reject_constant(value: str) -> object:\n            raise ValueError(f"non-standard JSON constant: {value}")\n\n        return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)\n\n    json_names = expected_names - set(schemas)\n    loaded_json: dict[str, object] = {}\n    for name in sorted(json_names):\n        artifact = output_dir / name\n        if not artifact.exists():\n            continue\n        try:\n            loaded_json[name] = load_strict_json(artifact)\n        except (ValueError, json.JSONDecodeError) as exc:\n            fail(f"{name}: strict JSON validation failed: {exc}")\n''',
    )
    replace_once(
        path,
        '''    if manifest_path.exists():\n        package_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))\n''',
        '''    if manifest_path.exists() and "package_manifest.json" in loaded_json:\n        package_manifest = loaded_json["package_manifest.json"]\n        if not isinstance(package_manifest, dict):\n            fail("package_manifest.json must contain an object")\n            package_manifest = {}\n''',
    )
    replace_once(
        path,
        '''    if hypothesis_path.exists():\n        rows_h = json.loads(hypothesis_path.read_text(encoding="utf-8"))\n        if {row.get("hypothesis_id") for row in rows_h if isinstance(row, dict)} != {\n            "H1",\n            "H2",\n            "H3",\n        }:\n            fail("hypothesis_outcomes.json must serialize H1, H2, and H3")\n''',
        '''    if schema_path.exists() and "package_schema.json" in loaded_json:\n        package_schema = loaded_json["package_schema.json"]\n        if not isinstance(package_schema, dict):\n            fail("package_schema.json must contain an object")\n        else:\n            tabular = package_schema.get("tabular_artifacts")\n            if not isinstance(tabular, dict) or set(tabular) != set(schemas):\n                fail("package_schema.json tabular artifact set does not match governed CSVs")\n            else:\n                for name, spec in tabular.items():\n                    if not isinstance(spec, dict):\n                        fail(f"package_schema.json invalid schema object for {name}")\n                        continue\n                    fields = spec.get("fields")\n                    schema_fields = [\n                        field.get("name")\n                        for field in fields\n                        if isinstance(field, dict)\n                    ] if isinstance(fields, list) else []\n                    with (output_dir / name).open(newline="", encoding="utf-8") as handle:\n                        actual_fields = list(csv.DictReader(handle).fieldnames or [])\n                    if schema_fields != actual_fields:\n                        fail(f"package_schema.json field order does not match {name}")\n            json_artifacts = package_schema.get("json_artifacts")\n            expected_json_artifacts = expected_names - set(schemas) - {"package_schema.json"}\n            if (\n                not isinstance(json_artifacts, dict)\n                or set(json_artifacts) != expected_json_artifacts\n            ):\n                fail("package_schema.json JSON artifact set does not match governed JSONs")\n\n    if hypothesis_path.exists() and "hypothesis_outcomes.json" in loaded_json:\n        rows_h = loaded_json["hypothesis_outcomes.json"]\n        protocol = yaml.safe_load(\n            (REPO_ROOT / "config" / "live_query_protocol.yml").read_text(encoding="utf-8")\n        )\n        declared_hypotheses = set(str(key) for key in protocol.get("hypotheses", {}))\n        emitted_hypotheses = {\n            row.get("hypothesis_id")\n            for row in rows_h\n            if isinstance(row, dict)\n        } if isinstance(rows_h, list) else set()\n        if emitted_hypotheses != declared_hypotheses:\n            fail(\n                "hypothesis_outcomes.json identifiers do not match authoritative protocol declarations"\n            )\n''',
    )


def patch_workflow() -> None:
    replace_once(
        ".github/workflows/full-analysis.yml",
        '''      - name: Validate generated output semantics\n        run: python scripts/validate_generated_outputs.py\n''',
        '''      - name: Validate generated output semantics\n        env:\n          MORSKAMARY_CUMULATIVE_DATABASE_DIR: ${{ runner.temp }}/full-analysis-retained-inputs/cumulative_database\n        run: python scripts/validate_generated_outputs.py\n''',
    )


def patch_tests() -> None:
    path = "tests/test_performative_demand_analysis.py"
    replace_once(path, "from pathlib import Path\n", "import json\nimport math\nfrom pathlib import Path\n")
    append_once(
        path,
        "def test_query_only_scope_fails_closed",
        dedent('''
        def test_query_only_scope_fails_closed() -> None:
            demands, evidence, signals = _frames()
            signals.loc[0, "semantic_scope"] = "source_query"
            with pytest.raises(PerformativeDemandAnalysisError, match="query-only"):
                build_performative_demand_analysis(
                    demands,
                    evidence,
                    signals,
                    {"sector_a": "Sector A", "sector_b": "Sector B"},
                    permutations=9,
                    seed=42,
                )


        def test_realm_fractional_audit_uses_screening_denominator() -> None:
            demands, evidence, signals = _frames()
            signals = signals.loc[~signals["evidence_id"].eq("E-4")].copy()
            analysis = build_performative_demand_analysis(
                demands,
                evidence,
                signals,
                {"sector_a": "Sector A", "sector_b": "Sector B"},
                permutations=9,
                seed=42,
            )
            audit = analysis.summary["realm_screening_audit"]
            assert audit["fractional_candidate_weight"] == 3
            assert audit["fractional_weight_expected"] == 3


        def test_source_provenance_rejects_run_alias_conflict(tmp_path: Path) -> None:
            from scripts.build_performative_demand_cross_axis_analysis import _source_provenance

            manifest = {
                "schema_version": "1.0.0",
                "built_at_utc": "2026-01-01T00:00:00+00:00",
                "current_run_id": "RUN-A",
                "classifier_version": "classifier-v1",
                "counts": {"evidence_records": 1, "competence_demand_signals": 1},
                "workflow_context": {},
            }
            layer4 = {
                "schema_version": "1.0.0",
                "built_at_utc": "2026-01-01T00:00:00+00:00",
                "current_run_id": "RUN-A",
                "classifier_version": "classifier-v1",
                "derived_demand_count": 1,
                "demand_strength_formula": "test",
            }
            readiness = {
                "schema_version": "1.0.0",
                "generated_at_utc": "2026-01-01T00:00:00+00:00",
                "layers": [{"schema_valid": True, "usable_for_layer4": True}],
            }
            (tmp_path / "cumulative_database_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (tmp_path / "layer4_manifest.json").write_text(
                json.dumps(layer4), encoding="utf-8"
            )
            (tmp_path / "layer_readiness_report.json").write_text(
                json.dumps(readiness), encoding="utf-8"
            )
            frames = {
                "demands": pd.DataFrame([{"competence_demand_id": "D-1"}]),
                "evidence": pd.DataFrame([{"evidence_id": "E-1"}]),
                "signals": pd.DataFrame(
                    [{"run_id": "RUN-B", "classifier_version": "classifier-v1"}]
                ),
            }
            with pytest.raises(RuntimeError, match="conflicts with cumulative current_run_id"):
                _source_provenance(tmp_path, frames)


        def test_strict_json_writer_converts_non_finite_to_null(tmp_path: Path) -> None:
            from scripts.build_performative_demand_cross_axis_analysis import _write_json

            path = tmp_path / "strict.json"
            _write_json(path, {"value": math.nan})
            assert json.loads(path.read_text(encoding="utf-8")) == {"value": None}
            assert "NaN" not in path.read_text(encoding="utf-8")


        def test_csv_writer_forces_lf(tmp_path: Path) -> None:
            from scripts.build_performative_demand_cross_axis_analysis import _write_csv

            path = tmp_path / "lf.csv"
            _write_csv(pd.DataFrame([{"a": 1}, {"a": 2}]), path)
            assert b"\\r\\n" not in path.read_bytes()
        '''),
    )


def patch_docs() -> None:
    append_once(
        "docs/PERFORMATIVE_DEMAND_CROSS_AXIS_METHOD.md",
        "## Final PR #270 review reconciliation",
        '''## Final PR #270 review reconciliation

The publication package fails closed on query-only semantic scopes and on inconsistent run/classifier lineage. Source provenance is read from the frozen cumulative, Layer-4, and layer-readiness manifests and cross-checked against loaded row counts; the package does not invent unavailable upstream metadata. `package_schema.json` publishes machine-readable field types, keys, controlled values, encoding and LF line-ending requirements. JSON output is strict (`null` for non-computable values; non-standard `NaN` is forbidden). `MANIFEST_SOURCES.csv` is regenerated from the final governed file set.''',
    )
    append_once(
        "CHANGELOG.txt",
        "PR #270 final review reconciliation",
        '''PR #270 final review reconciliation
- Preserve the retained cumulative database path through Full Analysis semantic validation.
- Canonicalize run_id/current_run_id lineage and fail on conflicts.
- Publish authoritative cumulative/Layer-4/readiness provenance and exact package coverage.
- Reject query-only semantic scopes, use the screening denominator for realm-weight audit, and serialize non-computable values as strict JSON nulls.
- Add package_schema.json and force LF bytes for deterministic cross-platform package rebuilds.
- Make hypothesis validation protocol-driven and refresh MANIFEST_SOURCES.csv.''',
    )


def main() -> None:
    patch_analysis()
    patch_builder()
    patch_validator()
    patch_workflow()
    patch_tests()
    patch_docs()


if __name__ == "__main__":
    main()
