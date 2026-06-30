#!/usr/bin/env python3
"""
Scientific Database Bridge for GitHub Copilot MCP Integration (OPTIONAL TOOLING)

**IMPORTANT: This is optional, local, workstation-specific tooling.**

This script provides an MCP server that queries scientific databases
via the modular provider architecture in src/scientific_sources/.

Supported providers (capability-gated):
  - Crossref (open, no key required)
  - Elsevier / Scopus (requires ELSEVIER_API_KEY or SCOPUS_API_KEY)
  - Web of Science (requires WOS_API_KEY)
  - SciVal (requires SCIVAL_API_KEY)
  - Google Drive metadata (requires GOOGLE_DRIVE_OAUTH_CREDENTIALS path)
  - Microsoft Graph / OneDrive (requires MICROSOFT_TENANT_ID etc.)

This is NOT a core repository dependency. Python ≥3.9 is the only required
dependency for morskamary development. Use this script only if you need GitHub
Copilot MCP integration with scientific database verification.

For standard Python-first development, see CONTRIBUTING.md and use
main_real_data.py for real-data workflows.

Usage:
    python scientific_bridge.py

Environment Variables (Optional):
    CROSSREF_MAILTO         Polite contact email for Crossref API
    ELSEVIER_API_KEY        Elsevier platform API key
    SCOPUS_API_KEY          Scopus-specific API key
    WOS_API_KEY             Web of Science API key
    SCIVAL_API_KEY          SciVal API key
    GOOGLE_DRIVE_OAUTH_CREDENTIALS  Path to local OAuth JSON (never commit)
    MICROSOFT_TENANT_ID     Azure AD tenant ID
    MICROSOFT_CLIENT_ID     Azure app registration client ID
    MICROSOFT_CLIENT_SECRET Azure app registration secret (never commit)
    LIVE_RESEARCH_API_TESTS Set to 'true' to enable live proprietary API calls

Author: morskamary project
License: See repository LICENSE file
"""

import json
import sys
import urllib.request  # kept for backward-compat monkeypatching in tests
from typing import Any, Dict, List, Optional

from src.scientific_sources.models import LiteratureRecord
from src.scientific_sources.source_registry import SourceRegistry

_urllib_request_for_test_monkeypatch = urllib.request


class ScientificBridge:
    """
    Thin MCP-compatible adapter over the src/scientific_sources provider registry.

    Exposes the following MCP tools:
      - list_research_source_capabilities
      - search_open_metadata
      - search_crossref
      - search_scopus_if_configured
      - search_web_of_science_if_configured
      - search_scival_if_configured
      - verify_doi
      - compare_bibliographic_sources
      - export_source_provenance
      - fetch_scientific_proofs  (legacy alias for search_crossref)
      - verify_citation          (legacy alias for verify_doi)
    """

    def __init__(self) -> None:
        self._registry = SourceRegistry()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_to_dict(self, rec: LiteratureRecord) -> Dict[str, Any]:
        """Convert a LiteratureRecord to a plain citation dictionary."""
        return {
            "title": rec.title,
            "authors": rec.authors,
            "journal": rec.journal,
            "year": rec.year,
            "url": rec.url,
            "doi": rec.doi,
            "provider": rec.provider,
        }

    def format_citation_markdown(self, citation: Dict[str, Any]) -> str:
        """Format a citation dictionary as Markdown."""
        if "error" in citation:
            return f"⚠️ {citation['error']}"

        parts = [f"**{citation['title']}**"]

        if citation.get("authors"):
            parts.append(f"by {citation['authors']}")

        if citation.get("journal") and citation.get("year"):
            parts.append(f"*{citation['journal']}* ({citation['year']})")
        elif citation.get("year"):
            parts.append(f"({citation['year']})")

        result = " ".join(parts)
        if citation.get("doi"):
            result += (
                f"\n  DOI: [{citation['doi']}](https://doi.org/{citation['doi']})"
            )
        if citation.get("url"):
            result += f"\n  Link: {citation['url']}"
        if citation.get("provider"):
            result += f"\n  Source: {citation['provider']}"

        return result

    # ------------------------------------------------------------------
    # search_crossref (backward-compat helper used by tests)
    # ------------------------------------------------------------------

    def search_crossref(
        self, query: str, max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Fetch citations from Crossref only.

        Kept for backward compatibility with tests and callers that use the
        original API.  New code should call search_open_metadata instead.

        Args:
            query: Search query string.
            max_results: Maximum number of results.

        Returns:
            List of citation dicts (title, authors, journal, year, url, doi).
        """
        results = self._registry.search(query, max_results, providers=["crossref"])
        citations: List[Dict[str, Any]] = []
        for result in results:
            for rec in result.records:
                citations.append(self._record_to_dict(rec))
            for err in result.errors:
                citations.append({"error": err})
        return citations

    # ------------------------------------------------------------------
    # MCP tool handlers
    # ------------------------------------------------------------------

    def handle_list_capabilities(self) -> Dict[str, Any]:
        """Return all provider capabilities as structured MCP content."""
        caps = self._registry.capabilities_dict()
        lines = ["## Research Source Capabilities\n"]
        for name, info in caps.items():
            status = "✓ configured" if info["configured"] else "✗ not configured"
            lines.append(f"**{info['provider']}** ({name}): {status}")
            lines.append(f"  Requires secret: {info['requires_secret']}")
            lines.append(f"  Live tests allowed: {info['live_test_allowed']}")
            lines.append(f"  Licence note: {info['licence_note']}\n")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    def handle_search_open_metadata(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search across all configured providers."""
        topic = args.get("topic", "")
        max_results = args.get("max_results", 5)
        if not topic:
            return {
                "content": [{"type": "text", "text": "Error: 'topic' is required"}]
            }
        all_results = self._registry.search(topic, max_results)
        records = self._registry.flat_records(all_results)
        return self._format_records_response(records, topic)

    def handle_fetch_scientific_proofs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle MCP tool call for fetching scientific proofs (legacy alias).

        Queries Crossref and formats results as Markdown.
        """
        topic = args.get("topic", "")
        max_results = args.get("max_results", 5)

        if not topic:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Error: 'topic' parameter is required",
                    }
                ]
            }

        citations = self.search_crossref(topic, max_results)

        if not citations:
            result_text = f"No scientific citations found for: {topic}"
        else:
            result_parts = [
                f"Scientific citations for: **{topic}**\n",
                f"Found {len(citations)} results from Crossref:\n",
            ]
            for i, citation in enumerate(citations, 1):
                result_parts.append(
                    f"\n{i}. {self.format_citation_markdown(citation)}"
                )
            result_text = "\n".join(result_parts)

        return {"content": [{"type": "text", "text": result_text}]}

    def handle_verify_citation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP tool call for verifying a specific DOI (legacy alias)."""
        doi = args.get("doi", "")
        if not doi:
            return {
                "content": [
                    {"type": "text", "text": "Error: 'doi' parameter is required"}
                ]
            }
        results = self._registry.verify_doi(doi)
        records = self._registry.flat_records(results)
        if records:
            rec = records[0]
            citation = self._record_to_dict(rec)
            result_text = (
                f"✓ DOI verified\n\n{self.format_citation_markdown(citation)}"
            )
        else:
            errors = [e for r in results for e in r.errors]
            result_text = (
                f"Error verifying DOI: {'; '.join(errors)}"
                if errors
                else f"No record found for DOI: {doi}"
            )
        return {"content": [{"type": "text", "text": result_text}]}

    def handle_verify_doi(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Verify a DOI across all configured providers."""
        return self.handle_verify_citation(args)

    def handle_export_provenance(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Export provenance summary for a search query."""
        from src.scientific_sources.provenance import export_provenance_json

        topic = args.get("topic", "")
        max_results = args.get("max_results", 5)
        if not topic:
            return {
                "content": [{"type": "text", "text": "Error: 'topic' is required"}]
            }
        all_results = self._registry.search(topic, max_results)
        json_str = export_provenance_json(all_results)
        return {"content": [{"type": "text", "text": json_str}]}

    def handle_compare_sources(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Compare bibliographic sources for a query."""
        from src.nlp_reliability.triangulation import format_overlap_matrix_text

        topic = args.get("topic", "")
        max_results = args.get("max_results", 5)
        if not topic:
            return {
                "content": [{"type": "text", "text": "Error: 'topic' is required"}]
            }
        all_results = self._registry.search(topic, max_results)
        summary = format_overlap_matrix_text(all_results)
        return {"content": [{"type": "text", "text": summary}]}

    def _format_records_response(
        self, records: List[LiteratureRecord], topic: str
    ) -> Dict[str, Any]:
        """Format a list of LiteratureRecord objects as an MCP text response."""
        if not records:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"No results found for: {topic}",
                    }
                ]
            }
        parts = [f"Results for: **{topic}**\n", f"Found {len(records)} records:\n"]
        for i, rec in enumerate(records, 1):
            parts.append(
                f"\n{i}. {self.format_citation_markdown(self._record_to_dict(rec))}"
            )
        return {"content": [{"type": "text", "text": "\n".join(parts)}]}

    # ------------------------------------------------------------------
    # MCP protocol handling
    # ------------------------------------------------------------------

    def _tool_list(self) -> List[Dict[str, Any]]:
        """Return the full MCP tool list."""
        return [
            {
                "name": "list_research_source_capabilities",
                "description": (
                    "Lists all configured and unconfigured scientific source "
                    "providers with their capability status and licence notes."
                ),
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "search_open_metadata",
                "description": (
                    "Searches all configured providers for literature on a topic. "
                    "Results are deduplicated by DOI across providers."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Research topic or keywords",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results per provider (default 5)",
                            "default": 5,
                        },
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "search_crossref",
                "description": "Search Crossref open metadata (no key required).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "search_scopus_if_configured",
                "description": (
                    "Search Elsevier Scopus if ELSEVIER_API_KEY or SCOPUS_API_KEY "
                    "is configured. Returns 'not configured' otherwise."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "search_web_of_science_if_configured",
                "description": (
                    "Search Web of Science if WOS_API_KEY is configured. "
                    "Returns 'not configured' otherwise."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "search_scival_if_configured",
                "description": (
                    "Search Elsevier SciVal if SCIVAL_API_KEY is configured. "
                    "Returns 'not configured' otherwise."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "verify_doi",
                "description": (
                    "Verify a DOI across all configured providers and return "
                    "full citation metadata."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "doi": {
                            "type": "string",
                            "description": "Digital Object Identifier to verify",
                        }
                    },
                    "required": ["doi"],
                },
            },
            {
                "name": "compare_bibliographic_sources",
                "description": (
                    "Search a topic across all providers and return a provider "
                    "overlap matrix showing corroborated vs single-source records."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "export_source_provenance",
                "description": (
                    "Export provenance metadata (provider, timestamp, hash) for "
                    "all records returned by a search query."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "max_results": {"type": "integer", "default": 5},
                    },
                    "required": ["topic"],
                },
            },
            # Legacy tool names preserved for backward compatibility
            {
                "name": "fetch_scientific_proofs",
                "description": (
                    "Fetches verified scientific citations, direct URLs, "
                    "and DOIs for a given research topic. Returns formatted "
                    "citations with authors, publication info, and links. "
                    "(Legacy alias for search_crossref.)"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Research topic or keywords to search",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 5)",
                            "default": 5,
                        },
                    },
                    "required": ["topic"],
                },
            },
            {
                "name": "verify_citation",
                "description": (
                    "Verifies a specific DOI and retrieves full citation "
                    "metadata from Crossref. (Legacy alias for verify_doi.)"
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "doi": {
                            "type": "string",
                            "description": "Digital Object Identifier (DOI) to verify",
                        }
                    },
                    "required": ["doi"],
                },
            },
        ]

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process MCP requests from Copilot."""
        method = request.get("method")

        if method == "tools/list":
            return {"tools": self._tool_list()}

        if method == "tools/call":
            tool_name = request.get("params", {}).get("name")
            args = request.get("params", {}).get("arguments", {})

            dispatch = {
                "list_research_source_capabilities": lambda a: (
                    self.handle_list_capabilities()
                ),
                "search_open_metadata": self.handle_search_open_metadata,
                "search_crossref": self.handle_fetch_scientific_proofs,
                "search_scopus_if_configured": lambda a: self._search_single(
                    a, "scopus"
                ),
                "search_web_of_science_if_configured": lambda a: self._search_single(
                    a, "wos"
                ),
                "search_scival_if_configured": lambda a: self._search_single(
                    a, "scival"
                ),
                "verify_doi": self.handle_verify_doi,
                "compare_bibliographic_sources": self.handle_compare_sources,
                "export_source_provenance": self.handle_export_provenance,
                # Legacy aliases
                "fetch_scientific_proofs": self.handle_fetch_scientific_proofs,
                "verify_citation": self.handle_verify_citation,
            }

            handler = dispatch.get(tool_name)
            if handler:
                result = handler(args)
                return {"result": result}

        return None

    def _search_single(
        self, args: Dict[str, Any], provider_name: str
    ) -> Dict[str, Any]:
        """Search a single named provider."""
        topic = args.get("topic", "")
        max_results = args.get("max_results", 5)
        if not topic:
            return {
                "content": [{"type": "text", "text": "Error: 'topic' is required"}]
            }
        results = self._registry.search(topic, max_results, providers=[provider_name])
        records = self._registry.flat_records(results)
        all_warnings = [w for r in results for w in r.warnings]
        if all_warnings and not records:
            return {
                "content": [{"type": "text", "text": "\n".join(all_warnings)}]
            }
        return self._format_records_response(records, topic)

    def run(self) -> None:
        """Run the MCP server stdio loop."""
        for line in sys.stdin:
            request: Dict[str, Any] = {}
            try:
                request = json.loads(line.strip())
                response = self.handle_request(request)

                if response:
                    response["id"] = request.get("id")
                    print(json.dumps(response), flush=True)

            except json.JSONDecodeError:
                continue
            except Exception as exc:
                error_response = {
                    "id": request.get("id"),
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {exc}",
                    },
                }
                print(json.dumps(error_response), flush=True)


def main() -> None:
    """Main entry point."""
    bridge = ScientificBridge()
    bridge.run()


if __name__ == "__main__":
    main()
