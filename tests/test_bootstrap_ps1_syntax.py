"""Lightweight PowerShell syntax check for scripts/bootstrap_research_secrets.ps1.

Runs the PowerShell Language.Parser on the script when pwsh (or powershell) is
available on the PATH.  The test is skipped automatically on systems without a
PowerShell runtime so that Linux-only CI legs are unaffected.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "bootstrap_research_secrets.ps1"

PWSH_PARSE = """\
$scriptPath = '{path}'
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput(
    (Get-Content $scriptPath -Raw),
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -gt 0) {{
    $errors | ForEach-Object {{ Write-Error $_.Message }}
    exit 1
}}
exit 0
"""


def _pwsh_exe() -> str | None:
    """Return path to pwsh or powershell, or None if neither is installed."""
    for name in ("pwsh", "powershell"):
        if shutil.which(name):
            return name
    return None


@pytest.mark.skipif(
    _pwsh_exe() is None,
    reason="pwsh / powershell not found on PATH; syntax check skipped",
)
class TestBootstrapPs1Syntax:
    """Ensure bootstrap_research_secrets.ps1 parses without errors."""

    def test_script_exists(self):
        """The PowerShell bootstrap script must be present in the repository."""
        assert SCRIPT_PATH.exists(), (
            f"scripts/bootstrap_research_secrets.ps1 not found at {SCRIPT_PATH}"
        )

    def test_script_has_no_parse_errors(self):
        """PowerShell Language.Parser must report zero errors on the script."""
        exe = _pwsh_exe()
        assert exe is not None

        inline = PWSH_PARSE.format(path=str(SCRIPT_PATH).replace("\\", "/"))
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", inline],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"PowerShell parser reported errors:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_script_contains_required_backends(self):
        """bootstrap_research_secrets.ps1 must declare all required backend aliases."""
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        required_aliases = ["DotEnv", "Gcp", "Github", "UserEnv", "user-env"]
        for alias in required_aliases:
            assert alias in content, (
                f"Expected backend alias '{alias}' not found in bootstrap_research_secrets.ps1"
            )

    def test_script_single_quote_escaping(self):
        """Escape-PowerShellSingleQuoted must double single quotes."""
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        assert "Replace(\"'\", \"''\")" in content, (
            "Single-quote escaping ('→'') not found in bootstrap_research_secrets.ps1"
        )

    def test_script_bstr_cleanup(self):
        """SecureString BSTR cleanup must use ZeroFreeBSTR on the allocated pointer."""
        content = SCRIPT_PATH.read_text(encoding="utf-8")
        assert "ZeroFreeBSTR" in content, (
            "ZeroFreeBSTR cleanup not found in bootstrap_research_secrets.ps1"
        )
        assert "SecureStringToBSTR" in content, (
            "SecureStringToBSTR not found in bootstrap_research_secrets.ps1"
        )
