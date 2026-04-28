<#
.SYNOPSIS
One-command full research run for morskamary.
.DESCRIPTION
Windows PowerShell version.
Requires Python 3.10 or newer.
#>
[CmdletBinding()]
param([switch]$Live)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$LiveMode = $Live.IsPresent -or ($env:LIVE_RESEARCH_API_TESTS -ieq "true")
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Step {
    param([string]$Title)
    Write-Host "`n--- $Title ---" -ForegroundColor Cyan
}

function RunCmd {
    param([string]$Exe, [string[]]$CmdArgs)
    & $Exe @CmdArgs
    if ($LASTEXITCODE -ne 0) {
        throw "$Exe $($CmdArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Write-Host "=============================================" -ForegroundColor Green
Write-Host " morskamary - Full Research Run" -ForegroundColor Green
Write-Host " Live API: $(if ($LiveMode) { 'ENABLED' } else { 'DISABLED' })" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green

Push-Location $RepoRoot
try {
    Step "Step 1: Python version"
    $pyVersion = python --version 2>&1
    Write-Host $pyVersion
    $match = [regex]::Match($pyVersion, "Python (\d+)\.(\d+)")
    if ($match.Success) {
        $major = [int]$match.Groups[1].Value
        $minor = [int]$match.Groups[2].Value
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
            Write-Error "Python 3.10+ required. Found: $pyVersion"
            exit 1
        }
    }

    Step "Step 2: Install dependencies"
    RunCmd "python" @("-m", "pip", "install", "--upgrade", "pip", "--quiet")
    RunCmd "python" @("-m", "pip", "install", "-e", ".[dev]", "--quiet")
    Write-Host "Package installed."

    Step "Step 3: Environment check"
    RunCmd "python" @("scripts/check_research_env.py")

    Step "Step 4: Offline smoke test"
    RunCmd "python" @("scripts/smoke_scientific_bridge.py", "--offline")

    Step "Step 5: Live API smoke test (requires Python 3.10+)"
    if ($LiveMode) {
        $hadOldLive = Test-Path Env:LIVE_RESEARCH_API_TESTS
        $oldLive = $env:LIVE_RESEARCH_API_TESTS
        try {
            $env:LIVE_RESEARCH_API_TESTS = 'true'
            RunCmd "python" @("scripts/smoke_scientific_bridge.py", "--live-if-secrets-present")
        } finally {
            if ($hadOldLive) {
                $env:LIVE_RESEARCH_API_TESTS = $oldLive
            } else {
                Remove-Item Env:LIVE_RESEARCH_API_TESTS -ErrorAction SilentlyContinue
            }
        }
    } else {
        Write-Host "SKIPPED (pass -Live to enable)"
    }

    Step "Step 6: Full analysis"
    RunCmd "python" @("run_full_analysis.py")
    RunCmd "python" @("scripts/validate_generated_outputs.py")

    Step "Step 7: Export provider capabilities"
    RunCmd "python" @("scripts/export_research_source_capabilities.py")

    Step "Step 8: Validate research source outputs"
    RunCmd "python" @("scripts/validate_research_source_outputs.py")

    Step "Step 9: Summary"
    Write-Host "`nRun complete." -ForegroundColor Green
    Write-Host "`nConfigured providers:"
    RunCmd "python" @("scripts/audit_research_api_config.py")
} finally {
    Pop-Location
}
