# .github/integrate-literature.skill.md
Skill for processing blue economy literature and extracting competences
- Search docs/literature/ for relevant papers
- Extract competence requirements with citations
- Map to TMBD axes with justification

# .github/competence-domain.instructions.md
---
applyTo: '**/load_real_competences.py,**/main_real_data.py'
---
When modifying competence loading:
- Always validate CSV structure matches expected columns
- Test dimension→axis mapping changes with all 4 dimensions
- Update MANIFEST_SOURCES.csv if adding new data sources