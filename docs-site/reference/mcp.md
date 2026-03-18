---
# This file is auto-generated. Do not edit manually.
# Generated: 2026-03-18 18:07 UTC
---

# MCP Tools Reference

::: tip Auto-Generated
This page was auto-generated from MCP server tool metadata on 2026-03-18 18:07 UTC.
See [source script](https://github.com/canonhq/canon/blob/main/docs-site/.vitepress/scripts/gen-mcp-ref.py).
:::

The Canon MCP server exposes tools for coding agents (Claude Code, Cursor, VS Code Copilot) to query and update the spec knowledge base.

## Setup

### Claude Code

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "canon": {
      "command": "uvx",
      "args": ["canon", "mcp"]
    }
  }
}
```

### Cursor / VS Code

Add to your MCP configuration with the same command and args.

## Tools (11)

### `search`

Search the spec knowledge base using hybrid search (vector + BM25). Returns matching sections with repo, path, title, heading, body snippet, status, and relevance score. Use this to find specs related to what you're working on.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `query` | `str` | Yes | — |
| `repo` | `str | None` | No | — |
| `status` | `str | None` | No | — |
| `limit` | `int` | No | 10 |

---

### `get_spec`

Get a full parsed spec document with frontmatter, sections, acceptance criteria, and status. Returns structured data.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `owner` | `str` | Yes | — |
| `repo` | `str` | Yes | — |
| `file_path` | `str` | Yes | — |

---

### `get_section`

Get a single section from a spec by its ID. Returns the section with content, acceptance criteria, and ticket link.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `owner` | `str` | Yes | — |
| `repo` | `str` | Yes | — |
| `file_path` | `str` | Yes | — |
| `section_id` | `str` | Yes | — |

---

### `get_doc`

Get raw markdown content of any document from a repository. Use this when you need the unprocessed markdown.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `owner` | `str` | Yes | — |
| `repo` | `str` | Yes | — |
| `file_path` | `str` | Yes | — |

---

### `list_specs`

List all spec documents in a repository (using configured doc_paths). Returns metadata (title, status, owner) without full content.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `owner` | `str` | Yes | — |
| `repo` | `str` | Yes | — |

---

### `list_docs`

List all indexed document paths in the knowledge base. Optionally filter by repository (e.g. 'owner/repo').

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `repo` | `str | None` | No | — |

---

### `get_coverage`

Get spec coverage metrics for the organization. Returns aggregate coverage summary (total specs, sections, ACs, realization rate, health score) and a time-series trend. Optionally filter by repository or team.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `repo` | `str | None` | No | — |
| `team` | `str | None` | No | — |
| `days` | `int` | No | 30 |

---

### `create_spec`

Create a new spec document in a repository from a template. Commits the file directly to the default branch.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `owner` | `str` | Yes | — |
| `repo` | `str` | Yes | — |
| `title` | `str` | Yes | — |
| `doc_type` | `str` | No | 'spec' |
| `team` | `str` | No | '' |
| `owner_name` | `str` | No | '' |
| `tags` | `list[str] | None` | No | — |
| `file_name` | `str | None` | No | — |

---

### `update_section_status`

Update the status of a spec section. Modifies the status comment in-place or inserts one if missing, then commits the change.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `owner` | `str` | Yes | — |
| `repo` | `str` | Yes | — |
| `file_path` | `str` | Yes | — |
| `section_id` | `str` | Yes | — |
| `new_state` | `str` | Yes | — |

---

### `add_realization`

Add realization evidence to a spec section's acceptance criterion. Links a PR and code location to an AC checkbox.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `owner` | `str` | Yes | — |
| `repo` | `str` | Yes | — |
| `file_path` | `str` | Yes | — |
| `section_id` | `str` | Yes | — |
| `ac_text` | `str` | Yes | — |
| `pr_number` | `int` | Yes | — |
| `code_file` | `str` | Yes | — |
| `lines` | `str` | No | '' |

---

### `sync_spec_status`

Bulk update a spec: apply multiple status updates and realizations in a single commit. More efficient than individual calls.

**Parameters:**

| Name | Type | Required | Default |
|------|------|----------|---------|
| `owner` | `str` | Yes | — |
| `repo` | `str` | Yes | — |
| `file_path` | `str` | Yes | — |
| `status_updates` | `list[dict] | None` | No | — |
| `realizations` | `list[dict] | None` | No | — |
| `commit_message` | `str` | No | '' |

---
