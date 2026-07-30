#!/usr/bin/env python3
"""Preflight health check for research API providers.

Performs lightweight, non-destructive requests against enabled providers and
returns explicit statuses suitable for CI gating and artifact retention.

Statuses:
- missing
- present-but-invalid
- rate-limited
- transient-network-error (temporary transport failure, e.g., ECONNRESET)
- ok
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_REQUEST_TIMEOUT_SECONDS = 12
_ERROR_BODY_MAX_BYTES = 512
_REDACTED_QUERY_PARAMS = frozenset({"api_key", "apikey", "key", "token", "secret"})
_SENSITIVE_QUERY_PARAM_RE = re.compile(
    r"(?i)([?&](?:api_key|apikey|key|token|secret)=)[^&\s'\"<>)]*"
)
DEACTIVATED_PROVIDERS = {
    "wos": (
        "Web of Science acquisition is temporarily deactivated until the "
        "scientific hardening plan and provider contract are completed"
    )
}


def _redact_url(url: str) -> str:
    """Return a URL with sensitive query-string parameters replaced by REDACTED."""
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        redacted = [
            (k, "REDACTED" if k.lower() in _REDACTED_QUERY_PARAMS else v)
            for k, v in params
        ]
        safe_query = urllib.parse.urlencode(redacted)
        return urllib.parse.urlunparse(parsed._replace(query=safe_query))
    except Exception:
        return "[url-redacted]"


def _redact_sensitive_text(value: object) -> str:
    """Redact credential-like query-string values inside arbitrary text."""
    return _SENSITIVE_QUERY_PARAM_RE.sub(r"\1REDACTED", str(value))


def _is_transient_network_error(exc: Exception) -> bool:
    """Return True for transport-level transient failures."""
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(
            reason, (ConnectionResetError, TimeoutError, ConnectionAbortedError)
        ):
            return True
        if isinstance(reason, OSError):
            return True
    if isinstance(exc, (ConnectionResetError, TimeoutError, ConnectionAbortedError)):
        return True
    detail = str(exc).lower()
    transient_tokens = (
        "econnreset",
        "connection reset",
        "timed out",
        "timeout",
        "temporary failure in name resolution",
        "name or service not known",
        "network is unreachable",
        "connection refused",
    )
    return any(token in detail for token in transient_tokens)


@dataclass
class ProbeResult:
    provider: str
    status: str
    detail: str
    http_status: int | None = None


def _is_rate_limited(code: int, body: str) -> bool:
    if code == 429:
        return True
    return "rate limit" in body.lower() or "too many requests" in body.lower()


def _request(url: str, headers: dict[str, str]) -> ProbeResult:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            return ProbeResult("", "ok", "request succeeded", resp.status)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(_ERROR_BODY_MAX_BYTES).decode("utf-8", errors="ignore")
        except Exception:
            pass
        if _is_rate_limited(exc.code, body):
            return ProbeResult("", "rate-limited", f"HTTP {exc.code}", exc.code)
        if exc.code in (401, 403):
            return ProbeResult("", "present-but-invalid", f"HTTP {exc.code}", exc.code)
        return ProbeResult("", "present-but-invalid", f"HTTP {exc.code}", exc.code)
    except Exception as exc:
        safe_detail = _redact_sensitive_text(exc)
        if _is_transient_network_error(exc):
            return ProbeResult("", "transient-network-error", safe_detail, None)
        return ProbeResult("", "present-but-invalid", safe_detail, None)


def probe_crossref() -> ProbeResult:
    url = "https://api.crossref.org/works?rows=1&query=blue%20economy"
    result = _request(url, {"User-Agent": "morskamary-healthcheck/1.0"})
    result.provider = "crossref"
    return result


def _get_elsevier_key() -> str:
    """Return the Elsevier API key from either ELSEVIER_API_KEY or SCOPUS_API_KEY."""
    return os.getenv("ELSEVIER_API_KEY", "") or os.getenv("SCOPUS_API_KEY", "")


def probe_scopus() -> ProbeResult:
    key = _get_elsevier_key()
    if not key:
        return ProbeResult(
            "scopus", "missing", "ELSEVIER_API_KEY/SCOPUS_API_KEY not set"
        )
    query = urllib.parse.quote("TITLE(ocean)")
    url = f"https://api.elsevier.com/content/search/scopus?query={query}&count=1"
    result = _request(url, {"X-ELS-APIKey": key, "Accept": "application/json"})
    result.provider = "scopus"
    return result


def probe_openalex() -> ProbeResult:
    api_key = os.getenv("OPENALEX_API_KEY", "")
    if not api_key:
        return ProbeResult("openalex", "missing", "OPENALEX_API_KEY not set")
    params = urllib.parse.urlencode(
        {"filter": "title.search:ocean", "per_page": "1", "api_key": api_key}
    )
    url = f"https://api.openalex.org/works?{params}"
    result = _request(
        url,
        {
            "Accept": "application/json",
            "User-Agent": "morskamary-openalex-healthcheck/1.0",
        },
    )
    result.provider = "openalex"
    return result


def probe_scival() -> ProbeResult:
    key = os.getenv("SCIVAL_API_KEY", "")
    if not key:
        return ProbeResult("scival", "missing", "SCIVAL_API_KEY not set")
    url = (
        "https://api.elsevier.com/analytics/scival/author/metrics"
        "?metricTypes=ScholarlyOutput&yearRange=5yrs&includedDocs=AllPublicationTypes"
        "&journalImpactType=CiteScore&showAsFieldWeighted=false&byYear=false"
        "&authors=1-s2.0-7004212771"
    )
    result = _request(url, {"X-ELS-APIKey": key, "Accept": "application/json"})
    result.provider = "scival"
    return result


def probe_microsoft_graph() -> ProbeResult:
    tenant = os.getenv("MICROSOFT_TENANT_ID", "")
    client_id = os.getenv("MICROSOFT_CLIENT_ID", "")
    client_secret = os.getenv("MICROSOFT_CLIENT_SECRET", "")
    if not (tenant and client_id and client_secret):
        return ProbeResult(
            "microsoft_graph",
            "missing",
            "MICROSOFT_TENANT_ID/MICROSOFT_CLIENT_ID/MICROSOFT_CLIENT_SECRET not set",
        )
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }
    ).encode("utf-8")
    request = urllib.request.Request(token_url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            if resp.status == 200:
                return ProbeResult(
                    "microsoft_graph", "ok", "token request succeeded", resp.status
                )
            return ProbeResult(
                "microsoft_graph",
                "present-but-invalid",
                f"HTTP {resp.status}",
                resp.status,
            )
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return ProbeResult(
                "microsoft_graph",
                "present-but-invalid",
                f"HTTP {exc.code}",
                exc.code,
            )
        if _is_rate_limited(exc.code, ""):
            return ProbeResult(
                "microsoft_graph", "rate-limited", f"HTTP {exc.code}", exc.code
            )
        return ProbeResult(
            "microsoft_graph", "present-but-invalid", f"HTTP {exc.code}", exc.code
        )
    except Exception as exc:
        if _is_transient_network_error(exc):
            return ProbeResult("microsoft_graph", "transient-network-error", str(exc))
        return ProbeResult("microsoft_graph", "present-but-invalid", str(exc))


def probe_google_drive() -> ProbeResult:
    credentials_path = os.getenv("GOOGLE_DRIVE_OAUTH_CREDENTIALS", "")
    if not credentials_path:
        return ProbeResult(
            "google_drive", "missing", "GOOGLE_DRIVE_OAUTH_CREDENTIALS not set"
        )
    if not Path(credentials_path).is_file():
        return ProbeResult(
            "google_drive",
            "missing",
            "GOOGLE_DRIVE_OAUTH_CREDENTIALS does not point to a file",
        )
    return ProbeResult("google_drive", "ok", "credentials file found")


def _probe_functions() -> dict[str, Callable[[], ProbeResult]]:
    return {
        "crossref": probe_crossref,
        "scopus": probe_scopus,
        "openalex": probe_openalex,
        "scival": probe_scival,
        "microsoft_graph": probe_microsoft_graph,
        "google_drive": probe_google_drive,
    }


def _parse_requested_providers(raw_value: str) -> list[str]:
    probe_functions = _probe_functions()
    requested = [item.strip().lower() for item in raw_value.split(",") if item.strip()]
    if not requested:
        raise ValueError(
            "--providers must not be empty. Specify one or more provider names."
        )
    if "all" in requested:
        if len(requested) > 1:
            raise ValueError("--providers=all cannot be combined with other providers.")
        return list(probe_functions.keys())
    deactivated = sorted(set(requested) & set(DEACTIVATED_PROVIDERS))
    if deactivated:
        reasons = "; ".join(
            f"{name}: {DEACTIVATED_PROVIDERS[name]}" for name in deactivated
        )
        raise ValueError(f"deactivated provider requested: {reasons}")
    unknown = sorted({name for name in requested if name not in probe_functions})
    if unknown:
        raise ValueError(
            f"Unknown provider(s): {unknown}. Valid active names are: {sorted(probe_functions)}"
        )
    return requested


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="outputs/research_api_health.json")
    parser.add_argument("--providers", default="all")
    parser.add_argument("--require-valid", action="store_true")
    parser.add_argument(
        "--require-configured",
        action="store_true",
        help="Fail when any requested provider reports missing configuration.",
    )
    args = parser.parse_args()
    try:
        requested_provider_names = _parse_requested_providers(args.providers)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    probe_functions = _probe_functions()
    results = [probe_functions[name]() for name in requested_provider_names]
    print("=== Research API health preflight ===")
    for result in results:
        code = f" (HTTP {result.http_status})" if result.http_status else ""
        print(
            f"  - {result.provider:<8} {result.status:<20} {result.detail}{code}"
        )
    payload = {
        "statuses": [result.__dict__ for result in results],
        "summary": {"ok": sum(1 for result in results if result.status == "ok")},
        "deactivated_providers": sorted(DEACTIVATED_PROVIDERS),
    }
    output_parent = os.path.dirname(args.output)
    if output_parent:
        os.makedirs(output_parent, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    if args.require_valid:
        invalid = [
            result
            for result in results
            if result.status
            in {"present-but-invalid", "rate-limited", "transient-network-error"}
        ]
        if invalid:
            print(
                "\nFailing preflight due to invalid/rate-limited/unreachable provider."
            )
            return 1
    if args.require_configured:
        missing = [result for result in results if result.status == "missing"]
        if missing:
            names = ", ".join(result.provider for result in missing)
            print(f"\nFailing preflight due to missing provider configuration: {names}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
