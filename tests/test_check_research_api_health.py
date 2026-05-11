"""Tests for check_research_api_health.py network error handling."""

import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


@pytest.mark.parametrize("errno", [104, 10054])
def test_request_marks_econnreset_as_transient_network_error(errno: int) -> None:
    """_request should classify ECONNRESET as a transient network error."""
    import check_research_api_health

    reset_error = urllib.error.URLError(
        ConnectionResetError(errno, "Connection reset by peer")
    )
    with patch(
        "check_research_api_health.urllib.request.urlopen",
        side_effect=reset_error,
    ):
        result = check_research_api_health._request("https://example.com", {})

    assert result.status == "transient-network-error"
    assert result.detail == "ECONNRESET: connection reset"


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
