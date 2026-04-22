# Extension Manifest Reference

Complete schema for `canon-extension.yml` — the manifest file required in every Canon extension.

## Schema Version

```yaml
schema_version: "1"  # Required. Currently only "1" is supported.
```

## Extension Metadata

```yaml
extension:
  id: "my-ext"                           # Required. Unique identifier.
  name: "My Extension"                   # Required. Human-readable name.
  version: "1.0.0"                       # Required. Semantic version.
  description: "What this extension does" # Optional.
  author: "Author Name"                  # Optional.
  repository: "https://github.com/..."   # Optional. Source code URL.
  license: "MIT"                         # Optional. SPDX identifier.
  homepage: "https://..."                # Optional. Documentation URL.
```

### ID Rules

| Rule | Example |
|------|---------|
| Lowercase letters, digits, hyphens | `sprint-plan`, `azure-devops` |
| 3-50 characters | `abc` (min), `my-really-long-extension-name-here` (ok) |
| Starts with letter | `a-ext` (ok), `1-ext` (invalid) |
| Ends with letter or digit | `ext-1` (ok), `ext-` (invalid) |
| Reserved: `canon`, `core`, `builtin` | These are always rejected |

## Compatibility Requirements

```yaml
requires:
  canon_version: ">=1.50.0"              # Required. Semver range.
  python: ">=3.12"                        # Optional. For adapter extensions.
  tools:                                  # Optional. External tool dependencies.
    - name: "azure-devops-mcp"
      required: false
      description: "Azure DevOps MCP server"
      install_url: "https://github.com/..."
  commands:                               # Optional. Core Canon commands needed.
    - "speckit.tasks"
```

### Version Range Syntax

Uses Python [packaging specifiers](https://packaging.pypa.io/en/latest/specifiers.html):

| Pattern | Meaning |
|---------|---------|
| `>=1.50.0` | Version 1.50.0 or higher |
| `>=1.50.0,<2.0.0` | 1.50.0 to 1.x.x (not 2.0) |
| `>=1.50.0,!=1.51.0` | 1.50.0+ but not 1.51.0 |

## Provided Components

At least one component type is required.

### Skills

```yaml
provides:
  skills:
    - name: "sprint-plan"                # Installed as .canon/skills/{name}/SKILL.md
      file: "skills/sprint-plan/SKILL.md" # Relative path in extension dir
      description: "Plan sprints"         # Optional.
```

### Commands

```yaml
provides:
  commands:
    - name: "canon-sprint"               # Installed as .claude/commands/{name}.md
      file: "commands/canon-sprint.md"    # Relative path in extension dir
      description: "Generate sprint plan" # Optional.
```

### Adapters


```yaml
provides:
  adapters:
    - id: "azure-devops"                  # Adapter system name
      entry_point: "pkg:AzureDevOpsAdapter" # Python dotted path
      capabilities:
        supports_custom_fields: true
        supports_hierarchy: true
        supports_subtasks: true
        supports_labels: true
        supports_issue_types: false
        supports_fingerprint_search: false
        supports_body_read: true
```

### Hooks


```yaml
provides:
  hooks:
    - event: "Stop"                       # Canon lifecycle event
      type: "command"                     # "command" or "prompt"
      command: "node ${EXTENSION_ROOT}/hooks/on-stop.mjs"
      timeout: 5                          # Seconds (default: 10)
```

Supported events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `Stop`, `after_sync`, `after_verify`, `after_realize`.

### MCP Tools


```yaml
provides:
  mcp_tools:
    - name: "ado_get_work_item"           # Namespaced as {ext_id}_{name}
      handler: "pkg.mcp:get_work_item"    # Python async function
      description: "Fetch a work item"
      input_schema:
        type: object
        required: [work_item_id]
        properties:
          work_item_id:
            type: integer
```

### Agents


```yaml
provides:
  agents:
    - name: "ado-reviewer"
      file: "agents/ado-reviewer/AGENT.md"
      description: "Review PRs against Azure DevOps work items"
```

### Config Templates

```yaml
provides:
  config:
    - name: "azure-devops.yml"            # Config file name
      template: "config/azure-devops.template.yml"  # Template source
      description: "Azure DevOps settings"
      required: true                      # Prompt user on install
```

## Lifecycle Hooks

Extensions can hook into Canon's workflow lifecycle:

```yaml
hooks:
  after_sync:
    command: "/canon-ado-sync"            # Command to run
    optional: true                        # Prompt user before running
    prompt: "Sync to Azure DevOps?"       # Prompt text
    description: "Push synced tickets"    # Optional description

  after_verify:
    command: "/canon-ado-update-status"
    optional: true
    prompt: "Update work item status?"
```

## Tags

```yaml
tags:
  - "issue-tracking"
  - "azure-devops"
  - "enterprise"
```

Tags are used for catalog search and discovery.

## Defaults

Default values for the extension's CANON.yaml config section:

```yaml
defaults:
  azure_devops:
    organization: null
    project: null
    work_item_type: "User Story"
```

## CLI Reference

### `canon extension add`

```bash
canon extension add <source> [--dev]
```

| Argument | Description |
|----------|-------------|
| `source` | Path to extension directory |
| `--dev` | Symlink instead of copy (dev mode) |

### `canon extension remove`

```bash
canon extension remove <ext_id>
```

Removes the extension and all placed files.

### `canon extension list`

```bash
canon extension list
```

Shows installed extensions with version, status, and file counts.

### `canon extension create`

```bash
canon extension create <ext_id> [options]
```

| Option | Description |
|--------|-------------|
| `--skill` | Include skill template |
| `--command` | Include command template |
| `--hook` | Include hook template |
| `--adapter` | Include adapter skeleton |
| `--author NAME` | Author name |
| `--output DIR` | Output directory (default: `./<ext_id>`) |

### `canon extension validate`

```bash
canon extension validate <source>
```

Validates manifest schema, file references, and version compatibility.

## Registry File

`.canon/extensions/.registry.json` tracks installed extensions:

```json
{
  "schema_version": "1",
  "extensions": {
    "sprint-plan": {
      "version": "1.0.0",
      "installed_at": "2026-04-15T10:30:00+00:00",
      "source": "dev",
      "dev_mode": true,
      "enabled": true,
      "source_path": "/home/user/canon-ext-sprint-plan",
      "installed_files": [
        ".canon/skills/sprint-plan/SKILL.md",
        ".claude/commands/canon-sprint.md"
      ]
    }
  }
}
```

This file is managed by the CLI. Do not edit it manually.
