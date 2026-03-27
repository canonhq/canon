# Installation

Canon can be installed in four ways: as a GitHub App, a Claude Code plugin, an MCP server, or self-hosted on Kubernetes.

## GitHub App

The GitHub App provides automated PR analysis, spec tracking, ticket sync, and doc maintenance.

### 1. Install the App

Visit the [Canon GitHub App](https://github.com/apps/canon) page and click **Install**. Select your organization and choose which repositories to enable.

### 2. Add CANON.yaml

Create a `CANON.yaml` file in your repository root:

```yaml
version: "1"

specs:
  doc_paths:
    - "docs/specs/*.md"

agents:
  pr_analysis: true
  doc_updates: true
  realization_check: true
```

### 3. Add a Spec

Create your first spec in `docs/specs/`:

```bash
mkdir -p docs/specs
cp docs/specs/_template.md docs/specs/my-feature.md
```

### 4. Open a PR

The Canon bot will analyze your PR against the relevant specs and post a comment with spec references, discrepancies, and realization status.

## Claude Code Plugin {#claude-code-plugin}

The Claude Code plugin adds spec-driven development skills (slash commands) to your Claude Code sessions.

### Install

**Option A: CLI setup (recommended)**

Run from your project root after creating `CANON.yaml`:

```bash
canon setup
```

This creates `CANON.yaml`, the MCP server config (`.mcp.json`), and the spec template. To also configure the Claude Code agent instructions:

```bash
canon setup --agent claude
```

**Option B: Plugin marketplace**

Add the Canon marketplace and install the plugin:

```bash
claude plugin marketplace add canonhq/canon
claude plugin install canon
```

::: tip
`canon setup` handles MCP and agent config but does not install the Claude Code plugin. For skills (slash commands), you need the plugin installed via the marketplace.
:::

### Available Skills

Once installed, skills are available as `/canon:<skill>`:

| Skill | Description |
|-------|-------------|
| `/canon:context` | Load spec context for your current task |
| `/canon:task` | Pick up a task, implement ACs, mark done |
| `/canon:verify` | Verify code against spec acceptance criteria |
| `/canon:new` | Create a new spec from template |
| `/canon:review` | Review changes against all documentation |
| `/canon:status` | Show spec coverage dashboard |
| `/canon:plan` | Spec-driven planning workflow |
| `/canon:update` | Update spec statuses from code evidence |
| `/canon:audit` | Full spec audit: update statuses, sync tickets, commit |

## MCP Server {#mcp-server}

The MCP server connects any MCP-compatible coding agent to the Canon knowledge base.

### Configure in Claude Code

`canon setup` automatically creates `.mcp.json` with the Canon MCP server. You can also add it manually:

```json
{
  "mcpServers": {
    "canon": {
      "command": "uvx",
      "args": ["--from", "canonhq", "canon-mcp"]
    }
  }
}
```

### Available Tools

- `search` — Hybrid search (vector + BM25) across all indexed specs and docs
- `get_spec` / `get_section` — Read parsed spec data with frontmatter, sections, and ACs
- `create_spec` — Create new specs from templates
- `update_section_status` — Update section statuses
- `add_realization` — Link code evidence to acceptance criteria
- `sync_spec_status` — Bulk updates in one commit

### Configure in Cursor / VS Code

MCP configuration varies by editor. Consult your editor's MCP documentation and point it at the Canon MCP server endpoint.

## Self-Hosted {#self-hosted}

For full control over your data and configuration, deploy Canon to your own Kubernetes cluster.

See the [Self-Hosting Guide](/guides/self-hosting) for detailed instructions covering:

- GitHub App creation
- Kubernetes secret management
- Helm chart installation
- Jira/Linear/GitHub Issues configuration
- DevSpace dev environment setup
