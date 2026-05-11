"""Tests for the optional scientific_bridge MCP server."""

import io
import json

import scientific_bridge as sb
from src.scientific_sources.models import LiteratureRecord, ProviderResult


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


def _record(
    title: str = "Blue Social Competences",
    doi: str = "10.1000/xyz",
    provider: str = "CrossRef",
) -> LiteratureRecord:
    """Create a minimal normalized record for bridge tests."""
    return LiteratureRecord(
        title=title,
        authors="A. Author",
        year="2025",
        doi=doi,
        source_id=doi,
        provider=provider,
        journal="Ocean Studies",
        url="https://example.org/blue",
    )


def test_format_citation_markdown_error_and_year_only():
    """format_citation_markdown should handle errors and partial metadata."""
    bridge = sb.ScientificBridge()

    assert bridge.format_citation_markdown({"error": "not found"}) == "⚠️ not found"

    markdown_output = bridge.format_citation_markdown(
        {"title": "Year-Only Record", "year": "2024"}
    )
    assert "**Year-Only Record**" in markdown_output
    assert "(2024)" in markdown_output


def test_handle_list_capabilities_formats_provider_status(monkeypatch):
    """list capabilities should include provider names and configured status."""
    bridge = sb.ScientificBridge()
    monkeypatch.setattr(
        bridge._registry,
        "capabilities_dict",
        lambda: {
            "crossref": {
                "provider": "Crossref",
                "requires_secret": False,
                "configured": True,
                "live_test_allowed": True,
                "allowed_metadata_fields": ["title"],
                "licence_note": "open",
            },
            "scopus": {
                "provider": "Scopus",
                "requires_secret": True,
                "configured": False,
                "live_test_allowed": False,
                "allowed_metadata_fields": ["title"],
                "licence_note": "licensed",
            },
        },
    )

    response = bridge.handle_list_capabilities()
    text = response["content"][0]["text"]
    assert "Crossref" in text
    assert "✓ configured" in text
    assert "Scopus" in text
    assert "✗ not configured" in text


def test_handle_search_open_metadata_validates_topic():
    """search_open_metadata should require a topic."""
    bridge = sb.ScientificBridge()

    response = bridge.handle_search_open_metadata({})

    assert "Error: 'topic' is required" in response["content"][0]["text"]


def test_handle_search_open_metadata_formats_records(monkeypatch):
    """search_open_metadata should render flattened records."""
    bridge = sb.ScientificBridge()
    result = ProviderResult(records=[_record(title="Oceanic Systems")])
    monkeypatch.setattr(bridge._registry, "search", lambda topic, max_results: [result])
    monkeypatch.setattr(bridge._registry, "flat_records", lambda results: [result.records[0]])

    response = bridge.handle_search_open_metadata({"topic": "oceanic systems"})

    text = response["content"][0]["text"]
    assert "Results for: **oceanic systems**" in text
    assert "Oceanic Systems" in text


def test_handle_verify_citation_requires_doi():
    """verify_citation should require DOI argument."""
    bridge = sb.ScientificBridge()

    response = bridge.handle_verify_citation({})

    assert "Error: 'doi' parameter is required" in response["content"][0]["text"]


def test_handle_verify_citation_no_record_and_error_paths(monkeypatch):
    """verify_citation should include provider errors or no-record result."""
    bridge = sb.ScientificBridge()
    monkeypatch.setattr(
        bridge._registry,
        "verify_doi",
        lambda doi: [ProviderResult(errors=["temporarily unavailable"])],
    )
    monkeypatch.setattr(bridge._registry, "flat_records", lambda results: [])

    error_response = bridge.handle_verify_citation({"doi": "10.1000/missing"})
    assert "Error verifying DOI: temporarily unavailable" in error_response["content"][0][
        "text"
    ]

    monkeypatch.setattr(bridge._registry, "verify_doi", lambda doi: [ProviderResult()])
    no_record_response = bridge.handle_verify_citation({"doi": "10.1000/none"})
    assert "No record found for DOI: 10.1000/none" in no_record_response["content"][0][
        "text"
    ]


def test_handle_verify_doi_alias(monkeypatch):
    """verify_doi tool alias should delegate to verify_citation."""
    bridge = sb.ScientificBridge()
    monkeypatch.setattr(
        bridge,
        "handle_verify_citation",
        lambda args: {"content": [{"type": "text", "text": "delegated"}]},
    )

    response = bridge.handle_verify_doi({"doi": "10.1/demo"})

    assert response["content"][0]["text"] == "delegated"


def test_export_and_compare_handlers_validate_topic():
    """export and compare handlers should require topic argument."""
    bridge = sb.ScientificBridge()

    export_response = bridge.handle_export_provenance({})
    compare_response = bridge.handle_compare_sources({})

    assert "Error: 'topic' is required" in export_response["content"][0]["text"]
    assert "Error: 'topic' is required" in compare_response["content"][0]["text"]


def test_export_and_compare_handlers_format_outputs(monkeypatch):
    """export and compare handlers should render imported formatter output."""
    bridge = sb.ScientificBridge()
    mock_results = [ProviderResult(records=[_record()])]
    monkeypatch.setattr(bridge._registry, "search", lambda topic, max_results: mock_results)
    monkeypatch.setattr(
        "src.scientific_sources.provenance.export_provenance_json",
        lambda results: '{"records": 1}',
    )
    monkeypatch.setattr(
        "src.nlp_reliability.triangulation.format_overlap_matrix_text",
        lambda results: "overlap matrix",
    )

    export_response = bridge.handle_export_provenance({"topic": "ports"})
    compare_response = bridge.handle_compare_sources({"topic": "ports"})

    assert '{"records": 1}' in export_response["content"][0]["text"]
    assert "overlap matrix" in compare_response["content"][0]["text"]


def test_format_records_response_handles_empty_and_non_empty():
    """_format_records_response should handle both empty and populated records."""
    bridge = sb.ScientificBridge()

    empty = bridge._format_records_response([], "blue economy")
    assert "No results found for: blue economy" in empty["content"][0]["text"]

    non_empty = bridge._format_records_response([_record(title="Ports Data")], "ports")
    assert "Found 1" in non_empty["content"][0]["text"]
    assert "Ports Data" in non_empty["content"][0]["text"]


def test_search_single_handles_warnings_when_no_records(monkeypatch):
    """_search_single should return warnings when no records are available."""
    bridge = sb.ScientificBridge()
    warning_result = ProviderResult(warnings=["provider not configured"])
    monkeypatch.setattr(
        bridge._registry,
        "search",
        lambda topic, max_results, providers: [warning_result],
    )
    monkeypatch.setattr(bridge._registry, "flat_records", lambda results: [])

    response = bridge._search_single({"topic": "ports"}, "scopus")
    assert "provider not configured" in response["content"][0]["text"]


def test_handle_request_tools_call_dispatch_and_unknown(monkeypatch):
    """handle_request should dispatch known tools and ignore unknown tools."""
    bridge = sb.ScientificBridge()
    monkeypatch.setattr(
        bridge,
        "handle_search_open_metadata",
        lambda args: {"content": [{"type": "text", "text": "ok"}]},
    )

    dispatched = bridge.handle_request(
        {
            "method": "tools/call",
            "params": {"name": "search_open_metadata", "arguments": {"topic": "x"}},
        }
    )
    unknown = bridge.handle_request(
        {"method": "tools/call", "params": {"name": "unknown", "arguments": {}}}
    )

    assert dispatched["result"]["content"][0]["text"] == "ok"
    assert unknown is None


def test_run_writes_responses_and_internal_errors(monkeypatch, capsys):
    """run should print valid responses and internal-error payloads."""
    bridge = sb.ScientificBridge()

    def _fake_handle_request(request):
        if request.get("method") == "explode":
            raise RuntimeError("boom")
        return {"result": {"content": [{"type": "text", "text": "ok"}]}}

    monkeypatch.setattr(
        bridge,
        "handle_request",
        _fake_handle_request,
    )
    monkeypatch.setattr(
        sb.sys,
        "stdin",
        io.StringIO(
            '{"id": 1, "method": "tools/list"}\n'
            '{"id": 2, "method": "explode"}\n'
        ),
    )

    bridge.run()
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line.strip()]

    assert len(lines) == 2
    ok_payload = json.loads(lines[0])
    error_payload = json.loads(lines[1])
    assert ok_payload["id"] == 1
    assert error_payload["id"] == 2
    assert error_payload["error"]["code"] == -32603
    assert "boom" in error_payload["error"]["message"]


def test_run_ignores_malformed_json_input(monkeypatch, capsys):
    """run should ignore malformed JSON lines and continue processing."""
    bridge = sb.ScientificBridge()
    monkeypatch.setattr(
        bridge,
        "handle_request",
        lambda request: {"result": {"content": [{"type": "text", "text": "ok"}]}},
    )
    monkeypatch.setattr(
        sb.sys,
        "stdin",
        io.StringIO('not-json\n{"id": 3, "method": "tools/list"}\n'),
    )

    bridge.run()
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line.strip()]

    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["id"] == 3


def test_scientific_bridge_main_delegates_to_run(monkeypatch):
    """module main should construct bridge and call run."""
    called = {"run": False}

    class FakeBridge:
        def run(self):
            called["run"] = True

    monkeypatch.setattr(sb, "ScientificBridge", FakeBridge)

    sb.main()

    assert called["run"] is True
