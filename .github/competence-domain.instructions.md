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

### Dimension → TMBD Axis Mapping
Test dimension→axis mapping changes with all 4 dimensions:

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
1. Document rationale with reference to TMBD framework definition
2. Test with full University of Szczecin dataset (16 competences)
3. Verify axis distribution remains balanced (avoid >80% in one axis)
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
- **TMBD axis justification**: Document why competence belongs to Marine/Maritime/Oceanic

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
    axis=BlueDynamicsAxis.MARINE,  # Biophysical focus per TMBD
    # ... other fields
)
```

### Prohibited Practices
- ❌ **No invented competences**: Must trace to repository source or baseline dataset
- ❌ **No unsupported axis assignments**: Always justify with TMBD framework reference
- ❌ **No unverified sector mappings**: Cross-reference against Blue Social Competences sector matrices

## Testing Requirements

### When modifying load_real_competences.py:
1. Test with actual CSV file from `data/derived/`
2. Verify competence count matches expected (16 from baseline)
3. Check axis distribution:
   ```python
   summary = mapper.get_summary()
   assert summary['competences_by_axis']['MARINE'] >= 3
   assert summary['competences_by_axis']['MARITIME'] >= 6
   assert summary['competences_by_axis']['OCEANIC'] >= 3
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
2. Highlight cross-axis requirements (e.g., renewable energy needs M+T+O)
3. Document rationale for sector associations in competence metadata
4. Reference Blue Social Competences sector matrix for validation:
   - File: `Blue Social Competences Univ Szczecin - Blue competences x blue economy sector.csv`
   - Columns: 12 sector columns with X markers for applicability
