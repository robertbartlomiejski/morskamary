# Data Providers — What They Are and Why They Exist

This document describes every scientific data source provider registered in
`src/scientific_sources/source_registry.py`. It explains what each provider is,
what it can return, whether it requires credentials, and what constraints apply
to stored data.

For the technical rules about which metadata fields may be stored per provider,
see `docs/RESEARCH_SOURCE_GOVERNANCE.md`.

For the licence principles that govern all providers, see
`docs/licensing_and_compliance.md` — that document translates the authoritative
rules in `DATA_GOVERNANCE.txt` into plain English for contributors.

---

## Stage 1 compliance filter

All exports from provider pipelines pass through `_to_stage1_compliant_dict()`
in `scripts/export_live_research_records.py`. This whitelist-based filter
enforces the "bibliographic metadata only" rule regardless of provider category:

| Field dropped | Reason |
|---|---|
| `citation_count` | Restricted redistribution under Category 2/3 provider terms (see `docs/licensing_and_compliance.md` — Institutional and Personal/Enterprise provider categories) |
| `abstract_available` | Internal flag — not a bibliographic fact; must not appear in outputs |
| `abstract_stored` | Internal flag — same reason as above |

`licence_note` is added to every CSV row to satisfy FAIR/CARE provenance
requirements. The filter is the programmatic enforcement of the rules described
in `docs/licensing_and_compliance.md` (Categories 1–3).

---

## Cumulative triangulation

`src/cumulative_analysis/triangulator.py` merges static baseline data
(CSV snapshots from `data/derived/`) with live provider records retrieved at
query time. Each record carries a `ClaimOrigin` label:

| Origin | Source | Priority |
|---|---|---|
| `DYNAMIC_API_CROSSREF` | Live Crossref API call | Higher — upgrades static record on DOI match |
| `STATIC_BASELINE` | CSV snapshot (e.g., University of Szczecin baseline) | Lower |

Deduplication is DOI-first; title-based fallback uses exact matching on
normalized titles (with punctuation stripped and whitespace collapsed). The
triangulated output contains only Stage 1-compliant fields.

---

## How providers work in this repository

All providers implement the same interface (`src/scientific_sources/base.py`):

- `search(query, max_results)` — returns a `ProviderResult` with normalised
  `LiteratureRecord` objects.
- `verify_doi(doi)` — looks up a single record by DOI.
- If a provider is not configured (missing credentials), it returns a structured
  "not configured" result without raising an exception. It never fabricates
  metadata.

All records are normalised into the same `LiteratureRecord` dataclass regardless
of provider. This means downstream analysis code is decoupled from provider-specific
formats.

---

## Provider directory

### 1. Crossref

| Property | Value |
|---|---|
| Module | `src/scientific_sources/crossref.py` |
| Credential required | No (optional `CROSSREF_MAILTO` for polite-pool rate limits) |
| Always configured | Yes |
| Live API | Yes — Crossref REST API (open, no institutional subscription needed) |
| Implementation status | Fully implemented |

**Why it exists:**
Crossref is the canonical open bibliographic metadata registry for scholarly
publishing. It covers the majority of peer-reviewed literature relevant to Blue
Sociology and EU blue economy policy, including journal articles, book chapters,
and reports. It is the only provider that works without any credentials, making
it the foundation of the offline-safe research pipeline.

**What it can return:**
Title, authors, year, DOI, journal/venue name, URL, subject terms.

**What it cannot return:**
Full abstracts, full text, citation counts, access-restricted analytics.

**Constraints:**
All Crossref bibliographic metadata is freely redistributable. Abstract text is
not returned by the default API and must not be fabricated. Set `CROSSREF_MAILTO`
to an institutional email address to access the polite pool (better rate limits).

---

### 2. Elsevier / Scopus

| Property | Value |
|---|---|
| Module | `src/scientific_sources/elsevier_scopus.py` |
| Credential required | Yes — `ELSEVIER_API_KEY` and/or `SCOPUS_API_KEY` |
| Always configured | No |
| Live API | Stub — architecture in place, live calls not yet implemented (Phase 2) |
| Implementation status | Capability-gated stub; returns structured "not configured" when key absent |

**Why it exists:**
Scopus is one of the two dominant citation databases for social-science and
maritime research. It provides citation counts, subject classifications, and
institutional affiliation metadata not available from Crossref. The architecture
is in place so that researchers with institutional Elsevier subscriptions can
activate the provider by adding credentials, without changing any code.

**What it can return (when configured and licensed):**
Title, authors, year, DOI, journal, URL, citation count, subject terms.

**What it cannot return:**
Full abstracts (redistribution requires explicit institutional licence), full-text
body, affiliation institutional data (personal data risk), raw Scopus database
exports.

**Constraints:**
Institutional subscription and IP entitlement required. Do not store full abstracts
or affiliation data. Check your institution's Elsevier licence before activating.

---

### 3. Web of Science (Clarivate)

| Property | Value |
|---|---|
| Module | `src/scientific_sources/web_of_science.py` |
| Credential required | Yes — `WOS_API_KEY` |
| Always configured | No |
| Live API | Stub — architecture in place, live calls not yet implemented (Phase 2) |
| Implementation status | Capability-gated stub |

**Why it exists:**
Web of Science is the standard citation index for natural and social science
research, with strong coverage of maritime, fisheries, and environmental
sociology literature. It complements Scopus with different indexing scope and
citation graph coverage.

**What it can return (when configured and licensed):**
Title, authors, year, DOI, journal, URL, aggregated citation counts.

**Constraints:**
Same constraints as Elsevier/Scopus. Do not store raw WoS database payloads.
Aggregated citation counts may be stored if your institutional licence explicitly
permits redistribution.

---

### 4. SciVal (Elsevier)

| Property | Value |
|---|---|
| Module | `src/scientific_sources/scival.py` |
| Credential required | Yes — `SCIVAL_API_KEY` |
| Always configured | No |
| Live API | Stub — architecture in place, live calls not yet implemented (Phase 2) |
| Implementation status | Capability-gated stub |

**Why it exists:**
SciVal provides aggregated bibliometric indicators and topic cluster labels for
institutions and research groups. It is relevant for mapping blue economy research
productivity at the institutional level — for example, assessing how a university's
maritime research portfolio maps to QMBD axes.

**What it can return (when configured and licensed):**
Aggregated bibliometric indicators, topic cluster labels, anonymised institutional
summary data.

**What it cannot return:**
Raw SciVal export files, researcher-level metrics that could identify individuals.

**Constraints:**
SciVal entitlement requires a separate subscription beyond standard Elsevier access.
Only store aggregated data. Do not store individual researcher analytics.

---

### 5. Google Drive

| Property | Value |
|---|---|
| Module | `src/scientific_sources/google_drive.py` |
| Credential required | Yes — `GOOGLE_DRIVE_OAUTH_CREDENTIALS` (path to local OAuth JSON) |
| Always configured | No |
| Live API | OAuth-gated; no live calls in CI |
| Implementation status | Capability-gated stub |

**Why it exists:**
This provider allows researchers to index and search local research document
collections stored in Google Drive — for example, working draft folders,
institutional report archives, or curated PDF collections that are not publicly
indexed. It is a personal productivity integration, not a public data source.

**What it can return (when configured):**
Sanitised metadata exported from local research folders: title, year, DOI (if
available), file identifier.

**Constraints:**
Never commit OAuth credentials or Drive file contents to the repository. The
OAuth JSON file must remain in a location excluded by `.gitignore`. Drive file
contents are not bibliographic records and must not be stored as research outputs
without sanitisation.

---

### 6. Microsoft Graph (OneDrive / SharePoint)

| Property | Value |
|---|---|
| Module | `src/scientific_sources/microsoft_graph.py` |
| Credential required | Yes — `MICROSOFT_TENANT_ID`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` |
| Always configured | No |
| Live API | Azure App Registration required; no live calls in CI |
| Implementation status | Capability-gated stub |

**Why it exists:**
This provider allows access to research documents stored in Microsoft OneDrive or
SharePoint — the common document storage for European academic institutions using
Microsoft 365. It mirrors the function of the Google Drive provider for
Microsoft-ecosystem users.

**What it can return (when configured):**
Sanitised metadata from OneDrive/SharePoint folders: title, year, DOI, file
identifier.

**Constraints:**
Never commit Azure client secrets. The client secret must be stored as a GitHub
Actions secret or in a local `.env` file excluded by `.gitignore`. Do not commit
OAuth credentials or SharePoint file contents.

---

## Summary table

| Provider | Open? | Credentials | Status | QMBD axis relevance |
|---|---|---|---|---|
| Crossref | Yes | None required | Fully implemented | All axes — broadest coverage |
| Elsevier / Scopus | No | Institutional | Stub (Phase 2) | Maritime (T), Oceanic (O) |
| Web of Science | No | Institutional | Stub (Phase 2) | Marine (M), Maritime (T) |
| SciVal | No | Institutional | Stub (Phase 2) | All axes — institutional analytics |
| Google Drive | Personal | OAuth JSON | Stub | Any — personal collections |
| Microsoft Graph | Personal / Enterprise | Azure App | Stub | Any — institutional collections |

The four QMBD axes are: Marine (M), Maritime (T), Oceanic (O), and Hydronization (H).
The single-letter codes follow the established convention: 'M' for Marine, 'T' for
Maritime (first letter of the root term *Terminologia*/*Techno-economic*, chosen to
avoid collision with 'M'), 'O' for Oceanic, and 'H' for Hydronization. These codes
are canonical in `src/core.py` (`BlueDynamicsAxis` enum).
Records retrieved from any provider are classified against these axes by
`src/axis_classifier.py` after passing through the Stage 1 compliance filter.

---

## Adding a new provider

See `docs/onboarding_new_provider.md` for the step-by-step human process.
