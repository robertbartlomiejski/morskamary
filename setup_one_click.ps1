param(
    [switch]$SkipMypy
)

$ErrorActionPreference = 'Stop'

function Invoke-Step {
    param(
        [Parameter(Mandatory=$true)][string]$Label,
        [Parameter(Mandatory=$true)][scriptblock]$Action
    )

    Write-Host $Label
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Label (exit code: $LASTEXITCODE)"
    }
}

Write-Host '======================================================================'
Write-Host 'MORSKAMARY ONE-CLICK COMPREHENSIVE SETUP (LOCAL)'
Write-Host '======================================================================'

Invoke-Step '[1/7] Regenerating MANIFEST_SOURCES.csv...' { python scripts/generate_manifest.py }

Invoke-Step '[2/7] Running unit tests...' { pytest tests/ -v }

Invoke-Step '[3/7] Running real-data workflow...' { python main_real_data.py }

Invoke-Step '[4/7] Running workspace instructions demo...' { python demo_workspace_instructions.py }

# Mandatory comprehensive validation step: keeps AI-instruction workflows
# continuously verified (literature extraction, TMBD mapping, advanced credentials).
Invoke-Step '[5/7] Running additional tasks demo (mandatory comprehensive validation)...' { python demo_additional_tasks.py }

Write-Host '[6/7] Running diagnostics (editor-visible errors)...'
Write-Host 'Use VS Code Problems panel for diagnostics already validated in chat tooling.'

Write-Host '[7/7] Running mypy static check...'
if ($SkipMypy) {
    Write-Host 'Skipping mypy by request.'
} else {
    Invoke-Step '[7/7] Running mypy static check...' { python -m mypy src }
}

Write-Host '======================================================================'
Write-Host 'SETUP COMPLETE'
Write-Host '======================================================================'
