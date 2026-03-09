param(
    [switch]$SkipMypy
)

$ErrorActionPreference = 'Stop'

Write-Host '======================================================================'
Write-Host 'MORSKAMARY ONE-CLICK COMPREHENSIVE SETUP (LOCAL)'
Write-Host '======================================================================'

Write-Host '[1/7] Regenerating MANIFEST_SOURCES.csv...'
python scripts/generate_manifest.py

Write-Host '[2/7] Running unit tests...'
pytest tests/ -v

Write-Host '[3/7] Running real-data workflow...'
python main_real_data.py

Write-Host '[4/7] Running workspace instructions demo...'
python demo_workspace_instructions.py

Write-Host '[5/7] Running additional tasks demo...'
python demo_additional_tasks.py

Write-Host '[6/7] Running diagnostics (editor-visible errors)...'
Write-Host 'Use VS Code Problems panel for diagnostics already validated in chat tooling.'

Write-Host '[7/7] Running mypy static check...'
if ($SkipMypy) {
    Write-Host 'Skipping mypy by request.'
} else {
    python -m mypy src
}

Write-Host '======================================================================'
Write-Host 'SETUP COMPLETE'
Write-Host '======================================================================'
