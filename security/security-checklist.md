# Security Checklist

This checklist must be reviewed when merging changes to pipeline scripts
(`load_real_competences.py`, `run_full_analysis.py`, and modules under `src/`).

## Input Validation

- [ ] All file paths are constructed from `Path` objects and resolved before use.
- [ ] CSV inputs are opened with an explicit `encoding="utf-8"` parameter.
- [ ] Missing files raise descriptive `FileNotFoundError` with remediation hints.
- [ ] Row data is stripped of leading/trailing whitespace before processing.
- [ ] No `eval()`, `exec()`, or dynamic code execution on user-supplied input.

## Output Safety

- [ ] HTML reports escape all user-derived strings (use `html.escape()`).
- [ ] JSON exports use `json.dumps()` — no raw string interpolation into JSON.
- [ ] Output filenames are hard-coded constants, not derived from input data.
- [ ] The `outputs/` directory is created with `mkdir(parents=True, exist_ok=True)`.

## Dependency & Supply-Chain

- [ ] No new third-party packages are added without updating `requirements.txt`
  and running `gh-advisory-database` to check for known vulnerabilities.
- [ ] `openpyxl` version constraint is `>=3.0.0` (not `>=3.8.0` — invalid semver).
- [ ] All imports are from the standard library or declared project dependencies.

## Code Readability

- [ ] No nested ternary operators (`a if x else b if y else c`); use `if/elif/else`
  blocks or lookup dictionaries instead.
- [ ] No bare `f""` strings without placeholders (flake8 F541 must pass).
- [ ] `black --check` and `flake8` pass with zero findings on changed files.
- [ ] All public functions and classes have docstrings.

## Data Governance

- [ ] Generated output files inside `outputs/` are **not** accidentally committed
  unless explicitly permitted by the repository policy.
- [ ] `CHANGELOG.txt` is updated when substantive scripts or data files change.
- [ ] `MANIFEST_SOURCES.csv` is regenerated via `scripts/generate_manifest.py`
  after adding new source documents to `data/`.
- [ ] No credentials, API keys, or personal data appear in committed files.

## CI/CD

- [ ] The `full-analysis.yml` workflow runs `python run_full_analysis.py`
  without errors on a clean Ubuntu runner.
- [ ] The `ci.yml` governance checks (file presence, manifest determinism,
  CHANGELOG enforcement) all pass.
- [ ] Uploaded CI artifacts (`blue-economy-analysis-outputs`) are verified
  present in the GitHub Actions summary after each run.
