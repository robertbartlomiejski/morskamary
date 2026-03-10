---
# This is a prompt file for adding new blue competences to the toolkit
# Usage: refer to this when creating new Competence objects
---

# Add Blue Competence Workflow

You are adding a new competence to the Blue Sociology toolkit. Follow these steps in order:

## Step 1: Evidence Gathering

**Before creating any competence, you must:**

1. **Search repository sources** for evidence:
   - Check `data/derived/Blue Social Competences Univ Szczecin*.csv` for baseline competences
   - Search `docs/literature/` for academic references
   - Review `docs/policy/` for policy framework alignment
   - Query `MANIFEST_SOURCES.csv` for relevant documents

2. **Extract verbatim quote** (short, specific):
   ```
   Example: "Building coastal buffers, off-shore and deep sea habitats"
   Source: Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv, row 14, C.3
   ```

3. **If no evidence found:**
   - Add `[citation needed]` placeholder in description
   - Mark competence as `PROVISIONAL` in documentation
   - DO NOT proceed with micro-credential design until evidence added

## Step 2: TMBD Axis Assignment

**Determine primary axis** using framework definitions:

| Axis | Code | Focus | Typical Competence Areas |
|------|------|-------|-------------------------|
| **MARINE** | M | Biophysical & ecological agency | Habitat monitoring, species knowledge, ecosystem management, coastal resilience |
| **MARITIME** | T | Techno-economic & institutional | Digital tools, governance structures, value chains, port logistics, maritime law |
| **OCEANIC** | O | Planetary governance & hydrosocial | Ocean literacy, systems thinking, transboundary cooperation, blue citizenship |

**Decision rules:**
- If competence primarily involves **natural systems** → MARINE
- If competence primarily involves **human systems/tech** → MARITIME
- If competence primarily involves **planetary/governance literacy** → OCEANIC
- If cross-axis, choose the **dominant** dimension (where most learning outcomes focus)

**Justification template:**
```
This competence is assigned to [AXIS] axis because it primarily addresses
[biophysical/techno-economic/planetary] dynamics. Specifically, it involves
[concrete skills/knowledge domains] that align with the [M/T/O] dimension
of the Tripartite Model of Blue Dynamics.
```

## Step 3: Competence Level Assignment

Choose proficiency level:

- **FOUNDATIONAL (1)**: Basic awareness, definitions, regulatory compliance
- **INTERMEDIATE (2)**: Practical application, sector-specific skills, standard procedures
- **ADVANCED (3)**: Cross-sector integration, strategic planning, complex problem-solving
- **EXPERT (4)**: Innovation, research, policy design, system transformation

**Guidelines:**
- Most blue economy workplace competences are INTERMEDIATE (2)
- Leadership/governance competences typically ADVANCED (3) or EXPERT (4)
- Entry-level literacy competences are FOUNDATIONAL (1)

## Step 4: Create Competence Object

```python
from src.core import Competence, BlueDynamicsAxis, CompetenceLevel

competence = Competence(
    id="comp_[descriptive_name]",  # Use snake_case, prefix with "comp_"
    name="Human-Readable Competence Name",
    description=(
        "Clear description of what the competence entails. "
        "Evidence: 'Direct quote from source' "
        "[Source: filename, location]. "
        "Additional context if needed."
    ),
    axis=BlueDynamicsAxis.[MARINE|MARITIME|OCEANIC],
    level=CompetenceLevel.[FOUNDATIONAL|INTERMEDIATE|ADVANCED|EXPERT],
    keywords=[
        "keyword1",
        "keyword2",
        "keyword3",  # 5-10 keywords for discovery
    ]
)
```

## Step 5: Add to CompetenceMapper

```python
from src.competence_mapper import CompetenceMapper

mapper = CompetenceMapper()
mapper.add_competence(competence)

# Verify addition
summary = mapper.get_summary()
print(f"Total competences: {summary['total_competences']}")
```

## Step 6: Write Tests

Add test case in `tests/test_core.py`:

```python
def test_new_competence_coastal_resilience():
    """Test newly added coastal resilience competence"""
    comp = Competence(
        id="comp_coastal_resilience_planning",
        name="Coastal Community Resilience Planning",
        description="...",
        axis=BlueDynamicsAxis.MARINE,
        level=CompetenceLevel.ADVANCED,
        keywords=["coastal", "resilience", "planning"]
    )
    
    assert comp.id == "comp_coastal_resilience_planning"
    assert comp.axis == BlueDynamicsAxis.MARINE
    assert comp.level == CompetenceLevel.ADVANCED
    assert "coastal" in comp.keywords
```

Run tests:
```bash
pytest tests/test_core.py -v
```

## Step 7: Update Documentation

1. **CHANGELOG.txt** - Record the addition:
   ```
   2026-03-10
   Change type: add
   Scope: competences
   Files affected: [script that adds competence]
   Summary: Added Coastal Community Resilience Planning competence (MARINE axis).
   Reason: Expand blue competence coverage for port and coastal sectors.
   Evidence: Blue Social Competences Univ Szczecin CSV, dimension C.3.
   ```

2. **Competence registry** (if maintaining separate registry):
   - Add entry with ID, name, axis, level, source

## Step 8: Cross-Sector Validation

Suggest related sectors for the new competence:

1. **Primary sectors** (where competence is required):
   - Example: Port Activities, Coastal Tourism

2. **Adjacent sectors** (where competence is beneficial):
   - Example: Renewable Energy (offshore), Living Resources (fisheries)

3. **Rationale** (why sectors are connected):
   ```
   Coastal resilience competence applies to port activities (primary) due to
   sea-level rise adaptation requirements. Also benefits renewable energy sector
   for offshore wind farm siting and environmental impact assessment.
   ```

## Validation Checklist

Before finalizing, verify:

- [ ] Evidence quote included in description with source locator
- [ ] TMBD axis justified with framework reference
- [ ] Competence level appropriate for complexity
- [ ] Keywords relevant and discoverable (5-10 terms)
- [ ] ID follows naming convention (`comp_*` prefix)
- [ ] Test case added and passing
- [ ] CHANGELOG.txt updated with date and rationale
- [ ] No duplicate competences with different IDs
- [ ] Sector associations documented

## Common Pitfalls to Avoid

❌ **Inventing competences without evidence** → Always cite repository sources first  
❌ **Misassigning TMBD axis** → Review framework definitions carefully  
❌ **Vague descriptions** → Be specific about skills/knowledge involved  
❌ **Missing keywords** → Add enough terms for semantic search discoverability  
❌ **Inconsistent IDs** → Use `comp_` prefix, snake_case, descriptive names  
❌ **Skipping tests** → Always add test coverage for new competences  
❌ **Forgetting CHANGELOG** → Document all additions with date and reason  

## Example: Complete Workflow

See `demo_workspace_instructions.py` → `task_1_add_coastal_resilience_competence()` for a fully worked example following all steps above.
