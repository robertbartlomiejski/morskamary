#!/usr/bin/env python3
"""Preflight health check for research API providers.

Performs lightweight, non-destructive requests against enabled providers and
returns explicit statuses suitable for CI gating and artifact retention.

Statuses:
- missing
- present-but-invalid
- rate-limited
- ok
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

_REQUEST_TIMEOUT_SECONDS = 12
_ERROR_BODY_MAX_BYTES = 512


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
        return ProbeResult("", "present-but-invalid", str(exc), None)


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
        return ProbeResult("scopus", "missing", "ELSEVIER_API_KEY/SCOPUS_API_KEY not set")
    query = urllib.parse.quote("TITLE(ocean)")
    url = f"https://api.elsevier.com/content/search/scopus?query={query}&count=1"
    result = _request(url, {"X-ELS-APIKey": key, "Accept": "application/json"})
    result.provider = "scopus"
    return result


def probe_wos() -> ProbeResult:
    key = os.getenv("WOS_API_KEY", "")
    if not key:
        return ProbeResult("wos", "missing", "WOS_API_KEY not set")
    query = urllib.parse.quote("TS=ocean")
    url = f"https://api.clarivate.com/apis/wos-starter/v1/documents?q={query}&limit=1&page=1"
    result = _request(url, {"X-ApiKey": key, "Accept": "application/json"})
    result.provider = "wos"
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="outputs/research_api_health.json")
    parser.add_argument("--require-valid", action="store_true")
    args = parser.parse_args()

    probes = [probe_crossref, probe_scopus, probe_wos, probe_scival]
    results = [p() for p in probes]

    print("=== Research API health preflight ===")
    for r in results:
        code = f" (HTTP {r.http_status})" if r.http_status else ""
        print(f"  - {r.provider:<8} {r.status:<20} {r.detail}{code}")

    payload = {
        "statuses": [r.__dict__ for r in results],
        "summary": {"ok": sum(1 for r in results if r.status == "ok")},
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    if args.require_valid:
        invalid = [r for r in results if r.status in {"present-but-invalid", "rate-limited"}]
        if invalid:
            print("\nFailing preflight due to invalid/rate-limited provider credentials.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
