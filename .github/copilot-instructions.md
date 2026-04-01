# GitHub Copilot Instructions for morskamary

## Project Overview

This repository is an evidence base and Python toolkit for **Blue Sociology** — an applied extension of maritime sociology for the EU Sustainable Blue Economy and "one ocean" governance. It supports competence mapping and micro-credential design grounded in the **Tripartite Model of Blue Dynamics (TMBD)**.

## Core Domain: Tripartite Model of Blue Dynamics (TMBD)

All code, data structures, and analysis must respect the three TMBD axes:

- **Marine (M)** — biophysical and ecological agency and constraints (nature/biota perspective)
- **Maritime (T)** — techno-economic, infrastructural, labour, and institutional mediation (human-social perspective)
- **Oceanic (O)** — planetary coupling, multi-level governance, hydrosocial subjectivity, and transboundary responsibility (posthumanist/planetary perspective)

When adding competences, credentials, or sector mappings, always assign them to one of these axes. See `src/core.py` (`BlueDynamicsAxis` enum) for the canonical representation.

## Repository Structure

```
src/
  core.py               # Data structures: Competence, MicroCredential, BlueDynamicsAxis, CompetenceLevel
  competence_mapper.py  # CompetenceMapper: add/query competences and credentials
  __init__.py
tests/
  test_core.py          # Pytest-based unit tests (8 tests expected to pass)
main.py                 # Demonstration entry point (synthetic data)
main_real_data.py       # Production demo with University of Szczecin baseline
load_real_competences.py  # CSV loader with dimension→axis mapping
scripts/
  generate_manifest.py  # Auto-generates MANIFEST_SOURCES.csv
  build_derived.py      # Excel→CSV export engine
data/
  raw/                  # Primary sources (literature CSVs, policy docs)
  derived/              # Processed outputs (competence matrices, frameworks)
LLM_CONTEXT_INSTRUCTION.txt  # Domain-specific LLM constraints and protocols
DATA_GOVERNANCE.txt     # FAIR/CARE data governance rules
CITATION.txt            # Citation and provenance guidance
CHANGELOG.txt           # Versioned change log
MANIFEST_SOURCES.csv    # Auto-generated source catalog for provenance
```

## Coding Conventions

- **Python ≥ 3.9** — use type hints; avoid constructs unavailable before 3.9
- **Formatter**: `black` with `line-length = 88`
- **Linter**: `flake8`
- **Type checker**: `mypy` (see `pyproject.toml` for config)
- **Tests**: `pytest`; test files go in `tests/` and must be named `test_*.py`
- Use `@dataclass` for data models (see `Competence`, `MicroCredential` in `src/core.py`)
- Use `Enum` for controlled vocabularies (axes, levels, sectors)
- All public functions and classes must have docstrings

## Development Quick Start

```bash
# First-time setup
pip install -r requirements.txt
pip install black flake8 mypy  # dev tools (optional)
pytest tests/ -v                # verify setup (expect 8 passing tests)

# Run demos
python main.py                  # synthetic data demo
python main_real_data.py        # real data from University of Szczecin baseline
python scripts/generate_manifest.py  # rebuild source catalog

# Code quality
black src/ tests/               # format code (line-length=88)
flake8 src/ tests/              # lint
mypy src/                       # type-check

# Docker workflows
docker compose up --build                      # production build
docker compose -f compose.debug.yaml up --build  # debug mode (debugpy on port 5678)
```

**Prerequisites**: Python ≥ 3.9, Git, (optional) Docker

## Domain Constraints (from `LLM_CONTEXT_INSTRUCTION.txt`)

- **Evidence discipline**: Substantive claims must be sourced from repository documents. Use placeholder `[citation needed]` when evidence is absent — do not invent references.
- **No hallucination**: Do not invent author names, legal references, policy titles, or empirical findings.
- **Quote then reason**: For every new term or definition, cite a short verbatim quote from a source file with its locator, then reason from it.
- **TMBD spine**: Apply Marine/Maritime/Oceanic classification in every competence, credential, or sector mapping.
- **Micro-credential outputs** must include at minimum: title, learner profile, workload/ECTS, EQF level, learning outcomes, assessment method, stackability rules.

## Key Domain Concepts

- **Marinization** (Janiszewski): process by which societies adapt to and are shaped by marine environments
- **Maritimisation**: techno-economic and institutional terraforming of the sea (ports, fleets, grids, MSP)
- **Oceanisation**: planetary-scale reconnection treating the ocean as a coupled socio-ecological system
- **Blue competences**: skills aligned to BlueComp framework and Blue Social Competences (University of Szczecin baseline)
- **Blue economy sectors**: offshore energy, ports, maritime transport, fisheries, aquaculture, coastal tourism, marine biotechnology, ocean governance

## Traceability Rules

- When producing mappings or tables, include the source file and locator for each row/cluster
- When revising drafts or data structures, record changes in `CHANGELOG.txt` with date and reason
- Follow FAIR principles (Findable, Accessible, Interoperable, Reusable) for any derived datasets

## Competence Mapping Workflow

When working on competence mapping, adhere to these task-specific practices:

### Axis Validation
- **Always validate TMBD axis assignment** (Marine/Maritime/Oceanic) against the framework definition
- Each competence must map to exactly one primary axis, though cross-axis relationships may be noted
- Justify axis choice with reference to the biophysical, techno-economic, or planetary dimensions it primarily serves

### Evidence and Citations
- **Block unverified claims**: Never add competences or learning outcomes without evidence from source documents
- Use `[citation needed]` placeholder when source is pending, then resolve before finalizing
- For every competence description, cite the source file and specific section (e.g., "Blue Social Competences Univ Szczecin — Overall Blue Competences Dimension.csv, row 24")
- Cross-reference competence keywords against the Blue Social Competences dataset (`data/derived/Blue Social Competences Univ Szczecin*`)

### Source Management
- When adding **new source documents**, update `MANIFEST_SOURCES.csv` with:
  - File path or URL
  - Document type (e.g., policy, literature, dataset)
  - Aggregation date
  - Key topics or competence areas covered
- Link competences to the **University of Szczecin baseline** where applicable (auto-mapping candidates in `data/derived/`)

### Micro-credential Completeness
- Ensure every `MicroCredential` object includes all required fields (see `LLM_CONTEXT_INSTRUCTION.txt`):
  - Title, learner profile, workload/ECTS, EQF level, learning outcomes, assessment method, stackability rules
- Validate using the `CompetenceMapper` class methods before committing changes

### Cross-sector Suggestions
- When adding competences to one sector (e.g., Maritime Transport), suggest related mappings to adjacent sectors (e.g., Ports, Offshore Energy)
- Document rationale for each sector association in competence metadata

## Architecture Patterns

### Data Model Design
- **Use `@dataclass` for all models** with full type hints on all fields
- **Enums for controlled vocabularies**: `BlueDynamicsAxis`, `CompetenceLevel` prevent invalid values
- **ID-based linking**: Store references as `List[str]` (IDs) rather than nested objects for flexible composition
- **Serialization pattern**: Implement `to_dict()` methods that convert enums to `.value` (codes) or `.name` (strings)

### Service Layer Patterns (CompetenceMapper)
- **Registry pattern**: Objects stored in `Dict[str, EntityType]` keyed by ID for O(1) lookups
- **Filtering**: Use list comprehensions for single-attribute filters: `[c for c in items if c.axis == target]`
- **Set operations for analysis**: `available & required`, `required - available` for gap analysis
- **Complex results**: Return `Dict[str, ...]` with structured nested data; document structure in docstring

### Code Conventions
- **Type hints everywhere**: Annotate all parameters and return types
- **Accept `Union[str, Path]`** for file operations; convert immediately to `Path` object
- **Avoid division by zero**: Use `max(1, len(collection))` when computing averages
- **Sort with computed metrics**: Build `List[Tuple[item, metric]]`, sort by metric, then extract items
- **Test organization**: Group tests by entity in classes (e.g., `TestCompetence`, `TestMicroCredential`)

## Data Workflows

### Key Datasets
**Blue Social Competences** (University of Szczecin baseline):
- **4 dimensions**: Understanding (A), Digital/Data (B), Sustainability/Resilience (C), Business/Governance (D)
- **16 competences** total mapped across 12 blue economy sectors
- **Location**: `data/derived/Blue Social Competences Univ Szczecin - *.csv`

**Dimension → TMBD Axis Mapping** (in `load_real_competences.py`):
- Dimension A (Understanding) → **OCEANIC** (planetary literacy, systems thinking)
- Dimension B (Digital/Data) → **MARITIME** (infrastructure, technology tools)
- Dimension C (Sustainability) → **MARINE** (ecological, biophysical systems)
- Dimension D (Business/Governance) → **MARITIME** (institutional, economic mediation)

### Data Processing Flow
```
data/raw/ (sources)
  ↓
scripts/build_derived.py (Excel → CSV export)
  ↓
data/derived/ (processed matrices)
  ↓
load_real_competences.py (CSV → Competence objects)
  ↓
CompetenceMapper (in-memory registry)
  ↓
main_real_data.py (analysis & micro-credential design)
```

### Path Expectations
- **main_real_data.py** expects: `data/derived/Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv`
- Script validates path existence and exits gracefully if missing
- **MANIFEST_SOURCES.csv** is auto-generated by `scripts/generate_manifest.py` for provenance tracking
