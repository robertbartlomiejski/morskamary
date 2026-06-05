"""Tests for check_research_api_health.py network error handling and provider selection."""

import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


@pytest.mark.parametrize(
    "reset_errno",
    [
        pytest.param(104, id="linux-econnreset"),
        pytest.param(10054, id="windows-wsaeconnreset"),
    ],
)
def test_request_marks_econnreset_as_transient_network_error(reset_errno: int) -> None:
    import check_research_api_health

    reset_error = urllib.error.URLError(
        ConnectionResetError(reset_errno, "Connection reset by peer")
    )
    with patch(
        "check_research_api_health.urllib.request.urlopen", side_effect=reset_error
    ):
        result = check_research_api_health._request("https://example.com", {})

    assert result.status == "transient-network-error"
    assert "connection reset" in result.detail.lower()


def test_request_success_returns_ok_status() -> None:
    import check_research_api_health

    response = MagicMock()
    response.status = 200
    response.__enter__.return_value = response
    response.__exit__.return_value = False

    with patch(
        "check_research_api_health.urllib.request.urlopen", return_value=response
    ):
        result = check_research_api_health._request("https://example.com", {})

    assert result.status == "ok"
    assert result.http_status == 200


def test_request_http_429_is_rate_limited() -> None:
    import check_research_api_health

    http_error = urllib.error.HTTPError(
        "https://example.com", 429, "Too Many Requests", hdrs=None, fp=None
    )
    with patch(
        "check_research_api_health.urllib.request.urlopen", side_effect=http_error
    ):
        result = check_research_api_health._request("https://example.com", {})

    assert result.status == "rate-limited"
    assert result.http_status == 429


def test_request_http_401_is_present_but_invalid() -> None:
    import check_research_api_health

    http_error = urllib.error.HTTPError(
        "https://example.com", 401, "Unauthorized", hdrs=None, fp=None
    )
    with patch(
        "check_research_api_health.urllib.request.urlopen", side_effect=http_error
    ):
        result = check_research_api_health._request("https://example.com", {})

    assert result.status == "present-but-invalid"
    assert result.http_status == 401


def test_probe_google_drive_missing_and_configured_paths(
    monkeypatch, tmp_path: Path
) -> None:
    import check_research_api_health

    monkeypatch.delenv("GOOGLE_DRIVE_OAUTH_CREDENTIALS", raising=False)
    missing_result = check_research_api_health.probe_google_drive()
    assert missing_result.status == "missing"
    assert missing_result.provider == "google_drive"

    credentials_file = tmp_path / "oauth.json"
    credentials_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_DRIVE_OAUTH_CREDENTIALS", str(credentials_file))

    configured_result = check_research_api_health.probe_google_drive()
    assert configured_result.status == "ok"
    assert configured_result.provider == "google_drive"


def test_parse_requested_providers_rejects_empty_unknown_and_mixed_all() -> None:
    import check_research_api_health

    with pytest.raises(ValueError):
        check_research_api_health._parse_requested_providers("  ")
    with pytest.raises(ValueError):
        check_research_api_health._parse_requested_providers("crossref,unknown")
    with pytest.raises(ValueError):
        check_research_api_health._parse_requested_providers("all,crossref")


def test_parse_requested_providers_adds_crossref_when_missing() -> None:
    import check_research_api_health

    assert check_research_api_health._parse_requested_providers("scopus") == [
        "scopus",
        "crossref",
    ]


def test_parse_requested_providers_all_expands_registry() -> None:
    import check_research_api_health

    assert check_research_api_health._parse_requested_providers("all") == [
        "crossref",
        "scopus",
        "wos",
        "scival",
        "microsoft_graph",
        "google_drive",
    ]


def test_main_filters_to_requested_providers_and_crossref(tmp_path: Path) -> None:
    import check_research_api_health

    output_file = tmp_path / "health" / "results.json"
    scopus_missing = check_research_api_health.ProbeResult(
        "scopus", "missing", "missing", None
    )
    crossref_ok = check_research_api_health.ProbeResult("crossref", "ok", "ok", 200)

    with (
        patch(
            "sys.argv",
            [
                "check_research_api_health.py",
                "--output",
                str(output_file),
                "--providers",
                "scopus",
            ],
        ),
        patch(
            "check_research_api_health.probe_scopus", return_value=scopus_missing
        ) as probe_scopus,
        patch(
            "check_research_api_health.probe_crossref", return_value=crossref_ok
        ) as probe_crossref,
        patch("check_research_api_health.probe_wos") as probe_wos,
        patch("check_research_api_health.probe_scival") as probe_scival,
        patch(
            "check_research_api_health.probe_microsoft_graph"
        ) as probe_microsoft_graph,
        patch("check_research_api_health.probe_google_drive") as probe_google_drive,
    ):
        exit_code = check_research_api_health.main()

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert [item["provider"] for item in payload["statuses"]] == ["scopus", "crossref"]
    probe_scopus.assert_called_once()
    probe_crossref.assert_called_once()
    probe_wos.assert_not_called()
    probe_scival.assert_not_called()
    probe_microsoft_graph.assert_not_called()
    probe_google_drive.assert_not_called()


def test_main_require_valid_fails_when_invalid_provider(tmp_path: Path) -> None:
    import check_research_api_health

    output_file = tmp_path / "health" / "results.json"
    invalid_scopus = check_research_api_health.ProbeResult(
        "scopus", "present-but-invalid", "HTTP 401", 401
    )
    crossref_ok = check_research_api_health.ProbeResult("crossref", "ok", "ok", 200)

    with (
        patch(
            "sys.argv",
            [
                "check_research_api_health.py",
                "--output",
                str(output_file),
                "--providers",
                "scopus",
                "--require-valid",
            ],
        ),
        patch("check_research_api_health.probe_scopus", return_value=invalid_scopus),
        patch("check_research_api_health.probe_crossref", return_value=crossref_ok),
    ):
        exit_code = check_research_api_health.main()

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["summary"]["ok"] == 1
