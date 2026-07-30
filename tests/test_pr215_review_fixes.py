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

    def test_parse_args_empty_list_uses_defaults(self) -> None:
        """An explicit empty list must still yield the documented defaults."""
        mod = _load_script("build_run_stability_report")
        args = mod.parse_args([])
        assert args.archive_root == "outputs/run_archive"
        assert args.output_path == "outputs/run_stability_report.json"
        assert args.jaccard_threshold == 0.85
        assert args.provisional_transitions == 2


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

    def test_duplicate_query_ids_collapse_via_set_semantics(self) -> None:
        """Repeated query_id values must not change the resulting hash."""
        mod = _load_script("build_run_stability_report")
        constraints = {
            "protocol_version": "1.0.0",
            "queries": [
                {"query_id": "Q001", "time_window": {}, "sampling_strategy": {}},
                {"query_id": "Q001", "time_window": {}, "sampling_strategy": {}},
                {"query_id": "Q002", "time_window": {}, "sampling_strategy": {}},
            ],
        }
        result = mod._normalize_query_constraints(constraints)
        expected_hash = hashlib.sha256(
            ",".join(sorted({"Q001", "Q002"})).encode("utf-8")
        ).hexdigest()
        assert result["query_id_hash"] == expected_hash

    def test_no_queries_yields_empty_query_id_hash(self) -> None:
        mod = _load_script("build_run_stability_report")
        result = mod._normalize_query_constraints(
            {"protocol_version": "1.0.0", "queries": []}
        )
        assert result["query_id_hash"] == ""

    def test_build_comparability_fingerprint_defaults_hash_to_unknown(self) -> None:
        """Omitting query_id_hash must fall back to the literal 'unknown' marker
        so pre-fix archived runs remain distinguishable from populated ones."""
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

    def test_non_static_recovery_run_is_not_excluded(self, tmp_path: Path) -> None:
        """A run without the static-recovery flag must still be loaded normally."""
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

    def test_static_recovery_false_is_not_excluded(self, tmp_path: Path) -> None:
        """An explicit False flag must be treated the same as absence."""
        mod = _load_script("build_run_stability_report")
        archive_root = tmp_path / "archive"
        run_dir = archive_root / "runs" / "run-explicit-false"
        run_dir.mkdir(parents=True)
        _write_json(
            run_dir / "manifest.json",
            {"run_id": "run-explicit-false", "is_static_recovery_mode": False},
        )
        ref = mod.RunReference(
            run_id="run-explicit-false",
            run_path="runs/run-explicit-false",
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

    def test_parse_evidence_ids_splits_and_filters_blank_tokens(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("EVD-1|EVD-2") == ("EVD-1", "EVD-2")
        assert mod._parse_evidence_ids("  EVD-1 | | EVD-2  ") == ("EVD-1", "EVD-2")
        assert mod._parse_evidence_ids("") == ()
        assert mod._parse_evidence_ids(None) == ()
        assert mod._parse_evidence_ids("|||") == ()


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

    def test_probe_returns_ok_and_sends_bearer_header_when_key_present(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import check_research_api_health

        captured_headers: dict[str, str] = {}

        def fake_request(url: str, headers: dict[str, str]):
            captured_headers.update(headers)
            return check_research_api_health.ProbeResult(
                "", "ok", "request succeeded", 200
            )

        with (
            patch.dict(os.environ, {"OPENALEX_API_KEY": "test-key-123"}, clear=True),
            patch(
                "check_research_api_health._request", side_effect=fake_request
            ),
        ):
            result = check_research_api_health.probe_openalex()

        assert result.status == "ok"
        assert result.provider == "openalex"
        assert captured_headers.get("Authorization") == "Bearer test-key-123"


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

    def test_strip_abstract_fields_passthrough_for_non_dict(self) -> None:
        from src.scientific_sources.openalex import _strip_abstract_fields

        assert _strip_abstract_fields("not a dict") == "not a dict"
        assert _strip_abstract_fields(None) is None
        assert _strip_abstract_fields([1, 2, 3]) == [1, 2, 3]

    def test_strip_abstract_fields_removes_top_level_index_without_results(self) -> None:
        """A single work object (e.g. DOI-verification payload) has no
        'results' wrapper; the top-level key must still be stripped."""
        from src.scientific_sources.openalex import _strip_abstract_fields

        payload = {
            "id": "W1",
            "title": "Solo work",
            "abstract_inverted_index": {"the": [0, 5]},
        }
        cleaned = _strip_abstract_fields(payload)
        assert "abstract_inverted_index" not in cleaned
        assert cleaned["title"] == "Solo work"

    def test_search_raw_payload_excludes_abstract_index(self) -> None:
        """Regression: OpenAlexProvider.search() must persist a stripped
        raw_payload, not the original response containing abstracts."""
        from src.scientific_sources.openalex import OpenAlexProvider

        provider = OpenAlexProvider()
        response = {
            "meta": {"count": 1},
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "Test Article",
                    "publication_year": 2024,
                    "doi": "https://doi.org/10.5555/test.1",
                    "authorships": [],
                    "abstract_inverted_index": {"the": [0]},
                }
            ],
        }

        def mock_backoff(*, url: str, context_label: str):
            del url, context_label
            return response, [], None

        with patch.object(
            provider, "_request_json_with_backoff", side_effect=mock_backoff
        ):
            result = provider.search("test", max_results=1)

        assert "abstract_inverted_index" not in result.raw_payload["results"][0]
        assert result.raw_payload["results"][0]["id"] == "https://openalex.org/W1"

    def test_verify_doi_raw_payload_excludes_top_level_abstract_index(self) -> None:
        from src.scientific_sources.openalex import OpenAlexProvider

        provider = OpenAlexProvider()
        work = {
            "id": "https://openalex.org/W1",
            "display_name": "Test Article",
            "publication_year": 2024,
            "doi": "https://doi.org/10.5555/test.1",
            "authorships": [],
            "abstract_inverted_index": {"the": [0]},
        }

        def mock_backoff(*, url: str, context_label: str):
            del url, context_label
            return work, [], None

        with patch.object(
            provider, "_request_json_with_backoff", side_effect=mock_backoff
        ):
            result = provider.verify_doi("10.5555/test.1")

        assert "abstract_inverted_index" not in result.raw_payload
        assert result.raw_payload["id"] == "https://openalex.org/W1"


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

    def test_redacted_path_hides_full_directory_tree(self) -> None:
        """Only the basename may survive redaction; no intermediate runner
        filesystem directory names should leak into the persisted artifact."""
        mod = _load_script("build_validated_credential_supply_map")
        deep_path = Path(
            "/var/lib/runner/_work/some-repo/tmp/secret_dir/registry.csv"
        )
        result = mod._repo_relative_posix(deep_path)
        assert result == "<redacted>/registry.csv"
        assert "secret_dir" not in result
        assert "_work" not in result
        assert "some-repo" not in result


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

    def test_blank_constraint_protocol_version_is_accepted(self) -> None:
        """An empty/absent protocol_version in constraints must not be
        treated as a mismatch (older artifacts may omit the field)."""
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
        # Should not raise.
        validate_complete_authoritative_protocol_projection(protocol, constraints)

    def test_query_count_mismatch_is_rejected(self) -> None:
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
            "queries": protocol.to_query_constraints()[:-1],
        }
        with pytest.raises(LiveQueryProtocolError, match="query count mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_queries_not_a_list_is_rejected(self) -> None:
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
            "queries": "not-a-list",
        }
        with pytest.raises(LiveQueryProtocolError, match="'queries' list"):
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
        bad_constraints = {"protocol_version": protocol.protocol_version}
        with pytest.raises(LiveQueryProtocolError, match="'queries' list"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

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
        bad_constraints["queries"][0]["query_id"] = "UNKNOWN_QUERY_ID_NOT_IN_PROTOCOL"
        with pytest.raises(LiveQueryProtocolError, match="unknown query_id"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_sector_slug_mismatch_is_rejected(self) -> None:
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
        bad_constraints["queries"][0]["sector_slug"] = "not_a_real_sector_slug"
        with pytest.raises(LiveQueryProtocolError, match="sector_slug.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_query_family_mismatch_is_rejected(self) -> None:
        from src.scientific_sources.live_query_protocol import (
            LiveQueryFamily,
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
        replacement = next(
            f.value for f in LiveQueryFamily if f.value != original_family
        )
        bad_constraints["queries"][0]["query_family"] = replacement
        with pytest.raises(LiveQueryProtocolError, match="query_family.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_query_text_mismatch_is_rejected(self) -> None:
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
        bad_constraints["queries"][0]["query_text"] = "definitely not the original text"
        with pytest.raises(LiveQueryProtocolError, match="query_text.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_sort_strategy_mismatch_is_rejected(self) -> None:
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
            "crossref": "wrong-strategy",
            "scopus": "wrong-strategy",
            "wos": "wrong-strategy",
        }
        with pytest.raises(LiveQueryProtocolError, match="sort_strategy.*mismatch"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

    def test_sampling_strategy_mismatch_is_rejected(self) -> None:
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

    def test_h2_map_step_declares_id_and_continue_on_error(self) -> None:
        """The H2 map step must expose a stable step id and tolerate its own
        failure so a missing/invalid registry never fails the whole run."""
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

    def test_h2_map_step_sets_has_validated_supply_env_var(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        h2_step = next(
            s for s in steps
            if s.get("name") == "Build preliminary H2 credential supply map"
        )
        assert "HAS_VALIDATED_SUPPLY" in h2_step["run"]
        assert "GITHUB_ENV" in h2_step["run"]

    def test_rebuild_layer5_step_is_conditional_on_has_validated_supply(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        rebuild_step = next(
            s for s in steps
            if s.get("name") == "Rebuild Layer 5 with validated supply map"
        )
        assert rebuild_step.get("if") == "env.HAS_VALIDATED_SUPPLY == 'true'"
        assert (
            "--validated-supply-map outputs/h2_credential_supply_map.json"
            in rebuild_step["run"]
        )

    def test_rebuild_layer5_step_immediately_follows_h2_map_step(self) -> None:
        """Ordering matters: the rebuild step must consume the artifact the
        H2 map step just produced, before any downstream gate evaluation."""
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        h2_idx = step_names.index("Build preliminary H2 credential supply map")
        rebuild_idx = step_names.index("Rebuild Layer 5 with validated supply map")
        novelty_idx = step_names.index("Evaluate live novelty gates (A-E)")
        assert rebuild_idx == h2_idx + 1
        assert rebuild_idx < novelty_idx


# ── 10. manifest and registry data integrity ──────────────────────────────────


class TestManifestAndRegistryDataIntegrity:
    """Data-file regressions accompanying this PR's code changes."""

    def test_manifest_sources_lists_this_test_file(self) -> None:
        manifest_path = REPO_ROOT / "MANIFEST_SOURCES.csv"
        with manifest_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        matching = [
            row for row in rows if row and row[0] == "tests/test_pr215_review_fixes.py"
        ]
        assert len(matching) == 1
        assert matching[0][1] == "script"

    def test_registry_csv_has_validation_evidence_ids_column(self) -> None:
        registry_path = (
            REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        )
        with registry_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            assert reader.fieldnames is not None
            assert "validation_evidence_ids" in reader.fieldnames
            rows = list(reader)
        assert rows, "registry must contain at least one placeholder entry"
        for row in rows:
            assert row["validation_evidence_ids"] == "", (
                "placeholder registry rows must not carry evidence ids"
            )

    def test_real_registry_loads_and_is_not_computable_without_evidence(self) -> None:
        """The shipped registry has zero validated+evidenced entries, so the
        H2 supply map must resolve to not_computable end-to-end."""
        mod = _load_script("build_validated_credential_supply_map")
        registry_path = (
            REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        )
        entries = mod.load_registry(registry_path)
        assert entries
        assert all(not entry.validation_evidence_ids for entry in entries)

        payload = mod.compute_h2_supply_map(registry_entries=entries, demand_signals=[])
        assert payload["interpretation"] == "not_computable"
        assert payload["validated_covered_demand_count"] == 0
