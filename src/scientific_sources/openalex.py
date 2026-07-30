"""
OpenAlex provider -- scholarly works search and metadata retrieval.

OpenAlex is an open scholarly database providing broad coverage of academic
literature. It serves as the canonical low-cost replacement for Web of Science
in the morskamary provider profile.

API documentation: https://docs.openalex.org/
Authentication: Optional API key via OPENALEX_API_KEY (increases rate limits).

Allowed metadata fields:
- title, authors, year, doi, journal, url, subject_terms, citation_count
Do NOT store full abstracts unless licence permits redistribution.

IMPORTANT: OpenAlex is an aggregator that incorporates metadata from multiple
upstream scholarly infrastructures, including overlapping DOI metadata
ecosystems. It is NOT statistically independent from Crossref.
Provider-level acquisition diversity is not identical to upstream
bibliographic-source independence.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
    "url",
    "citation_count",
    "subject_terms",
    "source_id",
    "provider",
    "source_query",
    "retrieval_timestamp",
]

_API_BASE = "https://api.openalex.org"
_MAX_RETRY_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 1.0
_MAX_PER_PAGE = 200
_DEFAULT_PER_PAGE = 50

_LICENCE_NOTE = (
    "OpenAlex open scholarly metadata. "
    "OpenAlex is an aggregator; provider-level diversity does not imply "
    "upstream bibliographic-source independence."
)


def _strip_abstract_fields(payload: Any) -> Any:
    """
    Remove abstract inverted-index data from an API payload before retention.
    
    Parameters:
        payload (Any): API payload to clean.
    
    Returns:
        Any: A cleaned copy of dictionary payloads, with nested result items processed recursively;
            other values are returned unchanged.
    """
    if isinstance(payload, dict):
        cleaned = {
            k: v for k, v in payload.items()
            if k != "abstract_inverted_index"
        }
        results = cleaned.get("results")
        if isinstance(results, list):
            cleaned["results"] = [_strip_abstract_fields(item) for item in results]
        return cleaned
    return payload


class OpenAlexProvider(BaseProvider):
    """OpenAlex scholarly works API provider."""

    def __init__(self) -> None:
        self._api_key: str = os.getenv("OPENALEX_API_KEY", "")
        self._mailto: str = os.getenv("CROSSREF_MAILTO", "")

    @property
    def capability(self) -> SourceCapability:
        live = os.getenv("LIVE_RESEARCH_API_TESTS", "").lower() == "true"
        return SourceCapability(
            name="openalex",
            provider="OpenAlex",
            requires_secret=False,
            configured=True,
            live_test_allowed=live,
            allowed_metadata_fields=_ALLOWED_FIELDS,
            licence_note=_LICENCE_NOTE,
        )

    def _user_agent(self) -> str:
        base = (
            "morskamary-scientific-bridge/1.0 "
            "(https://github.com/robertbartlomiejski/morskamary"
        )
        if self._mailto:
            base += f"; mailto:{self._mailto}"
        return base + ")"

    def _build_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "User-Agent": self._user_agent(),
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _request_json_with_backoff(
        self,
        *,
        url: str,
        context_label: str,
    ) -> Tuple[Optional[Dict[str, Any]], List[str], Optional[str]]:
        """Make an HTTP request with exponential backoff on 429/5xx."""
        warnings: List[str] = []
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            req = urllib.request.Request(url, headers=self._build_headers())
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    payload = json.loads(resp.read().decode())
                if warnings:
                    warnings.append(
                        f"OpenAlex retry terminal_status=success attempt={attempt}"
                    )
                return payload, warnings, None
            except urllib.error.HTTPError as exc:
                if exc.code == 429 or exc.code >= 500:
                    backoff = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    warnings.append(
                        f"OpenAlex {context_label}: attempt={attempt} "
                        f"http_status={exc.code} backoff_seconds={backoff}"
                    )
                    if attempt >= _MAX_RETRY_ATTEMPTS:
                        terminal_status = (
                            "rate_limited" if exc.code == 429 else f"http_{exc.code}"
                        )
                        return None, warnings, (
                            f"OpenAlex {context_label} failed after "
                            f"{_MAX_RETRY_ATTEMPTS} attempts "
                            f"(terminal_status={terminal_status})"
                        )
                    time.sleep(backoff)
                    continue
                body_snippet = ""
                try:
                    body_snippet = exc.read(240).decode(
                        "utf-8", errors="ignore"
                    ).strip()
                except Exception:
                    body_snippet = ""
                snippet = f" body={body_snippet[:180]!r}" if body_snippet else ""
                return None, warnings, (
                    f"OpenAlex {context_label} failed "
                    f"(terminal_status=http_{exc.code}).{snippet}"
                )
            except Exception as exc:
                return None, warnings, f"OpenAlex {context_label} error: {exc}"
        return None, warnings, (
            f"OpenAlex {context_label} failed after {_MAX_RETRY_ATTEMPTS} attempts"
        )

    @staticmethod
    def _parse_authors(authorship_list: List[Dict[str, Any]]) -> str:
        """Extract author names from OpenAlex authorship objects."""
        names: List[str] = []
        for authorship in authorship_list:
            author = authorship.get("author", {})
            name = str(author.get("display_name", "")).strip()
            if name:
                names.append(name)
        return ", ".join(names) if names else "Unknown"

    @staticmethod
    def _parse_year(work: Dict[str, Any]) -> str:
        year = work.get("publication_year")
        if year is not None:
            return str(year)
        publication_date = str(work.get("publication_date", "")).strip()
        if publication_date and len(publication_date) >= 4:
            return publication_date[:4]
        return ""

    @staticmethod
    def _parse_subject_terms(work: Dict[str, Any]) -> List[str]:
        """Extract subject terms from OpenAlex topics/concepts/keywords."""
        terms: List[str] = []
        for topic in work.get("topics", []):
            name = str(topic.get("display_name", "")).strip()
            if name and name not in terms:
                terms.append(name)
        if not terms:
            for concept in work.get("concepts", []):
                name = str(concept.get("display_name", "")).strip()
                if name and name not in terms:
                    terms.append(name)
        for keyword in work.get("keywords", []):
            if isinstance(keyword, dict):
                name = str(
                    keyword.get("keyword", keyword.get("display_name", ""))
                ).strip()
            else:
                name = str(keyword).strip()
            if name and name not in terms:
                terms.append(name)
        return terms

    def _parse_work(self, work: Dict[str, Any], query: str) -> LiteratureRecord:
        """Convert an OpenAlex work object into a LiteratureRecord."""
        title = str(work.get("display_name", work.get("title", ""))).strip()
        if not title:
            title = "Unknown Title"

        authors = self._parse_authors(work.get("authorships", []))
        year = self._parse_year(work)
        doi = str(work.get("doi", "")).strip()
        if doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/") :]

        primary_location = work.get("primary_location", {}) or {}
        source = primary_location.get("source", {}) or {}
        journal = str(source.get("display_name", "")).strip()

        url = str(work.get("doi", "")).strip()
        if not url:
            url = str(work.get("id", "")).strip()

        citation_count: Optional[int] = None
        raw_cited_by_count = work.get("cited_by_count")
        if raw_cited_by_count is not None:
            try:
                citation_count = int(raw_cited_by_count)
            except (TypeError, ValueError):
                citation_count = None

        subject_terms = self._parse_subject_terms(work)
        openalex_id = str(work.get("id", "")).strip()
        source_id = f"openalex:{doi}" if doi else f"openalex:{openalex_id}"

        return LiteratureRecord(
            title=title,
            authors=authors,
            year=year,
            doi=doi,
            source_id=source_id,
            provider="OpenAlex",
            journal=journal,
            url=url,
            citation_count=citation_count,
            subject_terms=subject_terms,
            source_query=query,
            retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
            licence_note=_LICENCE_NOTE,
        )

    def _parse_works(
        self,
        works: List[Dict[str, Any]],
        query: str,
    ) -> List[LiteratureRecord]:
        records: List[LiteratureRecord] = []
        for work in works:
            try:
                records.append(self._parse_work(work, query))
            except Exception:
                continue
        return records

    def _make_evidence(
        self,
        query: str,
        endpoint: str,
        records: List[LiteratureRecord],
    ) -> List[SourceEvidence]:
        timestamp = datetime.now(timezone.utc).isoformat()
        evidence: List[SourceEvidence] = []
        for record in records:
            raw = (
                f"openalex|{query}|{record.doi}|{record.source_id}|{timestamp}"
            )
            provenance_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
            evidence.append(
                SourceEvidence(
                    record_id=record.source_id,
                    source_provider="OpenAlex",
                    retrieval_mode="live",
                    query=query,
                    api_endpoint_label=endpoint,
                    timestamp=timestamp,
                    confidence_score=0.85,
                    provenance_hash=provenance_hash,
                )
            )
        return evidence

    def _build_search_url(
        self,
        query: str,
        *,
        per_page: int = _DEFAULT_PER_PAGE,
        page: int = 1,
        time_window: Optional[Dict[str, Any]] = None,
        sort_strategy: str = "",
    ) -> str:
        """Build an OpenAlex works search URL."""
        params: Dict[str, str] = {
            "search": query,
            "per_page": str(min(per_page, _MAX_PER_PAGE)),
            "page": str(page),
        }
        if not self._api_key and self._mailto:
            params["mailto"] = self._mailto

        if time_window:
            from_year = time_window.get("from_year")
            to_year = time_window.get("to_year")
            if from_year and to_year:
                params["filter"] = f"publication_year:{from_year}-{to_year}"
            elif from_year:
                params["filter"] = f"publication_year:>{int(from_year) - 1}"

        if sort_strategy in ("published-desc", "date-desc"):
            params["sort"] = "publication_date:desc"
        elif sort_strategy:
            params["sort"] = "relevance_score:desc"

        return f"{_API_BASE}/works?{urllib.parse.urlencode(params)}"

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """
        Search OpenAlex for scholarly records matching a query.
        
        Parameters:
        	query (str): Search terms to match.
        	max_results (int): Maximum number of records to return.
        
        Returns:
        	ProviderResult: Search records, provenance, warnings, and any terminal errors.
        """
        url = self._build_search_url(
            query,
            per_page=min(max_results, _MAX_PER_PAGE),
        )
        data, retry_warnings, terminal_error = self._request_json_with_backoff(
            url=url,
            context_label="search",
        )
        if terminal_error:
            rate_limit_status = (
                "rate-limited" if "rate_limited" in terminal_error else None
            )
            return ProviderResult(
                errors=[terminal_error],
                warnings=retry_warnings,
                rate_limit_status=rate_limit_status,
            )

        assert data is not None
        works = data.get("results", [])
        if not isinstance(works, list):
            works = []
        records = self._parse_works(works[:max_results], query)
        evidence = self._make_evidence(query, "openalex/works", records)
        meta = data.get("meta", {})
        result_count = meta.get("count", len(records))
        return ProviderResult(
            records=records,
            warnings=retry_warnings
            + [
                f"OpenAlex search: total_results={result_count}; "
                f"returned={len(records)}"
            ],
            provenance=evidence,
            raw_payload=_strip_abstract_fields(data),
        )

    def search_paginated(
        self,
        query: str,
        *,
        logical_pages: int = 1,
        rows_per_page: int = 50,
        time_window: Optional[Dict[str, Any]] = None,
        sort_strategy: str = "",
    ) -> Tuple[ProviderResult, List[Dict[str, Any]]]:
        """
        Search OpenAlex across multiple pages and collect records, provenance, warnings, and page diagnostics.
        
        Parameters:
        	query (str): Search query.
        	logical_pages (int): Maximum number of pages to request.
        	rows_per_page (int): Maximum number of records to request per page.
        	time_window (Optional[Dict[str, Any]]): Optional publication-year filter.
        	sort_strategy (str): Optional result ordering strategy.
        
        Returns:
        	Tuple[ProviderResult, List[Dict[str, Any]]]: Combined search results and diagnostics for each requested page.
        """
        all_records: List[LiteratureRecord] = []
        all_warnings: List[str] = []
        all_provenance: List[SourceEvidence] = []
        page_diagnostics: List[Dict[str, Any]] = []

        for page_num in range(logical_pages):
            api_page = page_num + 1
            per_page = min(rows_per_page, _MAX_PER_PAGE)
            url = self._build_search_url(
                query,
                per_page=per_page,
                page=api_page,
                time_window=time_window,
                sort_strategy=sort_strategy,
            )
            data, retry_warnings, terminal_error = self._request_json_with_backoff(
                url=url,
                context_label=f"search_page_{api_page}",
            )
            all_warnings.extend(retry_warnings)

            if terminal_error:
                page_diagnostics.append(
                    {
                        "logical_page": api_page,
                        "physical_requests": 1,
                        "requested_rows": per_page,
                        "returned_rows": 0,
                        "pagination_method": "openalex_page",
                        "api_page": api_page,
                        "error": terminal_error,
                    }
                )
                all_warnings.append(terminal_error)
                break

            assert data is not None
            works = data.get("results", [])
            if not isinstance(works, list):
                works = []
            records = self._parse_works(works[:per_page], query)
            all_records.extend(records)
            all_provenance.extend(
                self._make_evidence(
                    query,
                    f"openalex/works?page={api_page}",
                    records,
                )
            )
            page_diagnostics.append(
                {
                    "logical_page": api_page,
                    "physical_requests": 1,
                    "requested_rows": per_page,
                    "returned_rows": len(records),
                    "pagination_method": "openalex_page",
                    "api_page": api_page,
                }
            )
            if len(records) < per_page:
                break

        rate_limit_status = (
            "rate-limited" if any("rate_limited" in warning for warning in all_warnings)
            else None
        )
        return (
            ProviderResult(
                records=all_records,
                warnings=all_warnings,
                provenance=all_provenance,
                rate_limit_status=rate_limit_status,
            ),
            page_diagnostics,
        )

    def verify_doi(self, doi: str) -> ProviderResult:
        """
        Verify a DOI against OpenAlex and provide the matching literature record and provenance.
        
        Parameters:
        	doi (str): DOI to verify.
        
        Returns:
        	ProviderResult: Verification result containing the matching record and provenance, or errors when the request fails.
        """
        encoded_doi = urllib.parse.quote(doi, safe="")
        url = f"{_API_BASE}/works/https://doi.org/{encoded_doi}"
        data, retry_warnings, terminal_error = self._request_json_with_backoff(
            url=url,
            context_label="DOI_verification",
        )
        if terminal_error:
            rate_limit_status = (
                "rate-limited" if "rate_limited" in terminal_error else None
            )
            return ProviderResult(
                errors=[terminal_error],
                warnings=retry_warnings,
                rate_limit_status=rate_limit_status,
            )

        assert data is not None
        records = [self._parse_work(data, doi)] if "id" in data else []
        evidence = self._make_evidence(doi, f"openalex/works/doi:{doi}", records)
        return ProviderResult(
            records=records,
            warnings=retry_warnings,
            provenance=evidence,
            raw_payload=_strip_abstract_fields(data),
        )
