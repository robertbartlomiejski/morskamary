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


def _load_workflow_steps() -> list[dict]:
    import yaml  # type: ignore[import-untyped]

    wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
    wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    return wf["jobs"]["live-analysis"]["steps"]


class TestWorkflowValidatedSupplyGate:
    """Thread: 'Gate Layer 5 rebuild on validated-with-evidence supply entries'."""

    def test_h2_map_step_has_id_and_continue_on_error(self) -> None:
        steps = _load_workflow_steps()
        step = next(
            s for s in steps if s.get("name") == "Build preliminary H2 credential supply map"
        )
        assert step.get("id") == "h2_map"
        assert step.get("continue-on-error") is True

    def test_h2_map_step_sets_has_validated_supply_env(self) -> None:
        steps = _load_workflow_steps()
        step = next(
            s for s in steps if s.get("name") == "Build preliminary H2 credential supply map"
        )
        assert "HAS_VALIDATED_SUPPLY" in step["run"]
        assert "GITHUB_ENV" in step["run"]
        assert "validated_entries_hydronization_eqf_6_7" in step["run"]

    def test_rebuild_layer5_step_is_gated_on_env_var(self) -> None:
        steps = _load_workflow_steps()
        step = next(
            s for s in steps if s.get("name") == "Rebuild Layer 5 with validated supply map"
        )
        assert step.get("if") == "env.HAS_VALIDATED_SUPPLY == 'true'"
        assert "--validated-supply-map" in step["run"]
        assert "outputs/h2_credential_supply_map.json" in step["run"]

    def test_rebuild_layer5_step_follows_h2_map_step(self) -> None:
        steps = _load_workflow_steps()
        step_names = [s.get("name", "") for s in steps]
        h2_idx = step_names.index("Build preliminary H2 credential supply map")
        rebuild_idx = step_names.index("Rebuild Layer 5 with validated supply map")
        assert h2_idx < rebuild_idx


# ── 10. _parse_evidence_ids parsing ───────────────────────────────────────────


class TestParseEvidenceIds:
    """Thread: 'Parse pipe-delimited validation evidence IDs'."""

    def test_parses_pipe_delimited_ids(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("EVD-001|EVD-002") == ("EVD-001", "EVD-002")

    def test_empty_string_yields_empty_tuple(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("") == ()

    def test_none_value_yields_empty_tuple(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids(None) == ()

    def test_whitespace_and_blank_tokens_are_filtered(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids(" EVD-1 |  | EVD-2 ") == ("EVD-1", "EVD-2")

    def test_single_id_without_pipe(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("EVD-ONLY") == ("EVD-ONLY",)


# ── 11. query_id_hash edge cases ──────────────────────────────────────────────


class TestQueryIdHashEdgeCases:
    """Thread: 'Populate every comparability fingerprint dimension' (edge cases)."""

    def test_no_queries_yields_empty_hash(self) -> None:
        mod = _load_script("build_run_stability_report")
        result = mod._normalize_query_constraints(
            {"protocol_version": "1.0.0", "queries": []}
        )
        assert result["query_id_hash"] == ""

    def test_missing_queries_key_yields_empty_hash(self) -> None:
        mod = _load_script("build_run_stability_report")
        result = mod._normalize_query_constraints({"protocol_version": "1.0.0"})
        assert result["query_id_hash"] == ""

    def test_query_id_hash_is_order_independent(self) -> None:
        mod = _load_script("build_run_stability_report")
        first = mod._normalize_query_constraints(
            {"queries": [{"query_id": "Q1"}, {"query_id": "Q2"}]}
        )
        second = mod._normalize_query_constraints(
            {"queries": [{"query_id": "Q2"}, {"query_id": "Q1"}]}
        )
        assert first["query_id_hash"] == second["query_id_hash"]

    def test_fingerprint_default_query_id_hash_is_unknown(self) -> None:
        mod = _load_script("build_run_stability_report")
        _, payload = mod.build_comparability_fingerprint(
            providers_used=["crossref"],
            query_protocol_version="1.0.0",
            time_windows=[],
            sampling_strategies=[],
        )
        assert payload["query_id_hash"] == "unknown"

    def test_duplicate_query_ids_do_not_change_hash(self) -> None:
        mod = _load_script("build_run_stability_report")
        with_dupe = mod._normalize_query_constraints(
            {"queries": [{"query_id": "Q1"}, {"query_id": "Q1"}, {"query_id": "Q2"}]}
        )
        without_dupe = mod._normalize_query_constraints(
            {"queries": [{"query_id": "Q1"}, {"query_id": "Q2"}]}
        )
        assert with_dupe["query_id_hash"] == without_dupe["query_id_hash"]


# ── 12. static-recovery exclusion regression (normal runs unaffected) ────────


class TestStaticRecoveryExclusionRegression:
    """Regression guard: the static-recovery check must not exclude normal runs."""

    def test_run_without_flag_is_not_excluded(self, tmp_path: Path) -> None:
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

    def test_run_with_explicit_false_flag_is_not_excluded(self, tmp_path: Path) -> None:
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


# ── 13. protocol projection validation edge cases ─────────────────────────────


class TestProtocolProjectionValidationEdgeCases:
    """Additional coverage for validate_complete_authoritative_protocol_projection."""

    def test_missing_queries_key_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        with pytest.raises(LiveQueryProtocolError, match="queries"):
            validate_complete_authoritative_protocol_projection(
                protocol, {"protocol_version": protocol.protocol_version}
            )

    def test_non_list_queries_value_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        with pytest.raises(LiveQueryProtocolError, match="queries"):
            validate_complete_authoritative_protocol_projection(
                protocol,
                {"protocol_version": protocol.protocol_version, "queries": "not-a-list"},
            )

    def test_query_count_mismatch_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        constraints = {
            "protocol_version": protocol.protocol_version,
            "queries": protocol.to_query_constraints()[:-1],
        }
        with pytest.raises(LiveQueryProtocolError, match="count mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, constraints)

    def test_unknown_query_id_is_rejected(self) -> None:
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
        bad_constraints["queries"][0]["query_id"] = "Q_NOT_A_REAL_QUERY_999"
        with pytest.raises(LiveQueryProtocolError, match="unknown query_id"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_stale_query_text_is_rejected(self) -> None:
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
        bad_constraints["queries"][0]["query_text"] = "stale query text no longer in config"
        with pytest.raises(LiveQueryProtocolError, match="query_text.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_stale_sampling_strategy_is_rejected(self) -> None:
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
        bad_constraints["queries"][0]["sampling_strategy"]["pages"] = 999
        with pytest.raises(LiveQueryProtocolError, match="sampling_strategy.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_missing_protocol_version_in_constraints_does_not_fail_version_check(
        self,
    ) -> None:
        """protocol_version comparison is skipped when constraints omit the field,
        so an otherwise-correct projection still passes."""
        from src.scientific_sources.live_query_protocol import (
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        constraints = {"queries": protocol.to_query_constraints()}
        validate_complete_authoritative_protocol_projection(protocol, constraints)


# ── 14. OpenAlex end-to-end abstract stripping ────────────────────────────────


class TestOpenAlexAbstractStrippedIntegration:
    """Integration coverage: search()/verify_doi() persist stripped raw_payload."""

    @staticmethod
    def _work(work_id: str = "W1") -> dict:
        return {
            "id": f"https://openalex.org/{work_id}",
            "display_name": "Test Article",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1234/test",
            "authorships": [{"author": {"display_name": "Test Author"}}],
            "primary_location": {"source": {"display_name": "Test Journal"}},
            "cited_by_count": 1,
            "topics": [],
            "keywords": [],
            "abstract_inverted_index": {"the": [0], "study": [1]},
        }

    def test_search_raw_payload_excludes_abstract_index(self) -> None:
        from src.scientific_sources.openalex import OpenAlexProvider

        provider = OpenAlexProvider()
        response = {"meta": {"count": 1}, "results": [self._work()]}

        def mock_backoff(*, url: str, context_label: str):
            del url, context_label
            return response, [], None

        with patch.object(
            provider, "_request_json_with_backoff", side_effect=mock_backoff
        ):
            result = provider.search("test", max_results=1)

        assert "abstract_inverted_index" not in result.raw_payload["results"][0]
        # Non-abstract fields survive the strip.
        assert result.raw_payload["results"][0]["display_name"] == "Test Article"

    def test_verify_doi_raw_payload_excludes_abstract_index(self) -> None:
        from src.scientific_sources.openalex import OpenAlexProvider

        provider = OpenAlexProvider()
        work = self._work()

        def mock_backoff(*, url: str, context_label: str):
            del url, context_label
            return work, [], None

        with patch.object(
            provider, "_request_json_with_backoff", side_effect=mock_backoff
        ):
            result = provider.verify_doi("10.1234/test")

        assert "abstract_inverted_index" not in result.raw_payload
        assert result.raw_payload["display_name"] == "Test Article"


# ── 15. probe_openalex success path with key present ─────────────────────────


class TestOpenAlexProbeWithKeyPresent:
    """Regression guard: probe still authenticates and succeeds when key is set."""

    def test_probe_sends_bearer_header_and_returns_ok(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import check_research_api_health

        captured_headers: dict[str, str] = {}

        def fake_request(url: str, headers: dict[str, str]):
            captured_headers.update(headers)
            return check_research_api_health.ProbeResult("", "ok", "request succeeded", 200)

        with patch.dict(os.environ, {"OPENALEX_API_KEY": "test-key"}, clear=True), \
                patch.object(check_research_api_health, "_request", side_effect=fake_request):
            result = check_research_api_health.probe_openalex()

        assert result.status == "ok"
        assert result.provider == "openalex"
        assert captured_headers.get("Authorization") == "Bearer test-key"


# ── 16. credential registry data file integrity ──────────────────────────────


class TestCredentialRegistryDataFile:
    """Verify the shipped registry CSV matches the new schema and placeholder state."""

    def test_registry_header_includes_validation_evidence_ids(self) -> None:
        registry_path = REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        with registry_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames is not None
            assert "validation_evidence_ids" in reader.fieldnames
            rows = list(reader)
        assert len(rows) == 9
        for row in rows:
            assert row["validation_status"] == "review_required"
            assert row["validation_evidence_ids"] == ""

    def test_registry_loads_with_empty_evidence_ids_tuple(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        registry_path = REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        entries = mod.load_registry(registry_path)
        assert len(entries) == 9
        assert all(entry.validation_evidence_ids == () for entry in entries)

    def test_shipped_registry_is_not_computable_without_evidence(self) -> None:
        """No entries in the shipped placeholder registry are validated-with-evidence,
        so H2 must remain not_computable until evidence is attached."""
        mod = _load_script("build_validated_credential_supply_map")
        registry_path = REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        entries = mod.load_registry(registry_path)
        payload = mod.compute_h2_supply_map(
            registry_entries=entries,
            demand_signals=[],
            registry_path=registry_path,
        )
        assert payload["validated_entries_hydronization_eqf_6_7"] == 0
        assert payload["interpretation"] == "not_computable"
