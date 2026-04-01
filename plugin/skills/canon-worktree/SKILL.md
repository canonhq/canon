---
name: canon-worktree
description: >
  Create an isolated git worktree for spec-driven work. Use when starting feature
  work that needs isolation from the current workspace or before executing
  implementation plans.
allowed-tools:
  - Read
  - Bash
  - Glob
  - Grep
  - mcp__canon__get_spec
  - mcp__canon__search
---

# Git Worktree for Spec-Driven Work

You are creating an isolated git worktree for spec-driven development. This gives
the user (or a subagent) a clean workspace without polluting the main checkout.

## Step 1: Determine Worktree Directory

Find where to create worktrees, in priority order:

1. **Check for existing convention:**
   ```bash
   ls -d .claude/worktrees 2>/dev/null && echo "found"
   ```

2. **Check CLAUDE.md for guidance:**
   ```bash
   grep -i "worktree" CLAUDE.md 2>/dev/null
   ```

3. **Ask user** if neither exists. Suggest `.claude/worktrees/` as the default.

## Step 2: Safety Verification

The worktree directory MUST be git-ignored to avoid committing worktree contents.

```bash
git check-ignore <worktree-dir>
```

If NOT ignored, warn the user and suggest adding it to `.gitignore`:
```
Warning: <dir> is not git-ignored. Add it to .gitignore before proceeding:
  echo '<dir>/' >> .gitignore
```

Do not proceed until the directory is safely ignored.

## Step 3: Determine Spec Context

If the user provides a spec file or section ID, use it for naming. Otherwise:

1. Check recent git changes for spec references:
   ```bash
   git log --oneline -5
   git diff --name-only HEAD 2>/dev/null
   ```

2. Search for relevant specs via MCP or local glob:
   ```bash
   # MCP: mcp__canon__search with topic from user's request
   # Local: Glob for docs/specs/*.md, grep for relevant keywords
   ```

3. Ask the user which spec this work relates to.

Extract a spec slug (e.g., `auth-hardening`) and section ID (e.g., `2.1`) for
branch naming.

## Step 4: Create Worktree

```bash
git worktree add <dir>/<spec-slug> -b canon/<spec-slug>/<section-id>
```

Example:
```bash
git worktree add .claude/worktrees/auth-hardening -b canon/auth-hardening/2.1
```

If no section ID is known, use just the spec slug:
```bash
git worktree add .claude/worktrees/auth-hardening -b canon/auth-hardening
```

## Step 5: Project Setup

Auto-detect and run the project's setup commands in the new worktree:

```bash
cd <worktree-path>

# Node.js
[ -f package-lock.json ] && npm install
[ -f pnpm-lock.yaml ] && pnpm install
[ -f yarn.lock ] && yarn install
[ -f bun.lock ] && bun install

# Python
[ -f pyproject.toml ] && (command -v uv &>/dev/null && uv sync || pip install -e .)

# Rust
[ -f Cargo.toml ] && cargo build

# Go
[ -f go.mod ] && go mod download
```

## Step 6: Verify Baseline

Run the project's test suite to confirm a clean starting state:

```bash
# Detect and run tests
[ -f pyproject.toml ] && uv run pytest --tb=short -q
[ -f package.json ] && npm test 2>/dev/null
[ -f Cargo.toml ] && cargo test
[ -f go.mod ] && go test ./...
```

If tests fail, warn the user — they're starting from a broken baseline:
```
Warning: Baseline tests failing in worktree. Fix before starting new work,
or continue with caution (failures may not be related to your changes).
```

## Step 7: Load Spec Context

Load the relevant spec so the session has full context:

- If MCP available: `mcp__canon__get_spec` or `mcp__canon__get_section`
- If not: `Read` the spec file directly

Present a brief summary of the spec sections and ACs relevant to this work.

## Step 8: Report

```
Worktree ready:
  Path: <worktree-path>
  Branch: canon/<spec-slug>/<section-id>
  Spec: <spec-file> — <section-title>
  Setup complete, baseline tests passing

Next: use /canon:task or /canon:implement to start working.
```

## Cleanup

When work is complete (after merge/PR/discard via `canon-branch`):

```bash
git worktree remove <worktree-path>
git branch -d canon/<spec-slug>/<section-id>
```

If the branch wasn't merged and you want to force-delete:
```bash
git branch -D canon/<spec-slug>/<section-id>
```

## Common Mistakes

- **Creating worktree in a tracked directory** — always verify git-ignore first
- **Forgetting project setup** — the worktree is a fresh checkout, dependencies aren't there
- **Skipping baseline verification** — if tests already fail, you can't tell what you broke
- **Not loading spec context** — the whole point is spec-driven work, load the spec
