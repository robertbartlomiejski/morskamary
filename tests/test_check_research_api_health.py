"""Tests for check_research_api_health.py network error handling."""

import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


@pytest.mark.parametrize(
    "reset_errno",
    [
        pytest.param(104, id="linux-econnreset"),
        pytest.param(10054, id="windows-wsaeconnreset"),
    ],
)
def test_request_marks_econnreset_as_transient_network_error(reset_errno: int) -> None:
    """_request should classify ECONNRESET as a transient network error."""
    import check_research_api_health

    reset_error = urllib.error.URLError(
        ConnectionResetError(reset_errno, "Connection reset by peer")
    )
    with patch(
        "check_research_api_health.urllib.request.urlopen",
        side_effect=reset_error,
    ):
        result = check_research_api_health._request("https://example.com", {})

    assert result.status == "transient-network-error"
    assert "connection reset" in result.detail.lower()


def test_request_keeps_other_runtime_errors_as_present_but_invalid() -> None:
    """_request should keep non-network-reset exceptions as present-but-invalid."""
    import check_research_api_health

    with patch(
        "check_research_api_health.urllib.request.urlopen",
        side_effect=RuntimeError("boom"),
    ):
        result = check_research_api_health._request("https://example.com", {})

    assert result.status == "present-but-invalid"
    assert result.detail == "boom"


def test_probe_microsoft_graph_treats_timeout_as_transient(monkeypatch) -> None:
    """probe_microsoft_graph should classify timeout-like URLError as transient."""
    import check_research_api_health

    monkeypatch.setenv("MICROSOFT_TENANT_ID", "tid")
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "cid")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "secret")

    timeout_err = urllib.error.URLError(TimeoutError("timed out"))
    with patch(
        "check_research_api_health.urllib.request.urlopen",
        side_effect=timeout_err,
    ):
        result = check_research_api_health.probe_microsoft_graph()

    assert result.provider == "microsoft_graph"
    assert result.status == "transient-network-error"
    assert "timed out" in result.detail.lower()
