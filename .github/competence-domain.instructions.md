---
applyTo: '**/load_real_competences.py,**/main_real_data.py,**/demo_workspace_instructions.py'
---

# Competence Domain Instructions

When modifying competence loading or analysis workflows, follow these domain-specific rules:

## Data Loading & Validation

### CSV Structure Validation
- Always validate CSV structure matches expected columns before processing
- Required columns: `Dimension (Aspect)`, `ID`, `Competence Name`, `Key Simplified Focus`, plus sector columns
- Handle missing or malformed data gracefully with informative error messages
- Log data quality issues (missing IDs, empty names, invalid axis mappings)

### Dimension → QMBD Axis Mapping
Test dimension→axis mapping changes against the four-axis QMBD contract. The current four source dimensions do not, by themselves, prove representation of all four axes:

```python
# Standard mapping (from load_real_competences.py)
dimension_to_axis = {
    "A": BlueDynamicsAxis.OCEANIC,   # Understanding → planetary literacy
    "B": BlueDynamicsAxis.MARITIME,  # Digital/Data → infrastructure/tech
    "C": BlueDynamicsAxis.MARINE,    # Sustainability → ecological/biophysical
    "D": BlueDynamicsAxis.MARITIME,  # Business/Gov → institutional/economic
}
```

**Before changing mappings:**
1. Document rationale with reference to the four-axis QMBD framework definition
2. Test with full University of Szczecin dataset (16 competences)
3. Verify the distribution across `MARINE`, `MARITIME`, `OCEANIC`, and `HYDRONIZATION`; if the source baseline contains no hydronization evidence, report zero explicitly rather than inventing an assignment
4. Update tests in `tests/test_core.py` to reflect new mapping

### Source Management
When adding **new data sources**:
1. Update `MANIFEST_SOURCES.csv` with:
   - File path (relative to repo root)
   - Document type (dataset_derived, policy, literature)
   - Aggregation date (YYYY-MM-DD format)
   - Key topics or competence areas covered
2. Run `python scripts/generate_manifest.py` to regenerate manifest
3. Add citation entry to `CITATION.txt` if source requires attribution

## Evidence & Citation Requirements

### Competence Creation
Every new competence must include:
- **Description with evidence**: Quote source document directly in description field
- **Source locator**: Include file name, row/section number in description
- **QMBD axis justification**: Document why the competence belongs to `MARINE`, `MARITIME`, `OCEANIC`, or `HYDRONIZATION`; an absent axis must be reported as a source limitation

Example:
```python
Competence(
    id="comp_example",
    name="Example Competence",
    description=(
        "Core capability description. "
        "Evidence: 'Direct quote from source document' "
        "[Source: filename.csv, row X, dimension Y.Z]"
    ),
    axis=BlueDynamicsAxis.MARINE,  # Biophysical focus per QMBD
    # ... other fields
)
```

### Prohibited Practices
- ❌ **No invented competences**: Must trace to repository source or baseline dataset
- ❌ **No unsupported axis assignments**: Always justify with the four-axis QMBD framework reference; do not force `HYDRONIZATION` without retained evidence
- ❌ **No unverified sector mappings**: Cross-reference against Blue Social Competences sector matrices

## Testing Requirements

### When modifying load_real_competences.py:
1. Test with actual CSV file from `data/derived/`
2. Verify competence count matches expected (16 from baseline)
3. Check axis distribution:
   ```python
   summary = mapper.get_summary()
   counts = summary['competences_by_axis']
   # Source-derived baseline after loader de-duplicates repeated section marker IDs:
   # A=3 plus retained section marker fallback -> O=4, B=4 + D=4 -> T=8, C=4 -> M=4.
   assert counts.get('MARINE') == 4
   assert counts.get('MARITIME') == 8
   assert counts.get('OCEANIC') == 4
   # This baseline has no evidence-backed H assignment. Report zero explicitly.
   assert counts.get('HYDRONIZATION') == 0
   ```
4. Validate all IDs are prefixed correctly (`blue_comp_`)

### When modifying main_real_data.py:
1. Ensure script exits gracefully if CSV file missing
2. Test gap analysis with realistic worker profiles
3. Verify micro-credential creation includes all required fields (ECTS, EQF, assessment)
4. Check CHANGELOG.txt update logic works correctly

## Competence Mapper Integration

### Adding Competences to Mapper
Use consistent ID prefixes:
- `blue_comp_` for University of Szczecin baseline
- `comp_` for custom/extended competences
- `microcred_` for micro-credentials

### Filtering Patterns
Follow established patterns from `src/competence_mapper.py`:
```python
# Single-axis filtering
marine_comps = mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)

# Multi-axis filtering (manual)
target_axes = {BlueDynamicsAxis.MARINE, BlueDynamicsAxis.OCEANIC}
filtered = [c for c in mapper.competences.values() if c.axis in target_axes]

# Gap analysis with set operations
gaps = mapper.analyze_competence_gaps(available, required_sector)
missing_ids = set(gaps['missing'])
```

## Performance Considerations

- Load CSV files once at startup, cache in CompetenceMapper
- Avoid repeated file I/O in tight loops
- Use `Path.exists()` before attempting file operations
- For large datasets (>1000 competences), consider pagination in analysis output

## Cross-Sector Competence Mapping

When suggesting sector-to-sector transitions:
1. Identify shared competences across sectors
2. Highlight evidence-backed cross-axis requirements using the canonical name/code pairs `MARINE/M`, `MARITIME/T`, `OCEANIC/O`, and `HYDRONIZATION/H`
3. Document rationale for sector associations in competence metadata
4. Reference Blue Social Competences sector matrix for validation:
   - File: `Blue Social Competences Univ Szczecin - Blue competences x blue economy sector.csv`
   - Columns: 12 sector columns with X markers for applicability
