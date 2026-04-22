# Extensions

Canon extensions add new capabilities — ticket adapters, skills, commands, hooks, and more — without modifying core. Install community extensions or build your own for org-specific workflows.

## Quick Start

### Install an Extension

```bash
# From a local directory
canon extension add /path/to/my-extension

# In dev mode (symlinks — edits propagate instantly)
canon extension add --dev /path/to/my-extension
```

### List Installed Extensions

```bash
canon extension list
```

Output:

```
  azure-devops v1.2.0 [enabled] — 3 file(s)
  sprint-plan v0.3.0 [enabled] (dev) — 2 file(s)
    Source: /home/user/code/canon-ext-sprint-plan
```

### Remove an Extension

```bash
canon extension remove azure-devops
```

This removes all placed files (skills, commands) and cleans up the registry.

## What Extensions Can Provide

| Component | Where It Gets Installed | What It Does |
|-----------|------------------------|-------------|
| **Skills** | `.canon/skills/{name}/SKILL.md` | IDE workflows (e.g., sprint planning, compliance checks) |
| **Commands** | `.claude/commands/{name}.md` | Slash commands for Claude Code autocomplete |
| **Adapters** | Python entry point | Ticket system integrations (Azure DevOps, Monday.com, etc.) |
| **Hooks** | Merged into hook config | Lifecycle automation (post-sync, post-verify) |
| **MCP Tools** | Registered on Canon MCP server | Custom queries and actions |
| **Agents** | `.canon/agents/{name}/AGENT.md` | Multi-agent dispatch targets |

A single extension can provide any combination of these.

## How Installation Works

When you run `canon extension add`, Canon:

1. Reads the extension's `canon-extension.yml` manifest
2. Validates the schema and checks Canon version compatibility
3. Copies the extension to `.canon/extensions/{id}/` (or symlinks in dev mode)
4. Places skill files into `.canon/skills/` so they're available in your IDE
5. Places command files into `.claude/commands/` for slash-command autocomplete
6. Records everything in `.canon/extensions/.registry.json` for clean removal

::: tip Dev Mode
Use `--dev` when developing or testing extensions. It creates symlinks instead of copies, so edits to the extension source directory take effect immediately — no reinstall needed.
:::


## Extension Configuration

Extensions that need user-specific settings read them from the `extensions` section of `CANON.yaml`:

```yaml
# CANON.yaml
extensions:
  azure-devops:
    organization: "contoso"
    project: "Platform"
    area_path: "Platform\\Backend"
    work_item_type: "User Story"

  sprint-plan:
    sprint_length_days: 14
    velocity_points: 40
```

Each extension documents its own configuration keys. Canon passes the extension's section to the extension at runtime.

## Validating Extensions

Before installing, you can validate an extension's manifest:

```bash
canon extension validate /path/to/my-extension
```

This checks:
- Manifest schema is valid
- All referenced files (skills, commands) exist
- Canon version compatibility is satisfied

## Extension Discovery


Browse and install extensions from the official catalog.


Browse community extensions at [github.com/canonhq/canon-extensions](https://github.com/canonhq/canon-extensions) (once available).

## File Layout

After installing extensions, your project looks like:

```
your-repo/
├── CANON.yaml                         # Extension config in extensions: section
├── .canon/
│   ├── extensions/
│   │   ├── .registry.json             # Tracks all installed extensions
│   │   ├── azure-devops/              # Extension directory (copy or symlink)
│   │   │   ├── canon-extension.yml
│   │   │   ├── skills/
│   │   │   └── commands/
│   │   └── sprint-plan/
│   └── skills/
│       ├── canon-context/             # Built-in Canon skills
│       ├── azure-devops-sync/         # ← Placed by extension
│       └── sprint-plan/               # ← Placed by extension
├── .claude/
│   └── commands/
│       ├── canon.md                   # Built-in Canon commands
│       └── canon-ado-sync.md          # ← Placed by extension
```

## Git and Extensions

**What to commit:**
- `CANON.yaml` (extension configuration)

**What NOT to commit (add to .gitignore):**
- `.canon/extensions/` — installed extension artifacts
- `.canon/extensions/.registry.json` — local install state

Each developer runs `canon extension add` to install extensions locally, similar to `npm install`. The manifest and source repo are the source of truth, not the installed files.

::: tip Team Workflow
Document required extensions in your project README or a setup script:
```bash
#!/bin/bash
# setup-extensions.sh
canon extension add --dev ../canon-ext-azure-devops
canon extension add --dev ../canon-ext-sprint-plan
```
:::
