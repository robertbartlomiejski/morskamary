# GitHub Copilot MCP Setup Guide for morskamary

## ⚠️ Important: Optional local workstation tooling (Windows only)

This guide describes **optional advanced features** for integrating GitHub Copilot with local repositories and cloud storage through Model Context Protocol (MCP) servers. These features are:

- **NOT required** for core morskamary development
- **NOT a repository dependency** (Python ≥3.9 is the only core requirement)
- **Local workstation configuration** that should not be committed to version control
- **Second-phase tooling** to be considered only after real-data and provenance workflows are solid
- **Windows only** — the deployment script uses `%APPDATA%` for VS Code profile resolution

For standard Python-first development, see [CONTRIBUTING.md](CONTRIBUTING.md) and use `main_real_data.py` for real-data workflows.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Configuration Targets](#configuration-targets)
5. [Manual MCP Configuration](#manual-mcp-configuration)
6. [Google Drive OAuth Setup](#google-drive-oauth-setup)
7. [Scientific Database Configuration](#scientific-database-configuration)
8. [Privacy & Data Governance](#privacy--data-governance)
9. [Advanced Usage](#advanced-usage)
10. [Troubleshooting](#troubleshooting)

---

## Overview

This setup enables GitHub Copilot to access your full research context through **Model Context Protocol (MCP)** servers, providing:

- ✅ Direct access to local morskamary and maritimesociology repositories
- ✅ Integration with University of Szczecin SharePoint synchronized folders
- ✅ Google Drive research folder connectivity via OAuth
- ✅ Scientific database bridge for verified citations (Crossref, Scopus, Web of Science)
- ✅ Full data privacy with no telemetry/training on proprietary data

**Architecture**: MCP servers are invoked on demand by VS Code via `npx` (no global npm installation required). Configuration is split between:

- **Workspace** (`.vscode/mcp.json`) — repo-safe, shareable server definitions
- **User profile** (`mcp.json` in your VS Code profile directory) — personal paths, credentials, local clones

---

## Prerequisites

### Required Software

1. **Node.js ≥18.0** (LTS recommended)
   - Download: <https://nodejs.org>
   - Verify: `node -v` in PowerShell (must report v18.x or higher)

2. **Python ≥3.9**
   - Download: <https://python.org>
   - ⚠️ **Important**: Check "Add Python to PATH" during installation
   - Verify: `python --version` or `py --version`

3. **Visual Studio Code** (Stable or Insiders)
   - Download: <https://code.visualstudio.com>
   - Install **GitHub Copilot** extension

4. **Git**
   - Download: <https://git-scm.com>
   - Required for repository access

### Optional Components

- **Google Cloud Project** (for Google Drive integration)
  - Required only if connecting Google Drive research folders
  - See [Google Drive OAuth Setup](#google-drive-oauth-setup)

- **Scopus/Web of Science API Keys** (for enhanced scientific search)
  - Optional; Crossref works without authentication
  - Contact your university library for institutional API access

---

## Quick Start

### Windows Installation

1. **Open PowerShell** (no Administrator privileges required)

2. **Navigate to your morskamary repository:**

   ```powershell
   cd C:\Path\To\morskamary
   ```

3. **Run the deployment script:**

   ```powershell
   .\Deploy-CopilotSynergy.ps1
   ```

4. **Follow the on-screen instructions**
   - Script verifies Node.js ≥18 and Python ≥3.9
   - Generates `.vscode/mcp.json` (workspace) and user-profile `mcp.json`
   - No global npm packages are installed; npx handles on-demand execution
   - Provides next steps

5. **Restart VS Code**

6. **Verify in Copilot Chat:**

   ```text
   @workspace List available MCP tools and read the README.md from morskamary repository
   ```

### Advanced Installation with All Features

To enable all features (SharePoint, Google Drive, scientific bridge):

```powershell
$googleOAuthCredentialsPath = Read-Host "Google OAuth credentials JSON path" -AsSecureString

.\Deploy-CopilotSynergy.ps1 `
  -MorskaMaryRepoPath "C:\GitHub\morskamary" `
  -MaritimeSociologyRepoPath "C:\GitHub\maritimesociology" `
  -SharePointSyncPath "C:\Users\YourName\OneDrive - Uniwersytet Szczecinski\PORT CITY HUB UPLOAD" `
  -GoogleOAuthCredentialsPath $googleOAuthCredentialsPath
```

### Targeting VS Code Insiders

By default the script targets VS Code Stable. To target Insiders explicitly:

```powershell
.\Deploy-CopilotSynergy.ps1 -VsCodeChannel Insiders
```

Or use `-VsCodeChannel Auto` to detect which installation exists (prefers Stable).

---

## Configuration Targets

VS Code reads MCP configuration from `mcp.json` files in two locations:

| Location | Path (Windows) | Purpose |
| -------- | -------------- | ------- |
| **Workspace** | `.vscode/mcp.json` | Repo-safe servers that can be shared and committed |
| **User profile** | `%APPDATA%\Code\User\mcp.json` | Personal paths, credentials, local clones |

Both use the **same schema**: a top-level `"servers"` object and an optional `"inputs"` array.

> **Note**: The deployment script merges into existing files non-destructively. If an existing file has malformed JSON, the script creates a timestamped backup and aborts. Use `-Force` to overwrite instead.

### What goes where

| Server | Target | Reason |
| ------ | ------ | ------ |
| `scientificCitationBridge` | Workspace | Uses `${workspaceFolder}`, no personal paths |
| `morskamaryLocal` | User profile | Contains your personal clone path |
| `maritimesociologyLocal` | User profile | Contains your personal clone path |
| `sharepointUniversity` | User profile | Contains your OneDrive sync path |
| `googleDriveResearch` | User profile | Contains your OAuth credential path |

---

## Manual MCP Configuration

If you prefer manual setup, edit the relevant `mcp.json` files directly.

### Workspace: `.vscode/mcp.json`

This file is already present in the repository with a GitHub MCP server. You can add repo-safe servers here:

```json
{
  "servers": {
    "io.github.github/github-mcp-server": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "GITHUB_PERSONAL_ACCESS_TOKEN=${input:token}",
        "ghcr.io/github/github-mcp-server:0.31.0"
      ],
      "version": "0.31.0"
    },
    "scientificCitationBridge": {
      "type": "stdio",
      "command": "python",
      "args": ["${workspaceFolder}/scientific_bridge.py"]
    }
  },
  "inputs": [
    {
      "id": "token",
      "type": "promptString",
      "description": "GitHub Personal Access Token",
      "password": true
    }
  ]
}
```

### User profile: `mcp.json`

Open via: **Ctrl+Shift+P → MCP: Open User Configuration**

```json
{
  "servers": {
    "morskamaryLocal": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\GitHub\\morskamary"]
    },
    "sharepointUniversity": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\YourName\\OneDrive - Uniwersytet Szczecinski\\PORT CITY HUB UPLOAD"]
    },
    "googleDriveResearch": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@piotr-agier/google-drive-mcp"],
      "env": {
        "GOOGLE_DRIVE_OAUTH_CREDENTIALS": "C:\\Users\\YourName\\Documents\\gcp-oauth.keys.json"
      }
    }
  }
}
```

> You can also add servers interactively: **Ctrl+Shift+P → MCP: Add Server**

---

## Google Drive OAuth Setup

To access your Google Drive research folder:

1. **Go to [Google Cloud Console](https://console.cloud.google.com)**

2. **Create a new project** (e.g., "morskamary-research")

3. **Enable APIs:**
   - Google Drive API
   - Google Docs API

4. **Configure OAuth consent screen:**
   - User Type: External
   - Add your email as a test user

5. **Create OAuth 2.0 Client ID:**
   - Application type: Desktop App
   - Name: "morskamary MCP"
   - Download JSON credentials

6. **Save credentials:**
   - Save as `gcp-oauth.keys.json` in a secure location
   - Provide path to deployment script or add manually to user-profile `mcp.json`

7. **First Use:**
   - MCP server will open browser for OAuth authorization
   - Grant access to your Google Drive
   - Token is cached for future use

---

## Scientific Database Configuration

### Windows bootstrap quick path

If you are configuring credentials locally in PowerShell, use the DotEnv backend:

```powershell
.\scripts\bootstrap_research_secrets.ps1 -Backend DotEnv
. .\.env.ps1
python scripts/check_research_env.py
```

For Google Secret Manager:

```powershell
.\scripts\bootstrap_research_secrets.ps1 -Backend Gcp -ProjectId YOUR_PROJECT_ID
```

### Crossref (Free, No Authentication)

The default `scientific_bridge.py` uses Crossref's public REST API. No signup or API key is required.

- `CROSSREF_MAILTO` is optional but recommended as a polite contact email when you use the public pool heavily.
- If you do not set it, Crossref queries still work; you just lose the polite-pool contact hint.

### Scopus API (Optional)

For enhanced search with Elsevier Scopus:

1. Create or sign in to your account at the [Elsevier Developer Portal](https://dev.elsevier.com).
2. Register an application and generate an API key.
3. Confirm with your university library or research office that your institution has the required Scopus entitlement or IP-based access, because API availability can depend on institutional subscription status.
4. Store the key as `SCOPUS_API_KEY` (and, if your institutional setup uses a shared Elsevier platform key, also set `ELSEVIER_API_KEY`).
5. Set the environment variable manually if needed:

   ```powershell
   $env:SCOPUS_API_KEY = "your_scopus_api_key_here"
   $env:ELSEVIER_API_KEY = "your_elsevier_api_key_here"
   ```

### SciVal API (Optional)

For SciVal metrics and analytics access:

1. Confirm that your institution has an active SciVal subscription.
2. Use the [Elsevier SciVal APIs information page](https://dev.elsevier.com/scival_apis.html) to identify the relevant API product and onboarding path.
3. Request or enable SciVal API access through your Elsevier developer account and institutional contact, because entitlement is subscription-gated.
4. Store the issued credential as `SCIVAL_API_KEY`.

### Web of Science API (Optional)

For Web of Science integration:

1. Create a developer account at the [Clarivate Developer Portal](https://developer.clarivate.com/).
2. Register an application for the Web of Science API product you need.
3. Request the required API subscription or approval from Clarivate or your institution, because some products are gated and reviewed before activation.
4. Store the issued credential as `WOS_API_KEY`.
5. Set the environment variable manually if needed:

   ```powershell
   $env:WOS_API_KEY = "your_key_here"
   ```

---

## Privacy & Data Governance

### GitHub Copilot Data Privacy

⚠️ **Critical**: Starting April 24, 2026, GitHub may use your interactions to train and improve AI models unless you opt out.

**To opt out (strongly recommended for proprietary research):**

1. Go to <https://github.com/settings/copilot>
2. Under **Data handling**, select the **"Allow GitHub to use my data for AI model training"** dropdown
3. Click **Disabled**

**Policy Reference:** [Managing Copilot policies as an individual subscriber](https://docs.github.com/copilot/how-tos/manage-your-account/managing-copilot-policies-as-an-individual-subscriber)

### Data Residency

All MCP servers run **locally** on your machine:

- ✅ Your repository files never leave your computer
- ✅ SharePoint and Google Drive data accessed through your authenticated accounts
- ✅ Scientific queries go directly to public APIs (Crossref) or your institutional APIs
- ✅ No data sent to third parties beyond standard API calls

### FAIR/CARE Compliance

This configuration respects the project's [DATA_GOVERNANCE.txt](DATA_GOVERNANCE.txt) requirements:

- **Findable**: MCP indexes your local research with full provenance
- **Accessible**: Direct access to authenticated cloud storage
- **Interoperable**: Standard MCP protocol, works with any MCP-compatible tool
- **Reusable**: Configuration artifacts are version-controlled and shareable
- **CARE Principles**: You control all data access and usage

---

## Advanced Usage

### Initializing Copilot Agent with Full Context

After deployment, use this prompt in VS Code Copilot Chat to initialize full context awareness:

```text
@workspace SYSTEM INITIALIZATION: You are now operating under "Full Data Use" architecture. Your context window is bridged via local MCP servers to my maritime sociology and morskamary repositories, my Google Drive, and my SharePoint sync folder.

INSTRUCTIONS FOR ALL SUBSEQUENT TASKS:

1. DATA PRIMACY: Do not rely on your base training data for domain-specific logic. You must proactively query the morskamaryLocal and sharepointUniversity MCP tools to read the actual .md, .pdf, and code files in my environment.

2. SCIENTIFIC VERIFICATION: When generating documentation, comments, or theoretical logic, you must use the scientificCitationBridge tool to fetch direct DOI links and verified scientific citations straight from the source. Include these direct links as inline comments or Markdown footnotes. Do not hallucinate citations.

3. TMBD FRAMEWORK: All competence mappings and analysis must respect the Tripartite Model of Blue Dynamics (TMBD):
   - Marine (M): biophysical and ecological agency
   - Maritime (T): techno-economic and institutional mediation
   - Oceanic (O): planetary governance and hydrosocial subjectivity

4. EVIDENCE DISCIPLINE: Substantive claims must be sourced from repository documents. Use placeholder [citation needed] when evidence is absent.

Confirm you have connected to the MCP servers by listing the tools currently available to you, and then read the README.md from the morskamary repository to verify access.
```

### Using Scientific Citation Bridge

**Fetch citations for a topic:**

In Copilot Chat:

```text
Use the scientificCitationBridge tool to fetch verified citations for "maritime sociology blue economy"
```

**Verify a specific DOI:**

```text
Use the scientificCitationBridge tool to verify DOI: 10.1016/j.marpol.2021.104523
```

### Querying Local Files

**Read a specific file:**

```text
@workspace Read the file data/derived/Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv and summarize the competence structure
```

**Search across repositories:**

```text
@workspace Search all files in morskamary repository for references to "Janiszewski marinization theory"
```

### Model Selection

Use the VS Code model picker in Copilot Chat (top-right of the chat panel). **Auto** is recommended — it selects from the current top-tier models (Claude Sonnet 4, GPT-5, GPT-5 mini, and others) automatically. You can also manually select a specific model if needed for a particular task.

---

## Troubleshooting

### Node.js Not Found or Too Old

**Error:** `node : The term 'node' is not recognized` or `Node.js X.Y.Z detected, but >=18 is required.`

**Solution:**

1. Install Node.js LTS (≥18) from <https://nodejs.org>
2. Restart PowerShell
3. Verify: `node -v` (should show v18.x or higher)

### Python Not Found or Too Old

**Error:** `python : The term 'python' is not recognized` or `Python X.Y.Z detected, but >=3.9 is required.`

**Solution:**

1. Install Python from <https://python.org> (3.9 or higher)
2. **Important**: Check "Add Python to PATH" during installation
3. Restart PowerShell
4. Verify: `python --version` or `py --version`

### MCP Servers Not Appearing in VS Code

**Symptoms:** Copilot doesn't list MCP tools

**Solutions:**

1. **Restart VS Code completely** (File > Exit, then reopen)
2. Verify configuration files exist:
   - Workspace: `.vscode/mcp.json` in the morskamary repository
   - User profile: `%APPDATA%\Code\User\mcp.json` (Stable) or `%APPDATA%\Code - Insiders\User\mcp.json` (Insiders)
3. Check via: **Ctrl+Shift+P → MCP: List Servers**
4. Check VS Code Output panel (View > Output > select "GitHub Copilot")
5. Ensure you clicked "Start" when VS Code prompted about MCP servers

### JSON Parse Failure During Deployment

**Error:** `Existing <path> is malformed JSON. Aborting.`

**Solution:**

1. The script has created a timestamped backup of the malformed file
2. Fix the JSON manually, or re-run with `-Force` to overwrite:

   ```powershell
   .\Deploy-CopilotSynergy.ps1 -Force
   ```

### Google Drive Authentication Issues

**Error:** Browser doesn't open or OAuth fails

**Solutions:**

1. Verify `gcp-oauth.keys.json` path is correct
2. Ensure you added your email as a test user in Google Cloud Console
3. Check Google Drive API is enabled in your project
4. Delete cached token and re-authenticate:
   - Location: `%APPDATA%\@piotr-agier\google-drive-mcp\token.json`

### Scientific Bridge Not Working

**Error:** `scientificCitationBridge` tool not available

**Solutions:**

1. Verify `scientific_bridge.py` exists in morskamary repository
2. Test Python script directly:

   ```powershell
   echo '{"method":"tools/list"}' | python scientific_bridge.py
   ```

3. Check firewall isn't blocking Python's network access

### Performance Issues

**Symptom:** MCP queries are slow

**Solutions:**

1. Limit filesystem servers to necessary directories only
2. Exclude large binary files (add to `.gitignore`)
3. Use specific MCP tools instead of broad @workspace queries
4. Close unused MCP servers via **Ctrl+Shift+P → MCP: List Servers**

---

## Additional Resources

- **Project Documentation:**
  - [README.md](README.md) — Project overview and quick start
  - [CONTRIBUTING.md](CONTRIBUTING.md) — Development workflow
  - [LLM_CONTEXT_INSTRUCTION.txt](LLM_CONTEXT_INSTRUCTION.txt) — Domain-specific guidance

- **VS Code MCP Documentation:**
  - [MCP configuration reference](https://code.visualstudio.com/docs/copilot/reference/mcp-configuration)
  - [Add and manage MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
  - [Model Context Protocol Specification](https://modelcontextprotocol.io)

- **Scientific APIs:**
  - [Crossref API Documentation](https://api.crossref.org)
  - [Elsevier Scopus API](https://dev.elsevier.com)
  - [Web of Science API](https://clarivate.com/webofsciencegroup/solutions/web-of-science-apis/)

---

## Support

For issues specific to this configuration:

1. Check [Troubleshooting](#troubleshooting) section above
2. Review VS Code Output panel (View > Output > GitHub Copilot)
3. Open an issue on GitHub: <https://github.com/robertbartlomiejski/morskamary/issues>

For general GitHub Copilot support:

- <https://support.github.com/>

---

## Version History

- **2.0.0** (2026-04-09): Architecture rewrite for current VS Code MCP standard
  - Targets `.vscode/mcp.json` (workspace) and user-profile `mcp.json` only
  - Uses current `"servers"` + `"inputs"` schema (not legacy `"mcpServers"`)
  - Removes global `npm install -g` and Administrator requirement
  - Adds `-VsCodeChannel` parameter (Stable/Insiders/Auto)
  - Adds `-Force` parameter with backup-on-failure safety
  - Enforces Node.js ≥18 and Python ≥3.9 version checks
  - Updates model guidance to "Auto" (current top-tier model picker)
  - Updates privacy wording to current GitHub policy (effective Apr 24 2026)
  - Splits repo-safe versus personal MCP server concerns

- **1.0.0** (2026-04-01): Initial comprehensive MCP integration
  - PowerShell deployment script
  - Scientific citation bridge
  - Multi-repository support
  - Google Drive OAuth integration
  - Privacy-first configuration

---

## License

See [LICENSE](LICENSE) file for repository licensing terms.

Configuration artifacts (PowerShell scripts, JSON configs) are provided as-is for research use.
