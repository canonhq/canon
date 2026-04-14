---
# This file is auto-generated. Do not edit manually.
# Generated: 2026-04-11 21:34 UTC
---

# CLI Reference

::: tip Auto-Generated
This page was auto-generated from `canon --help` on 2026-04-11 21:34 UTC.
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
usage: canon verify [-h] [--section SECTION] [--json]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--section SECTION` | Filter to a single section ID |
| `--json` | Emit machine-readable JSON instead of human-friendly output |


---

### `canon audit`

Audit spec statuses against the codebase using Claude. Checks off realized ACs, inserts evidence comments, and optionally runs ticket sync.

```bash
usage: canon audit [-h] [--dry-run] [--sync] [--spec SPEC] [--no-ac-updates]
```

**Options:**

| Option | Description |
|--------|-------------|
| `-h, --help` | show this help message and exit |
| `--dry-run` | Preview changes without writing |
| `--sync` | Run ticket sync after audit |
| `--spec SPEC` | Filter to a single spec file |
| `--no-ac-updates` | Skip checking off ACs and inserting evidence |


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
