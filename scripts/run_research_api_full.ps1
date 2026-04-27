<#
.SYNOPSIS
    One-command full research run for morskamary (PowerShell).

.DESCRIPTION
    Steps:
      1. Check Python version (>= 3.9 required)
      2. Install / update the package
      3. Check research environment
      4. Offline smoke test
      5. Optional live API tests (-Live switch or $env:LIVE_RESEARCH_API_TESTS=true)
      6. Full analysis
      7. Export provider capabilities
      8. Validate research source outputs
      9. Print summary

.PARAMETER Live
    Enable live proprietary API calls (requires configured provider credentials).

.EXAMPLE
    .\scripts\run_research_api_full.ps1           # offline only
    .\scripts\run_research_api_full.ps1 -Live     # enable live API calls

.NOTES
    Load credentials first:
      . .\.env.ps1   # if you used bootstrap_research_secrets.ps1 -Backend DotEnv
    See docs/ONE_CLICK_RESEARCH_RUNBOOK.md for the full workflow.
#>

[CmdletBinding()]
param(
    [switch]$Live
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$LiveMode = $Live.IsPresent -or ($env:LIVE_RESEARCH_API_TESTS -ieq 'true')
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Step([string]$Title) {
    Write-Host ""
    Write-Host "--- $Title ---" -ForegroundColor Cyan
}

function RunPy([string]$Script, [hashtable]$Env = @{}) {
    $oldEnv = @{}
    foreach ($k in $Env.Keys) {
        $oldEnv[$k] = [System.Environment]::GetEnvironmentVariable($k)
        [System.Environment]::SetEnvironmentVariable($k, $Env[$k])
    }
    try {
        python $Script
        if ($LASTEXITCODE -ne 0) { throw "Script $Script failed with exit code $LASTEXITCODE" }
    } finally {
        foreach ($k in $oldEnv.Keys) {
            [System.Environment]::SetEnvironmentVariable($k, $oldEnv[$k])
        }
    }
}

Write-Host "=============================================" -ForegroundColor Green
Write-Host "  morskamary — Full Research Run (PowerShell)" -ForegroundColor Green
Write-Host "  Live API: $($LiveMode.ToString().ToUpper())" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green

Push-Location $RepoRoot
try {

    # Step 1: Python version check
    Step "Step 1: Python version"
    $pyVersion = python --version 2>&1
    Write-Host $pyVersion
    $match = [regex]::Match($pyVersion, 'Python (\d+)\.(\d+)')
    if ($match.Success) {
        $major = [int]$match.Groups[1].Value
        $minor = [int]$match.Groups[2].Value
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 9)) {
            Write-Error "Python 3.9+ required. Found: $pyVersion"
            exit 1
        }
    }

    # Step 2: Install/update package
    Step "Step 2: Install dependencies"
    python -m pip install --upgrade pip --quiet
    python -m pip install -e ".[dev]" --quiet
    Write-Host "Package installed."

    # Step 3: Environment check
    Step "Step 3: Environment check"
    RunPy "scripts/check_research_env.py"

    # Step 4: Offline smoke test (always)
    Step "Step 4: Offline smoke test"
    RunPy "scripts/smoke_scientific_bridge.py" @{} # passes --offline via script default
    python scripts/smoke_scientific_bridge.py --offline
    if ($LASTEXITCODE -ne 0) { throw "Offline smoke test failed." }

    # Step 5: Live API smoke (optional)
    Step "Step 5: Live API smoke test"
    if ($LiveMode) {
        $env:LIVE_RESEARCH_API_TESTS = 'true'
        python scripts/smoke_scientific_bridge.py --live-if-secrets-present
        if ($LASTEXITCODE -ne 0) { throw "Live smoke test failed." }
        $env:LIVE_RESEARCH_API_TESTS = 'false'
    } else {
        Write-Host "SKIPPED (pass -Live to enable)"
    }

    # Step 6: Full analysis
    Step "Step 6: Full analysis"
    python run_full_analysis.py
    if ($LASTEXITCODE -ne 0) { throw "run_full_analysis.py failed." }
    python scripts/validate_generated_outputs.py
    if ($LASTEXITCODE -ne 0) { throw "validate_generated_outputs.py failed." }

    # Step 7: Export capabilities
    Step "Step 7: Export provider capabilities"
    python scripts/export_research_source_capabilities.py
    if ($LASTEXITCODE -ne 0) { throw "export_research_source_capabilities.py failed." }

    # Step 8: Validate research outputs
    Step "Step 8: Validate research source outputs"
    python scripts/validate_research_source_outputs.py
    if ($LASTEXITCODE -ne 0) { throw "validate_research_source_outputs.py failed." }

    # Step 9: Summary
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor Green
    Write-Host "  Run complete." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Configured providers:"
    python scripts/audit_research_api_config.py 2>&1 | Where-Object { $_ -match '✓|✗' } | Select-Object -First 10
    Write-Host ""
    Write-Host "  Next steps:"
    if (-not $LiveMode) {
        Write-Host "  - Run with -Live to enable live API calls:"
        Write-Host "    .\scripts\run_research_api_full.ps1 -Live"
    }
    Write-Host "  - Run Cloud Build offline mirror:"
    Write-Host "    .\scripts\run_cloudbuild_research_full.ps1 -Offline"
    Write-Host "  - Run Cloud Build live mirror (requires secrets):"
    Write-Host "    .\scripts\run_cloudbuild_research_full.ps1 -Live"
    Write-Host "=============================================" -ForegroundColor Green

} finally {
    Pop-Location
}
