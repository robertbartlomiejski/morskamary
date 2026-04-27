<#
.SYNOPSIS
    One-command Cloud Build wrapper for morskamary (PowerShell).

.DESCRIPTION
    Checks gcloud authentication, project, Cloud Build API, and (for live mode)
    Secret Manager version presence before submitting the right build config.

      cloudbuild.yaml       — Offline mode: no secrets required.
      cloudbuild.live.yaml  — Live mode: requires populated Secret Manager secrets.

.PARAMETER Live
    Submit using cloudbuild.live.yaml (requires secrets in Secret Manager).

.PARAMETER Offline
    Submit using cloudbuild.yaml (no secrets required). Default.

.PARAMETER ProjectId
    GCP project ID. Defaults to $env:GCP_PROJECT_ID or the active gcloud project.

.PARAMETER NoSource
    Pass --no-source to gcloud builds submit (skips source upload).

.EXAMPLE
    .\scripts\run_cloudbuild_research_full.ps1 -Offline
    .\scripts\run_cloudbuild_research_full.ps1 -Live -ProjectId my-project-id

.NOTES
    For the Bash equivalent, see: scripts/run_cloudbuild_research_full.sh
    See docs/GOOGLE_CLOUD_BUILD_OPTIONAL_SETUP.md for full setup instructions.
#>

[CmdletBinding(DefaultParameterSetName = 'Offline')]
param(
    [Parameter(ParameterSetName = 'Live', Mandatory = $false)]
    [switch]$Live,

    [Parameter(ParameterSetName = 'Offline', Mandatory = $false)]
    [switch]$Offline,

    [string]$ProjectId = "",

    [switch]$NoSource
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$LiveMode = $Live.IsPresent
$Config   = if ($LiveMode) { "cloudbuild.live.yaml" } else { "cloudbuild.yaml" }
$Secrets  = @("crossref-mailto", "elsevier-api-key", "scopus-api-key", "wos-api-key", "scival-api-key")

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  morskamary — Cloud Build Wrapper (PowerShell)" -ForegroundColor Cyan
Write-Host "  Mode: $(if ($LiveMode) { 'LIVE (cloudbuild.live.yaml)' } else { 'offline (cloudbuild.yaml)' })" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# Step 1: Check gcloud is installed
# ---------------------------------------------------------------------------

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Error "gcloud CLI not found. Install Google Cloud SDK:`nhttps://cloud.google.com/sdk/docs/install"
    exit 1
}
Write-Host "[OK] gcloud CLI found"

# ---------------------------------------------------------------------------
# Step 2: Check authentication
# ---------------------------------------------------------------------------

gcloud auth print-access-token | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Not authenticated. Run:`n  gcloud auth login`n  gcloud auth application-default login"
    exit 1
}
Write-Host "[OK] gcloud authenticated"

# ---------------------------------------------------------------------------
# Step 3: Detect project
# ---------------------------------------------------------------------------

if ([string]::IsNullOrEmpty($ProjectId)) {
    $ProjectId = if ($env:GCP_PROJECT_ID) { $env:GCP_PROJECT_ID } else {
        (gcloud config get-value project 2>$null).Trim()
    }
}
if ([string]::IsNullOrEmpty($ProjectId)) {
    Write-Error "No GCP project set.`n  gcloud config set project YOUR_PROJECT_ID`n  # or: `$env:GCP_PROJECT_ID = 'YOUR_PROJECT_ID'"
    exit 1
}
Write-Host "[OK] Project: $ProjectId"

# ---------------------------------------------------------------------------
# Step 4: Check Cloud Build API is enabled
# ---------------------------------------------------------------------------

$apis = gcloud services list --project=$ProjectId --filter="name:cloudbuild.googleapis.com" --format="value(name)" 2>$null
if (-not ($apis -match 'cloudbuild')) {
    Write-Error "Cloud Build API not enabled for project $ProjectId.`n  Enable: gcloud services enable cloudbuild.googleapis.com --project=$ProjectId"
    exit 1
}
Write-Host "[OK] Cloud Build API enabled"

# ---------------------------------------------------------------------------
# Step 5 (live only): Check secret versions
# ---------------------------------------------------------------------------

if ($LiveMode) {
    Write-Host ""
    Write-Host "Checking Secret Manager versions (required for cloudbuild.live.yaml)..."
    $missingSecrets = @()
    foreach ($secret in $Secrets) {
        $versions = gcloud secrets versions list $secret `
            --project=$ProjectId `
            --filter="state=ENABLED" `
            --format="value(name)" 2>$null
        if ($versions) {
            Write-Host "  [OK] $secret — has version(s)"
        } else {
            Write-Host "  [MISSING] $secret — no enabled version" -ForegroundColor Red
            $missingSecrets += $secret
        }
    }
    if ($missingSecrets.Count -gt 0) {
        Write-Error ("Missing secret versions:`n" + ($missingSecrets -join "`n") +
            "`n`nAdd versions with:`n  .\scripts\bootstrap_research_secrets.ps1 -Backend Gcp -ProjectId $ProjectId")
        exit 1
    }
    Write-Host "[OK] All secret versions present" -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 6: Submit build
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Submitting build: $Config (project: $ProjectId)"
Write-Host ""

$SubmitArgs = @("builds", "submit", "--config=$Config", "--project=$ProjectId")
if ($NoSource) { $SubmitArgs += "--no-source" }

& gcloud @SubmitArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Cloud Build submission failed."
    exit 1
}

Write-Host ""
Write-Host "Cloud Build complete. Check Cloud Console for full logs:" -ForegroundColor Green
Write-Host "  https://console.cloud.google.com/cloud-build/builds?project=$ProjectId"
