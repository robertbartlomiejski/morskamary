#!/usr/bin/env python3
"""Build or verify MOR-21 descriptive tables without changing retained inputs."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.scientific_sources.publication_tables import (  # noqa: E402
    add_publication_sqlite, build_publication_tables, validate_publication_outputs,
    write_publication_tables,
)


def main() -> int:
    """Build or validate publication projections without changing retained sources."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, help='Fallback protocol for snapshots without a retained manifest binding')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        model = build_publication_tables(args.database_dir, args.protocol)
        sqlite_path = args.output_dir / 'publication_tables.sqlite'
        if not args.validate_only:
            write_publication_tables(model, args.output_dir)
            sqlite_path.unlink(missing_ok=True)
            with sqlite3.connect(sqlite_path) as conn:
                add_publication_sqlite(conn, model)
        if not sqlite_path.is_file():
            raise ValueError('publication SQLite missing')
        with sqlite3.connect(f'file:{sqlite_path}?mode=ro', uri=True) as conn:
            validate_publication_outputs(model, args.output_dir, conn)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'schema_version': model['schema_version'], 'run_id': model['run_id'],
                      'source_schema_version': model['source_schema_version'],
                      'table_blockers': model['audit']['table_blockers']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
