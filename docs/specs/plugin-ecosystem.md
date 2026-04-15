---
title: "Plugin Ecosystem"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-04-15
updated: 2026-04-15
tags: [plugins, extensions, ecosystem, adapters, community]
---

# Plugin Ecosystem

An extension system for Canon that allows organizations and third parties to add custom ticket adapters, skills, hooks, MCP tools, and agents without modifying core. Inspired by GitHub's [spec-kit extension system](https://github.com/github/spec-kit) and adapted to Canon's dual-layer architecture (Python runtime + Claude Code IDE plugin).

## 1. Background

<!-- canon:system:1 status:done -->

Canon today is a monolithic system — all ticket adapters, skills, hooks, and MCP tools live in the core repo. This creates several problems:

1. **Monolithic growth**: Adding Azure DevOps or Monday.com support means core repo PRs, expanded test matrices, and new dependencies for all users
2. **Limited flexibility**: Organizations use different ticket systems, compliance workflows, and team conventions — Canon can't support all without bloat
3. **Community friction**: External contributors can't add integrations without core repo approval and release cycles
4. **Org customization**: Enterprises want org-specific skills (sprint planning, Jira hygiene, compliance checks) that don't belong in OSS core

Canon already has strong extension points — the `TicketAdapter` protocol, markdown-based skills, lifecycle hooks, and an MCP server — but no mechanism for third parties to **discover, install, and compose** extensions built on these points.

**Related specs:**
- `enterprise-adoption-enablement.md` (System 9) — original plugin marketplace sketch
- `slack-integration.md` — notification delivery (extensions may provide additional channels)
- `ticket-mapping-model.md` — configurable ticket field/status mapping (adapters implement this)

### What we learned from spec-kit

GitHub's spec-kit extension system (65+ community extensions) demonstrates:
- `extension.yml` declarative manifests work well for discoverability and validation
- CLI-based install/search/list is the right UX (not manual file copying)
- Hook points (`after_tasks`, `after_implement`) drive useful automation
- A community catalog (JSON file in a GitHub repo) scales to dozens of extensions with minimal infrastructure
- `--dev` symlink mode is essential for extension authors
- Extensions should be **additive only** — never modify core behavior

### Where Canon differs

Canon has a dual-layer architecture that spec-kit lacks:

| Layer | Canon | Spec-kit |
|---|---|---|
| **Runtime** (Python) | Ticket adapters, MCP tools, evidence handlers | None — CLI-only |
| **IDE** (Claude Code) | Skills, hooks, commands, agents | Commands, hooks |

This means Canon extensions can provide **typed Python code** (adapters, MCP tool handlers) alongside **markdown IDE components** (skills, hooks, agents). Spec-kit extensions are markdown-only.

## 2. Extension Manifest

<!-- canon:system:2 status:todo -->

<!-- canon:ticket:github:513 -->
Every Canon extension is a directory containing a `canon-extension.yml` manifest. The manifest declares what the extension provides, what it requires, and how it integrates with Canon's lifecycle.

### 2.1 Manifest Schema

```yaml
# canon-extension.yml — Extension Manifest Schema v1
schema_version: "1"

# Extension metadata (REQUIRED)
extension:
  id: "azure-devops"                    # Unique ID: lowercase, alphanumeric, hyphens
  name: "Azure DevOps Integration"      # Human-readable name
  version: "1.0.0"                      # Semantic version
  description: "Sync specs to Azure DevOps work items"
  author: "Contoso Engineering"
  repository: "https://github.com/contoso/canon-ext-azure-devops"
  license: "MIT"
  homepage: "https://github.com/contoso/canon-ext-azure-devops#readme"

# Compatibility requirements (REQUIRED)
requires:
  canon_version: ">=0.3.0,<2.0.0"      # Semantic version range
  python: ">=3.12"                       # Optional: Python version (for adapter extensions)
  tools:                                 # Optional: external tools needed
    - name: "azure-devops-mcp"
      required: false
      description: "Azure DevOps MCP server for API access"
      install_url: "https://github.com/contoso/azure-devops-mcp"

# What this extension provides (at least one section required)
provides:
  # Ticket adapter (Python class implementing TicketAdapter protocol)
  adapters:
    - id: "azure-devops"
      entry_point: "canon_ext_azure_devops:AzureDevOpsAdapter"
      capabilities:
        supports_custom_fields: true
        supports_hierarchy: true
        supports_subtasks: true
        supports_labels: true

  # IDE skills (SKILL.md files)
  skills:
    - name: "azure-devops-sync"
      file: "skills/azure-devops-sync/SKILL.md"
      description: "Sync spec sections to Azure DevOps work items"

  # IDE commands (slash commands)
  commands:
    - name: "canon-ado-sync"
      file: "commands/canon-ado-sync.md"
      description: "Sync current spec to Azure DevOps"

  # IDE hooks
  hooks:
    - event: "Stop"
      type: "command"
      command: "node ${EXTENSION_ROOT}/hooks/on-stop.mjs"
      timeout: 5

  # MCP tools (extend Canon's MCP server)
  mcp_tools:
    - name: "ado_get_work_item"
      handler: "canon_ext_azure_devops.mcp:get_work_item"
      description: "Fetch an Azure DevOps work item by ID"
      input_schema:
        type: object
        required: [work_item_id]
        properties:
          work_item_id:
            type: integer
            description: "The work item ID"

  # Agents (AGENT.md files)
  agents:
    - name: "ado-reviewer"
      file: "agents/ado-reviewer/AGENT.md"
      description: "Review PRs against linked Azure DevOps work items"

  # Config template
  config:
    - name: "azure-devops.yml"
      template: "config/azure-devops.template.yml"
      description: "Azure DevOps connection and project settings"
      required: true

# Lifecycle hooks — run extension commands at Canon lifecycle points
hooks:
  after_sync:
    command: "/canon-ado-sync"
    optional: true
    prompt: "Sync work items to Azure DevOps?"
  after_verify:
    command: "/canon-ado-update-status"
    optional: true
    prompt: "Update Azure DevOps work item status?"

# Tags for catalog discovery
tags:
  - "issue-tracking"
  - "azure-devops"
  - "microsoft"
  - "enterprise"

# Extension-specific CANON.yaml section defaults
defaults:
  azure_devops:
    organization: null
    project: null
    area_path: null
    work_item_type: "User Story"
```

### 2.2 Schema Validation

The manifest is validated by Canon CLI on install using a Pydantic model. Validation checks:
- `schema_version` is supported
- `extension.id` is unique (no collision with installed extensions or core)
- `extension.id` matches pattern `^[a-z][a-z0-9-]{1,48}[a-z0-9]$`
- `requires.canon_version` is satisfied by the installed Canon version
- All files referenced in `provides` exist in the extension directory
- Adapter `entry_point` is a valid Python dotted path
- Hook events reference valid Canon lifecycle events
- No reserved IDs (`canon`, `core`, `builtin`) are used

### Acceptance Criteria

- [ ] `canon-extension.yml` schema defined as a Pydantic model in `src/canon/extensions/manifest.py`
- [ ] Schema supports all `provides` types: adapters, skills, commands, hooks, mcp_tools, agents, config
- [ ] Manifest validation reports clear errors for invalid fields
- [ ] `schema_version` field enables future schema evolution without breaking existing extensions
- [ ] File path references in `provides` validated against extension directory contents
- [ ] Reserved extension IDs (`canon`, `core`, `builtin`) rejected on validation

## 3. CLI Commands

<!-- canon:system:3 status:todo -->

<!-- canon:ticket:github:238 -->
The `canon extension` subcommand manages the full extension lifecycle: search, install, configure, update, remove.

### 3.1 Extension Search and Discovery

```bash
# Search all catalogs
canon extension search azure

# Filter by tag
canon extension search --tag issue-tracking

# Filter by category
canon extension search --category integration

# Show detailed info
canon extension info azure-devops
```

Search queries all active catalogs (official + community by default), returning name, description, version, author, install status, and category.

### 3.2 Extension Installation

```bash
# Install from catalog (downloads to .canon/extensions/{id}/)
canon extension add azure-devops

# Install from GitHub repo
canon extension add --repo contoso/canon-ext-azure-devops

# Install from local directory (dev mode — symlink, not copy)
canon extension add --dev /path/to/my-extension

# Install a specific version
canon extension add azure-devops@1.2.0

# Install with Python dependencies (for adapter extensions)
canon extension add azure-devops --with-deps
```

Installation steps:
1. Download/clone extension to `.canon/extensions/{id}/`
2. Validate `canon-extension.yml` manifest
3. Check `requires.canon_version` compatibility
4. If `provides.adapters` exists: install Python package or register entry point
5. If `provides.skills` exists: symlink/copy SKILL.md files to `.canon/skills/`
6. If `provides.commands` exists: symlink/copy command files to `.claude/commands/`
7. If `provides.hooks` exists: merge hook declarations into active hook config
8. If `provides.agents` exists: symlink/copy AGENT.md files to `.canon/agents/`
9. If `provides.config` exists and `required: true`: prompt user to configure
10. Write installation record to `.canon/extensions/.registry.json`

### 3.3 Extension Management

```bash
# List installed extensions
canon extension list

# Update a specific extension
canon extension update azure-devops

# Update all extensions
canon extension update --all

# Remove an extension (cleans up all installed components)
canon extension remove azure-devops

# Enable/disable without removing
canon extension disable azure-devops
canon extension enable azure-devops
```

### 3.4 Extension Registry File

`.canon/extensions/.registry.json` tracks installed extensions:

```json
{
  "schema_version": "1",
  "extensions": {
    "azure-devops": {
      "version": "1.2.0",
      "installed_at": "2026-04-15T10:30:00Z",
      "source": "catalog",
      "dev_mode": false,
      "enabled": true,
      "installed_files": [
        ".canon/skills/azure-devops-sync/SKILL.md",
        ".claude/commands/canon-ado-sync.md"
      ]
    }
  }
}
```

### Acceptance Criteria

- [ ] `canon extension search` queries official and community catalogs with keyword and tag filtering
- [ ] `canon extension info` displays detailed extension metadata, requirements, and provided components
- [ ] `canon extension add` installs from catalog, GitHub repo, or local directory
- [ ] `canon extension add --dev` creates symlinks instead of copies for local development
- [ ] Installation validates manifest, checks version compatibility, and registers all components
- [ ] `canon extension list` shows installed extensions with version, status, and component counts
- [ ] `canon extension update` pulls latest version and re-registers components
- [ ] `canon extension remove` cleans up all installed files, hooks, and registry entries
- [ ] `canon extension disable/enable` toggles extensions without removing files
- [ ] `.canon/extensions/.registry.json` tracks all installed extensions and their artifacts
- [ ] Extensions with `provides.adapters` trigger Python package installation when `--with-deps` is passed

## 4. Extension Types

<!-- canon:system:4 status:todo -->

<!-- canon:ticket:github:514 -->
Canon extensions can provide six types of components. An extension may provide any combination of these.

### 4.1 Ticket Adapters

Python classes implementing the `TicketAdapter` protocol from `src/canon/sync/adapters/base.py`. This is the highest-value extension type — it lets Canon sync specs to any ticket system.

**Registration**: Adapters register via Python entry points:

```toml
# In the extension's pyproject.toml
[project.entry-points."canon.adapters"]
azure-devops = "canon_ext_azure_devops:AzureDevOpsAdapter"
```

Or via the manifest's `provides.adapters[].entry_point` field for extensions that aren't pip-installed.

**Discovery**: `canon extension add --with-deps` runs `uv pip install` for the extension package. The adapter factory (`src/canon/sync/adapters/factory.py`) is extended to discover adapters from both built-in and entry-point sources.

**Capabilities**: Each adapter declares its `AdapterCapabilities` so Canon can adapt its behavior (e.g., skip subtask creation if `supports_subtasks: false`).

### 4.2 Skills

Markdown SKILL.md files following Canon's existing skill format. Extension skills are installed to `.canon/skills/{skill-name}/SKILL.md` and become available in the IDE alongside built-in skills.

Extension skills can reference the Canon MCP server and any MCP tools provided by the same extension.

### 4.3 Commands

Markdown command files installed to `.claude/commands/{command-name}.md`. These provide slash-command shortcuts (e.g., `/canon-ado-sync`) that appear in IDE autocomplete.

### 4.4 Hooks

Shell or Node.js scripts that fire at Canon lifecycle events. Extension hooks are merged into the active hook configuration alongside core hooks. Supported events:

| Event | When | Use case |
|---|---|---|
| `SessionStart` | IDE session starts | Load extension context |
| `UserPromptSubmit` | User sends a prompt | Inject extension-specific guidance |
| `PreToolUse` | Before a tool executes | Validate/gate tool usage |
| `Stop` | IDE session ends | Record evidence, sync state |
| `after_sync` | After ticket sync completes | Cross-system sync |
| `after_verify` | After spec verification | Update external status |
| `after_realize` | After realization recorded | Notify external systems |

Core Canon events (`SessionStart`, `Stop`, etc.) are processed by the Claude Code hook system. Custom Canon events (`after_sync`, `after_verify`, `after_realize`) are emitted by Canon CLI and dispatched to registered extension hooks.

### 4.5 MCP Tools

Extensions can register additional tools on the Canon MCP server. Each tool declares:
- `name`: tool name (namespaced: `{extension_id}_{tool_name}`)
- `handler`: Python dotted path to an async function
- `description`: tool description for the LLM
- `input_schema`: JSON Schema for tool parameters

MCP tool handlers receive the same context as built-in tools (repo info, config, auth) and must respect `ai_exposure` controls. The MCP server composes all registered tools at startup.

### 4.6 Agents

AGENT.md files following Canon's existing agent format. Extension agents are installed to `.canon/agents/{agent-name}/AGENT.md` and can be dispatched by skills or other agents via the Agent tool.

### Acceptance Criteria

- [ ] Adapter extensions register via Python entry points and are discoverable by the adapter factory
- [ ] Adapter factory falls back to manifest `entry_point` field for non-pip-installed extensions
- [ ] Skill extensions install to `.canon/skills/` and are available in IDE skill listings
- [ ] Command extensions install to `.claude/commands/` and appear in autocomplete
- [ ] Hook extensions merge into active hook config with correct event binding
- [ ] MCP tool extensions register on the Canon MCP server with namespaced tool names
- [ ] MCP tool handlers receive standard context and enforce `ai_exposure` controls
- [ ] Agent extensions install to `.canon/agents/` and are dispatchable via Agent tool
- [ ] Extensions providing multiple component types install all components atomically

## 5. Catalog System

<!-- canon:system:5 status:todo -->

<!-- canon:ticket:github:515 -->
Extensions are discoverable through JSON catalog files hosted on GitHub, following spec-kit's proven model.

### 5.1 Catalog Schema

```json
{
  "schema_version": "1",
  "updated_at": "2026-04-15T00:00:00Z",
  "catalog_url": "https://raw.githubusercontent.com/canonhq/canon-extensions/main/catalog.json",
  "extensions": {
    "azure-devops": {
      "id": "azure-devops",
      "name": "Azure DevOps Integration",
      "version": "1.2.0",
      "description": "Sync specs to Azure DevOps work items",
      "author": "Contoso Engineering",
      "repository": "https://github.com/contoso/canon-ext-azure-devops",
      "category": "integration",
      "tags": ["issue-tracking", "azure-devops", "enterprise"],
      "bundled": false,
      "verified": false
    }
  }
}
```

### 5.2 Catalog Types

| Catalog | URL | Governance |
|---|---|---|
| **Official** | `canonhq/canon` repo `extensions/catalog.json` | Maintained by Canon team, bundled extensions |
| **Community** | `canonhq/canon-extensions` repo `catalog.community.json` | PR-based submission, minimal review (format + policy only) |
| **Private** | Any HTTPS URL or local file path | Org-managed, for internal extensions |

### 5.3 Catalog Configuration

Catalogs are configured in CANON.yaml:

```yaml
extensions:
  catalogs:
    - name: official
      url: "https://raw.githubusercontent.com/canonhq/canon/main/extensions/catalog.json"
      enabled: true
    - name: community
      url: "https://raw.githubusercontent.com/canonhq/canon-extensions/main/catalog.community.json"
      enabled: true
    - name: internal
      url: "https://artifacts.company.com/canon/catalog.json"
      enabled: true
```

Default catalogs (official + community) are active unless explicitly disabled.

### 5.4 Community Submission Process

1. Extension author creates a GitHub repo with `canon-extension.yml` and extension components
2. Author submits a PR to `canonhq/canon-extensions` adding an entry to `catalog.community.json`
3. PR is reviewed for catalog format and policy compliance (not code review)
4. On merge, extension becomes discoverable via `canon extension search`

### 5.5 Extension Categories

| Category | Description | Examples |
|---|---|---|
| `integration` | Syncs with external platforms | Azure DevOps, Monday.com, Shortcut |
| `workflow` | Orchestrates development processes | Sprint planning, release management |
| `compliance` | Enforces org policies | SOC-2 gates, required fields, audit trails |
| `visibility` | Reports on project health | Coverage dashboards, metrics export |
| `docs` | Reads, validates, or generates docs | Changelog generation, ADR templates |
| `code` | Reviews or modifies source code | Custom linting, security scanning |

### Acceptance Criteria

- [ ] Official catalog hosted at `canonhq/canon` with JSON schema
- [ ] Community catalog hosted at `canonhq/canon-extensions` with PR-based submission
- [ ] `canon extension search` queries all active catalogs and merges results
- [ ] Private catalogs configurable via CANON.yaml `extensions.catalogs` section
- [ ] Catalog entries include id, name, version, description, author, repository, category, tags
- [ ] Default catalogs (official + community) active unless explicitly disabled
- [ ] Community submission documented with clear PR template and review criteria
- [ ] Catalog schema includes `verified` flag for extensions reviewed by Canon team

## 6. Adapter Registration

<!-- canon:system:6 status:todo -->

<!-- canon:ticket:github:516 -->
Extend the existing adapter factory to discover and load adapters from installed extensions, in addition to built-in adapters.

### 6.1 Discovery Order

The adapter factory resolves adapters in this order:

1. **Built-in adapters**: `src/canon/sync/adapters/` (GitHub, Jira, Linear, Canon API)
2. **Entry point adapters**: Python packages declaring `canon.adapters` entry points
3. **Manifest adapters**: Extensions with `provides.adapters[].entry_point` in their manifest

If multiple adapters declare the same `system_name`, the first one wins (built-in > entry point > manifest).

### 6.2 Adapter Validation

On registration, each adapter is validated:
- Implements all required methods of `TicketAdapter` protocol
- Declares `system_name` property (must be unique)
- Declares `capabilities` property (returns `AdapterCapabilities`)
- Can be instantiated with standard config (connection URL, API key, project key)

### 6.3 CANON.yaml Integration

Extensions that provide adapters add their system name to the ticket routing config:

```yaml
ticket_systems:
  - system: azure-devops          # Matches adapter system_name
    project: "MyProject"
    url: "https://dev.azure.com/contoso"
    api_key: "${ADO_API_KEY}"

routing:
  - match:
      tags: [platform]
    target: azure-devops          # Routes to extension adapter
```

### Acceptance Criteria

- [ ] Adapter factory discovers adapters from Python entry points (`canon.adapters` group)
- [ ] Adapter factory discovers adapters from installed extension manifests
- [ ] Built-in adapters take precedence over extension adapters with same `system_name`
- [ ] Adapter validation checks protocol compliance before registration
- [ ] Extension adapters work with CANON.yaml `ticket_systems` and `routing` configuration
- [ ] `canon extension list` shows which adapters each extension provides
- [ ] Adapter discovery logs registered adapters at startup for debugging

## 7. Local Development Mode

<!-- canon:system:7 status:todo -->

<!-- canon:ticket:github:517 -->
Extension authors need a fast feedback loop: edit code, see changes immediately in Canon. The `--dev` flag enables this.

### 7.1 Dev Mode Installation

```bash
# Symlink instead of copy — edits to source directory take effect immediately
canon extension add --dev /path/to/my-extension

# Also works for adapter development (with live reload)
canon extension add --dev /path/to/my-extension --with-deps
```

Dev mode creates symlinks from `.canon/extensions/{id}/` to the source directory. Skill, command, and agent files are also symlinked (not copied), so edits propagate instantly.

For Python adapters in dev mode, `--with-deps` runs `uv pip install -e /path/to/my-extension` (editable install).

### 7.2 Extension Scaffolding

```bash
# Create a new extension from template
canon extension create my-extension

# Create with specific component types
canon extension create my-extension --adapter --skill --hook
```

The `create` command scaffolds:
```
my-extension/
  canon-extension.yml       # Pre-filled manifest template
  README.md                 # Extension documentation template
  LICENSE                   # MIT license (default)
  skills/                   # If --skill
    my-extension/
      SKILL.md
  commands/                 # Scaffold for slash commands
  hooks/                    # If --hook
  adapters/                 # If --adapter
    __init__.py
    adapter.py              # TicketAdapter skeleton
  pyproject.toml            # If --adapter (Python packaging)
```

### 7.3 Extension Validation

```bash
# Validate extension structure and manifest without installing
canon extension validate /path/to/my-extension

# Run self-tests defined in the extension
canon extension test my-extension
```

### Acceptance Criteria

- [ ] `canon extension add --dev` symlinks extension directory instead of copying
- [ ] Dev mode symlinks propagate file edits immediately
- [ ] `canon extension add --dev --with-deps` uses `uv pip install -e` for editable Python installs
- [ ] `canon extension create` scaffolds a valid extension directory from template
- [ ] `canon extension create --adapter` includes Python adapter skeleton and `pyproject.toml`
- [ ] `canon extension validate` checks manifest, file references, and adapter protocol compliance
- [ ] Dev mode extensions are flagged in `.registry.json` and `canon extension list` output

## 8. Security and Isolation

<!-- canon:system:8 status:todo -->

<!-- canon:ticket:github:518 -->
Extensions run in the same trust context as Canon itself (same Python process, same Claude Code session). Security is enforced through declaration and validation, not sandboxing.

### 8.1 Capability Declaration

The manifest's `provides` section serves as a capability declaration. Canon validates that extensions only access the capabilities they declare:
- An extension without `provides.mcp_tools` cannot register MCP tools
- An extension without `provides.adapters` cannot appear in adapter discovery
- Hook scripts can only bind to events declared in the manifest

### 8.2 AI Exposure Compliance

MCP tools provided by extensions are subject to the same `ai_exposure` enforcement as built-in tools:
- Spec content with `ai_exposure: none` is never passed to extension MCP tools
- Spec content with `ai_exposure: metadata` is redacted before passing to extension tools
- Extensions cannot bypass exposure controls (enforcement is in the MCP server, not the tool handler)

### 8.3 Secret Management

Extensions that need API keys or tokens:
- Must declare required secrets in the config template
- Must use `${ENV_VAR}` syntax in CANON.yaml, never hardcoded values
- Must document required environment variables in their README

### Acceptance Criteria

- [ ] Extensions can only register component types declared in their manifest
- [ ] MCP tool handlers from extensions go through the same `ai_exposure` filtering as built-in tools
- [ ] Extension config templates use `${ENV_VAR}` syntax for secrets
- [ ] `canon extension validate` warns if config contains hardcoded values that look like secrets
- [ ] Extension hook scripts run with the same permissions as core hooks (no elevation)

## 9. CANON.yaml Integration

<!-- canon:system:9 status:todo -->

<!-- canon:ticket:github:519 -->
Extensions that need user configuration add their settings under the `extensions` section of CANON.yaml.

### 9.1 Extension Configuration Section

```yaml
# CANON.yaml
extensions:
  # Catalog sources
  catalogs:
    - name: official
      url: "https://raw.githubusercontent.com/canonhq/canon/main/extensions/catalog.json"
    - name: community
      url: "https://raw.githubusercontent.com/canonhq/canon-extensions/main/catalog.community.json"

  # Per-extension configuration
  azure-devops:
    organization: "contoso"
    project: "Platform"
    area_path: "Platform\\Backend"
    work_item_type: "User Story"

  sprint-plan:
    sprint_length_days: 14
    velocity_points: 40
```

### 9.2 Config Validation

Extensions can optionally declare a JSON Schema in their manifest (`config_schema` field). Canon validates the CANON.yaml extension section against this schema on startup and on `canon extension validate`.

### 9.3 Config Templates

On first install, if an extension has `provides.config` with `required: true`, the CLI:
1. Copies the template file to `.canon/extensions/{id}/{config-name}`
2. Prompts the user to fill in required fields
3. Validates against the extension's `config_schema`

### Acceptance Criteria

- [ ] Extensions read their configuration from `extensions.{extension_id}` in CANON.yaml
- [ ] Extension config validated against declared JSON Schema on startup
- [ ] Config template copied and user prompted on first install for required configs
- [ ] `canon extension validate` checks extension config against schema
- [ ] Missing required config fields produce clear error messages with setup instructions

## Open Questions

1. **Catalog hosting**: Should the community catalog be in the main `canonhq/canon` repo (simpler, one PR target) or a separate `canonhq/canon-extensions` repo (cleaner separation, independent merge cadence)? Recommendation: separate repo, matching spec-kit's pattern.

2. **MCP tool namespacing**: Should extension MCP tools be prefixed (`azure_devops_get_work_item`) or flat (`get_work_item`)? Prefixing prevents collisions but is verbose. Recommendation: prefix with extension ID, matching the `speckit.{ext}.{cmd}` pattern.

3. **Hook ordering**: When multiple extensions register hooks for the same event, what's the execution order? Recommendation: alphabetical by extension ID, with a `priority` field for explicit ordering when needed.

4. **Python dependency isolation**: Should adapter extensions install into Canon's virtual environment or a per-extension isolated environment? Recommendation: Canon's environment (simpler), with a documented version compatibility table. If conflicts arise, consider uv workspaces.

5. **Bundled extensions**: Should the built-in Git adapter (GitHub Issues) remain in core, or be extracted to a bundled extension (like spec-kit's `git` extension)? Recommendation: keep built-in for now; extract later once the extension system is proven.

## Rollout Plan

### Phase 1: Foundation (MVP)
- Extension manifest schema and validation
- `canon extension add/remove/list` (local and `--dev` mode only)
- Skill and command extensions (markdown-only, no Python)
- Extension template scaffolding

### Phase 2: Adapters and Catalog
- Python adapter entry point discovery
- `canon extension search` with official catalog
- Community catalog with PR submission process
- `canon extension add` from catalog and GitHub repo

### Phase 3: Full Extensibility
- MCP tool registration from extensions
- Hook extension with lifecycle event binding
- Agent extensions
- `canon extension update/disable/enable`

### Phase 4: Ecosystem Growth
- Verified extension program
- Extension authoring documentation site
- Featured extensions in Canon docs
- Private catalog support for enterprises
