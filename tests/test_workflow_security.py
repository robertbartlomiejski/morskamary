"""Parsed-YAML regression tests for GitHub Actions workflow security.

Asserts across every .github/workflows/*.yml:

1. Every ``actions/checkout`` step sets ``persist-credentials: false``.
2. Every job that references proprietary provider secrets declares
   ``environment: live-research`` (reviewer-gated before secrets are exposed).
3. Only explicitly allowlisted jobs receive ``contents: write`` or
   ``pull-requests: write`` permissions.

The tests parse actual YAML so structural changes in any workflow surface
immediately without relying on substring searches that can miss nested keys.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# Provider secret names that require a reviewer-gated environment.
PROVIDER_SECRETS: frozenset[str] = frozenset(
    {
        "CROSSREF_MAILTO",
        "ELSEVIER_API_KEY",
        "SCOPUS_API_KEY",
        "OPENALEX_API_KEY",
        "WOS_API_KEY",
        "SCIVAL_API_KEY",
        "MICROSOFT_TENANT_ID",
        "MICROSOFT_CLIENT_ID",
        "MICROSOFT_CLIENT_SECRET",
    }
)

# Jobs that are explicitly permitted to hold elevated write permissions.
# Key: workflow file stem, Value: set of allowed job IDs.
ALLOWED_WRITE_JOBS: Dict[str, set[str]] = {
    "full-live-analysis": {"commit-outputs"},
    "dependency-submission": {"dependency-submission"},
}


def _load_workflows() -> Dict[str, Any]:
    """Return {filename_stem: parsed_yaml} for every tracked workflow."""
    workflows: Dict[str, Any] = {}
    for wf_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        if wf_path.name == "codeql.yml":
            # CodeQL workflow is managed separately (PR #196); skip.
            continue
        with wf_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        workflows[wf_path.stem] = data
    return workflows


def _checkout_steps_for_job(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Collect all checkout steps from a job definition."""
    results = []
    for step in job.get("steps") or []:
        uses = step.get("uses", "")
        if uses.startswith("actions/checkout@"):
            results.append(step)
    return results


def _job_references_provider_secrets(job: Dict[str, Any]) -> bool:
    """Return True if the job env block references any provider secret."""
    env = job.get("env") or {}
    for value in env.values():
        if not isinstance(value, str):
            continue
        for secret in PROVIDER_SECRETS:
            if secret in value:
                return True
    return False


def _job_write_permissions(job: Dict[str, Any]) -> Dict[str, str]:
    """Return the job-level permissions dict (may be empty if inherited)."""
    return dict(job.get("permissions") or {})


def _effective_write_permissions(
    wf: Dict[str, Any], job: Dict[str, Any],
) -> Dict[str, str]:
    """Return effective permissions by combining workflow and job scopes.

    Job-level permissions override workflow-level when present.  Workflow-level
    ``permissions: write-all`` or string forms are expanded.
    """
    wf_perms: Any = wf.get("permissions") or {}
    job_perms: Any = job.get("permissions") or {}

    # Handle string shorthand forms.
    if isinstance(wf_perms, str):
        if wf_perms == "write-all":
            wf_perms = {"contents": "write", "pull-requests": "write"}
        else:
            wf_perms = {}
    if isinstance(job_perms, str):
        if job_perms == "write-all":
            job_perms = {"contents": "write", "pull-requests": "write"}
        else:
            job_perms = {}

    # Job-level overrides workflow-level when present; otherwise inherit.
    if job_perms:
        return dict(job_perms)
    return dict(wf_perms)


# ---------------------------------------------------------------------------
# Test 1 — every checkout disables persisted credentials
# ---------------------------------------------------------------------------


def test_all_checkouts_set_persist_credentials_false() -> None:
    """Every actions/checkout step in every workflow must set
    persist-credentials: false to prevent credential leakage on runners
    that may also handle proprietary provider secrets.
    """
    violations: List[str] = []
    workflows = _load_workflows()

    for wf_stem, wf in workflows.items():
        for job_id, job in (wf.get("jobs") or {}).items():
            for step in _checkout_steps_for_job(job):
                step_with = step.get("with") or {}
                if step_with.get("persist-credentials") is not False:
                    step_name = step.get("name", step.get("uses", "checkout"))
                    violations.append(
                        f"{wf_stem}.yml / job:{job_id} / step:'{step_name}' "
                        "— persist-credentials is not false"
                    )

    assert not violations, (
        "Workflows with checkout steps missing persist-credentials: false:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Test 2 — jobs with provider secrets declare live-research environment
# ---------------------------------------------------------------------------


def test_provider_secret_jobs_declare_live_research_environment() -> None:
    """Every job that exposes Elsevier/Scopus/WoS/SciVal/Microsoft provider
    secrets in its ``env`` block must declare ``environment: live-research``
    so that a reviewer must approve secret exposure.
    """
    violations: List[str] = []
    workflows = _load_workflows()

    for wf_stem, wf in workflows.items():
        for job_id, job in (wf.get("jobs") or {}).items():
            if not _job_references_provider_secrets(job):
                continue
            env_decl = job.get("environment")
            # environment may be a string or a dict with a ``name`` key.
            if isinstance(env_decl, dict):
                env_name = env_decl.get("name", "")
            else:
                env_name = env_decl or ""
            if env_name != "live-research":
                violations.append(
                    f"{wf_stem}.yml / job:{job_id} "
                    f"— references provider secrets but environment is {env_name!r}"
                )

    assert not violations, (
        "Jobs that reference provider secrets without 'environment: live-research':\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Test 3 — only allowlisted jobs receive write permissions
# ---------------------------------------------------------------------------


def test_only_allowlisted_jobs_have_write_permissions() -> None:
    """Only explicitly allowlisted jobs may declare ``contents: write`` or
    ``pull-requests: write`` at the job level.  All other jobs must operate
    with read-only or no elevated permissions.
    """
    violations: List[str] = []
    workflows = _load_workflows()

    for wf_stem, wf in workflows.items():
        allowed_jobs = ALLOWED_WRITE_JOBS.get(wf_stem, set())
        for job_id, job in (wf.get("jobs") or {}).items():
            perms = _effective_write_permissions(wf, job)
            for perm_key in ("contents", "pull-requests"):
                if perms.get(perm_key) == "write" and job_id not in allowed_jobs:
                    violations.append(
                        f"{wf_stem}.yml / job:{job_id} "
                        f"— {perm_key}: write not in allowlist"
                    )

    assert not violations, (
        "Jobs with unexpected write permissions (update ALLOWED_WRITE_JOBS if intentional):\n"
        + "\n".join(f"  {v}" for v in violations)
    )


# ---------------------------------------------------------------------------
# Research API smoke: offline mode must never contact provider endpoints
# ---------------------------------------------------------------------------


def test_research_api_smoke_defaults_to_no_provider_requests() -> None:
    """A false/omitted live flag must never reach provider health probes.

    This is a negative regression for the historical unconditional
    "Provider health preflight" step, which called HTTP with live_api_tests=false.
    """
    workflow = _load_workflows()["research-api-smoke"]
    job = workflow["jobs"]["research-api-smoke"]
    steps = job["steps"]
    network_steps = [
        step for step in steps
        if "check_research_api_health.py" in str(step.get("run", ""))
        or "smoke_scientific_bridge.py --live-if-secrets-present" in str(
            step.get("run", "")
        )
    ]
    assert network_steps, "Live mode must keep explicit health checks"
    assert all(
        step.get("if") == "github.event.inputs.live_api_tests == 'true'"
        for step in network_steps
    ), "Every provider-contacting step must require opt-in live_api_tests=true"

    offline = next(
        step for step in steps if step.get("name") == "Offline smoke test"
    )
    assert "smoke_scientific_bridge.py --offline" in offline["run"]
    assert not offline.get("if"), "Offline fixture regression must always run"

    offline_validator = next(
        step for step in steps
        if step.get("name") == "Validate research source outputs (offline)"
    )
    assert offline_validator.get("if") == (
        "github.event.inputs.live_api_tests != 'true'"
    )
    assert "--require-health" not in offline_validator["run"]
    assert "check_research_api_health.py" not in offline_validator["run"]

    live_validator = next(
        step for step in steps
        if step.get("name") == "Validate research source outputs (live)"
    )
    assert live_validator.get("if") == (
        "github.event.inputs.live_api_tests == 'true'"
    )
    assert "--require-health" in live_validator["run"]


def test_research_api_smoke_only_releases_secrets_to_opted_in_mode() -> None:
    """Protect all configured secret values from the default offline job."""
    job = _load_workflows()["research-api-smoke"]["jobs"]["research-api-smoke"]
    assert job["environment"] == "live-research"
    for key in (
        "CROSSREF_MAILTO", "ELSEVIER_API_KEY", "SCOPUS_API_KEY",
        "OPENALEX_API_KEY", "WOS_API_KEY", "SCIVAL_API_KEY",
        "MICROSOFT_TENANT_ID", "MICROSOFT_CLIENT_ID",
        "MICROSOFT_CLIENT_SECRET",
    ):
        value = job["env"].get(key, "")
        assert "github.event.inputs.live_api_tests == 'true'" in value
        assert "secrets." + key in value
        assert "|| ''" in value


def test_research_api_smoke_drops_stale_health_before_any_validation() -> None:
    """Offline artifact uploads must not inherit historic provider HTTP 200 results."""
    job = _load_workflows()["research-api-smoke"]["jobs"]["research-api-smoke"]
    steps = job["steps"]
    names = [step.get("name") for step in steps]
    clean = "Clear committed provider-health snapshot"
    assert names.count(clean) == 1
    clear_step = steps[names.index(clean)]
    assert "rm -f outputs/research_api_health.json" in clear_step["run"]
    assert not clear_step.get("if"), "Both offline and live modes need clean health state"
    for later in (
        "Provider configuration audit",
        "Offline smoke test",
        "Live smoke test",
        "Validate research source outputs (offline)",
        "Validate research source outputs (live)",
        "Upload sanitized research API reports",
    ):
        assert names.index(clean) < names.index(later), later
