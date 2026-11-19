# MOR-21: retained-data publication tables, analytical contract v1

This first slice audits the retained cumulative database and adds unit reconciliation
and sector × QMBD screening tables. It does not complete MOR-21 or MOR-12.
The authoritative input is `outputs/cumulative_database`, source schema **1.0.0**,
snapshot run **30090903921-1**, on main
`bcae32c732f840c2505e4d3421295e4463ab4ee6`. The retained protocol is preferred;
a manifest binding takes precedence over the configured fallback, including a
custom retained artifact path. An absent or escaping bound path is an error.
`MOR21_RETAINED_DATA_AUDIT.json` records exact input SHA-256 hashes, physical
CSV types, analytical types, column-level missing/invalid counts, key profiles,
and relationship cardinalities. It is a snapshot audit, not a refreshed dataset.

## Observed results

- 3,129 distinct evidence records; 2,105 distinct legacy semantic signals;
  13 signal categories; 1,478 distinct evidence–sector–axis associations and
  1,478 unique evidence records contributing to them. The 627 repeated signal
  associations are collapsed before aggregation, not interpreted as new evidence.
- 157 legacy demand aggregates, 79 credential-design candidates and 290 proposed
  learning outcomes are separate units. None is a validated competence count.
- 172 hypothesis-specific fragments are retained, but they are not the generic
  schema-v2 evidence-fragment population. Generic fragments, competence candidates,
  validated canonical competences, validated sector assignments and provider–query
  occurrences are unavailable in this snapshot, not observed zeros.
- All ten retained CSV tables have zero missing or duplicate declared keys and
  zero exact duplicate rows. The signal-to-evidence join is 2,105 → 2,105;
  the three learning-outcome joins are each 290 → 290. There are zero orphan
  references or extra joined rows in these four audited joins. Absent v2 joins
  are explicitly unavailable; this is not a claim about joins to unretained data.
- Evidence metadata: DOI missing 17/3,129; title and normalized title hash each
  missing 1/3,129; year missing 68/3,129; journal missing 389/3,129.
  No invalid numeric tokens were found in the explicitly typed columns.
  Missing warning text is not evidence of failed validation.
- Independent supply/translation evidence is not inferred or loaded by this
  descriptive layer. H2/H3 status remains governed by the existing Layer 5 and
  readiness contracts. This feature cannot make either hypothesis computable.

## Table from the frozen snapshot

Assignment counts below are distinct `(evidence_id, sector, axis_group)` tuples.
Full percentages, distinct-source margins, denominators, small-cell warnings and
statuses are emitted by the builder, rather than maintained separately here.

| Sector | MARINE (M) | MARITIME (T) | OCEANIC (O) | HYDRONIZATION (H) | Assignments |
|---|---:|---:|---:|---:|---:|
| blue_biotech | 153 | 0 | 22 | 0 | 175 |
| coastal_tourism | 0 | 0 | 155 | 0 | 155 |
| desalination | 0 | 0 | 2 | 111 | 113 |
| infra_robotics | 0 | 186 | 3 | 0 | 189 |
| living_res | 100 | 0 | 4 | 0 | 104 |
| maritime_defence | 0 | 72 | 15 | 0 | 87 |
| maritime_transport | 0 | 117 | 18 | 0 | 135 |
| non_living_res | 74 | 0 | 13 | 0 | 87 |
| port_activities | 0 | 144 | 9 | 0 | 153 |
| r_i | 0 | 0 | 103 | 0 | 103 |
| renewable_energy | 0 | 99 | 17 | 0 | 116 |
| ship_repair | 0 | 51 | 10 | 0 | 61 |
| Total | 327 | 669 | 371 | 111 | 1478 |

## Metric contract and interpretation

`publication_metric_contract.csv` and the JSON `metric_contract` are generated
from the same implementation as every result. Each metric records name, unit,
numerator, denominator, eligible population, N definition, missing-N definition,
exclusions, formula, source and snapshot run ID. Reconciliation records give the
actual N/missing N, status and reason. Source hashes/version accompany the model.
Count metrics have no percentage denominator (`not_applicable_count`).

The primary table counts screening associations supported by retained semantic
signals, with a valid evidence link and canonical dimensions, excluding rejected
signals. It does not use query text to establish sector or QMBD evidence.
Multiple eligible signals for the same tuple contribute one association. A source
may contribute to several sectors/axes; those groups are overlapping. Distinct
source margins are recomputed from sets, never summed. Row percentages divide by
the sector association margin, column percentages by the axis margin, and total
percentages by the grand association margin. These are association shares, not
population prevalence or probabilities for unique sources.

A cell with fewer than five associations carries a descriptive warning, not a
statistical significance decision. Six-decimal percentages can have rounding
residuals. Zero denominators produce NULL percentages and an explicit reason;
observed zero counts remain zero. An absent input population produces
`not_computable` with NULL value. Missing dimensions are counted at **global
signal-row grain**, repeated in every table row for context; they are not a
cell-specific estimate of missing unique associations. Unobserved literature,
missing distinct categories and missing provider–query occurrences cannot be
estimated from retained aggregates. No provider×query Cartesian product is used.

CSV source fields are text. The typed layer preserves invalid/missing year and
confidence as NULL plus a parsing status. IDs and labels are never converted to
numbers. A signal in schema v2 has the composite key `(signal_id, fragment_id)`;
two fragments sharing a signal identifier are not duplicates. Composite lineage checks
also require each signal and its fragment to identify the same evidence record,
and each candidate to retain its signal/fragment/evidence tuple. Invalid keys,
orphan references, missing required join tables and join expansion suppress
related counts, instead of silently dropping invalid source records. Canonical
competence counts additionally require an active (not superseded) retained accepted decision and passed
provenance flag; this is not an independent scientific revalidation.

## Reproduce and inspect

```sh
python scripts/build_publication_tables.py \
  --database-dir outputs/cumulative_database --output-dir /tmp/mor21-tables
python scripts/build_publication_tables.py \
  --database-dir outputs/cumulative_database --output-dir /tmp/mor21-tables --validate-only
```

The output contains full JSON, audit JSON, three CSVs, visible HTML and SQLite.
The main statistical report embeds the same visible tables and emits the same
sidecars. Release packaging adds these under `statistics/publication/`, and adds
`analysis_*_v1` tables to its existing SQLite database. Existing legacy TEXT tables
are preserved. SQL DDL and calculation definitions live in
`src/scientific_sources/publication_tables.py`; no separate dashboard formula is
authoritative. `analysis_metadata_v1` contains contract version, run, source hashes
and audit. Evidence/signals/assignments have explicit keys and foreign keys;
consumers must enable `PRAGMA foreign_keys=ON` when writing SQLite.

```sql
SELECT sector, axis_group, assignment_count, unique_evidence_n,
       row_denominator, column_denominator, row_pct, column_pct, status
FROM analysis_sector_qmbd_v1 WHERE row_kind = 'cell';
```

`--validate-only` recomputes from retained inputs and checks all projections,
including visible report HTML and SQLite facts/metadata/summary tables. Packaging
rejects stale or incomplete sidecars for any new-format report and checks the
same model before archiving. Entirely legacy reports retain compatibility. The
resolved analytical protocol is included under `statistics/publication/`.
JSON NULL corresponds to SQLite NULL and an empty CSV/HTML value; status and reason
must be read alongside it. Labels, units, statuses and numeric values are checked,
not just file presence. Existing optional-PDF behavior is unchanged.

## Remaining MOR-21 acceptance criteria

Provider/query publication tables require a separately governed occurrence grain
and an explicit decision about missing retained occurrence data. Robustness
analyses must cover attribution/deduplication choices and source concentration;
this first slice provides no inferential robustness claim. The full reading guide
and wider publication tables remain follow-up work. MOR-12 stays In Progress.
No acquisition, historical archive edits, credential-to-supply promotion or H2/H3
computability change is included.
