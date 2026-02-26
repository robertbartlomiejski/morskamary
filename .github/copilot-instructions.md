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
  test_core.py          # Pytest-based unit tests
main.py                 # Demonstration entry point
LLM_CONTEXT_INSTRUCTION.txt  # Domain-specific LLM constraints and protocols
DATA_GOVERNANCE.txt     # FAIR/CARE data governance rules
CITATION.txt            # Citation and provenance guidance
CHANGELOG.txt           # Versioned change log
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

## Running Tests and Tools

```bash
pip install -r requirements.txt
pytest tests/           # run tests
black src/ tests/       # format code
flake8 src/ tests/      # lint
mypy src/               # type-check
```

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
