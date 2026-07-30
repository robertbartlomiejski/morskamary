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

    def test_normalize_query_constraints_empty_queries_yields_empty_hash(self) -> None:
        mod = _load_script("build_run_stability_report")
        result = mod._normalize_query_constraints({"protocol_version": "1.0.0"})
        assert result["query_id_hash"] == ""

    def test_load_run_snapshot_propagates_query_id_hash_into_fingerprint(
        self, tmp_path: Path
    ) -> None:
        """End-to-end: a run's on-disk constraints file must flow through to
        the snapshot's fingerprint payload query_id_hash."""
        mod = _load_script("build_run_stability_report")
        archive_root = tmp_path / "archive"
        run_dir = archive_root / "runs" / "run-a"
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "manifest.json", {"run_id": "run-a"})
        constraints = {
            "protocol_version": "1.0.0",
            "queries": [
                {"query_id": "Q_ALPHA", "time_window": {}, "sampling_strategy": {}},
                {"query_id": "Q_BETA", "time_window": {}, "sampling_strategy": {}},
            ],
        }
        _write_json(
            run_dir / "research_sources" / "query_protocol_constraints.json",
            constraints,
        )
        ref = mod.RunReference(
            run_id="run-a",
            run_path="runs/run-a",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            archived_at="2026-01-01T00:00:00+00:00",
        )
        from src.axis_classifier import AxisClassifier

        snapshot = mod.load_run_snapshot(archive_root, ref, AxisClassifier())
        assert snapshot is not None
        expected_hash = hashlib.sha256(
            ",".join(sorted(["Q_ALPHA", "Q_BETA"])).encode("utf-8")
        ).hexdigest()
        assert snapshot.fingerprint_payload["query_id_hash"] == expected_hash

    def test_load_run_snapshot_without_static_recovery_flag_is_included(
        self, tmp_path: Path
    ) -> None:
        """Contrast case for the static-recovery exclusion: an ordinary run
        manifest (flag absent) must still be loaded."""
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

    def test_static_recovery_flag_explicitly_false_is_included(
        self, tmp_path: Path
    ) -> None:
        mod = _load_script("build_run_stability_report")
        archive_root = tmp_path / "archive"
        run_dir = archive_root / "runs" / "live-run"
        run_dir.mkdir(parents=True)
        _write_json(
            run_dir / "manifest.json",
            {"run_id": "live-run", "is_static_recovery_mode": False},
        )
        ref = mod.RunReference(
            run_id="live-run",
            run_path="runs/live-run",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            archived_at="2026-01-01T00:00:00+00:00",
        )
        from src.axis_classifier import AxisClassifier

        result = mod.load_run_snapshot(archive_root, ref, AxisClassifier())
        assert result is not None
        assert result.run_id == "live-run"


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


class TestParseEvidenceIds:
    """Thread: 'Require explicit validation evidence before including supply'
    (unit coverage for the pipe-delimited evidence-id parser)."""

    def test_single_id_parsed(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("EVD-001") == ("EVD-001",)

    def test_multiple_ids_split_on_pipe(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("EVD-001|EVD-002") == ("EVD-001", "EVD-002")

    def test_whitespace_around_ids_is_trimmed(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids(" EVD-001 | EVD-002 ") == ("EVD-001", "EVD-002")

    def test_blank_value_yields_empty_tuple(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("") == ()

    def test_none_value_yields_empty_tuple(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids(None) == ()

    def test_empty_tokens_between_pipes_are_filtered(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        assert mod._parse_evidence_ids("EVD-001||EVD-002|") == ("EVD-001", "EVD-002")


class TestRealRegistryHasNoValidatedEvidence:
    """Regression guard: the checked-in placeholder registry must remain
    entirely `review_required` with no evidence ids until credentials are
    genuinely validated, so H2 stays 'not_computable' by default."""

    def test_shipped_registry_produces_not_computable(self) -> None:
        mod = _load_script("build_validated_credential_supply_map")
        registry_path = (
            REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        )
        entries = mod.load_registry(registry_path)
        assert entries, "expected at least one registry row"
        assert all(entry.validation_status == "review_required" for entry in entries)
        assert all(entry.validation_evidence_ids == () for entry in entries)

        payload = mod.compute_h2_supply_map(
            registry_entries=entries,
            demand_signals=[],
            registry_path=registry_path,
        )
        assert payload["validated_entries_hydronization_eqf_6_7"] == 0
        assert payload["interpretation"] == "not_computable"

    def test_shipped_registry_has_validation_evidence_ids_column(self) -> None:
        registry_path = (
            REPO_ROOT / "data" / "validated" / "credential_supply_registry.csv"
        )
        with registry_path.open("r", encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle))
        assert "validation_evidence_ids" in header


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

    def test_strip_abstract_fields_is_idempotent_on_missing_key(self) -> None:
        from src.scientific_sources.openalex import _strip_abstract_fields

        payload = {"results": [{"id": "W1", "title": "No abstract here"}]}
        cleaned = _strip_abstract_fields(payload)
        assert cleaned == payload

    def test_strip_abstract_fields_passes_through_non_dict(self) -> None:
        from src.scientific_sources.openalex import _strip_abstract_fields

        assert _strip_abstract_fields(None) is None
        assert _strip_abstract_fields("not a dict") == "not a dict"

    def test_search_raw_payload_has_abstract_stripped(self) -> None:
        """Integration: OpenAlexProvider.search() must persist a raw_payload
        with abstract_inverted_index removed from every result item."""
        from src.scientific_sources.openalex import OpenAlexProvider

        provider = OpenAlexProvider()
        response = {
            "meta": {"count": 1, "page": 1, "per_page": 1},
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "display_name": "Test Article",
                    "publication_year": 2024,
                    "doi": "https://doi.org/10.5555/test.1",
                    "authorships": [],
                    "primary_location": {"source": {"display_name": "Journal"}},
                    "cited_by_count": 1,
                    "topics": [],
                    "keywords": [],
                    "abstract_inverted_index": {"secret": [0]},
                }
            ],
        }

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list, None]:
            del url, context_label
            return response, [], None

        with patch.object(
            provider, "_request_json_with_backoff", side_effect=mock_backoff
        ):
            result = provider.search("test", max_results=1)

        assert len(result.records) == 1
        assert "abstract_inverted_index" not in result.raw_payload["results"][0]
        assert result.raw_payload["results"][0]["id"] == "https://openalex.org/W1"

    def test_verify_doi_raw_payload_has_abstract_stripped(self) -> None:
        """Integration: OpenAlexProvider.verify_doi() must persist a raw_payload
        with abstract_inverted_index removed."""
        from src.scientific_sources.openalex import OpenAlexProvider

        provider = OpenAlexProvider()
        work = {
            "id": "https://openalex.org/W2",
            "display_name": "Verified Article",
            "publication_year": 2023,
            "doi": "https://doi.org/10.1234/verify",
            "authorships": [],
            "primary_location": {"source": {"display_name": "Journal"}},
            "cited_by_count": 3,
            "topics": [],
            "keywords": [],
            "abstract_inverted_index": {"hidden": [0, 1]},
        }

        def mock_backoff(*, url: str, context_label: str) -> tuple[dict, list, None]:
            del url, context_label
            return work, [], None

        with patch.object(
            provider, "_request_json_with_backoff", side_effect=mock_backoff
        ):
            result = provider.verify_doi("10.1234/verify")

        assert len(result.records) == 1
        assert "abstract_inverted_index" not in result.raw_payload


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

    def test_missing_protocol_version_is_accepted(self) -> None:
        """An empty/absent protocol_version constraint must not fail closed,
        since some historical constraint artifacts predate the field."""
        from src.scientific_sources.live_query_protocol import (
            load_live_query_protocol,
            validate_complete_authoritative_protocol_projection,
        )

        protocol = load_live_query_protocol(
            REPO_ROOT / "config" / "live_query_protocol.yml"
        )
        constraints = {"queries": protocol.to_query_constraints()}
        # Should not raise.
        validate_complete_authoritative_protocol_projection(protocol, constraints)

    def test_non_list_queries_is_rejected(self) -> None:
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
        with pytest.raises(LiveQueryProtocolError, match="must contain a 'queries' list"):
            validate_complete_authoritative_protocol_projection(protocol, bad_constraints)

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
        with pytest.raises(LiveQueryProtocolError, match="constraints query count mismatch"):
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
            "queries": protocol.to_query_constraints()[:-1]
            + [{**protocol.to_query_constraints()[-1], "query_id": "Q_DOES_NOT_EXIST"}],
        }
        with pytest.raises(LiveQueryProtocolError, match="unknown query_id"):
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
            "crossref": "wrong",
            "scopus": "wrong",
            "wos": "wrong",
        }
        with pytest.raises(LiveQueryProtocolError, match="sort_strategy.*mismatch"):
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

    def test_h2_map_step_has_stable_id(self) -> None:
        """The H2 supply map step must expose id `h2_map` so the env var it
        sets (HAS_VALIDATED_SUPPLY) is unambiguously attributable."""
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        h2_step = next(
            s for s in steps if s.get("name") == "Build preliminary H2 credential supply map"
        )
        assert h2_step.get("id") == "h2_map"
        assert h2_step.get("continue-on-error") is True

    def test_rebuild_layer5_step_is_gated_on_has_validated_supply_env(self) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        rebuild_step = next(
            s for s in steps if s.get("name") == "Rebuild Layer 5 with validated supply map"
        )
        assert rebuild_step.get("if") == "env.HAS_VALIDATED_SUPPLY == 'true'"
        assert "--validated-supply-map outputs/h2_credential_supply_map.json" in (
            rebuild_step.get("run", "")
        )

    def test_h2_map_step_precedes_rebuild_layer5_which_precedes_novelty_gates(
        self,
    ) -> None:
        import yaml  # type: ignore[import-untyped]

        wf_path = REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        steps = wf["jobs"]["live-analysis"]["steps"]
        step_names = [s.get("name", "") for s in steps]
        h2_idx = step_names.index("Build preliminary H2 credential supply map")
        rebuild_idx = step_names.index("Rebuild Layer 5 with validated supply map")
        gates_idx = step_names.index("Evaluate live novelty gates (A-E)")
        assert h2_idx < rebuild_idx < gates_idx


class TestHasValidatedSupplyEnvLogic:
    """Thread: 'Only rebuild Layer 5 when the supply map has real evidence'.

    Extracts the inline Python snippet the workflow uses to derive
    HAS_VALIDATED_SUPPLY from the H2 map JSON and executes it directly,
    guarding against regressions in that embedded logic.
    """

    @staticmethod
    def _extract_snippet() -> str:
        import re
        import textwrap

        wf_text = (
            REPO_ROOT / ".github" / "workflows" / "full-live-analysis.yml"
        ).read_text(encoding="utf-8")
        match = re.search(r'python -c "\n(.*?)\n\s*"\)', wf_text, re.DOTALL)
        assert match, "expected inline HAS_VALIDATED python snippet in workflow"
        return textwrap.dedent(match.group(1))

    def _run_snippet(self, tmp_path: Path, map_payload: dict) -> str:
        import subprocess

        (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "outputs" / "h2_credential_supply_map.json").write_text(
            json.dumps(map_payload), encoding="utf-8"
        )
        snippet = self._extract_snippet()
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def test_prints_true_when_validated_entries_present(self, tmp_path: Path) -> None:
        output = self._run_snippet(
            tmp_path, {"validated_entries_hydronization_eqf_6_7": 3}
        )
        assert output == "true"

    def test_prints_false_when_validated_entries_zero(self, tmp_path: Path) -> None:
        output = self._run_snippet(
            tmp_path, {"validated_entries_hydronization_eqf_6_7": 0}
        )
        assert output == "false"

    def test_prints_false_when_key_absent(self, tmp_path: Path) -> None:
        output = self._run_snippet(tmp_path, {"interpretation": "not_computable"})
        assert output == "false"
