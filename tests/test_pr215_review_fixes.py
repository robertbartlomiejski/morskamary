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

    def test_parse_args_explicit_empty_list_uses_defaults_not_sys_argv(self) -> None:
        """An explicit empty list must still mean 'no args', not fall through
        to sys.argv (distinguishing argv=[] from argv=None)."""
        mod = _load_script("build_run_stability_report")
        with patch.object(
            sys, "argv", ["prog", "--archive-root", "/tmp/should-not-be-used"]
        ):
            args = mod.parse_args([])
        assert args.archive_root == "outputs/run_archive"


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

    def test_normalize_query_constraints_hash_is_order_independent(self) -> None:
        """query_id_hash must depend only on the set of query_ids, not order."""
        mod = _load_script("build_run_stability_report")
        forward = mod._normalize_query_constraints(
            {"queries": [{"query_id": "Q001"}, {"query_id": "Q002"}]}
        )
        backward = mod._normalize_query_constraints(
            {"queries": [{"query_id": "Q002"}, {"query_id": "Q001"}]}
        )
        assert forward["query_id_hash"] == backward["query_id_hash"]

    def test_normalize_query_constraints_no_query_ids_yields_empty_hash(self) -> None:
        mod = _load_script("build_run_stability_report")
        result = mod._normalize_query_constraints(
            {"queries": [{"time_window": {}}, {"time_window": {}}]}
        )
        assert result["query_id_hash"] == ""

    def test_normalize_query_constraints_missing_queries_key(self) -> None:
        mod = _load_script("build_run_stability_report")
        result = mod._normalize_query_constraints({"protocol_version": "1.0.0"})
        assert result["query_id_hash"] == ""
        assert result["query_protocol_version"] == "1.0.0"

    def test_build_comparability_fingerprint_defaults_query_id_hash_to_unknown(
        self,
    ) -> None:
        mod = _load_script("build_run_stability_report")
        _, payload = mod.build_comparability_fingerprint(
            providers_used=["crossref"],
            query_protocol_version="1.0.0",
            time_windows=[],
            sampling_strategies=[],
        )
        assert payload["query_id_hash"] == "unknown"


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

    def test_normal_run_without_static_recovery_flag_is_not_excluded(
        self, tmp_path: Path
    ) -> None:
        """Regression guard: the new manifest check must not reject ordinary runs."""
        mod = _load_script("build_run_stability_report")
        archive_root = tmp_path / "archive"
        run_dir = archive_root / "runs" / "normal-run"
        run_dir.mkdir(parents=True)
        _write_json(
            run_dir / "manifest.json",
            {"run_id": "normal-run", "is_static_recovery_mode": False},
        )
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

    def test_run_without_static_recovery_key_at_all_is_not_excluded(
        self, tmp_path: Path
    ) -> None:
        mod = _load_script("build_run_stability_report")
        archive_root = tmp_path / "archive"
        run_dir = archive_root / "runs" / "no-key-run"
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "manifest.json", {"run_id": "no-key-run"})
        ref = mod.RunReference(
            run_id="no-key-run",
            run_path="runs/no-key-run",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            archived_at="2026-01-01T00:00:00+00:00",
        )
        from src.axis_classifier import AxisClassifier

        result = mod.load_run_snapshot(archive_root, ref, AxisClassifier())
        assert result is not None


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

    def test_validated_with_evidence_is_computable(self) -> None:
        """Positive counterpart: validated entries WITH evidence IDs must count."""
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
                    "credential_name": "Test Credential Governance",
                    "eqf_level": 7,
                    "issuing_body": "Test",
                    "country_iso": "EU",
                    "axis_coverage": "HYDRONIZATION",
                    "validation_status": "validated",
                    "source_url": "",
                    "validation_evidence_ids": "EVD-100",
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
                    "learning_outcome_candidate": "Test credential governance",
                }) + "\n",
                encoding="utf-8",
            )

            payload = mod.compute_h2_supply_map(
                registry_entries=mod.load_registry(reg_path),
                demand_signals=mod.load_demand_signals(sig_path),
            )
            assert payload["validated_entries_hydronization_eqf_6_7"] == 1
            assert payload["interpretation"] != "not_computable"

    def test_parse_evidence_ids_splits_pipe_and_strips_whitespace(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids(" EVD-1 | EVD-2 |EVD-3") == (
            "EVD-1",
            "EVD-2",
            "EVD-3",
        )

    def test_parse_evidence_ids_filters_empty_tokens(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("EVD-1||  |EVD-2") == ("EVD-1", "EVD-2")

    def test_parse_evidence_ids_blank_input_returns_empty_tuple(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("") == ()
        assert mod._parse_evidence_ids(None) == ()


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

    def test_probe_returns_missing_without_making_http_request(self) -> None:
        """Absent key must short-circuit before any network call is attempted."""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import check_research_api_health

        with patch.dict(os.environ, {}, clear=True), patch.object(
            check_research_api_health, "_request"
        ) as mock_request:
            check_research_api_health.probe_openalex()
        mock_request.assert_not_called()

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

        with patch.dict(
            os.environ, {"OPENALEX_API_KEY": "secret-key-123"}, clear=True
        ), patch.object(check_research_api_health, "_request", side_effect=fake_request):
            result = check_research_api_health.probe_openalex()

        assert captured["headers"] == {"Authorization": "Bearer secret-key-123"}
        assert result.provider == "openalex"
        assert result.status == "ok"


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

    def test_strip_abstract_fields_removes_top_level_key(self) -> None:
        """A single-work payload (e.g. verify_doi) has abstract_inverted_index
        at the top level, not nested under 'results'."""
        from src.scientific_sources.openalex import _strip_abstract_fields

        payload = {
            "id": "W1",
            "title": "Test",
            "abstract_inverted_index": {"the": [0]},
        }
        cleaned = _strip_abstract_fields(payload)
        assert "abstract_inverted_index" not in cleaned
        assert cleaned["title"] == "Test"

    def test_strip_abstract_fields_passthrough_for_non_dict(self) -> None:
        from src.scientific_sources.openalex import _strip_abstract_fields

        assert _strip_abstract_fields(None) is None
        assert _strip_abstract_fields("raw string") == "raw string"
        assert _strip_abstract_fields([1, 2, 3]) == [1, 2, 3]

    def test_strip_abstract_fields_does_not_mutate_original_payload(self) -> None:
        from src.scientific_sources.openalex import _strip_abstract_fields

        original = {"abstract_inverted_index": {"a": [0]}, "title": "Test"}
        _strip_abstract_fields(original)
        assert "abstract_inverted_index" in original


# ── 7. redact out-of-repo paths ──────────────────────────────────────────────


class TestPathRedaction:
    """Thread: 'Redact absolute input paths from credential artifacts'."""

    def test_out_of_repo_path_is_redacted(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        result = mod._repo_relative_posix(Path("/tmp/external/registry.csv"))
        assert not result.startswith("/tmp")
        assert "registry.csv" in result

    def test_out_of_repo_path_redaction_is_exact_and_hides_directory_structure(
        self,
    ) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        result = mod._repo_relative_posix(
            Path("/home/runner/secret-org/private-repo/registry.csv")
        )
        assert result == "<redacted>/registry.csv"
        assert "secret-org" not in result
        assert "private-repo" not in result
        assert "runner" not in result

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

    def test_missing_queries_key_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryProtocolError,
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        with pytest.raises(LiveQueryProtocolError, match="must contain a 'queries' list"):
            validate_complete_authoritative_protocol_projection(
                protocol, {"protocol_version": protocol.protocol_version}
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
        truncated_constraints = {
            "protocol_version": protocol.protocol_version,
            "queries": protocol.to_query_constraints()[:-1],
        }
        with pytest.raises(LiveQueryProtocolError, match="query count mismatch"):
            validate_complete_authoritative_protocol_projection(
                protocol, truncated_constraints
            )

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
        bad_constraints["queries"][0]["query_id"] = "NONEXISTENT_QUERY_ID"
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
        bad_constraints["queries"][0]["query_text"] = "stale query text"
        with pytest.raises(LiveQueryProtocolError, match="query_text.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_stale_sort_strategy_is_rejected(self) -> None:
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
        bad_constraints["queries"][0]["sort_strategy"] = {
            "crossref": "bogus", "scopus": "bogus", "wos": "bogus",
        }
        with pytest.raises(LiveQueryProtocolError, match="sort_strategy.*mismatch"):
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

    def test_stale_sector_slug_is_rejected(self) -> None:
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
        bad_constraints["queries"][0]["sector_slug"] = "nonexistent-sector"
        with pytest.raises(LiveQueryProtocolError, match="sector_slug.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_stale_query_family_is_rejected(self) -> None:
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
        original_family = bad_constraints["queries"][0]["query_family"]
        replacement = "core_sector" if original_family != "core_sector" else "theory_translation"
        bad_constraints["queries"][0]["query_family"] = replacement
        with pytest.raises(LiveQueryProtocolError, match="query_family.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_blank_constraint_protocol_version_does_not_raise(self) -> None:
        """An empty/absent protocol_version in constraints should be tolerated
        (falsy check), since only a *declared but mismatched* version is fatal."""
        from src.scientific_sources.live_query_protocol import (
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        constraints = {
            "protocol_version": "",
            "queries": protocol.to_query_constraints(),
        }
        validate_complete_authoritative_protocol_projection(protocol, constraints)


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

    def test_rebuild_layer5_step_is_conditional_on_validated_supply_env(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        rebuild_step = next(
            s for s in steps if s.get("name") == "Rebuild Layer 5 with validated supply map"
        )
        assert rebuild_step.get("if") == "env.HAS_VALIDATED_SUPPLY == 'true'"
        assert "--validated-supply-map outputs/h2_credential_supply_map.json" in rebuild_step["run"]

    def test_h2_supply_map_step_has_id_and_sets_has_validated_supply_env(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        h2_step = next(
            s for s in steps if s.get("name") == "Build preliminary H2 credential supply map"
        )
        assert h2_step.get("id") == "h2_map"
        assert "HAS_VALIDATED_SUPPLY" in h2_step["run"]
        assert "validated_entries_hydronization_eqf_6_7" in h2_step["run"]

    def test_h2_supply_map_step_precedes_rebuild_layer5_step(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        h2_idx = step_names.index("Build preliminary H2 credential supply map")
        rebuild_idx = step_names.index("Rebuild Layer 5 with validated supply map")
        assert h2_idx < rebuild_idx


# ── 10. real credential_supply_registry.csv parses with new schema ───────────


class TestRealCredentialRegistrySchema:
    """Thread: 'Add validation_evidence_ids column to the registry schema'."""

    def test_real_registry_file_loads_with_validation_evidence_ids_column(
        self,
    ) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        entries = mod.load_registry(
            REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        )
        assert len(entries) == 9
        for entry in entries:
            # All current placeholder rows have no evidence attached yet.
            assert entry.validation_evidence_ids == ()
            assert entry.validation_status == "review_required"

    def test_real_registry_produces_not_computable_supply_map(self) -> None:
        """With no validated+evidenced entries, H2 must remain not_computable."""
        mod = _load_script("build_validated_credential_supply_map")
        entries = mod.load_registry(
            REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        )
        payload = mod.compute_h2_supply_map(
            registry_entries=entries,
            demand_signals=[],
        )
        assert payload["validated_entries_hydronization_eqf_6_7"] == 0
        assert payload["interpretation"] == "not_computable"
