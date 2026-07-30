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

    def test_h2_map_step_has_id_and_continue_on_error(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        h2_step = next(
            s for s in steps
            if s.get("name") == "Build preliminary H2 credential supply map"
        )
        assert h2_step.get("id") == "h2_map"
        assert h2_step.get("continue-on-error") is True

    def test_rebuild_layer5_step_has_gated_condition_and_supply_map_arg(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        step = next(
            s for s in steps
            if s.get("name") == "Rebuild Layer 5 with validated supply map"
        )
        assert step.get("if") == "env.HAS_VALIDATED_SUPPLY == 'true'"
        assert "--validated-supply-map" in step["run"]

    def test_h2_map_step_precedes_rebuild_layer5_step(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        h2_idx = step_names.index("Build preliminary H2 credential supply map")
        rebuild_idx = step_names.index("Rebuild Layer 5 with validated supply map")
        assert h2_idx < rebuild_idx


# ── 10. additional build_run_stability_report boundary coverage ──────────────


class TestFingerprintQueryIdHashBoundaries:
    """Additional coverage: empty-query and default-value boundaries."""

    def test_normalize_query_constraints_with_no_queries_yields_empty_hash(self) -> None:
        mod = _load_script("build_run_stability_report")
        result = mod._normalize_query_constraints(
            {"protocol_version": "1.0.0", "queries": []}
        )
        assert result["query_id_hash"] == ""

    def test_normalize_query_constraints_ignores_queries_without_query_id(self) -> None:
        mod = _load_script("build_run_stability_report")
        result = mod._normalize_query_constraints(
            {
                "protocol_version": "1.0.0",
                "queries": [{"time_window": {}}, {"query_id": ""}],
            }
        )
        assert result["query_id_hash"] == ""

    def test_build_comparability_fingerprint_defaults_query_id_hash_to_unknown(self) -> None:
        mod = _load_script("build_run_stability_report")
        _fingerprint, payload = mod.build_comparability_fingerprint(
            providers_used=["crossref"],
            query_protocol_version="1.0.0",
            time_windows=[],
            sampling_strategies=[],
        )
        assert payload["query_id_hash"] == "unknown"

    def test_query_id_hash_is_order_independent(self) -> None:
        """Same query_id set in different orders must hash identically."""
        mod = _load_script("build_run_stability_report")
        result_a = mod._normalize_query_constraints(
            {
                "protocol_version": "1.0.0",
                "queries": [{"query_id": "Q002"}, {"query_id": "Q001"}],
            }
        )
        result_b = mod._normalize_query_constraints(
            {
                "protocol_version": "1.0.0",
                "queries": [{"query_id": "Q001"}, {"query_id": "Q002"}],
            }
        )
        assert result_a["query_id_hash"] == result_b["query_id_hash"]


class TestStaticRecoveryExclusionBoundaries:
    """Additional coverage: runs must not be excluded unless explicitly flagged."""

    def test_run_without_static_recovery_flag_is_not_excluded(self, tmp_path: Path) -> None:
        mod = _load_script("build_run_stability_report")
        archive_root = tmp_path / "archive"
        run_dir = archive_root / "runs" / "normal-run"
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "manifest.json", {"run_id": "normal-run"})
        ref = mod.RunReference(
            run_id="normal-run",
            run_path="runs/normal-run",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            archived_at="2026-01-01T00:00:00+00:00",
        )
        from src.axis_classifier import AxisClassifier

        result = mod.load_run_snapshot(archive_root, ref, AxisClassifier())
        assert result is not None
        assert result.run_id == "normal-run"

    def test_run_with_static_recovery_flag_false_is_not_excluded(self, tmp_path: Path) -> None:
        mod = _load_script("build_run_stability_report")
        archive_root = tmp_path / "archive"
        run_dir = archive_root / "runs" / "normal-run-2"
        run_dir.mkdir(parents=True)
        _write_json(
            run_dir / "manifest.json",
            {"run_id": "normal-run-2", "is_static_recovery_mode": False},
        )
        ref = mod.RunReference(
            run_id="normal-run-2",
            run_path="runs/normal-run-2",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            archived_at="2026-01-01T00:00:00+00:00",
        )
        from src.axis_classifier import AxisClassifier

        result = mod.load_run_snapshot(archive_root, ref, AxisClassifier())
        assert result is not None


# ── 11. additional credential supply map boundary coverage ───────────────────


class TestParseEvidenceIds:
    """Additional coverage: _parse_evidence_ids parsing edge cases."""

    def test_parses_pipe_delimited_ids_and_trims_whitespace(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        result = mod._parse_evidence_ids(" EVD-001 | EVD-002 ")
        assert result == ("EVD-001", "EVD-002")

    def test_filters_empty_tokens_from_double_pipes(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        result = mod._parse_evidence_ids("EVD-001||EVD-003")
        assert result == ("EVD-001", "EVD-003")

    def test_empty_and_none_input_yield_empty_tuple(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("") == ()
        assert mod._parse_evidence_ids(None) == ()


class TestValidationEvidenceRequiredBoundaries:
    """Additional coverage: evidence must accompany 'validated' status specifically."""

    def test_review_required_with_evidence_ids_is_not_counted_as_validated(self) -> None:
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
                    "validation_status": "review_required",
                    "source_url": "",
                    "validation_evidence_ids": "EVD-999",
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
            assert payload["validated_entries_hydronization_eqf_6_7"] == 0
            assert payload["interpretation"] == "not_computable"


class TestPathRedactionBoundaries:
    """Additional coverage: exact redaction format for out-of-repo paths."""

    def test_redacted_path_uses_expected_prefix_format(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        result = mod._repo_relative_posix(Path("/some/external/dir/registry.csv"))
        assert result == "<redacted>/registry.csv"


class TestCredentialRegistryDataFile:
    """Additional coverage: the actual committed registry data file."""

    def test_actual_registry_file_has_evidence_column_and_all_entries_pending(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        entries = mod.load_registry(
            REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        )
        assert len(entries) == 9
        assert all(entry.validation_status == "review_required" for entry in entries)
        assert all(entry.validation_evidence_ids == () for entry in entries)


# ── 12. additional OpenAlex probe boundary coverage ───────────────────────────


class TestOpenAlexProbeWithKey:
    """Additional coverage: probe_openalex sends an Authorization header when set."""

    def test_probe_sends_bearer_header_when_key_present(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import check_research_api_health

        captured: dict[str, object] = {}

        def fake_request(url: str, headers: dict[str, str]):
            captured["url"] = url
            captured["headers"] = headers
            return check_research_api_health.ProbeResult(
                "", "ok", "request succeeded", 200
            )

        with patch.dict(os.environ, {"OPENALEX_API_KEY": "test-key-123"}, clear=True), \
                patch.object(check_research_api_health, "_request", fake_request):
            result = check_research_api_health.probe_openalex()

        assert result.status == "ok"
        assert result.provider == "openalex"
        assert captured["headers"]["Authorization"] == "Bearer test-key-123"


# ── 13. additional OpenAlex abstract-stripping boundary coverage ─────────────


class TestOpenAlexAbstractStrippedBoundaries:
    """Additional coverage: single-work and non-dict payload shapes."""

    def test_top_level_dict_without_results_key_is_stripped_directly(self) -> None:
        from src.scientific_sources.openalex import _strip_abstract_fields

        payload = {
            "id": "W1",
            "title": "Single Work",
            "abstract_inverted_index": {"the": [0]},
        }
        cleaned = _strip_abstract_fields(payload)
        assert "abstract_inverted_index" not in cleaned
        assert cleaned["title"] == "Single Work"

    def test_non_dict_payload_passed_through_unchanged(self) -> None:
        from src.scientific_sources.openalex import _strip_abstract_fields

        assert _strip_abstract_fields(None) is None
        assert _strip_abstract_fields([1, 2, 3]) == [1, 2, 3]

    def test_payload_without_abstract_field_is_unaffected(self) -> None:
        from src.scientific_sources.openalex import _strip_abstract_fields

        payload = {"results": [{"id": "W1", "title": "T"}], "meta": {"count": 1}}
        cleaned = _strip_abstract_fields(payload)
        assert cleaned == payload


# ── 14. additional protocol-projection validation boundary coverage ──────────


class TestProtocolProjectionValidationBoundaries:
    """Additional coverage: structural and per-field mismatch scenarios."""

    def _load_protocol(self):
        from src.scientific_sources.live_query_protocol import load_live_query_protocol

        return load_live_query_protocol(REPO_ROOT / "config" / "live_query_protocol.yml")

    def test_missing_queries_key_raises(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = self._load_protocol()
        bad_constraints = {"protocol_version": protocol.protocol_version}
        with pytest.raises(LiveQueryProtocolError, match="'queries' list"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_query_count_mismatch_raises(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = self._load_protocol()
        truncated = protocol.to_query_constraints()[:-1]
        bad_constraints = {
            "protocol_version": protocol.protocol_version,
            "queries": truncated,
        }
        with pytest.raises(LiveQueryProtocolError, match="query count mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_unknown_query_id_raises(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = self._load_protocol()
        bad_constraints = {
            "protocol_version": protocol.protocol_version,
            "queries": json.loads(json.dumps(protocol.to_query_constraints())),
        }
        bad_constraints["queries"][0]["query_id"] = "UNKNOWN-999"
        with pytest.raises(LiveQueryProtocolError, match="unknown query_id"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_stale_query_text_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = self._load_protocol()
        bad_constraints = {
            "protocol_version": protocol.protocol_version,
            "queries": json.loads(json.dumps(protocol.to_query_constraints())),
        }
        bad_constraints["queries"][0]["query_text"] = "completely different query text"
        with pytest.raises(LiveQueryProtocolError, match="query_text.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_stale_sampling_strategy_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = self._load_protocol()
        bad_constraints = {
            "protocol_version": protocol.protocol_version,
            "queries": json.loads(json.dumps(protocol.to_query_constraints())),
        }
        bad_constraints["queries"][0]["sampling_strategy"] = {
            "mode": "tampered",
            "pages": 1,
            "rows_per_page": 1,
            "dedupe_key": "tampered",
        }
        with pytest.raises(LiveQueryProtocolError, match="sampling_strategy.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_blank_protocol_version_in_constraints_bypasses_version_check(self) -> None:
        """An empty protocol_version string must not trigger a false mismatch."""
        from src.scientific_sources.live_query_protocol import (
            validate_complete_authoritative_protocol_projection,
        )

        protocol = self._load_protocol()
        constraints = {
            "protocol_version": "",
            "queries": protocol.to_query_constraints(),
        }
        # Should not raise: blank constraint version is treated as absent.
        validate_complete_authoritative_protocol_projection(protocol, constraints)

    def test_valid_constraints_pass_without_error(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            validate_complete_authoritative_protocol_projection,
        )

        protocol = self._load_protocol()
        constraints = {
            "protocol_version": protocol.protocol_version,
            "queries": protocol.to_query_constraints(),
        }
        validate_complete_authoritative_protocol_projection(protocol, constraints)


# ── 15. MANIFEST_SOURCES.csv regression coverage ──────────────────────────────


class TestManifestSourcesEntry:
    """Additional coverage: the new test file must be tracked in the manifest."""

    def test_manifest_lists_pr215_review_fixes_test(self) -> None:
        manifest_path = REPO_ROOT / "MANIFEST_SOURCES.csv"
        content = manifest_path.read_text(encoding="utf-8")
        assert "tests/test_pr215_review_fixes.py,script" in content
