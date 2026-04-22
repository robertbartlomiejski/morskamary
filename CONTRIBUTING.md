# Contributing to morskamary

Welcome! This guide explains how to set up the development environment and start contributing to the **morskamary** Blue Sociology toolkit.

---

## 1. Prerequisites

- **Python ≥ 3.9** (check with `python --version`)
- **Git**
- **Node.js ≥ 18** (optional, required only for GitHub Copilot MCP integration)

### Windows quick install (winget)

If you are setting up a Windows workstation from scratch, you can install the
recommended toolchain with:

```powershell
winget install --id Git.Git
winget install --id OpenJS.NodeJS.LTS
winget install --id Python.Python.3.14
winget install --id Microsoft.DotNet.SDK.10
winget install --id GitHub.cli
```

### Verifying Python Installation

```bash
python --version
# or on Windows
py --version
```

If Python is not installed:
1. Download from https://python.org (version 3.9 or higher)
2. **Important**: Check "Add Python to PATH" during installation
3. Restart your terminal/command prompt

### Verifying Node.js Installation (Optional)

Node.js is only required if you plan to use the GitHub Copilot MCP integration for full-context research workflows.

```bash
node -v
```

If Node.js is not installed and you need MCP features:
1. Download from https://nodejs.org (LTS version recommended)
2. Restart your terminal/command prompt
3. See [COPILOT_MCP_SETUP.md](COPILOT_MCP_SETUP.md) for complete MCP setup

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

All 8 tests should pass. Then run the demo entry point:

```bash
python main.py
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
  core.py               # Data structures: Competence, MicroCredential, BlueDynamicsAxis, CompetenceLevel
  competence_mapper.py  # CompetenceMapper: add/query competences and credentials
tests/
  test_core.py          # Pytest unit tests
main.py                 # Demonstration entry point
data/                   # Source datasets (CSV, XLSX)
docs/                   # Policy and literature references
manuscripts/            # Research drafts
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
