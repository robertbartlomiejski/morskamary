---
# Skill for processing blue economy literature and extracting competences with citations
---

# Integrate Literature Skill

## Purpose

Extract and integrate competences from blue economy literature sources in the repository, ensuring proper citation and TMBD axis classification.

## When to Use This Skill

- Adding new competences derived from academic literature
- Validating existing competences against published research
- Building evidence base for micro-credential design
- Conducting literature reviews for Blue Sociology manuscripts

## Workflow

### 1. Search Repository Literature

**Available sources:**
- `docs/literature/*.pdf` - Academic papers (100+ sources)
- `data/raw/scholar_*.csv` - Google Scholar exports
- `data/raw/scispace_*.csv` - SciSpace search results
- `data/derived/combined_*.csv` - Thematically organized literature

**Search strategies:**
```python
# Example: Find papers on coastal resilience
import pandas as pd

# Load combined literature
df = pd.read_csv("data/derived/combined_blue_economy_labor_justice.csv")

# Search for resilience topics
resilience_papers = df[df['title'].str.contains('resilience|adaptation', case=False, na=False)]

# Extract relevant quotes for competence description
for idx, row in resilience_papers.iterrows():
    print(f"Title: {row['title']}")
    print(f"Abstract: {row['abstract'][:200]}...")
    print(f"URL: {row['url']}")
    print()
```

### 2. Extract Competence Requirements

**From literature, identify:**
- **Skills mentioned** (data analysis, GIS, stakeholder engagement)
- **Knowledge domains** (marine ecology, maritime law, circular economy)
- **Attitudes/values** (ethical governance, inclusivity, sustainability)
- **Sector context** (which blue economy sectors are addressed)

**Citation format:**
```
Evidence: "[Short verbatim quote from abstract or conclusion]"
[Source: Author(s). Year. Paper Title. Journal, row X in combined_*.csv]
```

### 3. Map to TMBD Axes

**Classification rules from literature themes:**

| Literature Theme | Typical TMBD Axis | Rationale |
|-----------------|-------------------|-----------|
| Marine biodiversity, ecosystem services, habitat restoration | **MARINE (M)** | Biophysical/ecological focus |
| Port operations, maritime transport, digital tools, value chains | **MARITIME (T)** | Techno-economic/institutional |
| Ocean governance, citizenship, transboundary cooperation, policy | **OCEANIC (O)** | Planetary/governance focus |
| Climate adaptation with ecosystem focus | **MARINE (M)** | Primary focus on ecological resilience |
| Climate adaptation with socio-technical focus | **MARITIME (T)** | Primary focus on infrastructure/institutions |
| Ocean literacy, systems thinking | **OCEANIC (O)** | Planetary literacy dimension |

**Multi-axis competences:**
- If literature addresses multiple axes, choose the **dominant** focus
- Document secondary axes in competence metadata
- Example: "Coastal resilience planning" may involve MARINE (ecological) and MARITIME (infrastructure), but if ecological restoration is primary → assign MARINE

### 4. Create Competence with Full Citation

```python
from src.core import Competence, BlueDynamicsAxis, CompetenceLevel

competence = Competence(
    id="comp_literature_derived_001",
    name="Competence Name from Literature",
    description=(
        "Description of competence. "
        "Evidence: 'Verbatim quote demonstrating competence requirement' "
        "[Source: Author(s). Year. Paper Title. Journal. "
        "data/derived/combined_blue_economy_*.csv, row 123]"
    ),
    axis=BlueDynamicsAxis.MARINE,  # Justified by biophysical focus in paper
    level=CompetenceLevel.INTERMEDIATE,
    keywords=["extracted", "from", "paper", "abstract", "keywords"]
)
```

### 5. Validate Against Existing Competences

**Check for duplicates:**
```python
from src.competence_mapper import CompetenceMapper

mapper = CompetenceMapper()
# Load existing competences
# ...

# Check if similar competence exists
existing_names = [c.name.lower() for c in mapper.competences.values()]
if competence.name.lower() in existing_names:
    print(f"⚠ Potential duplicate: {competence.name}")
    # Review and merge if appropriate
```

**Check for coverage gaps:**
```python
# Get competences by axis
marine_comps = mapper.get_competences_by_axis(BlueDynamicsAxis.MARINE)
maritime_comps = mapper.get_competences_by_axis(BlueDynamicsAxis.MARITIME)
oceanic_comps = mapper.get_competences_by_axis(BlueDynamicsAxis.OCEANIC)

print(f"MARINE competences: {len(marine_comps)}")
print(f"MARITIME competences: {len(maritime_comps)}")
print(f"OCEANIC competences: {len(oceanic_comps)}")

# If imbalanced (e.g., <3 in any axis), prioritize literature extraction for that axis
```

### 6. Update Provenance Records

**After adding literature-derived competences:**

1. **Update MANIFEST_SOURCES.csv** if new literature sources used:
   ```bash
   python scripts/generate_manifest.py
   ```

2. **Add citation to CITATION.txt**:
   ```
   Author, A., & Author, B. (Year). Paper title. Journal Name, Vol(Issue), pages.
   DOI or URL
   Used for: [Competence ID] - [Competence Name]
   ```

3. **Record in CHANGELOG.txt**:
   ```
   2026-03-10
   Change type: add
   Scope: competences, literature integration
   Files affected: [script name], data/derived/combined_*.csv
   Summary: Added [N] competences derived from [paper titles].
   Reason: Expand evidence base for [sector/theme] from literature review.
   Evidence: [Source citations]
   ```

## Literature Source Structure

### Combined Literature Files

**data/derived/combined_blue_economy_*.csv** contain thematically organized papers:

| File | Theme | Papers | Focus |
|------|-------|--------|-------|
| `combined_blue_economy_labor_justice.csv` | Labor & justice | 200+ | Worker rights, equity, community resilience |
| `combined_blue_economy_research_gaps.csv` | Research gaps | 100+ | Identified gaps in blue economy research |
| `combined_blue_economy_governance.csv` | Governance | 150+ | Policy, regulation, participatory approaches |

**Columns:**
- `title` - Paper title
- `url` - Link to paper (if available)
- `year` - Publication year
- `type` - Journal article, conference paper, report
- `journal` - Publication venue
- `authors` - Author list
- `abstract` - Full abstract text (sometimes truncated)
- `reasoning` - Analysis notes on relevance to Blue Sociology

### Raw Literature Exports

**data/raw/scholar_*.csv** and **data/raw/scispace_*.csv**:
- Direct exports from academic search engines
- May contain duplicates (use `title` matching to deduplicate)
- Use for initial screening, then add relevant papers to `combined_*.csv`

## Example: Extracting Competence from Literature

```python
import pandas as pd
from src.core import Competence, BlueDynamicsAxis, CompetenceLevel

# 1. Load literature
df = pd.read_csv("data/derived/combined_blue_economy_labor_justice.csv")

# 2. Find relevant paper
resilience_paper = df[df['title'].str.contains('coastal resilience', case=False)].iloc[0]

# 3. Extract quote from abstract
quote = "resilience assessment of coastal areas...stakeholder participation framework"
source = f"{resilience_paper['authors']}. {resilience_paper['year']}. {resilience_paper['title']}. {resilience_paper['journal']}."

# 4. Create competence
competence = Competence(
    id="comp_literature_coastal_participation",
    name="Participatory Coastal Resilience Assessment",
    description=(
        f"Conducting coastal resilience assessments using participatory methods. "
        f"Evidence: '{quote}' "
        f"[Source: {source} Row {resilience_paper.name} in combined_blue_economy_labor_justice.csv]"
    ),
    axis=BlueDynamicsAxis.MARINE,  # Focus on coastal ecology + community
    level=CompetenceLevel.ADVANCED,  # Requires stakeholder facilitation skills
    keywords=[
        "coastal resilience",
        "stakeholder participation",
        "resilience assessment",
        "community engagement",
        "adaptation planning"
    ]
)

# 5. Add to mapper
from src.competence_mapper import CompetenceMapper
mapper = CompetenceMapper()
mapper.add_competence(competence)

print(f"✓ Added competence: {competence.name}")
print(f"  Axis: {competence.axis.name}")
print(f"  Source: {source[:50]}...")
```

## Quality Checks

Before finalizing literature-derived competences:

- [ ] Quote is verbatim from paper (no paraphrasing in evidence field)
- [ ] Source includes: Author, Year, Title, Journal/Venue, file location
- [ ] TMBD axis justified by paper's primary analytical focus
- [ ] Keywords extracted from paper abstract/keywords section
- [ ] No duplicate competences (check against existing IDs)
- [ ] Citation added to CITATION.txt
- [ ] CHANGELOG.txt updated with literature source references

## Integration with Micro-Credentials

**Link literature-derived competences to credentials:**

```python
# Create micro-credential incorporating literature-derived competences
from src.core import MicroCredential

credential = MicroCredential(
    id="microcred_literature_based_001",
    title="Participatory Coastal Management Specialist",
    competences=[
        "comp_literature_coastal_participation",  # From literature
        "blue_comp_c_3",  # From baseline (coastal resilience)
        "blue_comp_d_4",  # From baseline (ethical governance)
    ],
    description=(
        "Evidence-based micro-credential for coastal managers, grounded in "
        "participatory resilience literature [Author et al., Year]."
    ),
    sector="coastal-management"
)
```

## Common Literature Sources in Repository

**High-value papers for competence extraction:**
1. Maritime sociology literature (fisheries, port communities, seafarer studies)
2. Ocean governance and MSP (Marine Spatial Planning) papers
3. Blue economy policy analyses (EU Blue Growth, Ocean Decade)
4. Climate adaptation and coastal resilience studies
5. Ocean literacy and public engagement research

**Search these first** when building evidence base for new sectors or competence clusters.

## Troubleshooting

**Issue: Paper quote too long for description field**
- Solution: Extract shortest quote that conveys competence requirement
- Max ~50 words; if longer, paraphrase description but keep original quote in citation

**Issue: Paper addresses multiple TMBD axes equally**
- Solution: Create separate competences for each axis focus
- Example: "Coastal Adaptation (Ecological)" → MARINE; "Coastal Adaptation (Infrastructure)" → MARITIME

**Issue: Can't find full text of cited paper**
- Solution: Use abstract from CSV exports; mark as `[full text unavailable]` in source note
- Recommend acquiring paper if competence is critical for micro-credential

**Issue: Duplicate competences from different papers**
- Solution: Merge into single competence with multiple source citations
- Format: `Evidence: 'Quote 1' [Source 1]; 'Quote 2' [Source 2]`

## Next Steps After Literature Integration

1. Test competences in gap analysis scenarios (see `demo_workspace_instructions.py`)
2. Design micro-credentials linking literature-derived and baseline competences
3. Export competences to Europass format with full bibliography
4. Share with stakeholders for validation against workplace requirements
