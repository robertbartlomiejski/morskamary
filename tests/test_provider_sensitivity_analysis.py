"""Regression tests for fail-closed provider-sensitivity diagnostics."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts import build_provider_sensitivity_analysis as sensitivity


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_demands(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=sensitivity.DERIVED_DEMAND_COLUMNS,
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "competence_demand_id": "D-MAR-1",
                    "competence_label": "safety",
                    "sector": "ports",
                    "axis_group": "MARITIME",
                },
                {
                    "competence_demand_id": "D-OCE-1",
                    "competence_label": "governance",
                    "sector": "coastal_tourism",
                    "axis_group": "OCEANIC",
                },
                {
                    "competence_demand_id": "D-HYD-1",
                    "competence_label": "hydrosocial governance",
                    "sector": "desalination",
                    "axis_group": "HYDRONIZATION",
                },
                {
                    "competence_demand_id": "D-CROSSREF-ONLY",
                    "competence_label": "policy",
                    "sector": "ports",
                    "axis_group": "MARITIME",
                },
            ],
        )


def _fixture(tmp_path: Path, *, include_wos: bool = False) -> dict[str, Path]:
    evidence = tmp_path / "evidence_records.jsonl"
    signals = tmp_path / "competence_demand_signals.jsonl"
    demands = tmp_path / "derived_competence_demands.csv"
    fragments = tmp_path / "hypothesis_semantic_fragments.jsonl"

    evidence_rows = [
        {
            "evidence_id": "E1",
            "canonical_doi": "10.1/a",
            "providers_seen": "crossref|scopus",
            "query_families_seen": "competence_demand|hypothesis_verification",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
        {
            "evidence_id": "E2",
            "canonical_doi": "10.1/b",
            "providers_seen": "openalex",
            "query_families_seen": "competence_demand",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
        {
            "evidence_id": "E3",
            "canonical_doi": "10.1/c",
            "providers_seen": "crossref",
            "query_families_seen": "competence_demand",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
        {
            "evidence_id": "E4",
            "canonical_doi": "10.1/d",
            "providers_seen": "crossref",
            "query_families_seen": "competence_demand",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
        {
            "evidence_id": "E5",
            "canonical_doi": "10.1/e",
            "providers_seen": "openalex",
            "query_families_seen": "competence_demand",
            "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
        },
    ]
    if include_wos:
        evidence_rows.append(
            {
                "evidence_id": "E6",
                "canonical_doi": "10.1/f",
                "providers_seen": "wos",
                "query_families_seen": "hypothesis_verification",
                "latest_seen_at_utc": "2026-07-20T00:00:00+00:00",
            }
        )
    _write_jsonl(evidence, evidence_rows)

    signal_rows = [
        {
            "signal_id": "S1",
            "evidence_id": "E1",
            "axis_group": "MARITIME",
            "competence_label": "safety",
            "sector": "ports",
            "query_family": "competence_demand",
            "confidence_score": 0.95,
        },
        {
            "signal_id": "S2",
            "evidence_id": "E2",
            "axis_group": "OCEANIC",
            "competence_label": "governance",
            "sector": "coastal_tourism",
            "query_family": "competence_demand",
            "confidence_score": 0.75,
        },
        {
            "signal_id": "S3",
            "evidence_id": "E3",
            "axis_group": "MARITIME",
            "competence_label": "policy",
            "sector": "ports",
            "query_family": "competence_demand",
            "confidence_score": 0.80,
        },
        {
            "signal_id": "S4",
            "evidence_id": "E4",
            "axis_group": "MARITIME",
            "competence_label": "safety",
            "sector": "ports",
            "query_family": "hypothesis_verification",
            "confidence_score": 0.60,
        },
        {
            "signal_id": "S5",
            "evidence_id": "E5",
            "axis_group": "HYDRONIZATION",
            "competence_label": "hydrosocial governance",
            "sector": "desalination",
            "query_family": "competence_demand",
            "confidence_score": 0.85,
        },
    ]
    if include_wos:
        signal_rows.append(
            {
                "signal_id": "S6",
                "evidence_id": "E6",
                "axis_group": "OCEANIC",
                "competence_label": "governance",
                "sector": "coastal_tourism",
                "query_family": "hypothesis_verification",
                "confidence_score": 0.70,
            }
        )
    _write_jsonl(signals, signal_rows)
    _write_demands(demands)
    (tmp_path / "layer4_manifest.json").write_text(
        json.dumps({"analysis_timestamp_utc": "2026-07-29T00:00:00+00:00"}) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(
        fragments,
        [
            {
                "evidence_id": "E1",
                "signal_id": "BRIDGE",
                "hypothesis_id": "H3",
                "axis_group": "MARINE",
            },
            {
                "evidence_id": "E2",
                "signal_id": "BRIDGE",
                "hypothesis_id": "H3",
                "axis_group": "OCEANIC",
            },
            {
                "evidence_id": "E2",
                "signal_id": "NOT-H3",
                "hypothesis_id": "H1",
                "axis_group": "OCEANIC",
            },
        ],
    )
    return {
        "evidence": evidence,
        "signals": signals,
        "demands": demands,
        "fragments": fragments,
    }


def _build(tmp_path: Path, paths: dict[str, Path], supply: Path | None = None) -> dict:
    return sensitivity.build_provider_sensitivity_analysis(
        evidence_path=paths["evidence"],
        signals_path=paths["signals"],
        derived_demands_path=paths["demands"],
        hypothesis_fragments_path=paths["fragments"],
        validated_supply_map_path=supply,
        protocol_path=Path("config/live_query_protocol.yml"),
        output_json_path=tmp_path / "provider_sensitivity_analysis.json",
        output_markdown_path=tmp_path / "provider_sensitivity_analysis.md",
    )


def test_recomputes_each_provider_subset_and_emits_complete_contract(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    result = _build(tmp_path, paths)

    assert result["api_calls_performed"] == 0
    assert {
        "all_canonical",
        "direct_crossref_excluded",
        "scopus_excluded",
        "openalex_excluded",
        "crossref_only",
        "scopus_only",
        "openalex_only",
    } <= set(result["subsets"])

    direct = result["subsets"]["direct_crossref_excluded"]
    baseline = result["subsets"]["all_canonical"]
    retained = next(
        row for row in direct["top_demands"] if row["competence_demand_id"] == "D-MAR-1"
    )
    original = next(
        row
        for row in baseline["top_demands"]
        if row["competence_demand_id"] == "D-MAR-1"
    )
    assert retained["provider_count"] == 1
    assert retained["unique_doi_count"] == 1
    assert retained["axis_code"] == "T"
    assert retained["demand_strength_score"] < original["demand_strength_score"]
    assert all(
        row["competence_demand_id"] != "D-CROSSREF-ONLY"
        for row in direct["top_demands"]
    )

    for hypothesis_id in ("h1", "h2", "h3"):
        assert direct[hypothesis_id]["hypothesis_id"] == hypothesis_id.upper()
        assert "hypothesis_label" in direct[hypothesis_id]
        assert "interpretation" in direct[hypothesis_id]

    assert baseline["h3"]["matched_fragment_count"] == 2
    assert baseline["h3"]["oceanic_fragment_count"] == 1
    assert baseline["h3"]["semantic_bridge_count"] == 0
    assert baseline["h3"]["interpretation"] == "not_computable"
    assert "no_validated_bridge_relation" in baseline["h3"]["validity_warning"]
    assert (tmp_path / "provider_sensitivity_analysis.md").is_file()


def test_subsets_follow_actual_contributing_providers_including_wos(
    tmp_path: Path,
) -> None:
    result = _build(tmp_path, _fixture(tmp_path, include_wos=True))
    assert "wos_only" in result["subsets"]
    assert "wos_excluded" in result["subsets"]
    assert "wos" in result["subsets"]["all_canonical"]["providers"]


def test_missing_required_input_fails_closed(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["signals"].unlink()
    with pytest.raises(ValueError, match="required signals file does not exist"):
        _build(tmp_path, paths)


def test_empty_signals_and_demands_are_valid_not_computable_inputs(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["signals"].write_text("", encoding="utf-8")
    paths["demands"].write_text(
        ",".join(sensitivity.DERIVED_DEMAND_COLUMNS) + "\n",
        encoding="utf-8",
    )
    result = _build(tmp_path, paths)
    baseline = result["subsets"]["all_canonical"]
    assert baseline["semantic_signal_count"] == 0
    assert baseline["derived_demand_count"] == 0
    assert baseline["h1"]["interpretation"] == "not_computable"
    assert baseline["h2"]["interpretation"] == "not_computable"


def test_empty_hypothesis_fragments_produces_not_computable(tmp_path: Path) -> None:
    """Empty hypothesis_semantic_fragments.jsonl is a valid scientific outcome.

    When live evidence produces competence signals but none match any hypothesis
    indicator registry, Layer 2 writes an empty JSONL file.  The pipeline must
    accept this and emit not_computable for affected hypotheses rather than
    aborting with an error.
    """
    paths = _fixture(tmp_path)
    # Write a valid but empty JSONL file (no data rows)
    paths["fragments"].write_text("", encoding="utf-8")
    result = _build(tmp_path, paths)
    # H3 uses fragments; with no fragments it must be not_computable
    baseline = result["subsets"]["all_canonical"]
    assert baseline["h3"]["interpretation"] == "not_computable"
    paths = _fixture(tmp_path)
    (tmp_path / "layer4_manifest.json").unlink()

    with pytest.raises(ValueError, match="deterministic scoring"):
        _build(tmp_path, paths)


def test_duplicate_layer2_evidence_ids_fail_before_outputs_written(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    rows = [
        json.loads(line)
        for line in paths["evidence"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows.append(dict(rows[0]))
    _write_jsonl(paths["evidence"], rows)

    with pytest.raises(ValueError, match="duplicate evidence_id"):
        _build(tmp_path, paths)

    assert not (tmp_path / "provider_sensitivity_analysis.json").exists()
    assert not (tmp_path / "provider_sensitivity_analysis.md").exists()


def test_explicit_unvalidated_supply_map_is_rejected(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    supply = tmp_path / "supply.json"
    supply.write_text(
        json.dumps(
            {
                "validation_status": "candidate",
                "has_validated_supply": True,
                "validated_supply_by_demand_id": {
                    "D-HYD-1": {
                        "eqf_levels": [6],
                        "validation_evidence_ids": ["REG-1"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be validated"):
        _build(tmp_path, paths, supply)


def test_validated_supply_changes_h2_only_with_evidence(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    supply = tmp_path / "supply.json"
    supply.write_text(
        json.dumps(
            {
                "validation_status": "validated",
                "has_validated_supply": True,
                "validated_supply_by_demand_id": {
                    "D-HYD-1": {
                        "validation_status": "validated",
                        "eqf_levels": [6],
                        "validation_evidence_ids": ["REG-1"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    result = _build(tmp_path, paths, supply)
    h2 = result["subsets"]["all_canonical"]["h2"]
    assert h2["validated_supply_map_provided"] is True
    assert h2["validated_covered_demand_count"] == 1
    assert h2["validated_missing_demand_count"] == 0
    assert h2["interpretation"] == "not_supported"


def test_query_family_diversity_comes_from_retained_evidence(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    result = _build(tmp_path, paths)
    demand = next(
        row
        for row in result["subsets"]["all_canonical"]["top_demands"]
        if row["competence_demand_id"] == "D-MAR-1"
    )
    assert demand["query_families_seen"] == "competence_demand|hypothesis_verification"


def test_hypothesis_labels_and_tests_are_loaded_from_protocol(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    protocol = tmp_path / "protocol.yml"
    protocol.write_text(
        """
hypotheses:
  H1:
    label: Custom H1
    test: custom test 1
    declared_outcomes:
      - supported_maritime_dominance
      - partially_supported_maritime
      - not_supported
      - not_computable
    required_result_fields:
      - hypothesis_id
      - hypothesis_label
      - sample_size_maritime
      - sample_size_oceanic
      - effect_size_cohens_d
      - interpretation
  H2:
    label: Custom H2
    test: custom test 2
    declared_outcomes: [supported, partially_supported, not_supported, not_computable]
    required_result_fields:
      - hypothesis_id
      - hypothesis_label
      - hydronization_demand_count
      - validated_covered_demand_count
      - validated_missing_demand_count
      - interpretation
  H3:
    label: Custom H3
    test: custom test 3
    declared_outcomes: [supported, partially_supported, not_supported, not_computable]
    required_result_fields:
      - hypothesis_id
      - hypothesis_label
      - marine_fragment_count
      - oceanic_fragment_count
      - semantic_bridge_count
      - interpretation
""".strip()
        + "\n",
        encoding="utf-8",
    )
    result = sensitivity.build_provider_sensitivity_analysis(
        evidence_path=paths["evidence"],
        signals_path=paths["signals"],
        derived_demands_path=paths["demands"],
        hypothesis_fragments_path=paths["fragments"],
        validated_supply_map_path=None,
        protocol_path=protocol,
        output_json_path=tmp_path / "custom.json",
        output_markdown_path=tmp_path / "custom.md",
    )
    baseline = result["subsets"]["all_canonical"]
    assert baseline["h1"]["hypothesis_label"] == "Custom H1"
    assert baseline["h1"]["test_used"] == "custom test 1"
    assert baseline["h2"]["hypothesis_label"] == "Custom H2"
    assert baseline["h3"]["hypothesis_label"] == "Custom H3"


def test_empty_demand_csv_rejects_missing_required_header_columns(
    tmp_path: Path,
) -> None:
    path = tmp_path / "derived_competence_demands.csv"
    path.write_text("unexpected_column\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        sensitivity._read_csv_required(
            path,
            "derived demands",
            allow_empty=True,
            required_fields=(
                "competence_demand_id",
                "competence_label",
                "sector",
                "axis_group",
            ),
            allowed_fields=sensitivity.DERIVED_DEMAND_COLUMNS,
        )


def test_empty_demand_csv_rejects_unexpected_header_column(tmp_path: Path) -> None:
    path = tmp_path / "derived_competence_demands.csv"
    path.write_text(
        ",".join((*sensitivity.DERIVED_DEMAND_COLUMNS, "unexpected_column")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unexpected columns"):
        sensitivity._read_csv_required(
            path,
            "derived demands",
            allow_empty=True,
            required_fields=sensitivity.DERIVED_DEMAND_COLUMNS,
            allowed_fields=sensitivity.DERIVED_DEMAND_COLUMNS,
        )


def test_declared_hypothesis_ids_drive_sensitivity_outputs(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    protocol = tmp_path / "protocol.yml"
    protocol.write_text(
        """
hypotheses:
  H1:
    label: Custom H1
    test: custom test
    declared_outcomes: [supported_maritime_dominance, partially_supported_maritime, not_supported, not_computable]
    required_result_fields: [hypothesis_id, hypothesis_label, interpretation]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    output_json = tmp_path / "custom.json"
    output_markdown = tmp_path / "custom.md"
    result = sensitivity.build_provider_sensitivity_analysis(
        evidence_path=paths["evidence"],
        signals_path=paths["signals"],
        derived_demands_path=paths["demands"],
        hypothesis_fragments_path=paths["fragments"],
        validated_supply_map_path=None,
        protocol_path=protocol,
        output_json_path=output_json,
        output_markdown_path=output_markdown,
    )
    baseline = result["subsets"]["all_canonical"]
    assert baseline["h1"]["hypothesis_id"] == "H1"
    assert "h2" not in baseline
    assert "h3" not in baseline
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "| subset | providers | evidence | DOI | signals | demands | max share | H1 |" in markdown
    assert " | H2 | " not in markdown


def test_protocol_rejects_unsupported_hypothesis_before_writing_reports(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    protocol = tmp_path / "protocol.yml"
    protocol.write_text(
        """
hypotheses:
  H1:
    label: H1
    test: test
    declared_outcomes: [not_computable]
    required_result_fields: [hypothesis_id]
  H2:
    label: H2
    test: test
    declared_outcomes: [not_computable]
    required_result_fields: [hypothesis_id]
  H3:
    label: H3
    test: test
    declared_outcomes: [not_computable]
    required_result_fields: [hypothesis_id]
  H4:
    label: H4
    test: unsupported
    declared_outcomes: [not_computable]
    required_result_fields: [hypothesis_id]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    output_json = tmp_path / "unsupported.json"
    output_markdown = tmp_path / "unsupported.md"
    with pytest.raises(ValueError, match="unsupported hypotheses: H4"):
        sensitivity.build_provider_sensitivity_analysis(
            evidence_path=paths["evidence"],
            signals_path=paths["signals"],
            derived_demands_path=paths["demands"],
            hypothesis_fragments_path=paths["fragments"],
            validated_supply_map_path=None,
            protocol_path=protocol,
            output_json_path=output_json,
            output_markdown_path=output_markdown,
        )
    assert not output_json.exists()
    assert not output_markdown.exists()
