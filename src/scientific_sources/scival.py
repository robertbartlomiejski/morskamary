"""
Elsevier SciVal provider.

Requires SCIVAL_API_KEY.
Returns a structured "not configured" result when key is absent.
"""

from __future__ import annotations

import hashlib
import json
import os
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
    "journal",
    "subject_terms",
    "source_id",
    "provider",
    "source_query",
    "retrieval_timestamp",
]


class SciValProvider(BaseProvider):
    """Elsevier SciVal provider."""

    def __init__(self) -> None:
        self._api_key: str = os.getenv("SCIVAL_API_KEY", "")
        self._api_base = "https://api.elsevier.com/analytics/scival/topicCompetency"

    @property
    def capability(self) -> SourceCapability:
        """Return capability descriptor for SciVal."""
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        return SourceCapability(
            name="scival",
            provider="Elsevier SciVal",
            requires_secret=True,
            configured=bool(self._api_key),
            live_test_allowed=live and bool(self._api_key),
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=(
                "SciVal analytics data: store only permitted aggregated "
                "indicators, not restricted database payloads."
            ),
        )

    def _request_json(self, url: str) -> Dict[str, Any]:
        req = urllib.request.Request(
            url, headers={"X-ELS-APIKey": self._api_key, "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read().decode())

    @staticmethod
    def _parse_topics(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        # SciVal response keys vary by endpoint/version; support common variants.
        for key in ("results", "data", "topicCompetencies", "topics"):
            val = payload.get(key)
            if isinstance(val, list):
                return [v for v in val if isinstance(v, dict)]
        return []

    @staticmethod
    def _topic_title(topic: Dict[str, Any]) -> str:
        for key in ("topicName", "name", "topic", "label"):
            value = topic.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "SciVal topic analytics result"

    @staticmethod
    def _topic_subject_terms(topic: Dict[str, Any]) -> List[str]:
        for key in ("keywords", "subjectAreas", "subjectTerms", "fields"):
            value = topic.get(key)
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
        return []

    @staticmethod
    def _topic_year(topic: Dict[str, Any]) -> str:
        for key in ("year", "publicationYear"):
            value = topic.get(key)
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
        return ""

    @staticmethod
    def _make_record(query: str, topic: Dict[str, Any], idx: int) -> LiteratureRecord:
        title = SciValProvider._topic_title(topic)
        source_id = str(topic.get("id", "")).strip() or f"scival:{query}:{idx}"
        url = str(topic.get("url", "")).strip()
        return LiteratureRecord(
            title=f"SciVal topic: {title}",
            authors="",
            year=SciValProvider._topic_year(topic),
            doi="",
            source_id=source_id,
            provider="SciVal",
            journal="",
            url=url,
            subject_terms=SciValProvider._topic_subject_terms(topic),
            source_query=query,
            licence_note="Elsevier SciVal aggregated analytics metadata",
        )

    def _make_evidence(
        self, query: str, endpoint: str, records: List[LiteratureRecord]
    ) -> List[SourceEvidence]:
        ts = datetime.now(timezone.utc).isoformat()
        evidence: List[SourceEvidence] = []
        for rec in records:
            raw = f"scival|{query}|{rec.source_id}|{ts}"
            evidence.append(
                SourceEvidence(
                    record_id=rec.source_id,
                    source_provider="SciVal",
                    retrieval_mode="live",
                    query=query,
                    api_endpoint_label=endpoint,
                    timestamp=ts,
                    confidence_score=0.8,
                    provenance_hash=hashlib.sha256(raw.encode()).hexdigest()[:16],
                )
            )
        return evidence

    @staticmethod
    def _http_error_result(action: str, exc: urllib.error.HTTPError) -> ProviderResult:
        if exc.code == 429:
            return ProviderResult(
                warnings=[f"SciVal {action} rate limited (HTTP 429)."],
                rate_limit_status="rate-limited",
            )
        if exc.code in (401, 403):
            return ProviderResult(errors=[f"SciVal {action} unauthorized (HTTP {exc.code})."])
        return ProviderResult(errors=[f"SciVal {action} failed (HTTP {exc.code})."])

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search SciVal topic analytics."""
        if not self._api_key:
            return self._not_configured_result()
        encoded_query = urllib.parse.quote(query)
        url = f"{self._api_base}?query={encoded_query}&limit={max_results}"
        try:
            payload = self._request_json(url)
            topics = self._parse_topics(payload)
            records = [
                self._make_record(query, topic, idx)
                for idx, topic in enumerate(topics[:max_results], start=1)
            ]
            return ProviderResult(
                records=records,
                provenance=self._make_evidence(query, "scival/topicCompetency", records),
            )
        except urllib.error.HTTPError as exc:
            return self._http_error_result("search", exc)
        except Exception as exc:
            return ProviderResult(errors=[f"SciVal search error: {exc}"])

    def verify_doi(self, doi: str) -> ProviderResult:
        """Verify DOI via SciVal-backed topic analytics query."""
        if not self._api_key:
            return self._not_configured_result()
        result = self.search(f'"{doi}"', max_results=1)
        if result.records:
            result.records[0].source_query = doi
        return result
