# morskamary agent task contract

Treat this repository as publication-oriented Blue Sociology research infrastructure, not a demonstration project.

Before changing anything, read:

- `.github/copilot-instructions.md`
- `docs/AGENT_WORKING_AGREEMENT.md`
- `config/live_query_protocol.yml`
- applicable `.github/instructions/*.instructions.md`

Start every task by recording:

- current branch and base SHA;
- relevant open PRs and overlapping files;
- objective and paths in scope;
- authoritative scientific/configuration source;
- acceptance criteria;
- validation commands.

Use one branch and one draft PR per coherent objective. Never push directly to `main`, and do not duplicate active PR work on overlapping paths.

Preserve the canonical four-axis QMBD contract:

- `MARINE` / `M`
- `MARITIME` / `T`
- `OCEANIC` / `O`
- `HYDRONIZATION` / `H`

Maintain the scientific chain:

theory -> research question/hypothesis -> construct -> variable -> indicator -> measure -> evidence -> method -> result -> interpretation -> contribution.

Keep evidence, inference, hypothesis outcome, interpretation and recommendation separate. Query text and `source_query` are retrieval/provenance data, not empirical evidence. Fixtures prove software behavior only and do not prove live-provider success.

Never reveal or print a secret. Never print `.env` contents. Secret checks may report only present, absent, invalid, rate-limited or configured.

Live scientific acquisition must run only through the reviewer-protected `live-research` GitHub Environment. `.github/workflows/copilot-setup-steps.yml` must remain `contents: read` and must not receive production provider credentials.

Before committing, inspect the git diff for unrelated user changes, add or update focused tests, update `CHANGELOG.txt` when required, regenerate `MANIFEST_SOURCES.csv` for new/removed/renamed files, and run the smallest relevant validation. Substantive Python changes additionally require:

```bash
python -m flake8 src scripts tests run_full_analysis.py main.py
python -m mypy src scripts run_full_analysis.py main.py
python -m pytest tests/ -v
python scripts/validate_generated_outputs.py
python scripts/validate_run_archive_integrity.py --archive-root outputs/run_archive --require-present
```

If blocked, report the exact blocker, affected file or workflow, evidence, safest next action, and the command or setting the maintainer should use.
