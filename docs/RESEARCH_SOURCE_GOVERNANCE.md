# Research Source Governance

This document explains what external bibliographic metadata may and may not
be stored in the morskamary repository, in accordance with DATA_GOVERNANCE.txt
and the FAIR/CARE principles.

## Permissible metadata fields

The following fields may be stored for any literature record, regardless of
the source provider, provided they are bibliographic (not full-text) data:

| Field | Notes |
|---|---|
| `title` | Full title of the work |
| `authors` | Author name string (family, given) |
| `year` | Publication year |
| `doi` | Digital Object Identifier |
| `journal` / `venue` | Publication venue name |
| `url` | Persistent URL or DOI link |
| `subject_terms` | Keywords/subject classifications |
| `citation_count` | Aggregated citation count (if licensed) |
| `source_id` | Internal identifier (provider:doi format) |
| `provider` | Name of the source provider |
| `retrieval_timestamp` | ISO 8601 timestamp of retrieval |
| `licence_note` | Licence constraint note for this record |

## Prohibited fields

The following MUST NOT be stored in derived outputs committed to the repository:

| Field | Reason |
|---|---|
| Full abstract text | Copyrighted by publisher; redistribution requires explicit licence |
| Full-text body | Copyrighted; never permitted without explicit licence |
| Affiliation institutional data | May constitute personal data under GDPR |
| Author contact information | Personal data — prohibited by DATA_GOVERNANCE.txt |
| Restricted analytics payloads | WoS/Scopus/SciVal raw database exports |
| OAuth tokens, API keys | Secrets — must never be committed |

## Provider-specific notes

### Crossref
- All bibliographic metadata from Crossref is freely redistributable.
- Abstract text is not returned by default by the Crossref works API.
- Store: title, authors, year, DOI, journal, URL.

### Elsevier / Scopus
- Store only: title, authors, year, DOI, journal, URL, citation count,
  subject terms.
- Do NOT store: full abstracts, full article text, affiliation details,
  or any Scopus database payload unless your institutional licence
  explicitly permits redistribution.

### Web of Science (Clarivate)
- Same constraints as Elsevier/Scopus.
- Aggregated citation counts (Citing Articles count) may be stored if
  permitted by your institutional licence.

### SciVal (Elsevier)
- Store only: aggregated bibliometric indicators, topic cluster labels,
  and anonymised institutional summary data.
- Do NOT store: raw SciVal export files or researcher-level metrics
  that could identify individuals.

### Google Drive / Microsoft OneDrive
- Store only: sanitized metadata exported from local research folders
  (title, year, DOI, file identifier).
- Do NOT commit OAuth credentials or Drive file contents.

## Derived output provenance

Every derived output file must include:
- Source provider name
- Retrieval timestamp (ISO 8601)
- Query string used
- Provenance hash (SHA-256 prefix of title|doi|provider|query)

Use `src/scientific_sources/provenance.py` to generate provenance records.

## FAIR principles application

- **Findable**: All stored records include DOI or persistent URL.
- **Accessible**: Crossref metadata is open; proprietary data is
  capability-gated and documented.
- **Interoperable**: Records are normalized into `LiteratureRecord` dataclass
  regardless of source provider.
- **Reusable**: Licence notes are stored per record; prohibited fields
  are never committed.

## Reporting concerns

If you believe a committed output file contains restricted data, open an issue
immediately and reference DATA_GOVERNANCE.txt section on "Removing sensitive
data from Git history".
