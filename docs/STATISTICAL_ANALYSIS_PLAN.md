# Statistical analysis plan

## Objective

Prepare the cumulative evidence database for descriptive, inferential, and
reliability-oriented analysis across Excel, Statistica, PS IMAGO/SPSS, Python,
and R.

## Export plan

Planned release outputs:

- `CSV` UTF-8 tables
- `XLSX` workbook with one sheet per table
- optional `SPSS/PS IMAGO .sav` files with variable labels and value labels
- `JSONL` canonical audit records
- checksum manifest

Where `.sav` export dependencies are unavailable, CSV + value-label tables remain
the required fallback.

## Canonical versus analytical outputs

- **Canonical**: normalized tables and JSONL audit records
- **Analytical**: flattened views for statistical software

Flattened views:

- `analysis_view_record_level.csv`
- `analysis_view_occurrence_level.csv`
- `analysis_view_sector_axis_gap_level.csv`
- `analysis_view_provider_sector_level.csv`
- `analysis_view_credential_level.csv`

## Planned analyses

- descriptive statistics by run, sector, provider, and axis
- cross-tabulations (`sector x axis`, `provider x sector`, `source type x quality`)
- missingness analysis
- duplicate-rate analysis
- provider-diversity and provider-bias analysis
- live/manual/historical source comparison
- trend analysis across runs
- gap-priority stability analysis
- cluster/profile analysis for competence and gap patterns
- machine-human agreement analysis
- credential-generation-rate analysis

## Variable treatment

- categorical variables: numeric-coded with paired labels and value-label tables
- ordinal variables: explicit ordered code scales
- continuous variables: numeric with unit notes where required
- restricted values: retain row with reserved missing code rather than deleting

## Software notes

- **Excel**: inspection, filtering, pivoting, teaching
- **Statistica**: CSV/XLSX import with numeric category codes
- **PS IMAGO/SPSS**: `.sav` preferred; CSV + labels fallback
- **Python/R**: normalized tables + flattened views for reproducible scripts
