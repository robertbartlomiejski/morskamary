"""Tests for the optional scientific_bridge MCP server."""

import json

import scientific_bridge as sb


class DummyResponse:
    """Simple context manager to mimic urllib responses."""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def test_search_crossref_parses_results(monkeypatch):
    """search_crossref should normalize Crossref API items."""
    payload = {
        "message": {
            "items": [
                {
                    "title": ["Ocean Literacy and Justice"],
                    "author": [{"given": "Ada", "family": "Lovelace"}],
                    "URL": "https://example.org/paper",
                    "DOI": "10.1234/example",
                    "published": {"date-parts": [[2024, 3, 15]]},
                    "container-title": ["Blue Sociology Journal"],
                }
            ]
        }
    }

    def fake_urlopen(request, timeout=10):
        return DummyResponse(payload)

    monkeypatch.setattr(sb.urllib.request, "urlopen", fake_urlopen)

    bridge = sb.ScientificBridge()
    results = bridge.search_crossref("ocean justice", max_results=1)

    assert results == [
        {
            "title": "Ocean Literacy and Justice",
            "authors": "Ada Lovelace",
            "journal": "Blue Sociology Journal",
            "year": "2024",
            "url": "https://example.org/paper",
            "doi": "10.1234/example",
            "provider": "Crossref",
        }
    ]


def test_handle_verify_citation_success(monkeypatch):
    """verify_citation should format returned metadata."""
    payload = {
        "message": {
            "title": ["Deep Sea Governance"],
            "author": [{"given": "Grace", "family": "Hopper"}],
            "URL": "https://doi.org/10.5555/deep",
        }
    }

    def fake_urlopen(request, timeout=10):
        return DummyResponse(payload)

    monkeypatch.setattr(sb.urllib.request, "urlopen", fake_urlopen)

    bridge = sb.ScientificBridge()
    response = bridge.handle_verify_citation({"doi": "10.5555/deep"})

    content = response["content"][0]["text"]
    assert "DOI verified" in content
    assert "Deep Sea Governance" in content
    assert "10.5555/deep" in content


def test_handle_fetch_scientific_proofs_requires_topic():
    """fetch_scientific_proofs should guard against missing topics."""
    bridge = sb.ScientificBridge()

    response = bridge.handle_fetch_scientific_proofs({})

    assert "topic' parameter is required" in response["content"][0]["text"]


def test_handle_fetch_scientific_proofs_formats_results(monkeypatch):
    """fetch_scientific_proofs should render results in order."""
    bridge = sb.ScientificBridge()
    monkeypatch.setattr(
        bridge,
        "search_crossref",
        lambda topic, max_results: [
            {
                "title": "Maritime Logistics",
                "authors": "I. Newton",
                "journal": "Ports Review",
                "year": "2025",
                "url": "https://example.org/ports",
                "doi": "10.42/ports",
            }
        ],
    )

    response = bridge.handle_fetch_scientific_proofs(
        {"topic": "ports", "max_results": 1}
    )

    content = response["content"][0]["text"]
    assert "Found 1 results" in content
    assert "Maritime Logistics" in content
    assert "10.42/ports" in content


def test_handle_request_lists_tools():
    """handle_request should surface available MCP tools."""
    bridge = sb.ScientificBridge()

    response = bridge.handle_request({"method": "tools/list"})

    tool_names = {tool["name"] for tool in response["tools"]}
    assert {"fetch_scientific_proofs", "verify_citation"}.issubset(tool_names)
