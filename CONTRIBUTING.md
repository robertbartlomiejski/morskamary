# Contributing to morskamary

Welcome! This guide explains how to set up the development environment and start contributing to the **morskamary** Blue Sociology toolkit.

---

## 1. Prerequisites

- **Python ≥ 3.10** (check with `python --version`)
- **Git**
- **Node.js ≥ 18** (optional, required only for GitHub Copilot MCP integration)

### Verifying Python Installation

```bash
python --version
# or on Windows
py --version
```

If Python is not installed:
1. Download from https://python.org (version 3.10 or higher)
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

### Codex CLI shell completion (optional)

If you use the Codex CLI, enable completions for your shell (choose one):

```bash
codex completion bash
# OR
codex completion zsh
# OR
codex completion fish
```

---

## 2. Clone the repository

```bash
git clone https://github.com/robertbartlomiejski/morskamary.git
cd morskamary
```

---

## 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

---

## 4. Verify the setup

Run the test suite to confirm everything works:

```bash
python -m pytest tests/
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
python -m flake8 src scripts tests run_full_analysis.py main.py
```

### Type-check

```bash
python -m mypy src scripts run_full_analysis.py main.py
```

### Run tests

```bash
python -m pytest tests/ -v
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

## 10. Codex shell completion details

You can generate shell completion scripts directly from the Codex CLI.

### Generate completion scripts

Run the exact command for your shell:

```bash
codex completion bash
codex completion zsh
codex completion fish
```

### Persistent install

#### Bash

Write completion output to the standard per-user completions path:

```bash
mkdir -p ~/.local/share/bash-completion/completions
codex completion bash > ~/.local/share/bash-completion/completions/codex
```

> Note: Some distros use a different completion directory (for example `/etc/bash_completion.d/` for system-wide installation).

#### Zsh

Write the completion function to a directory on `$fpath` (example: `~/.zfunc`), then initialize completion:

```bash
mkdir -p ~/.zfunc
codex completion zsh > ~/.zfunc/_codex

# ensure ~/.zfunc is in fpath (e.g. in ~/.zshrc)
fpath=(~/.zfunc $fpath)
autoload -Uz compinit && compinit
```

#### Fish

Write completion output to Fish's user completions directory:

```bash
mkdir -p ~/.config/fish/completions
codex completion fish > ~/.config/fish/completions/codex.fish
```

### Verify completion is active

- **Zsh/Bash function check**:

```bash
type _codex
```

- **Interactive completion smoke test**:
  - Open a new shell session.
  - Type `codex ` and press <kbd>TAB</kbd> to verify suggestions appear.

### Troubleshooting

- If completion does not load, confirm your shell startup file actually runs in your session type:
  - **Bash login shell**: `~/.bash_profile` or `~/.profile`
  - **Bash interactive non-login shell**: `~/.bashrc`
  - **Zsh**: `~/.zshrc`
  - **Fish**: `~/.config/fish/config.fish`
- After editing startup files, start a **new terminal session** (or `source` the file) and test again.
- Ensure the target completion file exists at the expected path and has readable permissions.

---

## 11. Questions?

Open an issue on GitHub or consult `LLM_CONTEXT_INSTRUCTION.txt` for domain-specific guidance on competence mapping and micro-credential design.
