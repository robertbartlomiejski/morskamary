# GitHub Copilot MCP Setup Guide for morskamary

**⚠️ IMPORTANT: This is Optional, Local, Workstation-Specific Tooling**

This guide describes **optional advanced features** for integrating GitHub Copilot with local repositories and cloud storage through Model Context Protocol (MCP) servers. These features are:

- **NOT required** for core morskamary development
- **NOT a repository dependency** (Python ≥3.9 is the only core requirement)
- **Local workstation configuration** that should not be committed to version control
- **Second-phase tooling** to be considered only after real-data and provenance workflows are solid

For standard Python-first development, see [CONTRIBUTING.md](CONTRIBUTING.md) and use `main_real_data.py` for real-data workflows.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Detailed Configuration](#detailed-configuration)
5. [Privacy & Data Governance](#privacy--data-governance)
6. [Advanced Usage](#advanced-usage)
7. [Troubleshooting](#troubleshooting)

---

## Overview

This setup enables GitHub Copilot to access your full research context through **Model Context Protocol (MCP)** servers, providing:

- ✅ Direct access to local morskamary and maritimesociology repositories
- ✅ Integration with University of Szczecin SharePoint synchronized folders
- ✅ Google Drive research folder connectivity via OAuth
- ✅ Scientific database bridge for verified citations (Crossref, Scopus, Web of Science)
- ✅ Full data privacy with no telemetry/training on proprietary data

**Architecture**: Local MCP servers run as background processes, bridging VS Code/GitHub Copilot with your research environment.

---

## Prerequisites

### Required Software

1. **Node.js ≥18.0** (LTS recommended)
   - Download: https://nodejs.org
   - Verify: `node -v` in PowerShell/Command Prompt

2. **Python ≥3.9**
   - Download: https://python.org
   - ⚠️ **Important**: Check "Add Python to PATH" during installation
   - Verify: `python --version` or `py --version`

3. **Visual Studio Code**
   - Download: https://code.visualstudio.com
   - Install **GitHub Copilot** extension

4. **Git**
   - Download: https://git-scm.com
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

### Windows Installation (Recommended)

1. **Open PowerShell as Administrator**

2. **Navigate to your morskamary repository:**
   ```powershell
   cd C:\Path\To\morskamary
   ```

3. **Run the deployment script:**
   ```powershell
   .\Deploy-CopilotSynergy.ps1
   ```

4. **Follow the on-screen instructions**
   - Script verifies Node.js and Python installation
   - Installs MCP server packages via npm
   - Generates configuration files
   - Provides next steps

5. **Restart VS Code**

6. **Verify in Copilot Chat:**
   ```
   @workspace List available MCP tools and read the README.md from morskamary repository
   ```

### Advanced Installation with All Features

To enable all features (SharePoint, Google Drive, scientific bridge):

```powershell
.\Deploy-CopilotSynergy.ps1 `
  -MorskaMaryRepoPath "C:\GitHub\morskamary" `
  -MaritimeSociologyRepoPath "C:\GitHub\maritimesociology" `
  -SharePointSyncPath "C:\Users\YourName\OneDrive - Uniwersytet Szczecinski\PORT CITY HUB UPLOAD" `
  -GoogleOAuthCredentialsPath "C:\Users\YourName\Documents\gcp-oauth.keys.json" `
  -ScientificBridgeScriptPath "C:\GitHub\morskamary\scientific_bridge.py"
```

---

## Detailed Configuration

### Manual MCP Configuration

If you prefer manual setup or need to customize, edit your VS Code MCP configuration:

**Location:** `%APPDATA%\Code\User\globalStorage\github.copilot\mcp_settings.json`

**Example Configuration:**

```json
{
  "mcpServers": {
    "morskamary-local": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "C:\\GitHub\\morskamary"
      ],
      "description": "Local morskamary Blue Sociology repository"
    },
    "scientific-citation-bridge": {
      "command": "python",
      "args": [
        "C:\\GitHub\\morskamary\\scientific_bridge.py"
      ],
      "description": "Scientific database bridge for verified citations"
    }
  }
}
```

### Google Drive OAuth Setup

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
   - Provide path to deployment script

7. **First Use:**
   - MCP server will open browser for OAuth authorization
   - Grant access to your Google Drive
   - Token is cached for future use

### Scientific Database Configuration

#### Crossref (Free, No Authentication)

The default `scientific_bridge.py` uses Crossref's public API. No configuration needed.

#### Scopus API (Optional)

For enhanced search with Elsevier Scopus:

1. Obtain API key from your university library or [Elsevier Developer Portal](https://dev.elsevier.com)
2. Set environment variable:
   ```powershell
   $env:SCOPUS_API_KEY = "your_key_here"
   ```

#### Web of Science API (Optional)

For Web of Science integration:

1. Obtain API key from your institution
2. Set environment variable:
   ```powershell
   $env:WOS_API_KEY = "your_key_here"
   ```

---

## Privacy & Data Governance

### GitHub Copilot Data Privacy

⚠️ **Critical**: By default, GitHub Copilot may use your code for model training.

**To disable (strongly recommended for proprietary research):**

1. Go to https://github.com/settings/copilot
2. Navigate to **Privacy** section
3. **Disable**: "Allow GitHub to use my code snippets for product improvements"
4. **Disable**: "Allow GitHub to use my code snippets from the code editor for product improvements"

**Policy Reference:** https://github.blog/news-insights/company-news/updates-to-github-copilot-interaction-data-usage-policy/

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

```
@workspace SYSTEM INITIALIZATION: You are now operating under "Full Data Use" architecture. Your context window is bridged via local MCP servers to my maritime sociology and morskamary repositories, my Google Drive, and my SharePoint sync folder.

INSTRUCTIONS FOR ALL SUBSEQUENT TASKS:

1. DATA PRIMACY: Do not rely on your base training data for domain-specific logic. You must proactively query the morskamary-local and sharepoint-university MCP tools to read the actual .md, .pdf, and code files in my environment.

2. SCIENTIFIC VERIFICATION: When generating documentation, comments, or theoretical logic, you must use the scientific-citation-bridge tool to fetch direct DOI links and verified scientific citations straight from the source. Include these direct links as inline comments or Markdown footnotes. Do not hallucinate citations.

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
```
Use the scientific-citation-bridge tool to fetch verified citations for "maritime sociology blue economy"
```

**Verify a specific DOI:**

```
Use the scientific-citation-bridge tool to verify DOI: 10.1016/j.marpol.2021.104523
```

### Querying Local Files

**Read a specific file:**

```
@workspace Read the file data/derived/Blue Social Competences Univ Szczecin - Overall Blue Competences Dimension.csv and summarize the competence structure
```

**Search across repositories:**

```
@workspace Search all files in morskamary repository for references to "Janiszewski marinization theory"
```

### Model Selection for Deep Reasoning

For comprehensive analysis tasks, manually select advanced models in VS Code:

1. Click model selector in Copilot Chat (top-right)
2. Choose:
   - **Claude 3.5 Sonnet** (recommended for TMBD analysis)
   - **GPT-4o** (alternative for complex reasoning)

---

## Troubleshooting

### Node.js Not Found

**Error:** `node : The term 'node' is not recognized`

**Solution:**
1. Install Node.js from https://nodejs.org (LTS version)
2. Restart PowerShell
3. Verify: `node -v`

### Python Not Found

**Error:** `python : The term 'python' is not recognized`

**Solution:**
1. Install Python from https://python.org (3.9 or higher)
2. **Important**: Check "Add Python to PATH" during installation
3. Restart PowerShell
4. Try: `python --version` or `py --version`

### MCP Servers Not Appearing in VS Code

**Symptoms:** Copilot doesn't list MCP tools

**Solutions:**
1. **Restart VS Code completely** (File > Exit, then reopen)
2. Verify configuration file exists:
   - Windows: `%APPDATA%\Code\User\globalStorage\github.copilot\mcp_settings.json`
3. Check VS Code Output panel (View > Output > select "GitHub Copilot")
4. Ensure you clicked "Trust" when VS Code prompted about MCP servers

### NPM Package Installation Fails

**Error:** `npm install -g` fails with permission errors

**Solution:**
1. **Run PowerShell as Administrator**
2. Re-run: `.\Deploy-CopilotSynergy.ps1`

**Alternative (Windows):**
```powershell
npm config set prefix "%APPDATA%\npm"
```
Then retry installation.

### Google Drive Authentication Issues

**Error:** Browser doesn't open or OAuth fails

**Solutions:**
1. Verify `gcp-oauth.keys.json` path is correct
2. Ensure you added your email as a test user in Google Cloud Console
3. Check Google Drive API is enabled in your project
4. Delete cached token and re-authenticate:
   - Location: `%APPDATA%\@piotr-agier\google-drive-mcp\token.json`

### Scientific Bridge Not Working

**Error:** `scientific-citation-bridge` tool not available

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
4. Close unused MCP servers in configuration

---

## Additional Resources

- **Project Documentation:**
  - [README.md](README.md) — Project overview and quick start
  - [CONTRIBUTING.md](CONTRIBUTING.md) — Development workflow
  - [LLM_CONTEXT_INSTRUCTION.txt](LLM_CONTEXT_INSTRUCTION.txt) — Domain-specific guidance

- **GitHub Copilot Documentation:**
  - [GitHub Copilot MCP Documentation](https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-mcp-servers)
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
3. Open an issue on GitHub: https://github.com/robertbartlomiejski/morskamary/issues

For general GitHub Copilot support:
- https://support.github.com/

---

## Version History

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
