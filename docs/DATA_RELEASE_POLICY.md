# Data release policy

## Policy summary

Large cumulative empirical artifacts are released as **versioned downloadable
dataset packages**, not embedded in this Code PR.

## What Git stores

The repository stores:

- code,
- schemas,
- codebook,
- methodology and analysis docs,
- manifests,
- checksums,
- release notes,
- tests,
- small deterministic fixtures.

## What the full data package stores

The later release package should include:

- CSV tables,
- XLSX workbook,
- JSONL audit records,
- optional SAV files,
- data dictionary,
- variable labels,
- value labels,
- validation report,
- checksum manifest.

## Governance constraints

- raw sources are never overwritten,
- derived data must be reproducible from parent sources,
- restricted/copyrighted materials are not redistributed unless permitted,
- checksums and release manifests must accompany downloadable data,
- retention decisions for `outputs/run_archive` and manual-source corpora must
  be explicit before publication.

## Storage decision rule

Before any Data PR or dataset release, decide:

- maximum repository volume,
- whether historical bundles live in Git, release assets, or external archives,
- whether only indexes/checksums are committed to Git,
- whether large raw/manual files remain external with checksums in repo,
- retention period for `outputs/run_archive`,
- licensing and redistribution limits.
