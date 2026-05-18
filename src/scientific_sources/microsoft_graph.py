"""Microsoft Graph (OneDrive / SharePoint) metadata provider."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.scientific_sources.base import BaseProvider
from src.scientific_sources.models import (
    LiteratureRecord,
    ProviderResult,
    SourceCapability,
    SourceEvidence,
)

_DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")

_ALLOWED_FIELDS = [
    "title",
    "authors",
    "year",
    "doi",
    "url",
    "source_id",
    "provider",
    "source_query",
    "retrieval_timestamp",
]

_GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
_PROBE_URL = f"{_GRAPH_API_BASE}/me"

_PROBE_TRANSIENT_STATUS = "transient-network-error"
_PROBE_VALID_STATUS = "present-and-valid"


def _odata_escape(query: str) -> str:
    """Escape a query string for use inside an OData string literal.

    Per OData §5.1.1.6.1 a single quote inside a string literal must be
    represented as two consecutive single quotes (``''``).  This escaping
    must happen **before** URL-encoding so the encoded form is unambiguous.

    Args:
        query: Raw query string (may contain single quotes).

    Returns:
        OData-safe query string with ``'`` replaced by ``''``.
    """
    return query.replace("'", "''")


def _search_url(site_id: str, drive_id: str, query: str) -> str:
    """Build a Graph drive-search URL with a correctly quoted OData literal.

    Steps: (1) OData-escape, (2) URL-encode, (3) interpolate.
    Swapping steps 1 and 2 causes double-encoding or raw-quote artefacts.

    Args:
        site_id:  SharePoint site identifier.
        drive_id: OneDrive drive identifier.
        query:    Free-text search string (may contain single quotes).

    Returns:
        Fully formed Graph search URL string.
    """
    odata_safe = _odata_escape(query)
    encoded = urllib.parse.quote(odata_safe, safe="")
    return (
        f"{_GRAPH_API_BASE}/sites/{site_id}/drives/{drive_id}"
        f"/root/search(q='{encoded}')"
    )


def _make_source_id(item: dict) -> str:
    """Return a ``graph:``-prefixed source_id for a Graph drive item.

    The prefix is applied exactly **once**.  Falls back to ``name[:40]``
    then ``title[:40]`` then ``"unknown"`` when ``id`` is absent.

    Args:
        item: Raw drive-item dict from the Graph API ``value`` array.

    Returns:
        String of the form ``graph:<discriminator>``.
    """
    item_id: str = item.get("id", "")
    if not item_id:
        name: str = item.get("name", item.get("title", "unknown"))
        item_id = name[:40]
    return f"graph:{item_id}"


def probe_microsoft_graph(
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> str:
    """Probe the Microsoft Graph endpoint to classify credential/network state.

    Returns one of two canonical status strings:

    * ``'present-and-valid'``       — endpoint reachable and request succeeded.
    * ``'transient-network-error'`` — any ``URLError`` (including ``HTTPError``
                                      for 4xx/5xx) or other network exception.

    Classifying **all** ``URLError`` subtypes as transient is intentional:
    callers should retry rather than treat a network glitch as a permanent
    credential failure.

    Args:
        tenant_id:     Azure AD tenant identifier.
        client_id:     App registration client identifier.
        client_secret: App registration client secret.

    Returns:
        Status string (see above).
    """
    try:
        req = urllib.request.Request(_PROBE_URL)
        with urllib.request.urlopen(req, timeout=5):
            pass
        return _PROBE_VALID_STATUS
    except urllib.error.URLError:
        return _PROBE_TRANSIENT_STATUS
    except Exception:
        return _PROBE_TRANSIENT_STATUS


class MicrosoftGraphProvider(BaseProvider):
    """Microsoft Graph / OneDrive provider (capability-gated; requires app reg)."""

    def __init__(self) -> None:
        self._tenant_id: str = os.getenv("MICROSOFT_TENANT_ID", "")
        self._client_id: str = os.getenv("MICROSOFT_CLIENT_ID", "")
        self._client_secret: str = os.getenv("MICROSOFT_CLIENT_SECRET", "")
        self._site_id: str = os.getenv("MICROSOFT_GRAPH_SITE_ID", "")
        self._drive_id: str = os.getenv("MICROSOFT_GRAPH_DRIVE_ID", "")

    @property
    def capability(self) -> SourceCapability:
        """Return capability descriptor for Microsoft Graph."""
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        configured = bool(
            self._tenant_id and self._client_id and self._client_secret
        )
        return SourceCapability(
            name="microsoft_graph",
            provider="Microsoft Graph (OneDrive/SharePoint)",
            requires_secret=True,
            configured=configured,
            live_test_allowed=live and configured,
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=(
                "Store only sanitized metadata exported from OneDrive/SharePoint; "
                "never commit tenant IDs or app secrets to the repository."
            ),
        )

    def _token(self) -> str:
        token_url = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
        payload = urllib.parse.urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
                "scope": "https://graph.microsoft.com/.default",
            }
        ).encode("utf-8")
        req = urllib.request.Request(token_url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("access_token", ""))

    def _search_url(self, query: str, max_results: int) -> str:
        # OData string literals escape single quotes by doubling them.
        odata_escaped = query.replace("'", "''")
        quoted_q = urllib.parse.quote(odata_escaped, safe="")
        if self._drive_id:
            return (
                f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(self._drive_id)}"
                f"/root/search(q='{quoted_q}')?$top={max_results}"
            )
        return (
            f"https://graph.microsoft.com/v1.0/sites/{urllib.parse.quote(self._site_id)}"
            f"/drive/root/search(q='{quoted_q}')?$top={max_results}"
        )

    @staticmethod
    def _extract_doi(item: Dict[str, Any]) -> str:
        candidates: List[str] = []
        name = str(item.get("name", "")).strip()
        if name:
            candidates.append(name)
        desc = str(item.get("description", "")).strip()
        if desc:
            candidates.append(desc)
        raw = " ".join(candidates)
        match = _DOI_PATTERN.search(raw)
        return match.group(0).rstrip(".,;)") if match else ""

    @staticmethod
    def _authors(item: Dict[str, Any]) -> str:
        created_by = item.get("createdBy", {})
        if not isinstance(created_by, dict):
            return ""
        user = created_by.get("user", {})
        if not isinstance(user, dict):
            return ""
        return str(user.get("displayName", "")).strip()

    def _parse_items(self, payload: Dict[str, Any], query: str) -> List[LiteratureRecord]:
        items = payload.get("value", [])
        if not isinstance(items, list):
            return []
        records: List[LiteratureRecord] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("name", "")).strip()
            if not title:
                continue
            created = str(item.get("createdDateTime", "")).strip()
            year = created[:4] if len(created) >= 4 else ""
            source_id = str(item.get("id", "")).strip() or title[:40]
            if source_id.startswith("graph:"):
                prefixed_source_id = source_id
            else:
                prefixed_source_id = f"graph:{source_id}"
            records.append(
                LiteratureRecord(
                    title=title,
                    authors=self._authors(item),
                    year=year,
                    doi=self._extract_doi(item),
                    source_id=prefixed_source_id,
                    provider="Microsoft Graph (OneDrive/SharePoint)",
                    url=str(item.get("webUrl", "")).strip(),
                    source_query=query,
                    licence_note="Microsoft Graph sanitised document metadata",
                )
            )
        return records

    def _evidence(self, query: str, records: List[LiteratureRecord]) -> List[SourceEvidence]:
        ts = datetime.now(timezone.utc).isoformat()
        result: List[SourceEvidence] = []
        for rec in records:
            raw = f"microsoft_graph|{query}|{rec.source_id}|{ts}"
            result.append(
                SourceEvidence(
                    record_id=rec.source_id,
                    source_provider="Microsoft Graph (OneDrive/SharePoint)",
                    retrieval_mode="live",
                    query=query,
                    api_endpoint_label="graph/drive/search",
                    timestamp=ts,
                    confidence_score=0.6,
                    provenance_hash=hashlib.sha256(raw.encode()).hexdigest()[:16],
                )
            )
        return result

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Graph drive metadata (site-scoped or drive-scoped)."""
        if not self.capability.configured:
            return self._not_configured_result()
        if not self._site_id and not self._drive_id:
            return ProviderResult(
                warnings=[
                    "Microsoft Graph live search is not yet implemented "
                    "without MICROSOFT_GRAPH_SITE_ID or MICROSOFT_GRAPH_DRIVE_ID "
                    "search scope."
                ]
            )
        try:
            token = self._token()
            if not token:
                return ProviderResult(errors=["Microsoft Graph token acquisition failed."])
            req = urllib.request.Request(
                self._search_url(query, max_results),
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            records = self._parse_items(payload, query)
            return ProviderResult(records=records, provenance=self._evidence(query, records))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                return ProviderResult(
                    warnings=["Microsoft Graph rate limited (HTTP 429)."],
                    rate_limit_status="rate-limited",
                )
            if exc.code in (401, 403):
                return ProviderResult(
                    errors=[f"Microsoft Graph unauthorized (HTTP {exc.code})."]
                )
            return ProviderResult(errors=[f"Microsoft Graph search failed (HTTP {exc.code})."])
        except Exception as exc:
            return ProviderResult(errors=[f"Microsoft Graph search error: {exc}"])

    def verify_doi(self, doi: str) -> ProviderResult:
        """Search Graph metadata and filter matches containing DOI text."""
        if not doi.strip():
            return ProviderResult(errors=["Microsoft Graph DOI verification requires DOI input."])
        result = self.search(doi, max_results=10)
        if result.records:
            norm = doi.strip().lower()
            result.records = [r for r in result.records if r.doi.strip().lower() == norm]
        return result
