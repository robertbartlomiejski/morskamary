# Data Providers and Bibliographic Sources

## Current Providers
1. **University of Szczecin:** Baseline Blue Social Competences (CSV).
2. **Crossref API:** Live bibliographic metadata and DOI verification.
3. **EU Blue Economy Reports (2025-2026):** Contextual triangulation for sector trends.

## Provider Requirements
- All providers must be documented in `CITATION.txt`.
- API calls must implement the **Manus Resilience Logic** (retries and latency handling).
- Data must be mapped to the TMBD axes before integration into the `competences_full_database.json`.
