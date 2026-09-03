#!/usr/bin/env python3
"""Build the evidence-level Morskamary sector/axis/realm analysis package."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence, cast

import pandas as pd
import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources.performative_demand_analysis import (  # noqa: E402
    AXES,
    AXIS_CODES,
    REALMS,
    build_performative_demand_analysis,
    build_unique_evidence_map,
    validate_evidence_identities,
)

DEFAULT_DATABASE = REPO_ROOT / "outputs" / "cumulative_database"
DEFAULT_OUTPUT = REPO_ROOT / "outputs" / "performative_demand_cross_axis"
DEFAULT_PROTOCOL = REPO_ROOT / "config" / "live_query_protocol.yml"
RUN_ID_ALIASES = ("current_run_id", "run_id")
ALLOWED_EVIDENCE_SURFACES = ("title", "subject_terms", "abstract", "full_text")
CHECKSUM_REQUIRED_INPUTS = (
    "derived_competence_demands.csv",
    "evidence_records.csv",
    "competence_demand_signals.csv",
    "cumulative_database_manifest.json",
    "layer4_manifest.json",
    "layer_readiness_report.json",
)
CHECKSUM_LINE_RE = re.compile(r"^([0-9a-f]{64})\s{2}(.+)$")
GIT_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


def _first_non_empty(*values: object) -> str | None:
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            return text
    return None


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    normalized = _normalize_json_value(payload)
    path.write_text(
        json.dumps(normalized, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, lineterminator="\n")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-dir", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--permutations", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=20_260_825)
    return parser.parse_args(argv)


def _tourism_case_table() -> pd.DataFrame:
    """Return external comparison-only H3 aggregate recoding as an explicit 4 x 4 table.

    This table is intentionally isolated as non-repository evidence and must not
    be interpreted as retained empirical support from the cumulative database.
    """
    title_counts = {
        "ECONOMY": 1,
        "TECHNOLOGY": 2,
        "POLICY_GOVERNANCE": 11,
        "CULTURE_LEARNING": 7,
    }
    rows: list[dict[str, object]] = []
    for axis in AXES:
        for realm in REALMS:
            rows.append(
                {
                    "sector": "coastal_tourism",
                    "axis_group": axis,
                    "axis_code": AXIS_CODES[axis],
                    "realm": realm,
                    "title_fragment_count": (
                        title_counts[realm] if axis == "OCEANIC" else 0
                    ),
                    "validated_demand_count": 0,
                    "validated_bridge_count": 0,
                    "evidence_surface": "title",
                    "manual_validation_status": "not_started",
                    "citation_needed": True,
                    "source_status": "comparison_data_not_repository_evidence",
                    "provenance_class": "external_comparison_only_not_repository_evidence",
                    "source_note": (
                        "aggregate realm recoding supplied outside retained repository "
                        "evidence; no retained citable source is available"
                    ),
                }
            )
    table = pd.DataFrame(rows)
    if int(table["title_fragment_count"].sum()) != 21:
        raise RuntimeError("coastal-tourism H3 case must contain 21 title fragments")
    return cast(pd.DataFrame, table)


def _write_long_matrix(
    matrix: pd.DataFrame,
    value_name: str,
    path: Path,
) -> None:
    long_series = cast(
        pd.Series,
        matrix.rename_axis(index="sector", columns="axis_group").stack(),
    )
    long_series.name = value_name
    long = long_series.reset_index()
    long["axis_code"] = long["axis_group"].map(AXIS_CODES)
    if long["axis_code"].isna().any():
        raise RuntimeError("matrix contains a non-canonical axis without axis_code")
    long = long[["sector", "axis_group", "axis_code", value_name]]
    _write_csv(long, path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_checksum_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeError(f"missing retained checksum manifest: {path}")
    checksums: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        match = CHECKSUM_LINE_RE.match(line)
        if not match:
            raise RuntimeError(
                f"malformed checksum entry at line {line_number} in {path.name}: {raw_line!r}"
            )
        digest, rel = match.group(1), match.group(2).strip()
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            # Keep existing legacy out-of-directory rows untouched, but they cannot
            # be used for retained-input validation.
            continue
        normalized_rel = rel_path.as_posix()
        if normalized_rel in checksums:
            raise RuntimeError(
                f"duplicate checksum entry for {normalized_rel!r} in {path.name}"
            )
        checksums[normalized_rel] = digest
    return checksums


def _verify_retained_inputs(database: Path) -> dict[str, str]:
    checksums = _parse_checksum_manifest(database / "_checksums.sha256")
    verified: dict[str, str] = {}
    for rel in CHECKSUM_REQUIRED_INPUTS:
        if rel not in checksums:
            raise RuntimeError(
                f"required retained input {rel!r} is missing from _checksums.sha256"
            )
        resolved = (database / rel).resolve()
        if not resolved.is_file():
            raise RuntimeError(f"required retained input file is missing: {database / rel}")
        if database.resolve() not in resolved.parents:
            raise RuntimeError(
                f"retained input path escapes database directory: {database / rel}"
            )
        actual = _sha256(resolved)
        expected = checksums[rel]
        if actual != expected:
            raise RuntimeError(
                f"retained input checksum mismatch for {rel}: expected {expected}, got {actual}"
            )
        verified[rel] = expected
    return verified


def _ensure_commit_available(commit: str) -> None:
    if subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
        capture_output=True,
    ).returncode == 0:
        return
    fetch = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "fetch", "--filter=blob:none", "origin", commit],
        check=False,
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        stderr = (fetch.stderr or "").strip()
        raise RuntimeError(
            f"unable to fetch retained protocol source commit {commit}: {stderr}"
        )
    if subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
        capture_output=True,
    ).returncode != 0:
        raise RuntimeError(
            f"retained protocol source commit is unavailable after fetch: {commit}"
        )


def _git_show_bytes(commit: str, path: str) -> bytes:
    _ensure_commit_available(commit)
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{commit}:{path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"unable to read retained protocol source {commit}:{path}: {stderr}"
        )
    return result.stdout


def _git_blob_id(commit: str, path: str) -> str:
    _ensure_commit_available(commit)
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", f"{commit}:{path}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(
            f"unable to resolve retained protocol blob id {commit}:{path}: {stderr}"
        )
    blob = result.stdout.strip()
    if not GIT_SHA1_RE.fullmatch(blob):
        raise RuntimeError(
            f"retained protocol blob id is invalid for {commit}:{path}: {blob!r}"
        )
    return blob


def _verified_protocol_identity(
    *,
    manifest: Mapping[str, Any],
    database: Path,
) -> tuple[dict[str, str], dict[str, Any]]:
    binding = manifest.get("protocol_binding")
    if not isinstance(binding, dict):
        raise RuntimeError(
            "cumulative_database_manifest.json is missing protocol_binding; "
            "retained snapshot must declare protocol binding/source identity metadata"
        )
    retained_protocol_artifact = str(binding.get("retained_protocol_artifact", "")).strip()
    source_commit = str(binding.get("source_commit", "")).strip()
    source_path = str(binding.get("source_path", "")).strip()
    source_blob_sha1 = str(binding.get("source_blob_sha1", "")).strip().lower()
    retained_protocol_version = str(binding.get("protocol_version", "")).strip()
    retained_protocol_sha256 = str(binding.get("protocol_sha256", "")).strip().lower()
    retained_protocol_path = str(binding.get("protocol_path", "")).strip()
    if not (
        retained_protocol_artifact
        and source_commit
        and source_path
        and source_blob_sha1
        and retained_protocol_path
        and retained_protocol_version
        and retained_protocol_sha256
    ):
        raise RuntimeError(
            "protocol_binding must include retained_protocol_artifact, source_commit, "
            "source_path, source_blob_sha1, protocol_path, protocol_version, and protocol_sha256"
        )
    if not GIT_SHA1_RE.fullmatch(source_commit):
        raise RuntimeError("protocol_binding.source_commit must be a 40-char hex git commit id")
    if not GIT_SHA1_RE.fullmatch(source_blob_sha1):
        raise RuntimeError("protocol_binding.source_blob_sha1 must be a 40-char hex git blob id")
    if not re.fullmatch(r"[0-9a-f]{64}", retained_protocol_sha256):
        raise RuntimeError("protocol_binding.protocol_sha256 must be a 64-char lowercase hex digest")
    if Path(source_path).is_absolute() or ".." in Path(source_path).parts:
        raise RuntimeError("protocol_binding.source_path must be a repository-relative safe path")
    if Path(retained_protocol_artifact).is_absolute() or ".." in Path(retained_protocol_artifact).parts:
        raise RuntimeError(
            "protocol_binding.retained_protocol_artifact must be a database-relative safe path"
        )

    workflow_context = manifest.get("workflow_context", {})
    source_sha_from_manifest = ""
    if isinstance(workflow_context, dict):
        source_sha_from_manifest = str(workflow_context.get("github_sha", "")).strip()
    if source_sha_from_manifest and source_sha_from_manifest != source_commit:
        raise RuntimeError(
            "protocol_binding.source_commit does not match cumulative manifest workflow_context.github_sha: "
            f"{source_commit} vs {source_sha_from_manifest}"
        )

    if source_path != retained_protocol_path:
        raise RuntimeError(
            "protocol_binding.source_path and protocol_path must match exactly for retained binding"
        )
    protocol_artifact_path = database / retained_protocol_artifact
    if not protocol_artifact_path.is_file():
        raise RuntimeError(f"retained protocol artifact is missing: {protocol_artifact_path}")
    if database.resolve() not in protocol_artifact_path.resolve().parents:
        raise RuntimeError(
            f"retained protocol artifact path escapes cumulative database dir: {protocol_artifact_path}"
        )
    artifact_bytes = protocol_artifact_path.read_bytes()
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    if artifact_sha256 != retained_protocol_sha256:
        raise RuntimeError(
            "retained protocol artifact digest mismatch: "
            f"expected {retained_protocol_sha256}, got {artifact_sha256}"
        )
    source_bytes = _git_show_bytes(source_commit, source_path)
    if source_bytes != artifact_bytes:
        raise RuntimeError(
            "retained protocol artifact bytes do not match recorded source commit/path"
        )
    resolved_source_blob_sha1 = _git_blob_id(source_commit, source_path)
    if resolved_source_blob_sha1 != source_blob_sha1:
        raise RuntimeError(
            "retained protocol source blob id mismatch: "
            f"expected {source_blob_sha1}, got {resolved_source_blob_sha1}"
        )
    protocol = yaml.safe_load(artifact_bytes.decode("utf-8"))
    protocol_version = str(protocol.get("protocol_version", "")).strip()
    if not protocol_version:
        raise RuntimeError("retained protocol artifact is missing protocol_version")
    if protocol_version != retained_protocol_version:
        raise RuntimeError(
            "retained protocol version mismatch: "
            f"artifact={protocol_version}, binding={retained_protocol_version}"
        )
    return ({
        "protocol_path": source_path,
        "protocol_version": retained_protocol_version,
        "protocol_sha256": retained_protocol_sha256,
        "retained_protocol_artifact": retained_protocol_artifact,
        "source_commit": source_commit,
        "source_path": source_path,
        "source_blob_sha1": source_blob_sha1,
        "verification_status": "verified_against_retained_snapshot",
    }, protocol)


@contextlib.contextmanager
def _staged_output_dir(output: Path) -> Iterator[Path]:
    """Build artifacts in an isolated staging directory, then promote atomically.

    Building directly into an existing output directory can leave stale or
    unrelated files (from a prior run, a manual edit, or a partially failed
    build) present alongside the newly generated artifacts, corrupting
    ``package_manifest.json`` file listing and checksum integrity. Writing
    into a fresh, empty staging directory and only promoting it to the final
    location on success guarantees the published package contains exactly
    the files this run generated.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".performative_demand_staging_", dir=str(output.parent))
    )
    try:
        yield staging
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    else:
        backup: Path | None = None
        if output.exists():
            backup = output.parent / f"{output.name}.stale_replaced"
            if backup.exists():
                shutil.rmtree(backup)
            output.rename(backup)
        staging.rename(output)
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)


def _source_provenance(
    database: Path,
    frames: Mapping[str, pd.DataFrame],
    *,
    verified_source_hashes: Mapping[str, str] | None = None,
    verified_protocol_identity: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return strict fail-closed lineage metadata from cumulative inputs.

    This is intentionally hard-fail coupled to lineage consistency. Build output
    publication must stop when run/classifier identity is ambiguous.
    """
    manifest_path = database / "cumulative_database_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(
            "cumulative database manifest is required for analysis provenance"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layer4_manifest_path = database / "layer4_manifest.json"
    if not layer4_manifest_path.exists():
        raise RuntimeError("layer4_manifest.json is required for analysis provenance")
    layer4_manifest = json.loads(layer4_manifest_path.read_text(encoding="utf-8"))
    layer_readiness_path = database / "layer_readiness_report.json"
    if not layer_readiness_path.exists():
        raise RuntimeError(
            "layer_readiness_report.json is required for analysis provenance"
        )
    layer_readiness = json.loads(layer_readiness_path.read_text(encoding="utf-8"))
    source_names = [
        "derived_competence_demands.csv",
        "evidence_records.csv",
        "competence_demand_signals.csv",
    ]
    observed: dict[str, dict[str, str]] = {}
    for table_name, frame in frames.items():
        for field in (*RUN_ID_ALIASES, "classifier_version"):
            if field not in frame.columns:
                continue
            values = {
                str(v).strip() for v in frame[field].dropna().tolist() if str(v).strip()
            }
            if len(values) > 1:
                raise RuntimeError(
                    f"{table_name} mixes multiple {field} values: {sorted(values)}"
                )
            if values:
                observed.setdefault(field, {})[table_name] = next(iter(values))
    for field, by_table in observed.items():
        values = set(by_table.values())
        if len(values) > 1:
            raise RuntimeError(f"input tables disagree on {field}: {sorted(values)}")

    run_id_values: set[str] = set()
    for alias in RUN_ID_ALIASES:
        run_id_values.update(observed.get(alias, {}).values())
        for source in (manifest, layer4_manifest):
            alias_value = str(source.get(alias, "")).strip()
            if alias_value:
                run_id_values.add(alias_value)
    if len(run_id_values) > 1:
        raise RuntimeError(
            "run lineage aliases conflict across cumulative inputs: "
            + ", ".join(sorted(run_id_values))
        )

    classifier_values: set[str] = set(observed.get("classifier_version", {}).values())
    for source in (manifest, layer4_manifest):
        classifier_value = str(source.get("classifier_version", "")).strip()
        if classifier_value:
            classifier_values.add(classifier_value)
    if len(classifier_values) > 1:
        raise RuntimeError(
            "classifier_version conflicts across cumulative inputs: "
            + ", ".join(sorted(classifier_values))
        )

    readiness_layers = layer_readiness.get("layers", [])
    if not isinstance(readiness_layers, list):
        raise RuntimeError("layer_readiness_report layers must be a list")
    if not readiness_layers:
        raise RuntimeError(
            "layer_readiness_report.json contains no usable layer entries; "
            "publication package cannot be built"
        )
    unusable_layers = [
        layer
        for layer in readiness_layers
        if not isinstance(layer, dict)
        or "usable_for_layer4" not in layer
        or not bool(layer.get("usable_for_layer4"))
    ]
    if unusable_layers:
        raise RuntimeError(
            "one or more layer_readiness_report.json entries are not usable for "
            "Layer 4; publication package cannot be built: "
            + json.dumps(unusable_layers, sort_keys=True)
        )
    cumulative_status = "layer_readiness_usable"
    workflow_context = manifest.get("workflow_context", {})
    generated_at = _first_non_empty(
        manifest.get("generated_at_utc"),
        manifest.get("built_at_utc"),
        layer4_manifest.get("built_at_utc"),
        layer_readiness.get("generated_at_utc"),
    )
    generated_by = _first_non_empty(
        manifest.get("generated_by"),
        cast(dict[str, Any], workflow_context).get("github_workflow")
        if isinstance(workflow_context, dict)
        else None,
    )
    qmbd_methodology = _first_non_empty(
        manifest.get("qmbd_assignment_methodology"),
        layer4_manifest.get("demand_strength_formula"),
    )
    evidence_map_for_provenance = build_unique_evidence_map(frames["demands"])
    evidence_rows = manifest.get("evidence_map_exact_rows")
    if evidence_rows is None:
        evidence_rows = int(len(evidence_map_for_provenance))
    records_in_database = manifest.get("records_in_database")
    if records_in_database is None:
        manifest_counts = manifest.get("counts", {})
        if isinstance(manifest_counts, dict):
            records_in_database = manifest_counts.get("evidence_records")
    if records_in_database is None:
        records_in_database = int(len(frames["evidence"]))

    required_scalar_fields = {
        "cumulative_manifest_generated_at_utc": generated_at,
        "cumulative_manifest_generated_by": generated_by,
        "qmbd_assignment_methodology": qmbd_methodology,
    }
    missing_required = [
        name for name, value in required_scalar_fields.items() if value is None
    ]
    if missing_required:
        raise RuntimeError(
            "required provenance fields are missing from authoritative cumulative inputs: "
            + ", ".join(sorted(missing_required))
        )

    return {
        "cumulative_manifest_schema_version": manifest.get("schema_version"),
        "cumulative_manifest_generated_at_utc": generated_at,
        "cumulative_manifest_generated_by": generated_by,
        "cumulative_manifest_status": _first_non_empty(
            manifest.get("status"), cumulative_status
        ),
        "qmbd_assignment_methodology": qmbd_methodology,
        "evidence_map_exact_rows": evidence_rows,
        "demand_profile_rows": manifest.get("demand_profile_rows", len(frames["demands"])),
        "joined_evidence_id_count": manifest.get(
            "joined_evidence_id_count",
            len(
                set(evidence_map_for_provenance["evidence_id"])
                & set(frames["evidence"]["evidence_id"])
            ),
        ),
        "records_in_database": records_in_database,
        "source_file_sha256": {
            name: (
                verified_source_hashes[name]
                if verified_source_hashes is not None and name in verified_source_hashes
                else _sha256(database / name)
            )
            for name in source_names
        },
        "protocol_identity": (
            dict(verified_protocol_identity)
            if verified_protocol_identity is not None
            else dict(manifest.get("protocol_binding", {}))
        ),
        "run_classifier_identity": {
            "status": (
                "verified_from_available_fields"
                if observed
                else "not_exposed_in_frozen_snapshot"
            ),
            "observed_fields": observed,
            "current_run_id": next(iter(run_id_values), None),
            "classifier_version": next(iter(classifier_values), None),
        },
        "lineage_validation_mode": "fail_closed",
    }


def _hypothesis_outcomes(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    reasons = {
        "H1": "this evidence-structure package does not recompute demand_strength_score effect sizes",
        "H2": "independently validated EQF 6-7 supply is unavailable in this package",
        "H3": "validated semantic translation bridges are unavailable in this package",
    }
    rows = []
    for hypothesis_id, config in protocol.get("hypotheses", {}).items():
        result_fields: dict[str, Any] = {
            str(field): None for field in config.get("required_result_fields", [])
        }
        result_fields["hypothesis_id"] = hypothesis_id
        result_fields["hypothesis_label"] = config.get("label")
        result_fields["interpretation"] = reasons.get(
            hypothesis_id, "required evidence is outside this package"
        )
        rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "hypothesis_label": config.get("label"),
                "definition": config.get("definition"),
                "test": config.get("test"),
                "direction": config.get("direction"),
                "required_axes": config.get("required_axes", []),
                "declared_outcomes": config.get("declared_outcomes", []),
                "status": "not_computable",
                "result_fields": result_fields,
                "warning": reasons.get(
                    hypothesis_id, "required evidence is outside this package"
                ),
            }
        )
    return rows


def _write_governance_artifacts(
    output: Path, protocol: Mapping[str, Any], source_provenance: Mapping[str, Any]
) -> None:
    _write_json(
        output / "validity_threats.json",
        {
            "package_scope": "deterministic_corpus_screening_not_validated_performativity_or_supply_gap",
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
                "deduplicated evidence IDs are corpus units, not iid observations",
                "a linked evidence identity can support multiple demand work packages and screening paths",
                "semantic signals require exact-span human validation",
                "multi-label screening is not an independent-event design",
            ],
            "reproducibility_contract": {
                "scientific_invariants": [
                    "canonical four-axis contract",
                    "configured hypothesis serialization with not_computable when required evidence is absent",
                    "strict provenance lineage consistency",
                ],
                "packaging_identity": [
                    "byte-for-byte artifact determinism for governed output files",
                    "checksum parity between package_manifest and artifact bytes",
                ],
                "consumer_read_order": [
                    "read validity_threats.json and value_labels.json before interpreting screening tables",
                    "treat sector/axis/realm CSV files as deterministic corpus-screening diagnostics only",
                ],
            },
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
            "analysis_scope_label": "deterministic_screening_only_not_validated",
            "zero_interpretation": "not observed in declared screening state, not absent in reality",
            "supply_gap_status": "not_computable_no_independent_supply",
            "consumer_warning": (
                "screening outputs are deterministic corpus diagnostics; they are not "
                "validated demand, validated translation, validated performativity, or "
                "independently validated supply prevalence"
            ),
        },
    )
    _write_json(output / "hypothesis_outcomes.json", _hypothesis_outcomes(protocol))
    _write_json(
        output / "package_schema.json",
        {
            "schema_version": "1.0",
            "package_scope": "deterministic_corpus_screening_not_validated_performativity_or_supply_gap",
            "axis_contract": {"canonical_names": list(AXES), "axis_codes": AXIS_CODES},
            "allowed_semantic_surfaces": list(ALLOWED_EVIDENCE_SURFACES),
            "review_status_enum": ["review_required", "rejected"],
            "artifacts": {
                "sector_axis_observed.csv": [
                    "sector",
                    "axis_group",
                    "axis_code",
                    "observed_evidence_count",
                ],
                "sector_axis_expected.csv": [
                    "sector",
                    "axis_group",
                    "axis_code",
                    "expected_evidence_count",
                ],
                "sector_axis_residuals.csv": [
                    "sector",
                    "sector_label",
                    "axis_group",
                    "axis_code",
                    "observed_evidence_count",
                    "expected_evidence_count",
                    "adjusted_standardized_residual",
                    "raw_cell_p",
                    "holm_p",
                    "bh_p",
                    "holm_significant_0_05",
                    "bh_significant_0_05",
                    "cell_status",
                ],
                "sector_axis_screening_features.csv": [
                    "sector",
                    "axis_group",
                    "axis_code",
                    "evidence_surface",
                    "screening_validation_state",
                ],
                "sector_axis_realm_screening.csv": [
                    "sector",
                    "axis_group",
                    "axis_code",
                    "evidence_surface",
                    "realm",
                    "screening_validation_state",
                ],
                "axis_screening_feature_shares.csv": [
                    "axis_group",
                    "axis_code",
                    "evidence_surface",
                    "feature",
                ],
                "sector_screening_profile.csv": [
                    "sector",
                    "dominant_axis",
                    "dominant_axis_code",
                    "screening_validation_state",
                ],
                "linked_evidence_sector_axis_lineage.csv": [
                    "evidence_id",
                    "sector",
                    "axis_group",
                    "axis_code",
                ],
                "external_comparison_coastal_tourism_axis_realm_case.csv": [
                    "sector",
                    "axis_group",
                    "axis_code",
                    "realm",
                    "citation_needed",
                    "source_status",
                    "provenance_class",
                ],
            },
        },
    )
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
            "package_scope": "deterministic_corpus_screening_not_validated_performativity_or_supply_gap",
            "protocol_version": protocol.get("protocol_version"),
            "source_provenance": source_provenance,
            "files": files,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    database = args.database_dir
    retained_hashes = _verify_retained_inputs(database)
    manifest = json.loads(
        (database / "cumulative_database_manifest.json").read_text(encoding="utf-8")
    )
    verified_protocol_identity, protocol = _verified_protocol_identity(
        manifest=manifest, database=database
    )
    sector_labels = {
        sector: str(config["label"]) for sector, config in protocol["sectors"].items()
    }
    demands = pd.read_csv(database / "derived_competence_demands.csv")
    evidence = pd.read_csv(database / "evidence_records.csv")
    signals = pd.read_csv(database / "competence_demand_signals.csv")
    validate_evidence_identities(evidence)
    source_provenance = _source_provenance(
        database,
        {"demands": demands, "evidence": evidence, "signals": signals},
        verified_source_hashes=retained_hashes,
        verified_protocol_identity=verified_protocol_identity,
    )

    analysis = build_performative_demand_analysis(
        demands,
        evidence,
        signals,
        sector_labels,
        permutations=args.permutations,
        seed=args.seed,
    )
    output = args.output_dir
    with _staged_output_dir(output) as staging:
        _write_long_matrix(
            analysis.observed,
            "observed_evidence_count",
            staging / "sector_axis_observed.csv",
        )
        _write_long_matrix(
            analysis.expected,
            "expected_evidence_count",
            staging / "sector_axis_expected.csv",
        )
        _write_csv(analysis.residuals, staging / "sector_axis_residuals.csv")
        _write_csv(
            analysis.sector_axis_features, staging / "sector_axis_screening_features.csv"
        )
        _write_csv(analysis.sector_axis_realms, staging / "sector_axis_realm_screening.csv")
        _write_csv(analysis.axis_features, staging / "axis_screening_feature_shares.csv")
        _write_csv(analysis.sector_profile, staging / "sector_screening_profile.csv")
        lineage = analysis.evidence_map.copy()
        lineage["axis_code"] = lineage["axis_group"].map(AXIS_CODES)
        lineage = lineage[["evidence_id", "sector", "axis_group", "axis_code"]]
        _write_csv(
            lineage.sort_values(["evidence_id", "sector", "axis_group"]),
            staging / "linked_evidence_sector_axis_lineage.csv",
        )
        _write_csv(
            _tourism_case_table(),
            staging / "external_comparison_coastal_tourism_axis_realm_case.csv",
        )
        summary = dict(analysis.summary)
        summary["source_provenance"] = source_provenance
        _write_json(staging / "statistics_summary.json", summary)
        _write_governance_artifacts(staging, protocol, source_provenance)
    print(
        json.dumps(
            _normalize_json_value(summary),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
