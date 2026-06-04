"""Tests for check_research_api_health.py network error handling."""

import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_request_success_returns_ok_status() -> None:
    """_request should return ok with HTTP status on successful response."""
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
    """_request should classify HTTP 429 as rate-limited."""
    import check_research_api_health

    http_error = urllib.error.HTTPError(
        "https://example.com",
        429,
        "Too Many Requests",
        hdrs=None,
        fp=None,
    )
    with patch(
        "check_research_api_health.urllib.request.urlopen",
        side_effect=http_error,
    ):
        result = check_research_api_health._request("https://example.com", {})

    assert result.status == "rate-limited"
    assert result.http_status == 429


def test_request_http_401_is_present_but_invalid() -> None:
    """_request should classify 401 as present-but-invalid credentials."""
    import check_research_api_health

    http_error = urllib.error.HTTPError(
        "https://example.com",
        401,
        "Unauthorized",
        hdrs=None,
        fp=None,
    )
    with patch(
        "check_research_api_health.urllib.request.urlopen",
        side_effect=http_error,
    ):
        result = check_research_api_health._request("https://example.com", {})

    assert result.status == "present-but-invalid"
    assert result.http_status == 401


def test_rate_limit_helpers_and_elsevier_key_resolution(monkeypatch) -> None:
    """Rate-limit helper and API key resolver should match precedence rules."""
    import check_research_api_health

    assert check_research_api_health._is_rate_limited(429, "")
    assert check_research_api_health._is_rate_limited(400, "Too many requests now")
    assert not check_research_api_health._is_rate_limited(400, "forbidden")

    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    assert check_research_api_health._get_elsevier_key() == ""

    monkeypatch.setenv("SCOPUS_API_KEY", "scopus-key")
    assert check_research_api_health._get_elsevier_key() == "scopus-key"

    monkeypatch.setenv("ELSEVIER_API_KEY", "elsevier-key")
    assert check_research_api_health._get_elsevier_key() == "elsevier-key"


def test_probe_scopus_missing_and_configured_paths(monkeypatch) -> None:
    """probe_scopus should return missing without key and provider-tagged result with key."""
    import check_research_api_health

    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    missing_result = check_research_api_health.probe_scopus()
    assert missing_result.status == "missing"
    assert missing_result.provider == "scopus"

    monkeypatch.setenv("ELSEVIER_API_KEY", "test-key")
    with patch(
        "check_research_api_health._request",
        return_value=check_research_api_health.ProbeResult(
            "", "ok", "request succeeded", 200
        ),
    ) as mocked_request:
        configured_result = check_research_api_health.probe_scopus()

    assert configured_result.provider == "scopus"
    assert configured_result.status == "ok"
    mocked_request.assert_called_once()


def test_probe_wos_and_scival_missing_keys(monkeypatch) -> None:
    """probe_wos/probe_scival should report missing when required keys are absent."""
    import check_research_api_health

    monkeypatch.delenv("WOS_API_KEY", raising=False)
    monkeypatch.delenv("SCIVAL_API_KEY", raising=False)

    wos_result = check_research_api_health.probe_wos()
    scival_result = check_research_api_health.probe_scival()

    assert wos_result.status == "missing"
    assert wos_result.provider == "wos"
    assert scival_result.status == "missing"
    assert scival_result.provider == "scival"


def test_main_require_valid_fails_when_invalid_provider(tmp_path: Path) -> None:
    """main should return non-zero with --require-valid when invalid provider exists."""
    import check_research_api_health

    output_file = tmp_path / "health" / "results.json"
    fake_results = [
        check_research_api_health.ProbeResult("crossref", "ok", "ok", 200),
        check_research_api_health.ProbeResult(
            "scopus", "present-but-invalid", "HTTP 401", 401
        ),
        check_research_api_health.ProbeResult("wos", "missing", "missing", None),
        check_research_api_health.ProbeResult("scival", "missing", "missing", None),
        check_research_api_health.ProbeResult(
            "google_drive", "present-but-invalid", "missing", None
        ),
        check_research_api_health.ProbeResult(
            "microsoft_graph", "missing", "missing", None
        ),
    ]

    with (
        patch(
            "sys.argv",
            [
                "check_research_api_health.py",
                "--output",
                str(output_file),
                "--require-valid",
            ],
        ),
        patch("check_research_api_health.probe_crossref", return_value=fake_results[0]),
        patch("check_research_api_health.probe_scopus", return_value=fake_results[1]),
        patch("check_research_api_health.probe_wos", return_value=fake_results[2]),
        patch("check_research_api_health.probe_scival", return_value=fake_results[3]),
        patch("check_research_api_health.probe_google_drive", return_value=fake_results[4]),
        patch(
            "check_research_api_health.probe_microsoft_graph",
            return_value=fake_results[5],
        ),
    ):
        exit_code = check_research_api_health.main()

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["summary"]["ok"] == 1
    assert any(item["provider"] == "scopus" for item in payload["statuses"])


def test_main_without_require_valid_returns_zero(tmp_path: Path) -> None:
    """main should return zero when --require-valid is not provided."""
    import check_research_api_health

    output_file = tmp_path / "health" / "results.json"
    ok_result = check_research_api_health.ProbeResult("crossref", "ok", "ok", 200)

    with (
        patch(
            "sys.argv", ["check_research_api_health.py", "--output", str(output_file)]
        ),
        patch("check_research_api_health.probe_crossref", return_value=ok_result),
        patch("check_research_api_health.probe_scopus", return_value=ok_result),
        patch("check_research_api_health.probe_wos", return_value=ok_result),
        patch("check_research_api_health.probe_scival", return_value=ok_result),
        patch("check_research_api_health.probe_google_drive", return_value=ok_result),
        patch(
            "check_research_api_health.probe_microsoft_graph", return_value=ok_result
        ),
    ):
        exit_code = check_research_api_health.main()

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["summary"]["ok"] == 6


def test_main_with_providers_scopes_probes_to_requested_subset(tmp_path: Path) -> None:
    """main should run only explicitly requested providers from --providers."""
    import check_research_api_health

    output_file = tmp_path / "health" / "results.json"
    crossref_result = check_research_api_health.ProbeResult("crossref", "ok", "ok", 200)
    scopus_result = check_research_api_health.ProbeResult("scopus", "missing", "missing", None)

    with (
        patch(
            "sys.argv",
            [
                "check_research_api_health.py",
                "--output",
                str(output_file),
                "--providers",
                "crossref,scopus",
            ],
        ),
        patch("check_research_api_health.probe_crossref", return_value=crossref_result) as probe_crossref,
        patch("check_research_api_health.probe_scopus", return_value=scopus_result) as probe_scopus,
        patch("check_research_api_health.probe_wos") as probe_wos,
        patch("check_research_api_health.probe_scival") as probe_scival,
        patch("check_research_api_health.probe_google_drive") as probe_google_drive,
        patch("check_research_api_health.probe_microsoft_graph") as probe_microsoft_graph,
    ):
        exit_code = check_research_api_health.main()

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert [item["provider"] for item in payload["statuses"]] == ["crossref", "scopus"]
    probe_crossref.assert_called_once()
    probe_scopus.assert_called_once()
    probe_wos.assert_not_called()
    probe_scival.assert_not_called()
    probe_google_drive.assert_not_called()
    probe_microsoft_graph.assert_not_called()


def test_main_with_providers_adds_crossref_when_missing(tmp_path: Path) -> None:
    """main should always include crossref even if omitted from --providers."""
    import check_research_api_health

    output_file = tmp_path / "health" / "results.json"
    crossref_result = check_research_api_health.ProbeResult("crossref", "ok", "ok", 200)
    scopus_result = check_research_api_health.ProbeResult("scopus", "missing", "missing", None)

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
        patch("check_research_api_health.probe_crossref", return_value=crossref_result) as probe_crossref,
        patch("check_research_api_health.probe_scopus", return_value=scopus_result) as probe_scopus,
        patch("check_research_api_health.probe_wos") as probe_wos,
        patch("check_research_api_health.probe_scival") as probe_scival,
        patch("check_research_api_health.probe_google_drive") as probe_google_drive,
        patch("check_research_api_health.probe_microsoft_graph") as probe_microsoft_graph,
    ):
        exit_code = check_research_api_health.main()

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert [item["provider"] for item in payload["statuses"]] == ["scopus", "crossref"]
    probe_scopus.assert_called_once()
    probe_crossref.assert_called_once()
    probe_wos.assert_not_called()
    probe_scival.assert_not_called()
    probe_google_drive.assert_not_called()
    probe_microsoft_graph.assert_not_called()


def test_main_with_providers_all_expands_registry(tmp_path: Path) -> None:
    """main should expand --providers all to every registered provider."""
    import check_research_api_health

    output_file = tmp_path / "health" / "results.json"
    crossref_result = check_research_api_health.ProbeResult("crossref", "ok", "ok", 200)
    scopus_result = check_research_api_health.ProbeResult("scopus", "missing", "missing", None)
    wos_result = check_research_api_health.ProbeResult("wos", "missing", "missing", None)
    scival_result = check_research_api_health.ProbeResult("scival", "missing", "missing", None)
    google_drive_result = check_research_api_health.ProbeResult(
        "google_drive", "present-but-invalid", "missing", None
    )
    microsoft_graph_result = check_research_api_health.ProbeResult(
        "microsoft_graph", "missing", "missing", None
    )

    with (
        patch(
            "sys.argv",
            [
                "check_research_api_health.py",
                "--output",
                str(output_file),
                "--providers",
                "all",
            ],
        ),
        patch("check_research_api_health.probe_crossref", return_value=crossref_result) as probe_crossref,
        patch("check_research_api_health.probe_scopus", return_value=scopus_result) as probe_scopus,
        patch("check_research_api_health.probe_wos", return_value=wos_result) as probe_wos,
        patch("check_research_api_health.probe_scival", return_value=scival_result) as probe_scival,
        patch("check_research_api_health.probe_google_drive", return_value=google_drive_result) as probe_google_drive,
        patch(
            "check_research_api_health.probe_microsoft_graph",
            return_value=microsoft_graph_result,
        ) as probe_microsoft_graph,
    ):
        exit_code = check_research_api_health.main()

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert [item["provider"] for item in payload["statuses"]] == [
        "crossref",
        "scopus",
        "wos",
        "scival",
        "google_drive",
        "microsoft_graph",
    ]
    probe_crossref.assert_called_once()
    probe_scopus.assert_called_once()
    probe_wos.assert_called_once()
    probe_scival.assert_called_once()
    probe_google_drive.assert_called_once()
    probe_microsoft_graph.assert_called_once()


def test_main_with_providers_ignores_unknown_names(tmp_path: Path, capsys) -> None:
    """main should skip unknown providers and continue with known ones."""
    import check_research_api_health

    output_file = tmp_path / "health" / "results.json"
    crossref_result = check_research_api_health.ProbeResult("crossref", "ok", "ok", 200)

    with (
        patch(
            "sys.argv",
            [
                "check_research_api_health.py",
                "--output",
                str(output_file),
                "--providers",
                "unknown,crossref,missing",
            ],
        ),
        patch("check_research_api_health.probe_crossref", return_value=crossref_result) as probe_crossref,
        patch("check_research_api_health.probe_scopus") as probe_scopus,
        patch("check_research_api_health.probe_wos") as probe_wos,
        patch("check_research_api_health.probe_scival") as probe_scival,
        patch("check_research_api_health.probe_google_drive") as probe_google_drive,
        patch("check_research_api_health.probe_microsoft_graph") as probe_microsoft_graph,
    ):
        exit_code = check_research_api_health.main()

    captured = capsys.readouterr()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert "unknown provider(s) ignored: unknown, missing" in captured.err
    assert [item["provider"] for item in payload["statuses"]] == ["crossref"]
    probe_crossref.assert_called_once()
    probe_scopus.assert_not_called()
    probe_wos.assert_not_called()
    probe_scival.assert_not_called()
    probe_google_drive.assert_not_called()
    probe_microsoft_graph.assert_not_called()


def test_main_with_empty_providers_string_fails_fast(tmp_path: Path, capsys) -> None:
    """main should fail when --providers is provided but empty after trimming."""
    import check_research_api_health

    output_file = tmp_path / "health" / "results.json"

    with (
        patch(
            "sys.argv",
            [
                "check_research_api_health.py",
                "--output",
                str(output_file),
                "--providers",
                "  ",
            ],
        ),
        patch("check_research_api_health.probe_crossref") as probe_crossref,
    ):
        exit_code = check_research_api_health.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        "Error: --providers must not be empty. Specify one or more provider names"
        in captured.err
    )
    assert not output_file.exists()
    probe_crossref.assert_not_called()
