# Repository Guardrails for Coding Agents Working in morskamary

This repository is a Python-first evidence and derived-data project for Blue Sociology, TMBD-informed competence mapping, micro-credential design, and related blue economy analysis. Treat the repository as an evidence base first, not as a generic dev-environment playground.

## 1. Core Execution Hierarchy

Use `main_real_data.py` as the **primary substantive results script** whenever the task is to generate, inspect, summarize, or validate repository outputs. This script is tied to real repository data and the University of Szczecin baseline.

Use `demo_workspace_instructions.py` only as a **secondary validation, demonstration, and workflow-check script**. Do not present its outputs as the main empirical or repository-defining results when `main_real_data.py` is available.

Treat `setup_one_click.ps1` and `docker compose up --build` as execution helpers, not as substitutes for evidence interpretation.

## 2. Evidence Discipline

Prefer outputs grounded in committed repository data, especially the Blue Social Competences baseline and other verified derived datasets named in the repository.

Do not invent evidence, competences, sectors, mappings, or legal claims. If evidence is missing, state that it is missing and leave a placeholder rather than fabricating support.

When introducing a new term, mapping, or micro-credential element, justify it against a verified repository source or explicitly label it as a proposed extension.

Do not overwrite baseline source files merely to add interpretation. Create new derived files for weighted matrices, gap analyses, summaries, and exports.

## 3. Dependency Discipline

**Do not introduce Node.js as a repository dependency** unless a verified repository file explicitly requires it.

Treat Python as the repository's core execution environment unless and until the repository itself changes.

Treat Node-based MCP servers or related tooling only as **optional local workstation tools**, not as default project requirements.

## 4. Separation of Repository and Workstation

Keep repository artifacts portable. Do not commit machine-specific paths, secrets, personal access tokens, local cloud-sync assumptions, or environment-bound credentials.

If assistant-access tooling is added, prefer portable templates and documentation over hard-coded local configuration.

Do not commit Google Drive credentials, SharePoint paths, local OneDrive paths, or similar private workstation details into the main repository.

## 5. Priority Order for Repository Improvement

**First priority** is derived-data value. Improve scripts and outputs that turn the existing evidence base into analytically useful results, especially sector-weighted competence matrices, proficiency differentiation, gap-analysis tables, and exportable summaries.

**Second priority** is provenance and governance. Strengthen citation guidance, data-governance notes, changelog traceability, and source manifest discipline.

**Third priority** is minimal assistant-access support. Only after the real-data and provenance layers are working cleanly should local assistant-access templates be considered.

## 6. Minimal Assistant-Access Principle

If assistant integration support is added, keep it minimal and local by default.

The preferred first phase is a local template that can read the morskamary repository and, if necessary, one synchronized research folder.

Google Drive connectors, scientific database bridges, broader MCP stacks, and multi-source orchestration are **second-phase optional tooling**. They are not default repository infrastructure.

## 7. Workflow Justification Rule

Before adding any Copilot, MCP, or agent-related configuration to the repository, justify it against a concrete morskamary workflow. Valid examples include literature extraction, competence mapping, EMODnet analysis, micro-credential generation, provenance tracking, derived-table creation, and real-data result export.

If a proposed integration does not measurably improve one of those workflows, do not add it.

## 8. Real-Data Precedence Rule

When both a demonstration path and a real-data path exist, always prefer the real-data path for reporting repository outputs.

For this repository, `main_real_data.py` has precedence over `demo_workspace_instructions.py` for substantive reporting because it loads real Blue Social Competences from CSV and produces TMBD distribution, mapping summary, gap analysis, pathway suggestions, and final key statistics.

## 9. Reporting Rule

When presenting outputs, distinguish clearly between:
- verified baseline data,
- derived analytical outputs,
- demonstration outputs,
- proposed future extensions.

Never blur those categories.

## 10. Safe Extension Rule for Competence Architecture

The current Blue Social Competences baseline is a transversal baseline. Extend it by creating new derived files for sector-specific weighting, proficiency targets, and competence-status encoding.

Do not rewrite the baseline merely to force specialization into the original file.

## 11. Quality Rule

High-quality output in this repository means:
- real-data grounded,
- source-traceable,
- TMBD-consistent,
- portable across workflows,
- clear about what is verified versus proposed,
- and reproducible through the repository's Python-first execution path.

## 12. Default Operational Behavior for Agents

On first pass, read `README.md`, `main_real_data.py`, `setup_one_click.ps1`, `requirements.txt`, and the relevant derived data files before proposing infrastructure changes.

If the task is about outputs, run or inspect the real-data path first.

If the task is about architecture, preserve repository portability and keep workstation orchestration out of committed core files unless explicitly requested.
