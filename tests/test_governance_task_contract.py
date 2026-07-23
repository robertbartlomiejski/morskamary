from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_root_agents_declares_required_task_start_contract() -> None:
    content = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    for token in (
        ".github/copilot-instructions.md",
        "docs/AGENT_WORKING_AGREEMENT.md",
        "config/live_query_protocol.yml",
        "current branch and base SHA",
        "relevant open PRs and overlapping files",
        "validation commands",
        "live-research",
        "Never print `.env` contents.",
    ):
        assert token in content


def test_pr_template_requires_start_state_and_validation_reporting() -> None:
    content = (REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(
        encoding="utf-8"
    )

    for token in (
        "### Current branch / base SHA",
        "### Relevant open PRs / overlapping files",
        "### Paths in scope",
        "### Authoritative scientific/configuration source",
        "### Acceptance criteria",
        "### Validation commands",
        "Generated artifacts, manifests, and checksums remain complete where applicable",
        "A regression test demonstrates the previous failure mode",
        "This PR body states exactly what was and was not validated",
    ):
        assert token in content
