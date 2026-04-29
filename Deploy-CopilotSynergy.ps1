<#
.SYNOPSIS
Automated Deployment for GitHub Copilot MCP Synergy Merge (OPTIONAL TOOLING)

.DESCRIPTION
**IMPORTANT: This is optional, local, workstation-specific tooling.**
**Platform: Windows only.** Supports VS Code (Stable) and VS Code Insiders.

This script scaffolds MCP configuration for the morskamary Blue Sociology project,
writing only to the two officially supported VS Code MCP targets:

  Workspace:     .vscode/mcp.json  (repo-safe, shareable servers)
  User profile:  <VS Code profile root>/mcp.json  (personal/credential servers)

It uses the current VS Code MCP schema (top-level "servers" + "inputs"), merges
non-destructively into any existing configuration, and does NOT install global npm
packages or require Administrator privileges. All MCP packages are invoked via
npx at runtime.

On JSON parse failure of an existing config file, a timestamped backup is created
and the script aborts. Use -Force to overwrite instead.

This is NOT a core repository dependency. Python >=3.9 is the only required
dependency for morskamary development.

For standard Python-first development, see CONTRIBUTING.md and use
main_real_data.py for real-data workflows.

.PARAMETER MorskaMaryRepoPath
Path to local morskamary repository.

.PARAMETER MaritimeSociologyRepoPath
Path to local maritimesociology repository.

.PARAMETER SharePointSyncPath
Path to synchronized SharePoint folder.

.PARAMETER GoogleOAuthCredentialsPath
Secure path to Google OAuth credentials JSON file.

.PARAMETER VsCodeChannel
Which VS Code installation to target. Stable (default), Insiders, or Auto.
Auto prefers Stable if its profile root exists, falls back to Insiders.

.PARAMETER Force
If set, overwrite a malformed existing mcp.json instead of aborting.

.EXAMPLE
.\Deploy-CopilotSynergy.ps1 -MorskaMaryRepoPath "C:\GitHub\morskamary"

.EXAMPLE
.\Deploy-CopilotSynergy.ps1 `
  -MorskaMaryRepoPath "C:\GitHub\morskamary" `
  -MaritimeSociologyRepoPath "C:\GitHub\maritimesociology" `
  -SharePointSyncPath "C:\Users\You\OneDrive - Uniwersytet Szczecinski\PORT CITY HUB UPLOAD" `
  -GoogleOAuthCredentialsPath (Read-Host "Google OAuth credentials JSON path" -AsSecureString) `
  -VsCodeChannel Insiders

.NOTES
Platform:  Windows only (uses %APPDATA% for VS Code profile root).
Requirements: Node.js >=18 (for npx), Python >=3.9.
No Administrator privileges required.
No global npm packages are installed; npx handles on-demand execution.
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$MorskaMaryRepoPath = "$PSScriptRoot",

    [Parameter(Mandatory=$false)]
    [string]$MaritimeSociologyRepoPath = "",

    [Parameter(Mandatory=$false)]
    [string]$SharePointSyncPath = "",

    [Parameter(Mandatory=$false)]
    [securestring]$GoogleOAuthCredentialsPath,

    [Parameter(Mandatory=$false)]
    [ValidateSet("Stable","Insiders","Auto")]
    [string]$VsCodeChannel = "Stable",

    [switch]$Force
)

$ErrorActionPreference = "Stop"

# ── Helper: safe JSON reader with backup-on-failure ──────────────────────────

function ConvertFrom-SecureStringToPlainText {
    param(
        [Parameter(Mandatory=$true)]
        [securestring]$SecureValue
    )

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Read-McpJson {
    param(
        [string]$Path,
        [switch]$ForceOverwrite
    )
    if (-not (Test-Path $Path)) { return $null }

    try {
        $raw = Get-Content -Path $Path -Raw
    } catch {
        Write-Host "  Failed to read existing config at $Path. Aborting." -ForegroundColor Red
        Write-Host "  $($_.Exception.Message)" -ForegroundColor Yellow
        exit 1
    }

    try {
        return ($raw | ConvertFrom-Json)
    } catch {
        $backupPath = "$Path.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item -Path $Path -Destination $backupPath -Force
        Write-Host "  Backup saved to: $backupPath" -ForegroundColor DarkYellow

        if ($ForceOverwrite) {
            Write-Host "  -Force specified: will overwrite malformed config." -ForegroundColor DarkYellow
            return $null
        } else {
            Write-Host "  Existing $Path is malformed JSON. Aborting." -ForegroundColor Red
            Write-Host "  Re-run with -Force to overwrite." -ForegroundColor Yellow
            exit 1
        }
    }
}

# ── Banner ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  GitHub Copilot MCP Synergy Merge Deployment" -ForegroundColor Cyan
Write-Host "  morskamary Blue Sociology Research Toolkit" -ForegroundColor Cyan
Write-Host "  Windows only | VS Code MCP schema: servers + inputs" -ForegroundColor DarkCyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

# ── Prerequisite: Node.js >=18 ───────────────────────────────────────────────

Write-Host "[PREREQUISITE] Verifying Node.js >=18 (needed for npx)..." -ForegroundColor Yellow
try {
    $nodeVersionRaw = node -v 2>&1
    if ($LASTEXITCODE -ne 0) { throw "node exited with $LASTEXITCODE" }
    $nodeMatch = [regex]::Match($nodeVersionRaw, '(\d+)\.(\d+)\.(\d+)')
    if (-not $nodeMatch.Success) { throw "Could not parse version from: $nodeVersionRaw" }
    $nodeMajor = [int]$nodeMatch.Groups[1].Value
    if ($nodeMajor -lt 18) {
        Write-Host "  Node.js $($nodeMatch.Value) detected, but >=18 is required." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Node.js $($nodeMatch.Value)" -ForegroundColor Green
} catch {
    Write-Host "  Node.js not found." -ForegroundColor Red
    Write-Host "  Install Node.js LTS (>=18) from https://nodejs.org, then re-run." -ForegroundColor Yellow
    exit 1
}

# ── Prerequisite: Python >=3.9 ───────────────────────────────────────────────

Write-Host "[PREREQUISITE] Verifying Python >=3.9..." -ForegroundColor Yellow
$pythonFound = $false
$pythonCmd = ""

foreach ($candidate in @("python", "py")) {
    if ($pythonFound) { break }
    try {
        $pyVersionText = & $candidate --version 2>&1
        if ($LASTEXITCODE -ne 0) { continue }
        $pyMatch = [regex]::Match($pyVersionText, '(\d+)\.(\d+)\.(\d+)')
        if (-not $pyMatch.Success) { continue }
        $pyMajor = [int]$pyMatch.Groups[1].Value
        $pyMinor = [int]$pyMatch.Groups[2].Value
        if (($pyMajor -lt 3) -or ($pyMajor -eq 3 -and $pyMinor -lt 9)) {
            Write-Host "  Python $($pyMatch.Value) detected via '$candidate', but >=3.9 is required." -ForegroundColor Red
            exit 1
        }
        $pythonFound = $true
        $pythonCmd = $candidate
        Write-Host "  Python $($pyMatch.Value) (via $candidate)" -ForegroundColor Green
    } catch {}
}

if (-not $pythonFound) {
    Write-Host "  Python not found." -ForegroundColor Red
    Write-Host "  Install Python >=3.9 from https://python.org (check 'Add Python to PATH')." -ForegroundColor Yellow
    exit 1
}

# ── Step 1/4: Resolve VS Code profile root & validate paths ─────────────────

Write-Host ""
Write-Host "[STEP 1/4] Resolving VS Code profile root (channel: $VsCodeChannel)..." -ForegroundColor Yellow

if (-not $env:APPDATA) {
    Write-Host "  %APPDATA% is not set. This script requires Windows." -ForegroundColor Red
    exit 1
}

$StableRoot  = "$env:APPDATA\Code\User"
$InsidersRoot = "$env:APPDATA\Code - Insiders\User"

switch ($VsCodeChannel) {
    "Stable" {
        $VsCodeProfileRoot = $StableRoot
    }
    "Insiders" {
        $VsCodeProfileRoot = $InsidersRoot
    }
    "Auto" {
        if (Test-Path $StableRoot) {
            $VsCodeProfileRoot = $StableRoot
            Write-Host "  Auto-detected: Stable" -ForegroundColor Gray
        } elseif (Test-Path $InsidersRoot) {
            $VsCodeProfileRoot = $InsidersRoot
            Write-Host "  Auto-detected: Insiders" -ForegroundColor Gray
        } else {
            Write-Host "  No VS Code profile root found at:" -ForegroundColor Red
            Write-Host "    $StableRoot" -ForegroundColor Red
            Write-Host "    $InsidersRoot" -ForegroundColor Red
            exit 1
        }
    }
}

$UserProfileMcpFile = "$VsCodeProfileRoot\mcp.json"
Write-Host "  User-profile MCP config: $UserProfileMcpFile" -ForegroundColor Gray

if (-not (Test-Path $MorskaMaryRepoPath)) {
    Write-Host "  morskamary repository not found at: $MorskaMaryRepoPath" -ForegroundColor Red
    exit 1
}
Write-Host "  morskamary repository: $MorskaMaryRepoPath" -ForegroundColor Green

$ScientificBridgeScriptPath = Join-Path $MorskaMaryRepoPath "scientific_bridge.py"
$WorkspaceMcpFile = Join-Path $MorskaMaryRepoPath ".vscode\mcp.json"
Write-Host "  Workspace MCP config:    $WorkspaceMcpFile" -ForegroundColor Gray

# ── Step 2/4: Workspace .vscode/mcp.json (repo-safe servers only) ────────────

Write-Host ""
Write-Host "[STEP 2/4] Preparing workspace MCP config (.vscode/mcp.json)..." -ForegroundColor Yellow

$WorkspaceConfig = Read-McpJson -Path $WorkspaceMcpFile -ForceOverwrite:$Force
if (-not $WorkspaceConfig) {
    $WorkspaceConfig = [PSCustomObject]@{ servers = [PSCustomObject]@{} }
}
if (-not $WorkspaceConfig.servers) {
    $WorkspaceConfig | Add-Member -NotePropertyName "servers" -NotePropertyValue ([PSCustomObject]@{})
}

# scientificCitationBridge: repo-safe (uses ${workspaceFolder}, no personal paths)
if (Test-Path $ScientificBridgeScriptPath) {
    $WorkspaceConfig.servers | Add-Member -Force -NotePropertyName "scientificCitationBridge" -NotePropertyValue ([PSCustomObject]@{
        type    = "stdio"
        command = $pythonCmd
        args    = @('${workspaceFolder}/scientific_bridge.py')
    })
    Write-Host "  + scientificCitationBridge (repo-safe, uses workspaceFolder)" -ForegroundColor Green
} else {
    Write-Host "  - scientific_bridge.py not found; skipping scientificCitationBridge" -ForegroundColor DarkYellow
}

# Ensure .vscode directory exists
$VsCodeDir = Join-Path $MorskaMaryRepoPath ".vscode"
if (-not (Test-Path $VsCodeDir)) {
    New-Item -ItemType Directory -Path $VsCodeDir -Force | Out-Null
}

$WorkspaceConfig | ConvertTo-Json -Depth 10 | Set-Content -Path $WorkspaceMcpFile -Encoding UTF8
Write-Host "  Saved: $WorkspaceMcpFile" -ForegroundColor Green

# ── Step 3/4: User-profile mcp.json (personal/credential servers) ────────────

Write-Host ""
Write-Host "[STEP 3/4] Preparing user-profile MCP config ($UserProfileMcpFile)..." -ForegroundColor Yellow

$UserConfig = Read-McpJson -Path $UserProfileMcpFile -ForceOverwrite:$Force
if (-not $UserConfig) {
    $UserConfig = [PSCustomObject]@{ servers = [PSCustomObject]@{} }
}
if (-not $UserConfig.servers) {
    $UserConfig | Add-Member -NotePropertyName "servers" -NotePropertyValue ([PSCustomObject]@{})
}

# morskamaryLocal: filesystem access to the local morskamary clone
$UserConfig.servers | Add-Member -Force -NotePropertyName "morskamaryLocal" -NotePropertyValue ([PSCustomObject]@{
    type    = "stdio"
    command = "npx"
    args    = @("-y", "@modelcontextprotocol/server-filesystem", $MorskaMaryRepoPath)
})
Write-Host "  + morskamaryLocal ($MorskaMaryRepoPath)" -ForegroundColor Green

# maritimesociologyLocal: optional second repo
if ($MaritimeSociologyRepoPath -and (Test-Path $MaritimeSociologyRepoPath)) {
    $UserConfig.servers | Add-Member -Force -NotePropertyName "maritimesociologyLocal" -NotePropertyValue ([PSCustomObject]@{
        type    = "stdio"
        command = "npx"
        args    = @("-y", "@modelcontextprotocol/server-filesystem", $MaritimeSociologyRepoPath)
    })
    Write-Host "  + maritimesociologyLocal ($MaritimeSociologyRepoPath)" -ForegroundColor Green
}

# sharepointUniversity: optional SharePoint sync folder
if ($SharePointSyncPath -and (Test-Path $SharePointSyncPath)) {
    $UserConfig.servers | Add-Member -Force -NotePropertyName "sharepointUniversity" -NotePropertyValue ([PSCustomObject]@{
        type    = "stdio"
        command = "npx"
        args    = @("-y", "@modelcontextprotocol/server-filesystem", $SharePointSyncPath)
    })
    Write-Host "  + sharepointUniversity ($SharePointSyncPath)" -ForegroundColor Green
}

# googleDriveResearch: optional Google Drive via OAuth
$googleOAuthCredentialsPlainPath = $null
if ($GoogleOAuthCredentialsPath) {
    $googleOAuthCredentialsPlainPath = ConvertFrom-SecureStringToPlainText -SecureValue $GoogleOAuthCredentialsPath
}

if ($googleOAuthCredentialsPlainPath -and (Test-Path $googleOAuthCredentialsPlainPath)) {
    $UserConfig.servers | Add-Member -Force -NotePropertyName "googleDriveResearch" -NotePropertyValue ([PSCustomObject]@{
        type    = "stdio"
        command = "npx"
        args    = @("-y", "@piotr-agier/google-drive-mcp")
        env     = [PSCustomObject]@{
            GOOGLE_DRIVE_OAUTH_CREDENTIALS = $googleOAuthCredentialsPlainPath
        }
    })
    Write-Host "  + googleDriveResearch (OAuth credentials configured)" -ForegroundColor Green
}

# Ensure parent directory exists
$UserProfileDir = Split-Path $UserProfileMcpFile -Parent
if (-not (Test-Path $UserProfileDir)) {
    New-Item -ItemType Directory -Path $UserProfileDir -Force | Out-Null
}

$UserConfig | ConvertTo-Json -Depth 10 | Set-Content -Path $UserProfileMcpFile -Encoding UTF8
Write-Host "  Saved: $UserProfileMcpFile" -ForegroundColor Green

# ── Step 4/4: Summary & next steps ──────────────────────────────────────────

Write-Host ""
Write-Host "[STEP 4/4] Deployment complete!" -ForegroundColor Green
Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  FILES WRITTEN" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Workspace (repo-safe, shareable):" -ForegroundColor White
Write-Host "    $WorkspaceMcpFile" -ForegroundColor Gray
Write-Host ""
Write-Host "  User profile (personal, credentials, local paths):" -ForegroundColor White
Write-Host "    $UserProfileMcpFile" -ForegroundColor Gray
Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  NEXT STEPS" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Restart VS Code to pick up the new MCP configuration." -ForegroundColor White
Write-Host ""
Write-Host "2. When VS Code prompts to 'Trust' an MCP server, click 'Start'." -ForegroundColor White
Write-Host "   Manage servers via: Ctrl+Shift+P > MCP: List Servers" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Use the VS Code model picker (Auto is recommended)." -ForegroundColor White
Write-Host "   Auto selects from current top-tier models automatically." -ForegroundColor Gray
Write-Host ""
Write-Host "4. Verify MCP access in Copilot Chat:" -ForegroundColor White
Write-Host ""
Write-Host "   @workspace List available MCP tools and read README.md from the" -ForegroundColor Cyan
Write-Host "   morskamary repository to verify access." -ForegroundColor Cyan
Write-Host ""
Write-Host "5. Review your GitHub Copilot privacy settings:" -ForegroundColor White
Write-Host "   https://github.com/settings/copilot" -ForegroundColor Gray
Write-Host "   Under Data handling, disable:" -ForegroundColor Gray
Write-Host "   'Allow GitHub to use my data for AI model training'" -ForegroundColor Gray
Write-Host "   (Effective from Apr 24 2026; see GitHub Docs for current wording)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "For detailed documentation, see: COPILOT_MCP_SETUP.md" -ForegroundColor Yellow
Write-Host ""
