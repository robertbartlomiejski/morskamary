from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "build_validated_credential_supply_map",
    str(REPO_ROOT / "scripts" / "build_validated_credential_supply_map.py"),
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)


def _write_registry(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "credential_id",
                "credential_name",
                "eqf_level",
                "issuing_body",
                "country_iso",
                "axis_coverage",
                "validation_status",
                "source_url",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_signals(path: Path, rows: list[dict[str, object]]) -> None:
    payload = "\n".join(json.dumps(row) for row in rows) + "\n"
    path.write_text(payload, encoding="utf-8")


def _signal(
    signal_id: str,
    *,
    axis_group: str = "HYDRONIZATION",
    sector: str = "desalination",
    competence_label: str = "Governance or policy skill",
    competence_description: str = (
        "Governance, institutional, and stakeholder coordination skills."
    ),
    demand_phrase: str = "governance",
    learning_outcome_candidate: str = (
        "Water governance and institutional coordination."
    ),
) -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "axis_group": axis_group,
        "sector": sector,
        "competence_label": competence_label,
        "competence_description": competence_description,
        "demand_phrase": demand_phrase,
        "learning_outcome_candidate": learning_outcome_candidate,
    }


def test_load_registry_parses_axis_coverage_and_status_distribution() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        registry_path = root / "registry.csv"
        _write_registry(
            registry_path,
            [
                {
                    "credential_id": "cred-1",
                    "credential_name": "Candidate MSc in Integrated Water Governance",
                    "eqf_level": 7,
                    "issuing_body": "Review required",
                    "country_iso": "EU",
                    "axis_coverage": "HYDRONIZATION|OCEANIC",
                    "validation_status": "review_required",
                    "source_url": "",
                    "notes": "Placeholder",
                }
            ],
        )

        registry = _MOD.load_registry(registry_path)

        assert len(registry) == 1
        assert registry[0].axis_coverage == ("HYDRONIZATION", "OCEANIC")
        assert registry[0].validation_status == "review_required"
        assert _MOD._status_distribution(registry) == {
            "review_required": 1,
            "validated": 0,
            "rejected": 0,
        }


def test_compute_supply_map_matches_demands_by_axis_and_tokens() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        registry_path = root / "registry.csv"
        demand_path = root / "signals.jsonl"
        _write_registry(
            registry_path,
            [
                {
                    "credential_id": "cred-h-1",
                    "credential_name": "Candidate MSc in Integrated Water Governance",
                    "eqf_level": 7,
                    "issuing_body": "Review required",
                    "country_iso": "EU",
                    "axis_coverage": "HYDRONIZATION",
                    "validation_status": "review_required",
                    "source_url": "",
                    "notes": "Water governance pathway",
                },
                {
                    "credential_id": "cred-t-1",
                    "credential_name": "Candidate BSc in Port Logistics",
                    "eqf_level": 6,
                    "issuing_body": "Review required",
                    "country_iso": "EU",
                    "axis_coverage": "MARITIME",
                    "validation_status": "review_required",
                    "source_url": "",
                    "notes": "Port operations",
                },
            ],
        )
        _write_signals(
            demand_path,
            [
                _signal("sig-1"),
                _signal(
                    "sig-2",
                    competence_label="Digital or data skill",
                    competence_description=(
                        "Digital, data, AI, autonomy, and cyber-technical "
                        "skill signals."
                    ),
                    demand_phrase="digital",
                    learning_outcome_candidate=(
                        "Digital twin and monitoring for coastal water systems."
                    ),
                ),
                _signal("sig-3", axis_group="MARITIME"),
            ],
        )

        payload = _MOD.compute_h2_supply_map(
            registry_entries=_MOD.load_registry(registry_path),
            demand_signals=_MOD.load_demand_signals(demand_path),
            registry_path=registry_path,
            demand_signals_path=demand_path,
        )

        assert payload["hydronization_demand_count"] == 2
        assert payload["preliminary_covered_demand_count"] == 1
        assert payload["preliminary_missing_demand_count"] == 1
        assert payload["validated_covered_demand_count"] == 0
        assert payload["interpretation"] == "not_computable"


def test_missing_ratio_and_interpretation_require_validated_entries() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        registry_path = root / "registry.csv"
        demand_path = root / "signals.jsonl"
        _write_registry(
            registry_path,
            [
                {
                    "credential_id": "cred-h-gov",
                    "credential_name": "Validated MSc in Water Governance",
                    "eqf_level": 7,
                    "issuing_body": "Validated issuer",
                    "country_iso": "EU",
                    "axis_coverage": "HYDRONIZATION",
                    "validation_status": "validated",
                    "source_url": "",
                    "notes": "Governance and water diplomacy",
                },
                {
                    "credential_id": "cred-h-digital",
                    "credential_name": "Validated Graduate Certificate in Coastal Digital Monitoring",
                    "eqf_level": 6,
                    "issuing_body": "Validated issuer",
                    "country_iso": "EU",
                    "axis_coverage": "HYDRONIZATION",
                    "validation_status": "validated",
                    "source_url": "",
                    "notes": "Digital monitoring and sensor systems",
                },
                {
                    "credential_id": "cred-h-resilience",
                    "credential_name": "Validated Certificate in Hydrosocial Resilience Planning",
                    "eqf_level": 6,
                    "issuing_body": "Validated issuer",
                    "country_iso": "EU",
                    "axis_coverage": "HYDRONIZATION",
                    "validation_status": "validated",
                    "source_url": "",
                    "notes": "Resilience planning",
                },
            ],
        )
        _write_signals(
            demand_path,
            [
                _signal(
                    "sig-1",
                    demand_phrase="governance",
                    learning_outcome_candidate="Water governance",
                ),
                _signal(
                    "sig-2",
                    competence_label="Digital or data skill",
                    competence_description=(
                        "Digital, data, AI, autonomy, and cyber-technical "
                        "skill signals."
                    ),
                    demand_phrase="digital",
                    learning_outcome_candidate=(
                        "Digital monitoring for coastal water systems."
                    ),
                ),
                _signal(
                    "sig-3",
                    competence_label="Sustainability, resilience, or adaptation skill",
                    competence_description="Sustainability, resilience, and adaptation skill signals.",
                    demand_phrase="resilience",
                    learning_outcome_candidate="Hydrosocial resilience planning.",
                ),
                _signal(
                    "sig-4",
                    competence_label="Learning outcome signal",
                    competence_description="Learning outcomes and curriculum descriptors.",
                    demand_phrase="curriculum",
                    learning_outcome_candidate="Curriculum translation with no validated credential match.",
                ),
            ],
        )

        payload = _MOD.compute_h2_supply_map(
            registry_entries=_MOD.load_registry(registry_path),
            demand_signals=_MOD.load_demand_signals(demand_path),
            registry_path=registry_path,
            demand_signals_path=demand_path,
        )

        assert payload["validated_covered_demand_count"] == 3
        assert payload["validated_missing_demand_count"] == 1
        assert payload["missing_ratio"] == 0.25
        assert payload["interpretation"] == "partially_supported"

        loaded_signals = _MOD.load_demand_signals(demand_path)
        supported_payload = _MOD.compute_h2_supply_map(
            registry_entries=_MOD.load_registry(registry_path),
            demand_signals=[
                loaded_signals[0],
                loaded_signals[-1],
                _MOD.DemandSignal(
                    signal_id="sig-5",
                    axis_group="HYDRONIZATION",
                    sector="desalination",
                    competence_label="Community mediation skill",
                    competence_description="Stakeholder listening and mediation.",
                    demand_phrase="mediation",
                    learning_outcome_candidate="Community mediation with no credential match.",
                ),
            ],
            registry_path=registry_path,
            demand_signals_path=demand_path,
        )
        assert supported_payload["validated_covered_demand_count"] == 1
        assert supported_payload["validated_missing_demand_count"] == 2
        assert supported_payload["missing_ratio"] == 0.666667
        assert supported_payload["interpretation"] == "supported"

        not_supported_payload = _MOD.compute_h2_supply_map(
            registry_entries=_MOD.load_registry(registry_path),
            demand_signals=loaded_signals[:3],
            registry_path=registry_path,
            demand_signals_path=demand_path,
        )
        assert not_supported_payload["validated_covered_demand_count"] == 3
        assert not_supported_payload["validated_missing_demand_count"] == 0
        assert not_supported_payload["missing_ratio"] == 0.0
        assert not_supported_payload["interpretation"] == "not_supported"


def test_eqf_filter_excludes_levels_outside_requested_range() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        registry_path = root / "registry.csv"
        demand_path = root / "signals.jsonl"
        _write_registry(
            registry_path,
            [
                {
                    "credential_id": "cred-h-5",
                    "credential_name": "Validated Diploma in Water Governance",
                    "eqf_level": 5,
                    "issuing_body": "Validated issuer",
                    "country_iso": "EU",
                    "axis_coverage": "HYDRONIZATION",
                    "validation_status": "validated",
                    "source_url": "",
                    "notes": "Water governance",
                }
            ],
        )
        _write_signals(demand_path, [_signal("sig-1")])

        excluded = _MOD.compute_h2_supply_map(
            registry_entries=_MOD.load_registry(registry_path),
            demand_signals=_MOD.load_demand_signals(demand_path),
            eqf_min=6,
            eqf_max=7,
            registry_path=registry_path,
            demand_signals_path=demand_path,
        )
        included = _MOD.compute_h2_supply_map(
            registry_entries=_MOD.load_registry(registry_path),
            demand_signals=_MOD.load_demand_signals(demand_path),
            eqf_min=5,
            eqf_max=7,
            registry_path=registry_path,
            demand_signals_path=demand_path,
        )

        assert excluded["validated_covered_demand_count"] == 0
        assert included["validated_covered_demand_count"] == 1


def test_main_writes_output_json_without_live_data() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        registry_path = root / "registry.csv"
        demand_path = root / "signals.jsonl"
        output_dir = root / "outputs"
        _write_registry(
            registry_path,
            [
                {
                    "credential_id": "cred-h-1",
                    "credential_name": "Candidate MSc in Integrated Water Governance",
                    "eqf_level": 7,
                    "issuing_body": "Review required",
                    "country_iso": "EU",
                    "axis_coverage": "HYDRONIZATION",
                    "validation_status": "review_required",
                    "source_url": "",
                    "notes": "Water governance",
                }
            ],
        )
        _write_signals(demand_path, [_signal("sig-1")])

        with patch.object(_MOD, "_timestamp_utc", return_value="2026-07-25T12:00:00+00:00"):
            exit_code = _MOD.main(
                [
                    "--registry-path",
                    str(registry_path),
                    "--demand-signals",
                    str(demand_path),
                    "--output-dir",
                    str(output_dir),
                ]
            )

        payload = json.loads(
            (output_dir / "h2_credential_supply_map.json").read_text(
                encoding="utf-8"
            )
        )
        assert exit_code == 0
        assert payload["timestamp_utc"] == "2026-07-25T12:00:00+00:00"
        assert payload["interpretation"] == "not_computable"
