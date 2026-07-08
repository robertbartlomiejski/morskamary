#!/usr/bin/env python3
"""Ingest manually uploaded supporting sources into an append-only ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator
from zipfile import ZipFile

DEFAULT_LEDGER_DIR = Path("outputs/manual_sources")
LEDGER_FILENAME = "manual_sources_ledger.jsonl"
INDEX_FILENAME = "manual_sources_index.csv"
REPORT_FILENAME = "manual_sources_ingest_report.json"
FILES_DIRNAME = "files"
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json"}
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".zip",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_bytes(payload: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(payload)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _iter_input_files(paths: Iterable[Path]) -> Iterator[Path]:
    for token in paths:
        path = token.expanduser().resolve()
        if not path.exists():
            print(f"WARNING: missing input path: {path}", file=sys.stderr)
            continue
        if path.is_file():
            if _is_supported_file(path):
                yield path
            continue
        if path.is_dir():
            for file_path in path.rglob("*"):
                if file_path.is_file() and _is_supported_file(file_path):
                    yield file_path


def _canonical_source_id(sha256: str) -> str:
    return f"manual_src_{sha256[:16]}"


def _load_existing_ledger(
    ledger_path: Path,
) -> tuple[list[dict[str, str]], set[str], set[str]]:
    rows: list[dict[str, str]] = []
    seen_sha: set[str] = set()
    seen_ids: set[str] = set()
    if not ledger_path.exists():
        return rows, seen_sha, seen_ids
    with ledger_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            item = json.loads(payload)
            if not isinstance(item, dict):
                continue
            cast_item = {str(k): str(v) for k, v in item.items()}
            rows.append(cast_item)
            if cast_item.get("sha256"):
                seen_sha.add(cast_item["sha256"])
            if cast_item.get("source_id"):
                seen_ids.add(cast_item["source_id"])
    return rows, seen_sha, seen_ids


def _write_index_csv(path: Path, rows: list[dict[str, str]]) -> None:
    columns = (
        "source_id",
        "ingested_at_utc",
        "source_kind",
        "file_name",
        "extension",
        "size_bytes",
        "sha256",
        "text_available",
        "original_path",
        "zip_member_path",
        "stored_path",
        "archive_sha256",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(rows)


def _store_binary_copy(
    *,
    source_id: str,
    extension: str,
    payload: bytes,
    files_dir: Path,
) -> str:
    files_dir.mkdir(parents=True, exist_ok=True)
    suffix = (
        extension if extension.startswith(".") else f".{extension}" if extension else ""
    )
    target = files_dir / f"{source_id}{suffix.lower()}"
    if not target.exists():
        target.write_bytes(payload)
    return target.as_posix()


def _build_row(
    *,
    source_kind: str,
    file_name: str,
    extension: str,
    size_bytes: int,
    sha256: str,
    original_path: str,
    zip_member_path: str,
    stored_path: str,
) -> dict[str, str]:
    return {
        "source_id": _canonical_source_id(sha256),
        "ingested_at_utc": _utc_now(),
        "source_kind": source_kind,
        "file_name": file_name,
        "extension": extension.lower(),
        "size_bytes": str(size_bytes),
        "sha256": sha256,
        "text_available": "yes" if extension.lower() in TEXT_EXTENSIONS else "no",
        "original_path": original_path,
        "zip_member_path": zip_member_path,
        "stored_path": stored_path,
    }


def ingest_manual_sources(
    *,
    inputs: list[Path],
    ledger_dir: Path,
    copy_files: bool,
) -> int:
    ledger_dir = ledger_dir.resolve()
    ledger_path = ledger_dir / LEDGER_FILENAME
    index_path = ledger_dir / INDEX_FILENAME
    report_path = ledger_dir / REPORT_FILENAME
    files_dir = ledger_dir / FILES_DIRNAME

    existing_rows, seen_sha, seen_ids = _load_existing_ledger(ledger_path)
    new_rows: list[dict[str, str]] = []
    duplicates_skipped = 0
    scanned_items = 0

    for source_path in _iter_input_files(inputs):
        scanned_items += 1
        if source_path.suffix.lower() != ".zip":
            payload = source_path.read_bytes()
            sha256 = _sha256_bytes(payload)
            source_id = _canonical_source_id(sha256)
            if sha256 in seen_sha or source_id in seen_ids:
                duplicates_skipped += 1
                continue
            stored_path = (
                _store_binary_copy(
                    source_id=source_id,
                    extension=source_path.suffix,
                    payload=payload,
                    files_dir=files_dir,
                )
                if copy_files
                else ""
            )
            row = _build_row(
                source_kind="manual_document",
                file_name=source_path.name,
                extension=source_path.suffix,
                size_bytes=source_path.stat().st_size,
                sha256=sha256,
                original_path=source_path.as_posix(),
                zip_member_path="",
                stored_path=stored_path,
            )
            new_rows.append(row)
            seen_sha.add(sha256)
            seen_ids.add(source_id)
            continue

        zip_sha = _sha256_file(source_path)
        with ZipFile(source_path, "r") as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_path = Path(member.filename)
                extension = member_path.suffix.lower()
                if extension not in SUPPORTED_EXTENSIONS or extension == ".zip":
                    continue
                scanned_items += 1
                payload = archive.read(member)
                sha256 = _sha256_bytes(payload)
                source_id = _canonical_source_id(sha256)
                if sha256 in seen_sha or source_id in seen_ids:
                    duplicates_skipped += 1
                    continue
                stored_path = (
                    _store_binary_copy(
                        source_id=source_id,
                        extension=extension,
                        payload=payload,
                        files_dir=files_dir,
                    )
                    if copy_files
                    else ""
                )
                row = _build_row(
                    source_kind="zip_member_document",
                    file_name=member_path.name,
                    extension=extension,
                    size_bytes=member.file_size,
                    sha256=sha256,
                    original_path=source_path.as_posix(),
                    zip_member_path=member.filename,
                    stored_path=stored_path,
                )
                row["archive_sha256"] = zip_sha
                new_rows.append(row)
                seen_sha.add(sha256)
                seen_ids.add(source_id)

    if new_rows:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("a", encoding="utf-8") as handle:
            for row in new_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    merged_rows = existing_rows + new_rows
    merged_rows.sort(
        key=lambda row: (
            row.get("ingested_at_utc", ""),
            row.get("source_id", ""),
        )
    )
    _write_index_csv(index_path, merged_rows)

    report_payload = {
        "captured_at_utc": _utc_now(),
        "ledger_path": ledger_path.as_posix(),
        "index_path": index_path.as_posix(),
        "scanned_items": scanned_items,
        "existing_records": len(existing_rows),
        "inserted_records": len(new_rows),
        "duplicates_skipped": duplicates_skipped,
        "total_records": len(merged_rows),
        "copy_files": copy_files,
    }
    report_path.write_text(
        json.dumps(report_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {ledger_path}")
    print(f"Wrote {index_path}")
    print(f"Wrote {report_path}")
    print(
        "Manual ingest summary: "
        f"{len(new_rows)} inserted, {duplicates_skipped} duplicates skipped, "
        f"{len(merged_rows)} total."
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Ingest manually uploaded supporting sources into append-only ledger."
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="File or directory path to ingest (repeatable).",
    )
    parser.add_argument(
        "--ledger-dir",
        default=str(DEFAULT_LEDGER_DIR),
        help="Output directory for manual source ledger artifacts.",
    )
    parser.add_argument(
        "--copy-files",
        default="true",
        help="Copy ingested binaries into outputs/manual_sources/files (true/false).",
    )
    return parser.parse_args(argv)


def _to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        copy_files = _to_bool(str(args.copy_files))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    input_paths = [Path(value) for value in args.input]
    return ingest_manual_sources(
        inputs=input_paths,
        ledger_dir=Path(str(args.ledger_dir)),
        copy_files=copy_files,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
