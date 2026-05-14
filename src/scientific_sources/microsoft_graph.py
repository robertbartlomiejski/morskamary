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
        quoted_q = urllib.parse.quote(query)
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
        match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", raw)
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
            source_id = str(item.get("id", "")).strip() or f"graph:{title[:40]}"
            records.append(
                LiteratureRecord(
                    title=title,
                    authors=self._authors(item),
                    year=year,
                    doi=self._extract_doi(item),
                    source_id=f"graph:{source_id}",
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
