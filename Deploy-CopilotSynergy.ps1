<#
.SYNOPSIS
Automated Deployment for GitHub Copilot MCP Synergy Merge (OPTIONAL TOOLING)

.DESCRIPTION
**IMPORTANT: This is optional, local, workstation-specific tooling.**

This script installs Node.js dependencies, scaffolds the MCP configuration, and links local/cloud repositories
for the morskamary Blue Sociology project with full data integration.

This is NOT a core repository dependency. Python ≥3.9 is the only required dependency for morskamary development.
Use this script only if you need advanced GitHub Copilot integration with local files and cloud storage.

For standard Python-first development, see CONTRIBUTING.md and use main_real_data.py for real-data workflows.

.PARAMETER MorskaMaryRepoPath
Path to local morskamary repository

.PARAMETER MaritimeSociologyRepoPath
Path to local maritimesociology repository

.PARAMETER SharePointSyncPath
Path to synchronized SharePoint folder

.PARAMETER GoogleOAuthCredentialsPath
Path to Google OAuth credentials JSON file

.PARAMETER ScientificBridgeScriptPath
Path to scientific_bridge.py script

.PARAMETER SkipNodeInstall
Skip Node.js package installation

.EXAMPLE
.\Deploy-CopilotSynergy.ps1 -MorskaMaryRepoPath "C:\GitHub\morskamary"

.NOTES
Requirements: Node.js ≥18, Python ≥3.9
Run as Administrator for global npm package installation
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$MorskaMaryRepoPath = "$PSScriptRoot",

    [Parameter(Mandatory=$false)]
    [string]$MaritimeSociologyRepoPath = "",

    [Parameter(Mandatory=$false)]
    [string]$SharePointSyncPath = "",

    [Parameter(Mandatory=$false)]
    [string]$GoogleOAuthCredentialsPath = "",

    [Parameter(Mandatory=$false)]
    [string]$ScientificBridgeScriptPath = "$PSScriptRoot\scientific_bridge.py",

    [switch]$SkipNodeInstall
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  GitHub Copilot MCP Synergy Merge Deployment" -ForegroundColor Cyan
Write-Host "  morskamary Blue Sociology Research Toolkit" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

# Verify Node.js Installation
Write-Host "[PREREQUISITE] Verifying Node.js installation..." -ForegroundColor Yellow
try {
    $nodeVersion = node -v
    Write-Host "  ✓ Node.js detected: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Node.js not found!" -ForegroundColor Red
    Write-Host "  Please install Node.js from https://nodejs.org (LTS version recommended)" -ForegroundColor Red
    Write-Host "  After installation, restart PowerShell and run this script again." -ForegroundColor Yellow
    exit 1
}

# Verify Python Installation
Write-Host "[PREREQUISITE] Verifying Python installation..." -ForegroundColor Yellow
$pythonFound = $false
$pythonCmd = ""

try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pythonFound = $true
        $pythonCmd = "python"
        Write-Host "  ✓ Python detected: $pythonVersion" -ForegroundColor Green
    }
} catch {}

if (-not $pythonFound) {
    try {
        $pythonVersion = py --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonFound = $true
            $pythonCmd = "py"
            Write-Host "  ✓ Python detected (via py launcher): $pythonVersion" -ForegroundColor Green
        }
    } catch {}
}

if (-not $pythonFound) {
    Write-Host "  ✗ Python not found!" -ForegroundColor Red
    Write-Host "  Please install Python ≥3.9 from https://python.org" -ForegroundColor Red
    Write-Host "  Ensure you check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    exit 1
}

# Define Configuration Paths
Write-Host ""
Write-Host "[STEP 1/5] Configuring paths..." -ForegroundColor Yellow

$VsCodeUserDir = "$env:APPDATA\Code\User"
$McpConfigDir = "$VsCodeUserDir\globalStorage\github.copilot"
$McpConfigFile = "$McpConfigDir\mcp_settings.json"

# VS Code may use different paths for different extensions
$AlternativeMcpPaths = @(
    "$VsCodeUserDir\globalStorage\saoudrizwan.claude-dev\settings",
    "$VsCodeUserDir\globalStorage\anthropics.claude-vscode\settings",
    "$VsCodeUserDir"
)

Write-Host "  Primary MCP config target: $McpConfigFile" -ForegroundColor Gray

# Validate Repository Paths
if (-not (Test-Path $MorskaMaryRepoPath)) {
    Write-Host "  ✗ morskamary repository not found at: $MorskaMaryRepoPath" -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ morskamary repository: $MorskaMaryRepoPath" -ForegroundColor Green

# Install MCP Server Packages
if (-not $SkipNodeInstall) {
    Write-Host ""
    Write-Host "[STEP 2/5] Installing MCP server packages..." -ForegroundColor Yellow
    Write-Host "  This may take a few minutes..." -ForegroundColor Gray

    try {
        Write-Host "  Installing @modelcontextprotocol/server-filesystem..." -ForegroundColor Gray
        npm install -g @modelcontextprotocol/server-filesystem

        Write-Host "  Installing @piotr-agier/google-drive-mcp..." -ForegroundColor Gray
        npm install -g @piotr-agier/google-drive-mcp

        Write-Host "  ✓ MCP packages installed successfully" -ForegroundColor Green
    } catch {
        Write-Host "  ✗ Failed to install MCP packages" -ForegroundColor Red
        Write-Host "  Error: $_" -ForegroundColor Red
        Write-Host "  Try running PowerShell as Administrator" -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host ""
    Write-Host "[STEP 2/5] Skipping Node.js package installation (--SkipNodeInstall)" -ForegroundColor Yellow
}

# Create Configuration Directory
Write-Host ""
Write-Host "[STEP 3/5] Creating configuration directory..." -ForegroundColor Yellow
if (-not (Test-Path -Path $McpConfigDir)) {
    New-Item -ItemType Directory -Path $McpConfigDir -Force | Out-Null
    Write-Host "  ✓ Created: $McpConfigDir" -ForegroundColor Green
} else {
    Write-Host "  ✓ Directory exists: $McpConfigDir" -ForegroundColor Green
}

# Generate MCP Configuration
Write-Host ""
Write-Host "[STEP 4/5] Generating MCP configuration..." -ForegroundColor Yellow

$McpServers = @{
    "morskamary-local" = @{
        command = "npx"
        args = @("-y", "@modelcontextprotocol/server-filesystem", $MorskaMaryRepoPath)
        description = "Local morskamary Blue Sociology repository"
    }
}

# Add optional servers if paths are provided
if ($MaritimeSociologyRepoPath -and (Test-Path $MaritimeSociologyRepoPath)) {
    $McpServers["maritimesociology-local"] = @{
        command = "npx"
        args = @("-y", "@modelcontextprotocol/server-filesystem", $MaritimeSociologyRepoPath)
        description = "Local maritimesociology repository"
    }
    Write-Host "  ✓ Added maritimesociology repository" -ForegroundColor Green
}

if ($SharePointSyncPath -and (Test-Path $SharePointSyncPath)) {
    $McpServers["sharepoint-university"] = @{
        command = "npx"
        args = @("-y", "@modelcontextprotocol/server-filesystem", $SharePointSyncPath)
        description = "University of Szczecin SharePoint synchronized folder"
    }
    Write-Host "  ✓ Added SharePoint sync folder" -ForegroundColor Green
}

if ($GoogleOAuthCredentialsPath -and (Test-Path $GoogleOAuthCredentialsPath)) {
    $McpServers["google-drive-research"] = @{
        command = "npx"
        args = @("-y", "@piotr-agier/google-drive-mcp")
        env = @{
            GOOGLE_DRIVE_OAUTH_CREDENTIALS = $GoogleOAuthCredentialsPath
        }
        description = "Google Drive research folder"
    }
    Write-Host "  ✓ Added Google Drive access" -ForegroundColor Green
}

if (Test-Path $ScientificBridgeScriptPath) {
    $McpServers["scientific-citation-bridge"] = @{
        command = $pythonCmd
        args = @($ScientificBridgeScriptPath)
        description = "Scientific database bridge for Crossref and academic sources"
    }
    Write-Host "  ✓ Added scientific citation bridge" -ForegroundColor Green
}

$McpConfig = @{
    mcpServers = $McpServers
}

# Save Configuration
$McpConfig | ConvertTo-Json -Depth 10 | Set-Content -Path $McpConfigFile -Encoding UTF8
Write-Host "  ✓ Configuration saved to: $McpConfigFile" -ForegroundColor Green

# Also save to project .vscode directory for version control
$ProjectMcpConfig = "$MorskaMaryRepoPath\.vscode\mcp_local.json"
$McpConfig | ConvertTo-Json -Depth 10 | Set-Content -Path $ProjectMcpConfig -Encoding UTF8
Write-Host "  ✓ Project configuration saved to: $ProjectMcpConfig" -ForegroundColor Green

# Final Instructions
Write-Host ""
Write-Host "[STEP 5/5] Deployment complete!" -ForegroundColor Green
Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  NEXT STEPS" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Restart VS Code to initialize MCP servers" -ForegroundColor White
Write-Host ""
Write-Host "2. When VS Code prompts to 'Trust' the MCP servers, click 'Yes'" -ForegroundColor White
Write-Host ""
Write-Host "3. In GitHub Copilot Chat, select the model:" -ForegroundColor White
Write-Host "   • Claude 3.5 Sonnet (recommended for deep reasoning)" -ForegroundColor Gray
Write-Host "   • GPT-4o (alternative)" -ForegroundColor Gray
Write-Host ""
Write-Host "4. Initialize the Copilot Agent with full context:" -ForegroundColor White
Write-Host ""
Write-Host "   @workspace You are now connected to MCP servers for the morskamary" -ForegroundColor Cyan
Write-Host "   Blue Sociology project. List available MCP tools and read the" -ForegroundColor Cyan
Write-Host "   README.md from the morskamary repository to verify access." -ForegroundColor Cyan
Write-Host ""
Write-Host "5. For privacy, verify GitHub Copilot settings:" -ForegroundColor White
Write-Host "   • GitHub.com > Settings > Copilot > Privacy" -ForegroundColor Gray
Write-Host "   • Disable 'Allow GitHub to use my code snippets for model training'" -ForegroundColor Gray
Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "For detailed documentation, see: COPILOT_MCP_SETUP.md" -ForegroundColor Yellow
Write-Host ""
