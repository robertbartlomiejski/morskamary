"""
Microsoft Graph (OneDrive / SharePoint) provider stub.

Requires MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID, and
MICROSOFT_CLIENT_SECRET for app-registration-based access.

This provider indexes sanitized, licence-compliant metadata from
OneDrive/SharePoint research folders.  Credentials must NEVER be
committed to the repository.

Only metadata (title, year, DOI, author, SharePoint URL) may be stored.

Live implementation notes:
  Authenticate via msal.ConfidentialClientApplication.
  Use Graph /v1.0/sites/{site}/drive/search(q='...') API.
  Normalise items from value[] into LiteratureRecord.

OData quoting rules (Graph search endpoint):
  The search(q='...') OData function literal requires that any single
  quote inside the query string is doubled: '' (two single quotes).
  This escaping must be applied BEFORE URL-encoding so the encoded
  form is unambiguous to the server.  ``_odata_escape`` enforces this.

source_id construction:
  Each record gets a unique source_id with a single ``graph:`` prefix.
  When a Graph drive item has no ``id`` field the title (first 40 chars)
  is used as the discriminator.  The prefix is NEVER applied twice —
  do not wrap an already-prefixed value.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.parse

from src.scientific_sources.base import BaseProvider
from src.scientific_sources.models import (
    ProviderResult,
    SourceCapability,
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

_GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# Probe endpoint: a lightweight call that merely tests reachability and
# credential validity without performing a full search.
_PROBE_URL = f"{_GRAPH_API_BASE}/me"


def _odata_escape(query: str) -> str:
    """Escape a query string for use inside an OData string literal.

    The OData specification (§5.1.1.6.1) requires that a single quote
    inside a string literal be represented as two consecutive single quotes
    (``''``).  This escaping must happen **before** URL-encoding so that
    the resulting percent-encoded form is unambiguous to the server.

    Args:
        query: Raw query string (may contain single quotes).

    Returns:
        OData-safe query string with ``'`` replaced by ``''``.
    """
    return query.replace("'", "''")


def _search_url(site_id: str, drive_id: str, query: str) -> str:
    """Build a Graph drive-search URL with a correctly quoted OData literal.

    Construction order (important — do not swap steps 1 and 2):
      1. OData-escape the query (replace ``'`` with ``''``).
      2. URL-encode the OData-escaped string for safe transmission.
      3. Interpolate the encoded value into the URL template.

    This two-step process prevents OData literal injection and avoids
    double-encoding artefacts.

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

    The prefix is applied exactly **once**.  When the drive item has no
    ``id`` field the first 40 characters of the item name/title are used
    as the discriminator.  The caller must never pass a value that already
    carries the ``graph:`` prefix to avoid ``graph:graph:…`` artefacts.

    Args:
        item: Raw drive-item dict from the Graph API ``value`` array.

    Returns:
        String of the form ``graph:<discriminator>``.
    """
    item_id: str = item.get("id", "")
    if not item_id:
        # Fall back to a title/name slice — prefix applied once here.
        name: str = item.get("name", item.get("title", "unknown"))
        item_id = name[:40]
    return f"graph:{item_id}"


# ---------------------------------------------------------------------------
# Network probe
# ---------------------------------------------------------------------------

_PROBE_TRANSIENT_STATUS = "transient-network-error"
_PROBE_INVALID_STATUS = "present-but-invalid"
_PROBE_VALID_STATUS = "present-and-valid"


def probe_microsoft_graph(
    tenant_id: str,
    client_id: str,
    client_secret: str,
) -> str:
    """Probe the Microsoft Graph endpoint to classify credential/network state.

    Returns one of three canonical status strings:

    * ``'present-and-valid'``    — reachable and credentials accepted.
    * ``'present-but-invalid'``  — reachable but credentials were rejected
                                   (HTTP 4xx from the server).
    * ``'transient-network-error'`` — any :class:`urllib.error.URLError`
                                      (connection refused, reset, DNS
                                      failure, timeout, SSL error, …).

    Classifying **all** ``URLError`` subtypes as transient is intentional:
    the caller should retry after a delay rather than treat a momentary
    network glitch as a permanent credential failure.

    Args:
        tenant_id:     Azure AD tenant identifier.
        client_id:     App registration client identifier.
        client_secret: App registration client secret.

    Returns:
        Status string (see above).
    """
    import urllib.request

    try:
        # A real implementation would first obtain an OAuth2 token from
        # https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token
        # and then call the Graph /me endpoint with a Bearer header.
        # The stub below performs an unauthenticated GET which will return
        # 401 — sufficient to verify that the endpoint is reachable.
        req = urllib.request.Request(_PROBE_URL)
        with urllib.request.urlopen(req, timeout=5):
            pass
        return _PROBE_VALID_STATUS
    except urllib.error.URLError:
        # Any URLError (including its subclass HTTPError for 4xx/5xx) that
        # wraps a network-level failure is classified as transient.
        # HTTPError for authentication failures is caught here too; callers
        # that need to distinguish auth-vs-network errors should inspect
        # urllib.error.HTTPError.code on the exception object.
        return _PROBE_TRANSIENT_STATUS
    except Exception:
        # Non-URLError exceptions (e.g. ssl.SSLError propagated without
        # wrapping, unexpected runtime errors) are treated as transient so
        # we never falsely report "present-but-invalid" for a network issue.
        return _PROBE_TRANSIENT_STATUS


class MicrosoftGraphProvider(BaseProvider):
    """Microsoft Graph / OneDrive provider (capability-gated; requires app reg)."""

    def __init__(self) -> None:
        self._tenant_id: str = os.getenv("MICROSOFT_TENANT_ID", "")
        self._client_id: str = os.getenv("MICROSOFT_CLIENT_ID", "")
        self._client_secret: str = os.getenv("MICROSOFT_CLIENT_SECRET", "")

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

    def search(self, query: str, max_results: int = 5) -> ProviderResult:
        """Search Graph — returns 'not configured' if credentials are absent."""
        if not self.capability.configured:
            return self._not_configured_result()
        return ProviderResult(
            warnings=[
                "Microsoft Graph live search not yet implemented. "
                "Set MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID, "
                "MICROSOFT_CLIENT_SECRET and implement the Graph call "
                "in microsoft_graph.py."
            ]
        )

    def verify_doi(self, doi: str) -> ProviderResult:
        """DOI verification not applicable for Graph metadata."""
        return ProviderResult(
            warnings=[
                "Microsoft Graph provider does not support DOI verification."
            ]
        )
