---
# This file is auto-generated. Do not edit manually.
# Generated: 2026-05-15 00:00 UTC
---

# CLI Reference

::: tip Auto-Generated
This page was auto-generated from `canon --help` on 2026-05-15 00:00 UTC.
See [source script](https://github.com/canonhq/canon/blob/main/docs-site/.vitepress/scripts/gen-cli-ref.py).
:::

The Canon CLI provides local spec management commands.

## Installation

```bash
# With uv (recommended)
uv tool install canonhq

# With pip
pip install canonhq

# Run without installing
uvx --from canonhq canon --help
```

## Commands

```
usage: canon [-h]
```

## Global Flags

These flags are available on all commands:

| Flag | Description |
|------|-------------|
| `--no-color` | Disable colored output (also respects `NO_COLOR` env var) |
| `-q, --quiet` | Suppress non-essential output |
| `-v, --verbose` | Enable debug-level logging |

### `canon setup`

Initialize a repository for Canon. Creates `CANON.yaml`, the spec directory, and a starter template.

```bash
usage: canon setup [-h] [--team TEAM] [--ticket-system {github,jira,linear}] [--non-interactive] [--agent AGENT] [--force]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--team TEAM` | Team name for CANON.yaml |
| `--ticket-system {github,jira,linear}` | Ticket system (default: github) |
| `--non-interactive` | Skip prompts (for CI/Actions) |
| `--agent AGENT` | Generate agent config file (claude, cursor, copilot, codex, gemini, or all) |
| `--force` | Overwrite existing non-Canon agent config files |


---

### `canon login`

Authenticate with the Canon platform using device authorization flow or API key.

```bash
usage: canon login [-h] [--api-key API_KEY] [--server SERVER] [--org ORG]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--api-key API_KEY` | Authenticate with an API key instead of OAuth |
| `--server SERVER` | Platform URL (default: $CANON_URL or https://canonhq.co) |
| `--org ORG` | Target organization slug (e.g. 'canonhq'). Used to scope the device-flow token to a specific Auth0 Organization. If omitted, auto-detected from the current git remote when run inside a repo. |


---

### `canon logout`

Log out and revoke the current session.

```bash
usage: canon logout [-h]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |


---

### `canon auth`

Authentication utilities. Use `auth status` to check current authentication state.

```bash
usage: canon auth [-h] {status} ...
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `status` | Show current authentication status |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |


#### `canon auth status`

```bash
usage: canon auth status [-h]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |


---

### `canon tasks`

List actionable work items from specs. Shows sections with `todo` or `in_progress` status and their acceptance criteria.

```bash
usage: canon tasks [-h] [--status STATUS] [--spec SPEC] [--all]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--status STATUS` | Filter by specific status |
| `--spec SPEC` | Filter to a single spec file |
| `--all` | Include done/deprecated/draft |


---

### `canon status`

Show spec coverage dashboard. Displays per-spec and aggregate coverage metrics. Supports `--json` for machine-readable output consumed by the coverage-report GitHub Action.

```bash
usage: canon status [-h] [--spec SPEC] [--json]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--spec SPEC` | Show detail for a single spec file |
| `--json` | Emit machine-readable JSON instead of human-friendly output |


---

### `canon start`

Mark a spec section as `in_progress`. Optionally creates or updates a linked GitHub Issue.

```bash
usage: canon start [-h] [--issue] section_id
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `section_id` | Section ID, number, or partial slug |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--issue` | Create/update GitHub Issue for this section |


---

### `canon done`

Mark a spec section as `done`. Optionally closes the linked GitHub Issue.

```bash
usage: canon done [-h] [--issue] section_id
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `section_id` | Section ID, number, or partial slug |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--issue` | Update/close GitHub Issue if ticket link exists |


---

### `canon sync`

Sync spec sections with the configured ticket system (GitHub Issues, Jira, or Linear). Supports forward sync (spec → tickets) and reverse sync (tickets → spec).

```bash
usage: canon sync [-h] [--reverse] [--spec SPEC] [--dry-run] [--local] [--backfill-fingerprints] [--close-stale] [--remote]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--reverse` | Pull ticket statuses into spec markdown |
| `--spec SPEC` | Filter to a single spec file |
| `--dry-run` | Preview changes without executing |
| `--local` | Bypass server proxy and use GITHUB_TOKEN / gh CLI directly |
| `--backfill-fingerprints` | Add section fingerprints to existing issue bodies (one-time migration) |
| `--close-stale` | Close tickets for all done/deprecated sections (one- shot cleanup) |
| `--remote` | Force server proxy mode (overrides auto-detection) |


---

### `canon lint`

Static structural validation of spec files — frontmatter schema, section numbering, AC format, status comment syntax, and `depends_on` resolvability. Pure parser, no Claude spend, no network. The cheapest layer of the lint → verify → audit ladder; safe to run on every PR.

```bash
usage: canon lint [-h] [--spec SPEC] [--json] [--warnings-as-errors]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--spec SPEC` | Lint a single spec by partial path match (default: all discovered specs) |
| `--json` | Emit machine-readable JSON instead of human-friendly output |
| `--warnings-as-errors` | Treat warnings as errors (affects exit code) |


---

### `canon verify`

Static verification of acceptance criteria against the codebase. Greps source paths for keywords from each unchecked AC and classifies it as likely realized, not started, or unknown. No Claude spend. Supports `--json` for the verify GitHub Action.

```bash
usage: canon verify [-h] [--section SECTION] [--json] [--gate]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--section SECTION` | Filter to a single section ID |
| `--json` | Emit machine-readable JSON instead of human-friendly output |
| `--gate` | Gate mode — exit nonzero if any in-scope ACs are unchecked |


---

### `canon audit`

Audit spec statuses against the codebase using Claude. Checks off realized ACs, inserts evidence comments, and optionally runs ticket sync.

```bash
usage: canon audit [-h] [--dry-run] [--sync] [--spec SPEC] [--no-ac-updates] [--json]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--dry-run` | Preview changes without writing |
| `--sync` | Run ticket sync after audit |
| `--spec SPEC` | Filter to a single spec file |
| `--no-ac-updates` | Skip checking off ACs and inserting evidence |
| `--json` | Emit machine-readable JSON instead of human-friendly output |


---

### `canon plan`

Generate a task plan from a spec. Outputs a structured implementation plan based on unchecked acceptance criteria.

```bash
usage: canon plan [-h] [--output OUTPUT] spec_file
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `spec_file` | Spec file path or partial match |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--output OUTPUT` | Write plan to file instead of stdout |


---

### `canon new`

Scaffold a new spec file from a template. Non-interactive — every input is a flag. Used by the new-spec GitHub Action to produce consistent output.

```bash
usage: canon new [-h] --title TITLE [--type {adr,design,runbook,spec}] [--owner OWNER] [--team TEAM] [--output OUTPUT] [--force]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--title TITLE` | Spec title (e.g. "Auth Hardening") |
| `--type {adr,design,runbook,spec}` | Document type (default: spec) |
| `--owner OWNER` | Owner GitHub handle or name |
| `--team TEAM` | Owning team |
| `--output OUTPUT` | Explicit output path. Defaults to `<doc_paths_directory>/<slug>.md` based on CANON.yaml's first `doc_paths` entry |
| `--force` | Overwrite the output file if it already exists |


---

### `canon release-notes`

Generate spec-driven release notes between two git refs. Diffs spec files at the section level and reports sections that transitioned to `done`, new realization evidence, and new/removed spec files.

```bash
usage: canon release-notes [-h] [--from FROM_REF] [--to TO_REF] [--json] [--output OUTPUT]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--from FROM_REF` | Git ref (tag, branch, or SHA) to compare from. Defaults to the previous tag from `git describe --tags --abbrev=0 HEAD^` |
| `--to TO_REF` | Git ref to compare to (default: HEAD) |
| `--json` | Emit machine-readable JSON instead of human-friendly markdown |
| `--output OUTPUT` | Write output to file instead of stdout |


---

### `canon stale`

Find specs whose realization code has churned but the spec itself has not been updated. Uses git log timestamps and line-count deltas — no Claude spend, no network. Feeds the `stale-spec-check` GitHub Action.

A spec is flagged as stale when: its file has not been touched in N days AND at least one file referenced in its `<!-- canon:realized-in -->` comments has changed AND the combined churn exceeds the configured threshold.

```bash
usage: canon stale [-h] [--stale-days STALE_DAYS] [--code-churn-threshold CODE_CHURN_THRESHOLD] [--json]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--stale-days STALE_DAYS` | Spec is candidate-stale when not touched in this many days (default: 90) |
| `--code-churn-threshold CODE_CHURN_THRESHOLD` | Combined changed lines across realization files required to flag (default: 50) |
| `--json` | Emit machine-readable JSON instead of human-friendly output |


---

### `canon export`

Emit a compliance-grade audit trail of every acceptance criterion across every spec. One row per AC with spec coordinates, owner, team, realization references, and last-modified date. Designed for regulated environments.

```bash
usage: canon export [-h] [--format {json,csv}] [--output OUTPUT] [--spec SPEC]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--format {json,csv}` | Output format (default: json). CSV joins list fields with semicolons |
| `--output OUTPUT` | Write to file instead of stdout |
| `--spec SPEC` | Filter to a single spec file (substring match) |


---

### `canon dedup`

Find and resolve duplicate tickets for spec sections. Rewrites `ticket:unknown` links to `ticket:github` and detects duplicate open tickets for the same section.

```bash
usage: canon dedup [-h] [--dry-run] [--spec SPEC]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--dry-run` | Preview changes without acting |
| `--spec SPEC` | Path to specific spec file |


---

### `canon ide-config`

Emit the resolved `ide:` section from `CANON.yaml` as JSON for hook scripts. Always exits 0 — missing or malformed `CANON.yaml` degrades to defaults so hooks never need to handle error cases.

```bash
usage: canon ide-config [-h] [--json]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--json` | Emit JSON to stdout (currently the only output mode; reserved for future formats) |


---

### `canon evidence`

Capture and inspect dev-session evidence for the plugin evidence pipeline. Manages session records in `.canon/session-evidence.json` and verify logs in `.canon/verify-log.jsonl`.

```bash
usage: canon evidence [-h] {record,list-verify-runs,show,push} ...
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `record` | Compose a SessionRecord and append to `.canon/session-evidence.json` |
| `list-verify-runs` | Print records from `.canon/verify-log.jsonl` |
| `show` | Pretty-print `.canon/session-evidence.json` |
| `push` | Persist evidence per `commit_on_push` mode (called by pre-push hook) |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |


#### `canon evidence list-verify-runs`

```bash
usage: canon evidence list-verify-runs [-h] [--since SINCE]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--since SINCE` | Only show records with `at` >= this ISO 8601 timestamp |


#### `canon evidence push`

```bash
usage: canon evidence push [-h] [--mode {auto,always,ask,never}]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--mode {auto,always,ask,never}` | Override `commit_on_push` mode (default: read from CANON.yaml) |


---

### `canon integrations`

Manage ticket system and service connections. Alias: `canon int`.

```bash
usage: canon integrations [-h] {list,add,remove,test} ...
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `list` | List configured integrations |
| `add` | Connect a ticket system or service |
| `remove` | Disconnect an integration |
| `test` | Health check integration connections |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |


#### `canon integrations list`

```bash
usage: canon integrations list [-h] [--json] [--source {backend,local,env}]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--json` | JSON output |
| `--source {backend,local,env}` | Filter by credential source |


#### `canon integrations add`

```bash
usage: canon integrations add [-h] [--token TOKEN] [--non-interactive] {github,jira,linear}
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `provider` | Provider to connect (`github`, `jira`, or `linear`) |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--token TOKEN` | API token (skip interactive prompt) |
| `--non-interactive` | Fail if prompts are needed |


#### `canon integrations remove`

```bash
usage: canon integrations remove [-h] [--yes] {github,jira,linear}
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `provider` | Provider to disconnect |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--yes, -y` | Skip confirmation |


#### `canon integrations test`

```bash
usage: canon integrations test [-h] [--json] [{github,jira,linear}]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `provider` | Provider to test (default: all configured) |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--json` | JSON output |


---

### `canon extension`

Manage Canon extensions — install, remove, list, create, validate, search, and update extensions.

```bash
usage: canon extension [-h] {add,remove,list,create,validate,search,info,update,enable,disable} ...
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `add` | Install an extension from a local directory |
| `remove` | Remove an installed extension |
| `list` | List installed extensions |
| `create` | Scaffold a new extension |
| `validate` | Validate an extension manifest |
| `search` | Search extension catalogs |
| `info` | Show detailed extension information |
| `update` | Update an installed extension |
| `enable` | Enable a disabled extension |
| `disable` | Disable an extension without removing it |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |


#### `canon extension add`

```bash
usage: canon extension add [-h] [--dev] source
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `source` | Path to extension directory |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--dev` | Symlink instead of copy (dev mode — edits propagate instantly) |


#### `canon extension create`

```bash
usage: canon extension create [-h] [--skill] [--command] [--hook] [--adapter] [--author AUTHOR] [-o OUTPUT] ext_id
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `ext_id` | Extension ID (lowercase, hyphens) |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--skill` | Include skill template |
| `--command` | Include command template |
| `--hook` | Include hook template |
| `--adapter` | Include adapter skeleton |
| `--author AUTHOR` | Author name |
| `-o, --output OUTPUT` | Output directory (default: `./<ext_id>`) |


#### `canon extension search`

```bash
usage: canon extension search [-h] [--tag TAG] [--category CATEGORY] [query]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `query` | Search query (substring match) |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--tag TAG` | Filter by tag |
| `--category CATEGORY` | Filter by category |


#### `canon extension update`

```bash
usage: canon extension update [-h] [--all] [ext_id]
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `ext_id` | Extension ID to update |


**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--all` | Update all extensions |


---

### `canon doctor`

Run diagnostic checks on your Canon installation. Checks config (`CANON.yaml`, `.mcp.json`, spec files), authentication (Canon token, GitHub CLI), integrations, and MCP server availability.

```bash
usage: canon doctor [-h] [--json] [--fix]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--json` | JSON output |
| `--fix` | Attempt to auto-fix issues where possible |


---

### `canon search`

Search spec files by keyword. Searches section titles, body content, and acceptance criteria text.

```bash
usage: canon search [-h] [--status STATUS] [--spec SPEC] [--json] query
```

**Arguments:**

| Argument | Description |
|----------|-------------|
| `query` | Search terms (space-separated, case-insensitive) |

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--status STATUS` | Filter by section status (e.g. `todo`, `in_progress`, `done`) |
| `--spec SPEC` | Limit search to a specific spec file |
| `--json` | JSON output |

**Exit codes:** 0 = results found, 1 = no results.


---

### `canon dashboard`

Combined overview showing spec coverage, active tasks, and incomplete specs in a single view.

```bash
usage: canon dashboard [-h] [--json]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--json` | JSON output |

Runs entirely locally — no network calls required.
