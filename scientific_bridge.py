#!/usr/bin/env python3
"""
Scientific Database Bridge for GitHub Copilot MCP Integration

This script provides an MCP server that queries scientific databases
(Crossref, Scopus API if configured) to fetch verified citations, DOIs,
and direct links for the morskamary Blue Sociology research project.

Requirements:
    - Python ≥3.9
    - Internet connection for API access

Usage:
    python scientific_bridge.py

Environment Variables (Optional):
    - SCOPUS_API_KEY: Elsevier Scopus API key for enhanced search
    - WOS_API_KEY: Web of Science API key for enhanced search

Author: morskamary project
License: See repository LICENSE file
"""

import sys
import json
import urllib.request
import urllib.parse
from typing import Dict, List, Any, Optional
import os


class ScientificBridge:
    """MCP server for scientific database queries."""

    def __init__(self):
        self.scopus_api_key = os.getenv("SCOPUS_API_KEY")
        self.wos_api_key = os.getenv("WOS_API_KEY")

    def search_crossref(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Fetch verified scientific citations from Crossref API.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of citation dictionaries with title, authors, URL, DOI
        """
        url = (
            f"https://api.crossref.org/works"
            f"?query={urllib.parse.quote(query)}"
            f"&select=title,author,URL,DOI,published,container-title"
            f"&rows={max_results}"
        )

        try:
            # Crossref requires a polite User-Agent with contact information
            headers = {
                "User-Agent": "morskamary-mcp-bridge/1.0 "
                "(https://github.com/robertbartlomiejski/morskamary; "
                "mailto:research@example.edu)"
            }

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

                results = []
                for item in data.get("message", {}).get("items", []):
                    # Extract author names
                    authors = []
                    for author in item.get("author", []):
                        family = author.get("family", "")
                        given = author.get("given", "")
                        if family:
                            full_name = f"{given} {family}".strip()
                            authors.append(full_name)

                    authors_str = ", ".join(authors) if authors else "Unknown"

                    # Extract title
                    title_list = item.get("title", [])
                    title = title_list[0] if title_list else "Unknown Title"

                    # Extract publication info
                    container = item.get("container-title", [])
                    journal = container[0] if container else ""

                    published = item.get("published", {})
                    year = ""
                    if "date-parts" in published:
                        date_parts = published["date-parts"][0]
                        if date_parts:
                            year = str(date_parts[0])

                    # Build citation
                    citation = {
                        "title": title,
                        "authors": authors_str,
                        "journal": journal,
                        "year": year,
                        "url": item.get("URL", ""),
                        "doi": item.get("DOI", ""),
                    }
                    results.append(citation)

                return results

        except Exception as e:
            return [{"error": f"Crossref API error: {str(e)}"}]

    def format_citation_markdown(self, citation: Dict[str, Any]) -> str:
        """Format a citation dictionary as Markdown."""
        if "error" in citation:
            return f"⚠️ {citation['error']}"

        parts = []
        parts.append(f"**{citation['title']}**")

        if citation.get("authors"):
            parts.append(f"by {citation['authors']}")

        if citation.get("journal") and citation.get("year"):
            parts.append(f"*{citation['journal']}* ({citation['year']})")
        elif citation.get("year"):
            parts.append(f"({citation['year']})")

        result = " ".join(parts)

        if citation.get("doi"):
            result += f"\n  DOI: [{citation['doi']}](https://doi.org/{citation['doi']})"

        if citation.get("url"):
            result += f"\n  Link: {citation['url']}"

        return result

    def handle_fetch_scientific_proofs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP tool call for fetching scientific proofs."""
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

        # Query Crossref
        citations = self.search_crossref(topic, max_results)

        # Format results
        if not citations:
            result_text = f"No scientific citations found for: {topic}"
        else:
            result_parts = [
                f"Scientific citations for: **{topic}**\n",
                f"Found {len(citations)} results from Crossref:\n",
            ]

            for i, citation in enumerate(citations, 1):
                result_parts.append(f"\n{i}. {self.format_citation_markdown(citation)}")

            result_text = "\n".join(result_parts)

        return {"content": [{"type": "text", "text": result_text}]}

    def handle_verify_citation(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP tool call for verifying a specific DOI or citation."""
        doi = args.get("doi", "")

        if not doi:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Error: 'doi' parameter is required",
                    }
                ]
            }

        # Query Crossref for specific DOI
        url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"

        try:
            headers = {
                "User-Agent": "morskamary-mcp-bridge/1.0 "
                "(https://github.com/robertbartlomiejski/morskamary)"
            }

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                item = data.get("message", {})

                # Extract metadata
                title_list = item.get("title", [])
                title = title_list[0] if title_list else "Unknown"

                authors = []
                for author in item.get("author", []):
                    family = author.get("family", "")
                    given = author.get("given", "")
                    if family:
                        authors.append(f"{given} {family}".strip())

                citation = {
                    "title": title,
                    "authors": ", ".join(authors) if authors else "Unknown",
                    "url": item.get("URL", ""),
                    "doi": doi,
                }

                result_text = f"✓ DOI verified\n\n{self.format_citation_markdown(citation)}"
                return {"content": [{"type": "text", "text": result_text}]}

        except Exception as e:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error verifying DOI: {str(e)}",
                    }
                ]
            }

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process MCP requests from Copilot."""
        method = request.get("method")

        # List available tools
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "fetch_scientific_proofs",
                        "description": (
                            "Fetches verified scientific citations, direct URLs, "
                            "and DOIs for a given research topic. Returns formatted "
                            "citations with authors, publication info, and links."
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
                            "metadata from Crossref."
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
            }

        # Handle tool calls
        if method == "tools/call":
            tool_name = request.get("params", {}).get("name")
            args = request.get("params", {}).get("arguments", {})

            if tool_name == "fetch_scientific_proofs":
                result = self.handle_fetch_scientific_proofs(args)
                return {"result": result}

            elif tool_name == "verify_citation":
                result = self.handle_verify_citation(args)
                return {"result": result}

        return None

    def run(self):
        """Run the MCP server stdio loop."""
        for line in sys.stdin:
            try:
                request = json.loads(line.strip())
                response = self.handle_request(request)

                if response:
                    response["id"] = request.get("id")
                    print(json.dumps(response), flush=True)

            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_response = {
                    "id": request.get("id") if "request" in locals() else None,
                    "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                }
                print(json.dumps(error_response), flush=True)


def main():
    """Main entry point."""
    bridge = ScientificBridge()
    bridge.run()


if __name__ == "__main__":
    main()
