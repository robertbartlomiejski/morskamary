"""Layer 1 — Raw provider acquisition audit builder.

This module builds a deterministic, per-run audit bundle that preserves *raw*
provider acquisition separately from *normalized* evidence, in support of
PR-190 / Layer 1 of the live cumulative scientific database.

Design principles
-----------------
* **Additive, not intrusive.** This module reads the outputs already produced
  by ``scripts/export_live_research_records.py`` (which is intentionally NOT
  modified as part of this layer) and writes a new bundle under
  ``outputs/live_runs/<run_id>/`` alongside the existing
  ``outputs/research_sources/`` layout. The exporter's contract, the run
  archive layout, and every PR-186/187/189 safeguard remain intact.
* **Raw-vs-normalized separation at the directory level.** The bundle keeps
  raw provider rows (pre-merge, pre-triangulation) under ``raw/`` and the
  normalized/triangulated winners under ``normalized/``. This makes it
  possible for downstream layers (novelty gates, cumulative statistical
  database, statistical report) to prove that every normalized record
  descends from a raw acquisition observed during the same run.
* **Deterministic output.** Every JSON payload is written with sorted keys
  and stable indentation; every CSV row is sorted by a stable sort key; a
  SHA-256 checksum file is emitted for archive-integrity checks.
* **Layer 0 linkage.** When ``config/live_query_protocol.yml`` is available
  the audit maps every observed ``source_query`` string back to the Layer 0
  ``query_id`` / ``sector_slug`` / ``query_family`` / ``axis_target``, so
  that raw acquisition can be interrogated by protocol identity rather than
  by free-text query strings.

Public surface
--------------
* :class:`LiveRunAuditError` — raised for malformed input files
* :class:`LiveRunAuditBuilder` — orchestrates the build for one run
* :class:`LiveRunAuditResult` — frozen return type describing the bundle
* :class:`RawAcquisitionRow` — frozen row type for the acquisition index
* :func:`build_live_run_audit` — one-shot convenience entry point

The bundle written to ``outputs/live_runs/<run_id>/`` has this shape::

    outputs/live_runs/<run_id>/
        live_run_manifest.json          top-level manifest with file SHA-256s
        _checksums.sha256               deterministic <sha256>  <relpath> lines
        raw/
            raw_acquisition_index.csv   one row per (query_id, provider)
            raw_provider_records.json   copy of raw provider rows pre-merge
            raw_api_payloads/           copy of per-query envelopes (optional)
        normalized/
            live_records.json           copy of normalized winners
            live_provenance.json        copy of provenance rows
            live_source_coverage.csv    copy of coverage matrix
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from src.scientific_sources.live_query_protocol import (
    LiveQuery,
    LiveQueryProtocol,
    load_live_query_protocol,
)

__all__ = [
    "LiveRunAuditError",
    "LiveRunAuditBuilder",
    "LiveRunAuditResult",
    "RawAcquisitionRow",
    "build_live_run_audit",
    "AUDIT_MANIFEST_FILENAME",
    "AUDIT_CHECKSUMS_FILENAME",
    "RAW_ACQUISITION_INDEX_COLUMNS",
]

AUDIT_MANIFEST_FILENAME = "live_run_manifest.json"
AUDIT_CHECKSUMS_FILENAME = "_checksums.sha256"
AUDIT_SCHEMA_VERSION = "1.0.0"

RAW_ACQUISITION_INDEX_COLUMNS: Tuple[str, ...] = (
    "query_id",
    "sector_slug",
    "sector_label",
    "axis_target",
    "query_family",
    "provider",
    "query_text",
    "raw_record_count",
    "normalized_record_count",
    "unique_source_ids",
    "coverage_record_count",
    "has_raw_payload_envelope",
    "raw_payload_sha256",
    "raw_payload_captured_at",
    "protocol_binding",
)

_RAW_RECORDS_FILENAME = "raw_provider_records.json"
_NORMALIZED_RECORDS_FILENAME = "live_records.json"
_PROVENANCE_FILENAME = "live_provenance.json"
_COVERAGE_FILENAME = "live_source_coverage.csv"
_PAYLOAD_ENVELOPES_DIRNAME = "raw_api_payloads"


class LiveRunAuditError(ValueError):
    """Raised when live-run input files are missing or malformed."""


@dataclass(frozen=True)
class RawAcquisitionRow:
    """One entry in the raw acquisition index (query_id + provider)."""

    query_id: str
    sector_slug: str
    sector_label: str
    axis_target: str
    query_family: str
    provider: str
    query_text: str
    raw_record_count: int
    normalized_record_count: int
    unique_source_ids: int
    coverage_record_count: int
    has_raw_payload_envelope: bool
    raw_payload_sha256: str
    raw_payload_captured_at: str
    protocol_binding: str

    def as_csv_row(self) -> Dict[str, str]:
        return {
            "query_id": self.query_id,
            "sector_slug": self.sector_slug,
            "sector_label": self.sector_label,
            "axis_target": self.axis_target,
            "query_family": self.query_family,
            "provider": self.provider,
            "query_text": self.query_text,
            "raw_record_count": str(self.raw_record_count),
            "normalized_record_count": str(self.normalized_record_count),
            "unique_source_ids": str(self.unique_source_ids),
            "coverage_record_count": str(self.coverage_record_count),
            "has_raw_payload_envelope": "true" if self.has_raw_payload_envelope else "false",
            "raw_payload_sha256": self.raw_payload_sha256,
            "raw_payload_captured_at": self.raw_payload_captured_at,
            "protocol_binding": self.protocol_binding,
        }


@dataclass(frozen=True)
class LiveRunAuditResult:
    """Outcome of one bundle build."""

    run_id: str
    bundle_dir: Path
    raw_row_count: int
    normalized_row_count: int
    acquisition_rows: Tuple[RawAcquisitionRow, ...]
    files: Tuple[Tuple[str, str, int], ...] = field(default_factory=tuple)
    """Tuple of (relative_path, sha256_hex, size_bytes)."""

    def relative_files(self) -> List[str]:
        return [entry[0] for entry in self.files]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_run_id(value: str) -> str:
    """Reject run_ids that would escape the bundle root."""
    token = value.strip()
    if not token:
        raise LiveRunAuditError("run_id must be non-empty")
    cleaned = "".join(ch for ch in token if ch.isalnum() or ch in ("-", "_", "."))
    if not cleaned or cleaned != token:
        raise LiveRunAuditError(
            "run_id must only contain [A-Za-z0-9], '-', '_' or '.' characters"
        )
    if token.startswith(".") or ".." in token:
        raise LiveRunAuditError("run_id must not contain '.' prefix or '..' segments")
    return cleaned


def _read_json_list(path: Path, *, label: str) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise LiveRunAuditError(f"{label} not found at {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LiveRunAuditError(f"{label} at {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise LiveRunAuditError(
            f"{label} at {path} must be a JSON array; got {type(payload).__name__}"
        )
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise LiveRunAuditError(
                f"{label} at {path} contains non-object item at index {idx}"
            )
    return payload  # type: ignore[return-value]


def _read_coverage_csv(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: List[Dict[str, str]] = []
        for raw in reader:
            rows.append({k: (v or "").strip() for k, v in raw.items()})
    return rows


def _write_json_sorted(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _walk_files(root: Path) -> List[Path]:
    """Return a stably-sorted list of every file under *root*."""
    return sorted(p for p in root.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# core builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ProtocolIndex:
    """Fast lookups from the Layer 0 protocol into (query_text -> LiveQuery)."""

    by_text: Mapping[str, LiveQuery]
    protocol: LiveQueryProtocol

    @classmethod
    def from_protocol(cls, protocol: LiveQueryProtocol) -> "_ProtocolIndex":
        by_text: Dict[str, LiveQuery] = {}
        for query in protocol.all_queries():
            key = query.query_text.strip().lower()
            # First occurrence wins; the loader already rejects duplicate query_ids
            # so any collision here would come from two protocol queries sharing
            # identical text, which is legitimate (same phrasing across families).
            by_text.setdefault(key, query)
        return cls(by_text=by_text, protocol=protocol)

    def lookup(self, query_text: str) -> Optional[LiveQuery]:
        return self.by_text.get(query_text.strip().lower())


@dataclass
class LiveRunAuditBuilder:
    """Build the Layer 1 audit bundle for one run.

    Parameters
    ----------
    run_id:
        Deterministic identifier for the run being audited.
    research_sources_dir:
        Directory produced by :mod:`scripts.export_live_research_records` —
        typically ``outputs/research_sources``.
    output_root:
        Root under which ``<output_root>/<run_id>/`` will be created — typically
        ``outputs/live_runs``.
    protocol_path:
        Optional path to ``config/live_query_protocol.yml``. When provided
        (and when it loads successfully) raw queries are bound to Layer 0
        ``query_id`` / ``sector_slug`` / ``query_family`` / ``axis_target``.
        When absent or unparseable the bundle is still produced with
        ``protocol_binding = "unbound"``.
    workflow_context:
        Optional mapping of workflow metadata (e.g. github_run_id, commit_sha)
        that will be embedded verbatim inside ``live_run_manifest.json``.
    """

    run_id: str
    research_sources_dir: Path
    output_root: Path
    protocol_path: Optional[Path] = None
    workflow_context: Mapping[str, Any] = field(default_factory=dict)
    built_at_utc: Optional[str] = None
    """Optional frozen ISO-8601 timestamp. When set the manifest's
    ``built_at_utc`` field is deterministic across rebuilds (used by tests
    and by callers that want byte-identical bundles for archive integrity)."""

    def __post_init__(self) -> None:
        self.run_id = _safe_run_id(self.run_id)
        self.research_sources_dir = Path(self.research_sources_dir)
        self.output_root = Path(self.output_root)

    # ---- public entry point ------------------------------------------------

    def build(self) -> LiveRunAuditResult:
        """Assemble and write the bundle. Returns a result descriptor."""
        if not self.research_sources_dir.is_dir():
            raise LiveRunAuditError(
                f"research_sources_dir does not exist: {self.research_sources_dir}"
            )

        raw_records = _read_json_list(
            self.research_sources_dir / _RAW_RECORDS_FILENAME,
            label="raw_provider_records.json",
        )
        normalized_records = _read_json_list(
            self.research_sources_dir / _NORMALIZED_RECORDS_FILENAME,
            label="live_records.json",
        )
        provenance_rows = _read_json_list(
            self.research_sources_dir / _PROVENANCE_FILENAME,
            label="live_provenance.json",
        )
        coverage_rows = _read_coverage_csv(
            self.research_sources_dir / _COVERAGE_FILENAME
        )

        protocol_index = self._load_protocol_index()
        payload_envelopes = self._load_payload_envelope_index()

        acquisition_rows = self._build_acquisition_rows(
            raw_records=raw_records,
            normalized_records=normalized_records,
            coverage_rows=coverage_rows,
            protocol_index=protocol_index,
            payload_envelopes=payload_envelopes,
        )

        bundle_dir = self.output_root / self.run_id
        self._prepare_bundle_dir(bundle_dir)
        self._write_raw_side(bundle_dir, raw_records, acquisition_rows)
        self._write_normalized_side(
            bundle_dir, normalized_records, provenance_rows
        )
        self._copy_side_car_files(bundle_dir)

        manifest_files = self._collect_file_descriptors(bundle_dir)
        manifest = self._build_manifest(
            protocol_index=protocol_index,
            acquisition_rows=acquisition_rows,
            raw_records=raw_records,
            normalized_records=normalized_records,
            files=manifest_files,
        )
        # Write the manifest first, then compute its checksum and include it
        # in the checksums file. The manifest itself does NOT include its own
        # sha256 (only the sha256 of every other file), so re-hashing after
        # write yields a deterministic checksums line for the manifest.
        _write_json_sorted(bundle_dir / AUDIT_MANIFEST_FILENAME, manifest)
        checksum_entries = list(manifest_files) + [
            (
                AUDIT_MANIFEST_FILENAME,
                _sha256_file(bundle_dir / AUDIT_MANIFEST_FILENAME),
                (bundle_dir / AUDIT_MANIFEST_FILENAME).stat().st_size,
            )
        ]
        self._write_checksums_file(bundle_dir, checksum_entries)

        return LiveRunAuditResult(
            run_id=self.run_id,
            bundle_dir=bundle_dir,
            raw_row_count=len(raw_records),
            normalized_row_count=len(normalized_records),
            acquisition_rows=tuple(acquisition_rows),
            files=tuple(checksum_entries),
        )

    # ---- private helpers ---------------------------------------------------

    def _load_protocol_index(self) -> Optional[_ProtocolIndex]:
        if self.protocol_path is None:
            return None
        path = Path(self.protocol_path)
        if not path.is_file():
            return None
        try:
            protocol = load_live_query_protocol(path)
        except Exception:  # noqa: BLE001 — tolerate malformed protocol
            return None
        return _ProtocolIndex.from_protocol(protocol)

    def _load_payload_envelope_index(self) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """Map (provider_lower, query_text_lower) -> envelope dict."""
        envelopes_dir = self.research_sources_dir / _PAYLOAD_ENVELOPES_DIRNAME
        result: Dict[Tuple[str, str], Dict[str, Any]] = {}
        if not envelopes_dir.is_dir():
            return result
        for envelope_path in sorted(envelopes_dir.glob("*.json")):
            try:
                envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise LiveRunAuditError(
                    f"payload envelope {envelope_path} is not valid JSON: {exc}"
                ) from exc
            if not isinstance(envelope, dict):
                raise LiveRunAuditError(
                    f"payload envelope {envelope_path} must be a JSON object"
                )
            provider = str(envelope.get("provider", "")).strip().lower()
            query_text = str(envelope.get("query", "")).strip().lower()
            if not provider or not query_text:
                continue
            result[(provider, query_text)] = envelope
        return result

    def _build_acquisition_rows(
        self,
        *,
        raw_records: Sequence[Mapping[str, Any]],
        normalized_records: Sequence[Mapping[str, Any]],
        coverage_rows: Sequence[Mapping[str, str]],
        protocol_index: Optional[_ProtocolIndex],
        payload_envelopes: Mapping[Tuple[str, str], Mapping[str, Any]],
    ) -> List[RawAcquisitionRow]:
        raw_buckets: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
        for record in raw_records:
            key = (
                str(record.get("provider", "")).strip().lower(),
                str(record.get("source_query", "")).strip(),
            )
            raw_buckets.setdefault(key, []).append(record)

        normalized_buckets: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
        for record in normalized_records:
            # Normalized records inherit `source_query` and `provider` from the
            # provider row that produced them. When they additionally carry an
            # `evidence` list (as some downstream triangulators emit) each
            # evidence entry is counted independently against its own
            # (provider, query) key.
            base_key = (
                str(record.get("provider", "")).strip().lower(),
                str(record.get("source_query", "")).strip(),
            )
            if base_key != ("", ""):
                normalized_buckets.setdefault(base_key, []).append(record)
            evidence_list = record.get("evidence") if isinstance(record, Mapping) else None
            if isinstance(evidence_list, list):
                for evidence in evidence_list:
                    if not isinstance(evidence, Mapping):
                        continue
                    key = (
                        str(evidence.get("source_provider", "")).strip().lower(),
                        str(evidence.get("query", "")).strip(),
                    )
                    if key == ("", "") or key == base_key:
                        continue
                    normalized_buckets.setdefault(key, []).append(record)

        coverage_buckets: Dict[Tuple[str, str], int] = {}
        for row in coverage_rows:
            provider = row.get("provider", "").strip().lower()
            query = row.get("query", "").strip()
            try:
                count = int(row.get("record_count", "0") or "0")
            except ValueError:
                count = 0
            coverage_buckets[(provider, query)] = count

        # Emit one row per (provider, query_text) observed anywhere.
        keys: set[Tuple[str, str]] = set()
        keys.update(raw_buckets.keys())
        keys.update(normalized_buckets.keys())
        keys.update(coverage_buckets.keys())

        rows: List[RawAcquisitionRow] = []
        for provider, query_text in sorted(keys):
            raw_bucket = raw_buckets.get((provider, query_text), [])
            normalized_bucket = normalized_buckets.get((provider, query_text), [])
            coverage_count = coverage_buckets.get((provider, query_text), 0)
            envelope = payload_envelopes.get((provider, query_text.lower()))
            protocol_query = (
                protocol_index.lookup(query_text) if protocol_index is not None else None
            )

            unique_source_ids = len(
                {
                    str(rec.get("source_id", ""))
                    for rec in raw_bucket
                    if rec.get("source_id")
                }
            )

            if protocol_query is not None:
                query_id = protocol_query.query_id
                sector_slug = protocol_query.sector_slug
                sector_label = protocol_query.sector
                axis_target = protocol_query.axis_target.value
                query_family = protocol_query.query_family.value
                protocol_binding = "bound"
            else:
                query_id = _unbound_query_id(provider, query_text)
                sector_slug = ""
                sector_label = ""
                axis_target = ""
                query_family = ""
                protocol_binding = "unbound" if protocol_index is not None else "no_protocol"

            rows.append(
                RawAcquisitionRow(
                    query_id=query_id,
                    sector_slug=sector_slug,
                    sector_label=sector_label,
                    axis_target=axis_target,
                    query_family=query_family,
                    provider=provider,
                    query_text=query_text,
                    raw_record_count=len(raw_bucket),
                    normalized_record_count=len(normalized_bucket),
                    unique_source_ids=unique_source_ids,
                    coverage_record_count=coverage_count,
                    has_raw_payload_envelope=envelope is not None,
                    raw_payload_sha256=(
                        str(envelope.get("payload_sha256", "")) if envelope else ""
                    ),
                    raw_payload_captured_at=(
                        str(envelope.get("captured_at", "")) if envelope else ""
                    ),
                    protocol_binding=protocol_binding,
                )
            )
        return rows

    def _prepare_bundle_dir(self, bundle_dir: Path) -> None:
        if bundle_dir.exists():
            # Clear previous contents so the bundle is a byte-for-byte
            # regenerable artefact. The bundle root is `output_root/run_id`
            # where run_id has been sanitised, so this rmtree is safe.
            for child in sorted(bundle_dir.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        else:
            bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "raw").mkdir(parents=True, exist_ok=True)
        (bundle_dir / "normalized").mkdir(parents=True, exist_ok=True)

    def _write_raw_side(
        self,
        bundle_dir: Path,
        raw_records: Sequence[Mapping[str, Any]],
        acquisition_rows: Sequence[RawAcquisitionRow],
    ) -> None:
        _write_json_sorted(
            bundle_dir / "raw" / _RAW_RECORDS_FILENAME,
            list(raw_records),
        )
        self._write_acquisition_index(
            bundle_dir / "raw" / "raw_acquisition_index.csv",
            acquisition_rows,
        )

    def _write_normalized_side(
        self,
        bundle_dir: Path,
        normalized_records: Sequence[Mapping[str, Any]],
        provenance_rows: Sequence[Mapping[str, Any]],
    ) -> None:
        _write_json_sorted(
            bundle_dir / "normalized" / _NORMALIZED_RECORDS_FILENAME,
            list(normalized_records),
        )
        _write_json_sorted(
            bundle_dir / "normalized" / _PROVENANCE_FILENAME,
            list(provenance_rows),
        )

    def _copy_side_car_files(self, bundle_dir: Path) -> None:
        coverage_src = self.research_sources_dir / _COVERAGE_FILENAME
        if coverage_src.is_file():
            _copy_file(coverage_src, bundle_dir / "normalized" / _COVERAGE_FILENAME)
        envelopes_src = self.research_sources_dir / _PAYLOAD_ENVELOPES_DIRNAME
        if envelopes_src.is_dir():
            dst_dir = bundle_dir / "raw" / _PAYLOAD_ENVELOPES_DIRNAME
            dst_dir.mkdir(parents=True, exist_ok=True)
            for envelope_path in sorted(envelopes_src.glob("*.json")):
                _copy_file(envelope_path, dst_dir / envelope_path.name)

    def _write_acquisition_index(
        self,
        path: Path,
        acquisition_rows: Sequence[RawAcquisitionRow],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        sorted_rows = sorted(
            acquisition_rows,
            key=lambda r: (r.query_id, r.provider, r.query_text),
        )
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(RAW_ACQUISITION_INDEX_COLUMNS),
                lineterminator="\n",
            )
            writer.writeheader()
            for row in sorted_rows:
                writer.writerow(row.as_csv_row())

    def _collect_file_descriptors(
        self, bundle_dir: Path
    ) -> List[Tuple[str, str, int]]:
        """Return every file except the manifest itself (which is written last)."""
        descriptors: List[Tuple[str, str, int]] = []
        for path in _walk_files(bundle_dir):
            relative = path.relative_to(bundle_dir).as_posix()
            if relative in (AUDIT_MANIFEST_FILENAME, AUDIT_CHECKSUMS_FILENAME):
                continue
            descriptors.append((relative, _sha256_file(path), path.stat().st_size))
        return descriptors

    def _write_checksums_file(
        self,
        bundle_dir: Path,
        entries: Sequence[Tuple[str, str, int]],
    ) -> None:
        path = bundle_dir / AUDIT_CHECKSUMS_FILENAME
        sorted_entries = sorted(entries, key=lambda item: item[0])
        with path.open("w", encoding="utf-8", newline="") as handle:
            for relative, sha256, _size in sorted_entries:
                handle.write(f"{sha256}  {relative}\n")

    def _build_manifest(
        self,
        *,
        protocol_index: Optional[_ProtocolIndex],
        acquisition_rows: Sequence[RawAcquisitionRow],
        raw_records: Sequence[Mapping[str, Any]],
        normalized_records: Sequence[Mapping[str, Any]],
        files: Sequence[Tuple[str, str, int]],
    ) -> Dict[str, Any]:
        bound_query_ids = sorted(
            {
                row.query_id
                for row in acquisition_rows
                if row.protocol_binding == "bound"
            }
        )
        protocol_summary: Dict[str, Any]
        if protocol_index is None:
            protocol_summary = {
                "loaded": False,
                "path": None,
                "protocol_version": None,
                "declared_query_count": 0,
                "projected_query_count": 0,
                "observed_query_count": 0,
                "bound_query_ids": [],
                "family_counts": {},
                "sector_counts": {},
                "unbound_observations": [
                    row.query_text
                    for row in acquisition_rows
                    if row.protocol_binding == "no_protocol"
                ],
            }
        else:
            declared_ids = {q.query_id for q in protocol_index.protocol.all_queries()}
            family_counts: Dict[str, int] = {}
            sector_counts: Dict[str, int] = {}
            for family in protocol_index.protocol.query_families:
                family_counts[family.value] = 0
            for slug, sector in protocol_index.protocol.sectors.items():
                sector_counts[slug] = len(sector.queries)
                for query in sector.queries:
                    family_counts[query.query_family.value] = (
                        family_counts.get(query.query_family.value, 0) + 1
                    )
            protocol_summary = {
                "loaded": True,
                "path": (
                    str(self.protocol_path) if self.protocol_path is not None else None
                ),
                "protocol_version": protocol_index.protocol.protocol_version,
                "declared_query_count": len(declared_ids),
                "projected_query_count": len(protocol_index.protocol.flattened_query_texts()),
                "observed_query_count": len(bound_query_ids),
                "bound_query_ids": bound_query_ids,
                "family_counts": dict(sorted(family_counts.items())),
                "sector_counts": dict(sorted(sector_counts.items())),
                "unbound_observations": sorted(
                    {
                        row.query_text
                        for row in acquisition_rows
                        if row.protocol_binding == "unbound"
                    }
                ),
            }

        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "built_at_utc": self.built_at_utc or _now_utc_iso(),
            "source": {
                "research_sources_dir": str(self.research_sources_dir),
            },
            "counts": {
                "raw_records": len(raw_records),
                "normalized_records": len(normalized_records),
                "acquisition_rows": len(acquisition_rows),
                "raw_records_with_normalized_descendants": sum(
                    1 for row in acquisition_rows if row.normalized_record_count > 0
                ),
            },
            "protocol": protocol_summary,
            "workflow_context": dict(self.workflow_context) if self.workflow_context else {},
            "files": [
                {"path": rel, "sha256": sha, "size_bytes": size}
                for rel, sha, size in sorted(files, key=lambda item: item[0])
            ],
        }


def _unbound_query_id(provider: str, query_text: str) -> str:
    """Deterministic placeholder id for queries not present in the protocol."""
    digest = hashlib.sha256(
        f"{provider}|{query_text}".encode("utf-8")
    ).hexdigest()[:12]
    return f"unbound:{digest}"


# ---------------------------------------------------------------------------
# convenience entry point
# ---------------------------------------------------------------------------


def build_live_run_audit(
    run_id: str,
    research_sources_dir: Union[str, Path],
    output_root: Union[str, Path],
    *,
    protocol_path: Optional[Union[str, Path]] = None,
    workflow_context: Optional[Mapping[str, Any]] = None,
    built_at_utc: Optional[str] = None,
) -> LiveRunAuditResult:
    """One-shot builder invocation. See :class:`LiveRunAuditBuilder`."""
    builder = LiveRunAuditBuilder(
        run_id=run_id,
        research_sources_dir=Path(research_sources_dir),
        output_root=Path(output_root),
        protocol_path=Path(protocol_path) if protocol_path is not None else None,
        workflow_context=workflow_context or {},
        built_at_utc=built_at_utc,
    )
    return builder.build()
