# Contributing to morskamary

Welcome! This guide explains how to set up the development environment and start contributing to the **morskamary** Blue Sociology toolkit.

---

## 1. Prerequisites

- **Python ≥ 3.9** (check with `python --version`)
- **Git**

---

## 2. Clone the repository

```bash
git clone https://github.com/robertbartlomiejski/morskamary.git
cd morskamary
```

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

To also install development tools (formatter, linter, type checker):

```bash
pip install black flake8 mypy
```

---

## 4. Verify the setup

Run the test suite to confirm everything works:

```bash
pytest tests/
```

All tests should pass (currently 31). Then run the demo entry point:

```bash
python main.py
```

To run the full analysis pipeline:

```bash
python run_full_analysis.py
```

---

## 5. Development workflow

### Format code

```bash
black src/ tests/
```

### Lint

```bash
flake8 src/ tests/
```

### Type-check

```bash
mypy src/
```

### Run tests

```bash
pytest tests/ -v
```

---

## 6. Project structure

```
src/
  core.py                   # Data structures: Competence, MicroCredential, BlueDynamicsAxis, CompetenceLevel
  competence_mapper.py      # CompetenceMapper: add/query competences and credentials
  literature_extractor.py   # Parse combined_*.csv files → Competence objects with TMBD axis mapping
  gap_analyzer.py           # Competence gap analysis across 12 Blue Economy sectors
  credential_designer.py    # Auto-design micro-credentials per sector (ECTS, EQF, assessment)
  report_generator.py       # Emit outputs/ HTML/JSON/CSV with GitHub blob hyperlinks
tests/
  test_core.py              # Pytest unit tests for core data structures
  test_full_analysis.py     # Integration tests for the full analysis pipeline
run_full_analysis.py        # Orchestrator: 8-step pipeline → 444 competences, 24 micro-credentials
main.py                     # Demonstration entry point (synthetic data)
data/                       # Source datasets (CSV, XLSX)
docs/                       # Policy and literature references
manuscripts/                # Research drafts
outputs/                    # Generated reports (HTML/JSON/CSV) — created by run_full_analysis.py
```

---

## 7. Domain conventions (TMBD)

Every competence and credential must be assigned to exactly one axis of the **Tripartite Model of Blue Dynamics**:

| Axis | Code | Scope |
|------|------|-------|
| Marine | `M` | Biophysical and ecological agency |
| Maritime | `T` | Techno-economic and institutional mediation |
| Oceanic | `O` | Planetary governance and hydrosocial subjectivity |

See `src/core.py` (`BlueDynamicsAxis`) and `LLM_CONTEXT_INSTRUCTION.txt` for full definitions.

---

## 8. Traceability rules

- Record every meaningful change in `CHANGELOG.txt` with date, type, scope, and reason.
- Cite sources for all competence descriptions (see `CITATION.txt`).
- Follow FAIR principles for any derived datasets (see `DATA_GOVERNANCE.txt`).
- When adding new source documents, update `MANIFEST_SOURCES.csv`.

---

## 9. Docker (optional)

To run the project in a container:

```bash
docker compose up --build
```

---

## 10. Questions?

Open an issue on GitHub or consult `LLM_CONTEXT_INSTRUCTION.txt` for domain-specific guidance on competence mapping and micro-credential design.
