# Copilot Instructions for morskamary

## Repository purpose

This repository is an evidence base and working research environment for **Blue Sociology** and the **One Ocean Economy**. It supports:

- Competence mapping and micro-credential design grounded in EU blue economy policy.
- Application of the **Tripartite Model of Blue Dynamics (TMBD)**: Marine (M), Maritime (T), and Oceanic (O) axes.
- Integration with large language models (ChatGPT, Gemini) for semantic analysis, article drafting, and credential design.

The primary maintainer is an early-stage researcher. Keep all suggestions simple, well-explained, and beginner-friendly.

## Key files to read before helping

| File | Purpose |
|------|---------|
| `LLM_CONTEXT_INSTRUCTION.txt` | Master prompt rules for any LLM working in this repo. Always follow its non-negotiable constraints. |
| `DATA_GOVERNANCE.txt` | FAIR/CARE data rules. Respect data class (A–D) distinctions. |
| `CITATION.txt` | How to cite sources. Always cite original documents first. |
| `CHANGELOG.txt` | Record substantive changes here with date, type, and reason. |
| `README.md` | High-level project logic and inventory of sources. |

## Code conventions

- **Language**: Python 3.9+.
- **Style**: PEP 8, formatted with `black` (line length 88). Run `black src/ tests/` before committing.
- **Linting**: `flake8 src/ tests/`.
- **Type hints**: Encouraged but not enforced. Follow patterns in `src/core.py`.
- **Tests**: Place in `tests/`, prefix files with `test_`. Run with `pytest tests/`.
- **Dependencies**: Declare in `pyproject.toml`. Before adding a new package run `pip-audit` (or check https://osv.dev) to verify it has no known vulnerabilities.

## Domain conventions

- Apply the **TMBD** (M / T / O) classification to every competence, sector, or learning outcome.
- Start competence work from `Blue Social Competences Univ Szczecin` matrices.
- Every new substantive claim needs a source quote and a locator (file name + page/section).
- Mark unsupported claims as `[citation needed]`. Do not invent citations.
- Record any structural change to governance files or data in `CHANGELOG.txt`.

## LLM / AI integration guidance

When the user asks for ChatGPT or Gemini integration:

1. Prefer the **OpenAI Python SDK** (`openai`) or **Google Generative AI SDK** (`google-generativeai`) — both are pip-installable.
2. Read `LLM_CONTEXT_INSTRUCTION.txt` at runtime and pass it as the system prompt so the model respects evidence discipline and no-hallucination rules.
3. Keep API keys in environment variables (`.env` file, never committed). Use `python-dotenv` to load them.
4. Implement a simple `query_llm(system_prompt, user_message)` helper in `src/` following the patterns already in `src/core.py`.
5. Log every LLM call with timestamp, model name, and token count for traceability.

## What Copilot should not do

- Do not invent author names, legal references, or empirical findings.
- Do not overwrite Class A (raw source) files.
- Do not commit secrets, API keys, or personal data.
- Do not remove or skip CHANGELOG updates when changing tracked artifacts.
