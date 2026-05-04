# Onboarding a New Research Source Provider

This document describes the **human process** for adding a new bibliographic data
source to the morskamary research pipeline. It is a checklist of decisions and
actions, not a code template.

Read this document before writing any code. The decisions made here determine
what gets implemented and what constraints apply permanently.

---

## Before you start — mandatory questions

Answer all of these before touching any file in the repository.

### 1. Is this provider open or institutional?

- **Open** — data is freely available without a subscription (e.g., Crossref,
  OpenAlex, DOAJ). You may activate this for any contributor.
- **Institutional** — data requires a paid subscription or IP entitlement
  (e.g., Scopus, Web of Science, SciVal). Activating this gives access only
  to contributors with the relevant institutional credentials. It must not be
  assumed to work for everyone.
- **Personal** — data comes from a personal or team document store
  (e.g., Google Drive, OneDrive). It will only work for the specific person
  or organisation that owns the credential.

Record this in the provider's `SourceCapability.licence_note`.

### 2. What metadata fields are permitted to be stored?

For every field the provider can return, explicitly decide:

- **Store** — this field is open or licensed for redistribution.
- **Do not store** — this field is copyrighted, personal data, or restricted
  by the provider's terms of use.

If you are unsure about a field, the answer is **do not store** until you have
confirmed with the licence. See `docs/licensing_and_compliance.md` for the
principles.

Record permitted fields in `SourceCapability.allowed_metadata_fields`.

### 3. Does the provider require a credential?

- If yes: what type (API key, OAuth, multi-part Azure credentials)?
- Where will it be stored for local use (`.env` file, excluded by `.gitignore`)?
- Where will it be stored for CI use (GitHub Actions Secrets)?
- Has anyone confirmed the secret will never be committed?

### 4. Is a live API call safe to make in CI?

By default, no new provider should make live API calls in the primary CI workflow
(`ci.yml`). Live calls belong in `research-api-smoke.yml` (triggered manually)
or `export-research-records.yml`.

If you answer yes: confirm that the call is rate-limit-safe, will not consume
billed quota unnecessarily, and will not fail the build when credentials are absent.

### 5. Does this provider add coverage that none of the existing providers have?

If the coverage overlaps substantially with Crossref, Scopus, or Web of Science,
consider whether a new provider is necessary, or whether better queries on an
existing provider would suffice.

---

## Step-by-step process

### Step 1 — Record the decision in this document

Before writing any code, add a new section at the end of this document describing:

- Provider name and organisation
- Open / institutional / personal classification
- Permitted metadata fields (with justification)
- Credential type and storage plan
- Reason for adding (what gap does it fill)
- TMBD relevance (which axes does it primarily serve)

Commit this document update on its own, before any code changes. This creates an
auditable record of the intent, separate from the implementation.

### Step 2 — Create the provider module

Create `src/scientific_sources/<provider_name>.py` implementing `BaseProvider`
(`src/scientific_sources/base.py`).

Required methods:

- `capability` property — returns a `SourceCapability` with `name`, `provider`,
  `requires_secret`, `configured`, `live_test_allowed`, `allowed_metadata_fields`,
  and `licence_note` filled in.
- `search(query, max_results)` — returns a `ProviderResult`. If not configured,
  call `self._not_configured_result()` and return immediately. Never fabricate
  metadata.
- `verify_doi(doi)` — returns a `ProviderResult` with at most one record.

Key rules:

- The `configured` flag must check for the credential at import time using
  `os.environ.get(...)`. Do not raise an exception if the credential is absent.
- Normalise all records into `LiteratureRecord`. Do not pass provider-specific
  objects to callers.
- Only populate `LiteratureRecord` fields that are in `allowed_metadata_fields`.
  Leave others as empty string or `None`.

### Step 3 — Register the provider in SourceRegistry

Add the new provider to the `_providers` list in
`src/scientific_sources/source_registry.py`.

The order of this list determines the order of results in `SourceRegistry.search()`.
Place open/always-configured providers before institutional ones.

### Step 4 — Update docs/providers.md

Add a row to the summary table and a full provider section to `docs/providers.md`.
Use the same format as the existing entries.

### Step 5 — Write tests

Add tests for the new provider in `tests/test_scientific_sources.py` or a new
dedicated test file.

Minimum test cases:

- `test_<name>_not_configured_returns_provider_result` — confirm that calling
  `search()` without credentials returns a `ProviderResult` (not an exception)
  with `records == []` and `warnings` containing an explanatory message.
- `test_<name>_capability_reflects_configuration_state` — confirm that
  `SourceCapability.configured` is `False` when the credential env var is absent.
- Mock-based tests for `search()` and `verify_doi()` using a patched HTTP client.

Live API tests are not run in the primary CI. If you write live tests, gate them
with `pytest.mark.skipif(not os.environ.get("LIVE_RESEARCH_API_TESTS"), ...)`.

### Step 6 — Add environment variable documentation

Add the new credential to the table in `docs/RESEARCH_API_CICD_SETUP.md` and to
the credential bootstrap script `scripts/bootstrap_research_secrets.sh` (and the
PowerShell equivalent).

### Step 7 — Update CHANGELOG.txt

Record the addition following the established format: date, change type (add),
scope (scripts and src), files affected, summary, reason, impact.

---

## What not to do

- **Do not** add a live API call to `ci.yml` without a fallback that passes
  when the credential is absent.
- **Do not** store fields that are not in `allowed_metadata_fields`, even if
  the provider API returns them.
- **Do not** commit credentials, OAuth JSON files, or client secrets under any
  circumstances.
- **Do not** create a provider that raises an exception when unconfigured — use
  `_not_configured_result()`.
- **Do not** make a provider depend on a specific third-party library without
  first checking whether it is already in `requirements.txt` / `pyproject.toml`.

---

## Providers added through this process

*This section is updated each time a new provider is onboarded.*

| Provider | Date added | Classification | Added by |
|---|---|---|---|
| Crossref | pre-Stage 1 | Open | Initial build |
| Elsevier / Scopus | pre-Stage 1 | Institutional (stub) | Initial build |
| Web of Science | pre-Stage 1 | Institutional (stub) | Initial build |
| SciVal | pre-Stage 1 | Institutional (stub) | Initial build |
| Google Drive | pre-Stage 1 | Personal (stub) | Initial build |
| Microsoft Graph | pre-Stage 1 | Personal / Enterprise (stub) | Initial build |
