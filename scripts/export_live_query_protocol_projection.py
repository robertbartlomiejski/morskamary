#!/usr/bin/env python3
"""Export deterministic legacy `query_groups` projection from live protocol."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scientific_sources.live_query_protocol import (  # noqa: E402
    LiveQueryProtocolError,
    LiveQueryProtocol,
    load_live_query_protocol,
    validate_complete_authoritative_protocol_projection,
    validate_legacy_projection_matches_protocol,
)


def _path_exists(path: Path) -> bool:
    """Return whether a regular path or dangling symlink is present."""
    return path.exists() or path.is_symlink()


def _unlink_if_present(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _stage_bytes_artifact(destination: Path, content: bytes) -> Path:
    """Write one artifact beside its destination without publishing it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".stage",
        dir=str(destination.parent),
    )
    stage_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        _unlink_if_present(stage_path)
        raise
    return stage_path


def _reserve_rollback_path(destination: Path) -> Path:
    """Reserve a same-directory backup path for an existing artifact."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".rollback",
        dir=str(destination.parent),
        text=True,
    )
    os.close(descriptor)
    return Path(temporary_name)


def _rollback_published_artifacts(
    published_paths: Sequence[Path], backups: Mapping[Path, Path]
) -> None:
    """Restore prior outputs and remove newly created outputs after a failure."""
    rollback_errors: List[OSError] = []
    for destination in reversed(published_paths):
        try:
            _unlink_if_present(destination)
        except OSError as exc:
            rollback_errors.append(exc)

    for destination, backup_path in reversed(list(backups.items())):
        if not _path_exists(backup_path):
            continue
        try:
            os.replace(backup_path, destination)
        except OSError as exc:
            rollback_errors.append(exc)

    if rollback_errors:
        raise OSError(
            "could not completely roll back staged protocol-projection publication"
        ) from rollback_errors[0]


def _record_secondary_failure(
    original_error: BaseException, secondary_error: BaseException, operation: str
) -> None:
    """Preserve the triggering failure while retaining rollback diagnostics."""
    if sys.version_info >= (3, 11):
        original_error.add_note(  # type: ignore[attr-defined]
            f"{operation} also failed: {secondary_error}"
        )


def _publish_staged_text_artifacts(
    artifacts: Sequence[Tuple[Path, bytes]],
    validate_staged: Callable[[Mapping[Path, Path]], None],
) -> None:
    """Validate and publish artifacts as a rollback-safe group.

    A filesystem cannot atomically replace multiple files at once.  This
    protocol stages and validates every byte first, moves existing outputs to
    same-directory backups, and restores them if any later replacement fails.
    """
    destinations = [destination for destination, _ in artifacts]
    resolved_destinations = [path.resolve() for path in destinations]
    if len(set(resolved_destinations)) != len(resolved_destinations):
        raise ValueError("staged protocol-projection artifacts must use distinct paths")

    staged_paths: Dict[Path, Path] = {}
    backups: Dict[Path, Path] = {}
    reserved_backups: List[Path] = []
    published_paths: List[Path] = []
    publication_succeeded = False
    publication_error: BaseException | None = None

    try:
        for destination, content in artifacts:
            staged_paths[destination] = _stage_bytes_artifact(destination, content)

        validate_staged(staged_paths)

        for destination in destinations:
            if not _path_exists(destination):
                continue
            backup_path = _reserve_rollback_path(destination)
            reserved_backups.append(backup_path)
            os.replace(destination, backup_path)
            backups[destination] = backup_path

        for destination in destinations:
            os.replace(staged_paths[destination], destination)
            published_paths.append(destination)
        publication_succeeded = True
    except BaseException as exc:
        publication_error = exc
        if backups or published_paths:
            try:
                _rollback_published_artifacts(published_paths, backups)
            except BaseException as rollback_error:
                _record_secondary_failure(exc, rollback_error, "rollback")
        raise
    finally:
        for stage_path in staged_paths.values():
            try:
                _unlink_if_present(stage_path)
            except OSError as cleanup_error:
                if publication_error is None:
                    raise
                _record_secondary_failure(publication_error, cleanup_error, "cleanup")
        for backup_path in reserved_backups:
            if publication_succeeded or backup_path not in backups.values():
                try:
                    _unlink_if_present(backup_path)
                except OSError as cleanup_error:
                    if publication_error is None:
                        raise
                    _record_secondary_failure(
                        publication_error, cleanup_error, "cleanup"
                    )


def _validate_serialized_projection_artifacts(
    *,
    protocol: LiveQueryProtocol,
    protocol_path: Path,
    output_path: Path,
    summary_path: Path,
    constraints_path: Path,
    projection: Mapping[str, Any],
    summary: Mapping[str, Any],
    constraints_payload: Mapping[str, Any],
    projection_bytes: bytes,
    summary_bytes: bytes,
    constraints_bytes: bytes,
) -> None:
    """Validate final UTF-8 artifact bytes before any destination is changed."""
    try:
        projection_from_bytes = yaml.safe_load(projection_bytes.decode("utf-8")) or {}
        summary_from_bytes = json.loads(summary_bytes)
        constraints_from_bytes = json.loads(constraints_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError("serialized protocol artifacts are not valid UTF-8 payloads") from exc

    if projection_from_bytes != projection:
        raise ValueError("serialized protocol projection differs from its source payload")
    if summary_from_bytes != summary:
        raise ValueError("serialized protocol summary differs from its source payload")
    if constraints_from_bytes != constraints_payload:
        raise ValueError(
            "serialized protocol constraints differ from their source payload"
        )

    validate_legacy_projection_matches_protocol(protocol, projection_from_bytes)
    validate_complete_authoritative_protocol_projection(protocol, constraints_from_bytes)

    all_queries = protocol.all_queries()
    expected_family_counts = Counter(
        query.query_family.value for query in all_queries
    )
    expected_sector_counts = {
        slug: len(sector.queries) for slug, sector in protocol.sectors.items()
    }
    expected_summary = {
        "protocol_path": str(protocol_path),
        "projection_path": str(output_path),
        "protocol_query_count": len(all_queries),
        "projected_query_count": len(protocol.flattened_query_texts()),
        "family_counts": dict(sorted(expected_family_counts.items())),
        "sector_counts": dict(sorted(expected_sector_counts.items())),
        "constraints_path": str(constraints_path),
    }
    if summary != expected_summary:
        raise ValueError("protocol summary is not consistent with the projection")
    resolved_paths = {
        output_path.resolve(),
        summary_path.resolve(),
        constraints_path.resolve(),
    }
    if len(resolved_paths) != 3:
        raise ValueError("protocol artifact paths must be distinct")
    if constraints_payload.get("query_count") != summary["protocol_query_count"]:
        raise ValueError("protocol constraints and summary have different query counts")


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project config/live_query_protocol.yml into legacy query_groups YAML."
    )
    parser.add_argument(
        "--protocol-path",
        default="config/live_query_protocol.yml",
        help="Path to authoritative live protocol YAML.",
    )
    parser.add_argument(
        "--output-path",
        default="outputs/research_sources/research_queries_from_protocol.yml",
        help="Path for generated legacy query_groups projection.",
    )
    parser.add_argument(
        "--min-total-queries",
        type=int,
        default=120,
        help="Fail unless the protocol declares exactly this many executable queries.",
    )
    parser.add_argument(
        "--emit-summary-path",
        default="outputs/research_sources/research_queries_from_protocol_summary.json",
        help="JSON summary output path for protocol/projection counts.",
    )
    parser.add_argument(
        "--emit-constraints-path",
        default="outputs/research_sources/query_protocol_constraints.json",
        help=(
            "JSON path for the per-query protocol constraints log "
            "(time_window, sort_strategy, sampling_strategy).  "
            "Consumed by the Layer 1 audit bundle to record applied vs "
            "unsupported filters."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    protocol = load_live_query_protocol(args.protocol_path)
    projection = protocol.to_legacy_query_groups()
    validate_legacy_projection_matches_protocol(protocol, projection)

    all_queries = protocol.all_queries()
    if len(all_queries) != args.min_total_queries:
        raise LiveQueryProtocolError(
            f"protocol query count {len(all_queries)} must equal required "
            f"scientific count {args.min_total_queries}: exact protocol count mismatch"
        )

    output_path = Path(args.output_path)
    family_counts = Counter(q.query_family.value for q in all_queries)
    sector_counts = {slug: len(sector.queries) for slug, sector in protocol.sectors.items()}
    summary_path = Path(args.emit_summary_path)
    constraints_path = Path(args.emit_constraints_path)
    summary = {
        "protocol_path": str(Path(args.protocol_path)),
        "projection_path": str(output_path),
        "protocol_query_count": len(all_queries),
        "projected_query_count": len(protocol.flattened_query_texts()),
        "family_counts": dict(sorted(family_counts.items())),
        "sector_counts": dict(sorted(sector_counts.items())),
    }

    # Record per-query constraints so downstream audit bundles can identify
    # which time_window, sort_strategy and sampling_strategy values were
    # declared versus applied by individual provider adapters.
    constraints = protocol.to_query_constraints()
    constraints_payload = {
        "protocol_version": protocol.protocol_version,
        "query_count": len(constraints),
        "queries": constraints,
    }
    validate_complete_authoritative_protocol_projection(protocol, constraints_payload)

    summary["constraints_path"] = str(constraints_path)

    projection_bytes = yaml.safe_dump(
        projection, sort_keys=False, allow_unicode=True
    ).encode("utf-8")
    summary_bytes = (json.dumps(summary, indent=2) + "\n").encode("utf-8")
    constraints_bytes = (
        json.dumps(constraints_payload, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    _validate_serialized_projection_artifacts(
        protocol=protocol,
        protocol_path=Path(args.protocol_path),
        output_path=output_path,
        summary_path=summary_path,
        constraints_path=constraints_path,
        projection=projection,
        summary=summary,
        constraints_payload=constraints_payload,
        projection_bytes=projection_bytes,
        summary_bytes=summary_bytes,
        constraints_bytes=constraints_bytes,
    )

    def validate_staged(staged_paths: Mapping[Path, Path]) -> None:
        try:
            staged_projection_bytes = staged_paths[output_path].read_bytes()
            staged_summary_bytes = staged_paths[summary_path].read_bytes()
            staged_constraints_bytes = staged_paths[constraints_path].read_bytes()
        except OSError as exc:
            raise ValueError("could not read staged protocol artifacts") from exc
        _validate_serialized_projection_artifacts(
            protocol=protocol,
            protocol_path=Path(args.protocol_path),
            output_path=output_path,
            summary_path=summary_path,
            constraints_path=constraints_path,
            projection=projection,
            summary=summary,
            constraints_payload=constraints_payload,
            projection_bytes=staged_projection_bytes,
            summary_bytes=staged_summary_bytes,
            constraints_bytes=staged_constraints_bytes,
        )

    _publish_staged_text_artifacts(
        (
            (output_path, projection_bytes),
            (summary_path, summary_bytes),
            (constraints_path, constraints_bytes),
        ),
        validate_staged,
    )

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LiveQueryProtocolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
