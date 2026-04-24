#!/usr/bin/env bash
# Canon SessionStart hook — inject spec awareness when CANON.yaml is present.
# Respects ide.auto_context.on_session_start config.
# Target: < 2 seconds.
set -euo pipefail

# Guard: CLAUDE_PROJECT_DIR must be set by the plugin host
if [ -z "${CLAUDE_PROJECT_DIR:-}" ]; then
  exit 0
fi

CANON_YAML="${CLAUDE_PROJECT_DIR}/CANON.yaml"

# Quick exit if not a Canon repo
if [ ! -f "$CANON_YAML" ]; then
  exit 0
fi

# Read ide config via canon CLI; fall back to grep on missing CLI or jq.
read_ide_config() {
  if command -v canon >/dev/null 2>&1; then
    (cd "$CLAUDE_PROJECT_DIR" && canon ide-config --json 2>/dev/null) || echo '{}'
  else
    echo '{}'
  fi
}

if command -v jq >/dev/null 2>&1; then
  ide_config=$(read_ide_config)
  on_session_start=$(echo "$ide_config" | jq -r '.auto_context.on_session_start' 2>/dev/null)
  if [ "$on_session_start" = "false" ]; then
    exit 0
  fi
else
  # Fallback: legacy grep when jq is unavailable.
  if grep -q 'on_session_start:.*false' "$CANON_YAML" 2>/dev/null; then
    exit 0
  fi
fi

# Persist CANON_REPO env var for downstream hooks.
# CLAUDE_ENV_FILE is set by Claude Code during SessionStart events.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export CANON_REPO=true" >> "$CLAUDE_ENV_FILE" 2>/dev/null || true
fi

# Build core skill discovery message first (before any slow operations)
msg="This repo uses Canon specs for spec-driven development."

# Detect whether specs exist and adjust messaging
has_specs=false
if [ -d "${CLAUDE_PROJECT_DIR}/docs/specs" ]; then
  has_specs=true
fi

# Try to get quick stats if canon CLI is available
# Use portable timeout: check for GNU timeout, then macOS gtimeout, then skip
spec_count=""
if command -v canon >/dev/null 2>&1; then
  timeout_cmd=""
  if command -v timeout >/dev/null 2>&1; then
    timeout_cmd="timeout 2"
  elif command -v gtimeout >/dev/null 2>&1; then
    timeout_cmd="gtimeout 2"
  fi
  stats=$($timeout_cmd canon status --json 2>/dev/null || true)
  if [ -n "$stats" ]; then
    spec_count=$(echo "$stats" | grep -o '"total_specs":[0-9]*' | grep -o '[0-9]*' || true)
  fi
fi

if [ -n "$spec_count" ]; then
  msg="$msg ($spec_count specs tracked)"
fi

if [ "$has_specs" = true ]; then
  msg="$msg

Canon Iron Laws (read before any code change):

  1. Before any non-trivial change, run /canon:context first to load the
     relevant spec. 30 seconds of context saves 30 minutes of rework.
  2. If a spec doesn't exist for what you're building, create one with
     /canon:new before writing code. A 5-minute spec prevents drift.
  3. After implementing an AC, record realization evidence with /canon:verify.
     \"I'll update the spec later\" means never.
  4. Before claiming work is done, run /canon:verify --gate. Tests passing
     is not the same as ACs satisfied.

If you find yourself thinking any of these, STOP and run the right Canon skill:
  - \"This is just a quick fix\"                  → /canon:context
  - \"The spec doesn't exist yet\"                → /canon:new
  - \"I'll update the spec later\"                → /canon:verify
  - \"I know what to do, I don't need the spec\"  → /canon:context

Canon skills:
  /canon:context     — Load spec context for current task (start here)
  /canon:task        — Pick up a single task, implement its ACs
  /canon:implement   — Execute a multi-task plan end-to-end
  /canon:plan        — Plan: explore → propose → spec → design → tasks → implementation plan
  /canon:interrogate — Red-team a spec or plan before implementing
  /canon:new         — Create a new spec, proposal, ADR, or design doc
  /canon:worktree    — Create isolated git worktree for spec work
  /canon:branch      — Complete a branch: verify, update statuses, merge/PR
  /canon:verify      — Check if code satisfies spec acceptance criteria
  /canon:review      — Review changes against all documentation
  /canon:update      — Update spec statuses from code evidence
  /canon:audit       — Full spec audit with ticket sync
  /canon:status      — Spec coverage dashboard
  /canon:meta        — Skill discovery: find the right Canon skill for your task

Use /canon:context before starting work."
else
  msg="$msg

No specs found yet. Run /canon:new to create your first spec, or /canon:plan to plan a new feature.

Canon skills: context, task, implement, plan, interrogate, new, worktree, branch, verify, review, update, audit, status, meta."
fi

echo "$msg"
