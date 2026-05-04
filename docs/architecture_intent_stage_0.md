# Architecture Intent Note — Stage 0: Baseline Lock-In

**Date:** 2026-05-01  
**Status:** Internal / Baseline  
**Lead Agent:** morskamary Lead Agent (Manus)

## 1. Purpose
This document freezes the current architectural assumptions of the `morskamary` repository before any automated enforcement or refactoring occurs. It serves as the "ground truth" for the transition from a static analytical script to a research-grade infrastructure.

## 2. Current State Assumptions
- **Core Logic:** The Tripartite Model of Blue Dynamics (TMBD) is the primary analytical framework.
- **Execution:** Python 3.11+ is the required environment; `run_full_analysis.py` is the main entry point.
- **Data:** 15 baseline competences (University of Szczecin) + ~451 literature-derived competences.
- **Sectors:** 12 canonical sectors are currently hardcoded but are being transitioned to an emergent topology.
- **Tooling:** PowerShell scripts handle local workstation orchestration and API smoke tests.

## 3. Transition Strategy
- **Additive Approach:** All new governance and logic will be added as layers (docs, schemas, then CI) to avoid breaking existing research workflows.
- **Conflict Prevention:** No code refactors will be performed until the "Human Contracts" (Stage 1) are signed off via documentation.
- **Triangulation Goal:** The end state must achieve a seamless triangulation between local CSV data, Crossref/API sources, and qualitative sociological theory.

## 4. Self-Note for Stage 1
> *Do not introduce any automation until expectations are written in plain language in the `docs/` directory. Focus on the "Human Contracts" first.*
