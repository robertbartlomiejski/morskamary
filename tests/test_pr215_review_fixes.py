"""Regression tests for non-outdated PR #215 review thread fixes.

Each test demonstrates the previous failure mode and verifies the correction.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ── 1. parse_args forwards CLI arguments ─────────────────────────────────────


class TestStabilityParseArgs:
    """Thread: 'Forward workflow arguments to the stability CLI'."""

    def test_parse_args_honours_sys_argv(self) -> None:
        """parse_args(None) must read sys.argv, not discard it."""
        mod = _load_script("build_run_stability_report")
        with patch.object(
            sys,
            "argv",
            ["prog", "--output-path", "/tmp/custom.json", "--jaccard-threshold", "0.99"],
        ):
            args = mod.parse_args(None)
        assert args.output_path == "/tmp/custom.json"
        assert args.jaccard_threshold == 0.99

    def test_parse_args_explicit_list_still_works(self) -> None:
        mod = _load_script("build_run_stability_report")
        args = mod.parse_args(["--archive-root", "/tmp/ar"])
        assert args.archive_root == "/tmp/ar"


# ── 2. query_id_hash in fingerprint ──────────────────────────────────────────


class TestFingerprintQueryIdHash:
    """Thread: 'Populate every comparability fingerprint dimension'."""

    def test_different_query_universes_produce_different_fingerprints(self) -> None:
        mod = _load_script("build_run_stability_report")
        fp_a, payload_a = mod.build_comparability_fingerprint(
            providers_used=["crossref"],
            query_protocol_version="1.0.0",
            time_windows=[],
            sampling_strategies=[],
            query_id_hash="abc123",
        )
        fp_b, payload_b = mod.build_comparability_fingerprint(
            providers_used=["crossref"],
            query_protocol_version="1.0.0",
            time_windows=[],
            sampling_strategies=[],
            query_id_hash="def456",
        )
        assert fp_a != fp_b
        assert payload_a["query_id_hash"] == "abc123"
        assert payload_b["query_id_hash"] == "def456"

    def test_normalize_query_constraints_extracts_query_id_hash(self) -> None:
        mod = _load_script("build_run_stability_report")
        constraints = {
            "protocol_version": "1.0.0",
            "queries": [
                {"query_id": "Q001", "time_window": {}, "sampling_strategy": {}},
                {"query_id": "Q002", "time_window": {}, "sampling_strategy": {}},
            ],
        }
        result = mod._normalize_query_constraints(constraints)
        expected_hash = hashlib.sha256(
            ",".join(sorted(["Q001", "Q002"])).encode("utf-8")
        ).hexdigest()
        assert result["query_id_hash"] == expected_hash


# ── 3. static-recovery runs excluded ─────────────────────────────────────────


class TestStaticRecoveryExclusion:
    """Thread: 'Exclude static-recovery runs from saturation'."""

    def test_static_recovery_run_is_excluded(self, tmp_path: Path) -> None:
        mod = _load_script("build_run_stability_report")
        archive_root = tmp_path / "archive"
        run_dir = archive_root / "runs" / "static-run"
        run_dir.mkdir(parents=True)
        _write_json(
            run_dir / "manifest.json",
            {"run_id": "static-run", "is_static_recovery_mode": True},
        )
        ref = mod.RunReference(
            run_id="static-run",
            run_path="runs/static-run",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            archived_at="2026-01-01T00:00:00+00:00",
        )
        from src.axis_classifier import AxisClassifier

        result = mod.load_run_snapshot(archive_root, ref, AxisClassifier())
        assert result is None


# ── 4. validation_evidence_ids required ───────────────────────────────────────


class TestValidationEvidenceRequired:
    """Thread: 'Require explicit validation evidence before including supply'."""

    def test_validated_without_evidence_is_not_computable(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg_path = root / "registry.csv"
            sig_path = root / "signals.jsonl"

            with reg_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "credential_id", "credential_name", "eqf_level",
                        "issuing_body", "country_iso", "axis_coverage",
                        "validation_status", "source_url",
                        "validation_evidence_ids", "notes",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "credential_id": "cred-1",
                    "credential_name": "Test Credential",
                    "eqf_level": 7,
                    "issuing_body": "Test",
                    "country_iso": "EU",
                    "axis_coverage": "HYDRONIZATION",
                    "validation_status": "validated",
                    "source_url": "",
                    "validation_evidence_ids": "",  # blank!
                    "notes": "",
                })

            sig_path.write_text(
                json.dumps({
                    "signal_id": "sig-1",
                    "axis_group": "HYDRONIZATION",
                    "sector": "water",
                    "competence_label": "Test",
                    "competence_description": "Test",
                    "demand_phrase": "test credential governance",
                    "learning_outcome_candidate": "Test",
                }) + "\n",
                encoding="utf-8",
            )

            payload = mod.compute_h2_supply_map(
                registry_entries=mod.load_registry(reg_path),
                demand_signals=mod.load_demand_signals(sig_path),
            )
            # Validated without evidence should be treated as not computable
            assert payload["interpretation"] == "not_computable"
            assert payload["validated_covered_demand_count"] == 0


# ── 5. OpenAlex probe requires API key ────────────────────────────────────────


class TestOpenAlexProbeRequiresKey:
    """Thread: 'Fail preflight when the OpenAlex key is absent'."""

    def test_probe_returns_missing_when_key_absent(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import check_research_api_health

        with patch.dict(os.environ, {}, clear=True):
            result = check_research_api_health.probe_openalex()
        assert result.status == "missing"
        assert "OPENALEX_API_KEY" in result.detail


# ── 6. abstract_inverted_index stripped ───────────────────────────────────────


class TestOpenAlexAbstractStripped:
    """Thread: 'Strip OpenAlex abstracts before retaining raw pages'."""

    def test_strip_abstract_fields_removes_inverted_index(self) -> None:
        from src.scientific_sources.openalex import _strip_abstract_fields

        payload = {
            "results": [
                {"id": "W1", "title": "Test", "abstract_inverted_index": {"the": [0, 5]}},
                {"id": "W2", "title": "Test2"},
            ],
            "meta": {"count": 2},
        }
        cleaned = _strip_abstract_fields(payload)
        assert "abstract_inverted_index" not in cleaned["results"][0]
        assert cleaned["results"][0]["title"] == "Test"
        assert cleaned["results"][1]["title"] == "Test2"
        assert cleaned["meta"]["count"] == 2


# ── 7. redact out-of-repo paths ──────────────────────────────────────────────


class TestPathRedaction:
    """Thread: 'Redact absolute input paths from credential artifacts'."""

    def test_out_of_repo_path_is_redacted(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        result = mod._repo_relative_posix(Path("/tmp/external/registry.csv"))
        assert not result.startswith("/tmp")
        assert "registry.csv" in result

    def test_in_repo_path_is_relative(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        result = mod._repo_relative_posix(
            REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        )
        assert result == "data/validated/credential_supply_registry.csv"


# ── 8. validate_complete_authoritative_protocol_projection ────────────────────


class TestProtocolProjectionValidation:
    """Thread: 'Compare every acquisition-defining field'."""

    def test_stale_time_window_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        correct_constraints = {
            "protocol_version": protocol.protocol_version,
            "queries": protocol.to_query_constraints(),
        }
        # Valid constraints should pass
        validate_complete_authoritative_protocol_projection(protocol, correct_constraints)

        # Mutated time_window should fail
        bad_constraints = json.loads(json.dumps(correct_constraints))
        bad_constraints["queries"][0]["time_window"] = {"from_year": 1900, "to_year": 1901}
        with pytest.raises(LiveQueryProtocolError, match="time_window.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_stale_evidence_intent_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        bad_constraints = {
            "protocol_version": protocol.protocol_version,
            "queries": json.loads(json.dumps(protocol.to_query_constraints())),
        }
        bad_constraints["queries"][0]["evidence_intent"] = "WRONG_INTENT"
        with pytest.raises(LiveQueryProtocolError, match="evidence_intent.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_stale_protocol_version_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        bad_constraints = {
            "protocol_version": "0.0.0-stale",
            "queries": protocol.to_query_constraints(),
        }
        with pytest.raises(LiveQueryProtocolError, match="protocol_version mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)


# ── 9. workflow YAML structure ────────────────────────────────────────────────


class TestWorkflowStructure:
    """Threads: 'Feed validated map into Layer 5', 'Archive before stability'."""

    def test_workflow_has_rebuild_layer5_step(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        assert "Rebuild Layer 5 with validated supply map" in step_names

    def test_archive_precedes_stability_in_workflow(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        archive_idx = step_names.index("Archive full run outputs")
        stability_idx = step_names.index("Build cross-run stability report")
        assert archive_idx < stability_idx, (
            "Archive must precede stability report in workflow"
        )

    def test_h2_map_step_has_id_and_continues_on_error(self) -> None:
        """The H2 supply-map build step must expose its outcome via `id: h2_map`
        and must not fail the job outright, since the registry may be absent."""
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        h2_step = next(
            s for s in steps if s.get("name") == "Build preliminary H2 credential supply map"
        )
        assert h2_step.get("id") == "h2_map"
        assert h2_step.get("continue-on-error") is True

    def test_rebuild_layer5_step_is_conditioned_on_has_validated_supply(self) -> None:
        """The Layer 5 rebuild step must only run when the H2 map step recorded
        at least one validated-with-evidence entry."""
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        rebuild_step = next(
            s for s in steps if s.get("name") == "Rebuild Layer 5 with validated supply map"
        )
        assert rebuild_step.get("if") == "env.HAS_VALIDATED_SUPPLY == 'true'"
        assert "--validated-supply-map" in rebuild_step["run"]

    def test_h2_map_step_precedes_rebuild_layer5_step(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        h2_idx = step_names.index("Build preliminary H2 credential supply map")
        rebuild_idx = step_names.index("Rebuild Layer 5 with validated supply map")
        assert h2_idx < rebuild_idx

    def test_h2_map_step_sets_has_validated_supply_env_in_all_branches(self) -> None:
        """HAS_VALIDATED_SUPPLY must be set to a value on every code path
        (registry missing, map missing, map present) so the downstream `if`
        condition never evaluates against an undefined env var."""
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        h2_step = next(
            s for s in steps if s.get("name") == "Build preliminary H2 credential supply map"
        )
        script = h2_step["run"]
        # Two fallback branches (registry missing, map file missing) hard-code false.
        assert script.count('echo "HAS_VALIDATED_SUPPLY=false" >> "$GITHUB_ENV"') == 2
        # The success branch forwards the computed HAS_VALIDATED python result.
        assert 'echo "HAS_VALIDATED_SUPPLY=${HAS_VALIDATED}" >> "$GITHUB_ENV"' in script
