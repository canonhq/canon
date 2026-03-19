#!/usr/bin/env bash
# Canon PreToolUse hook — advisory spec references for git commits.
# Matched on the Bash tool, so this runs for every shell command.
# Exits early for non-commit commands (line 12-14) to minimize fork overhead.
# Respects ide.auto_verify.on_commit config.
set -euo pipefail

# Read tool input from stdin
input=$(cat)

# Only process git commit commands
tool_input=$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null || true)
if [[ "$tool_input" != *"git commit"* ]]; then
  exit 0
fi

CANON_YAML="${CLAUDE_PROJECT_DIR}/CANON.yaml"

# Quick exit if not a Canon repo
if [ ! -f "$CANON_YAML" ]; then
  exit 0
fi

# Check if on_commit is enabled (default: false).
# When false: advisory only. When true: requires user acknowledgment before commit.
# Scoped to ide: section to avoid matching on_commit in other YAML sections.
on_commit_enabled="false"
if grep -A 20 '^ide:' "$CANON_YAML" 2>/dev/null | grep -q 'on_commit:.*true'; then
  on_commit_enabled="true"
fi

# Get staged files
staged=$(git -C "$CLAUDE_PROJECT_DIR" diff --name-only --cached 2>/dev/null || true)
if [ -z "$staged" ]; then
  exit 0
fi

# Check for spec-related staged files
spec_files=$(echo "$staged" | grep -E '\.(md)$' | grep -iE '(spec|docs/)' || true)
src_files=$(echo "$staged" | grep -E '^(src/|lib/|app/)' || true)

if [ -z "$spec_files" ] && [ -z "$src_files" ]; then
  exit 0
fi

# Build advisory message
msg=""
if [ -n "$spec_files" ]; then
  msg="Staged files include spec documents: $(echo "$spec_files" | tr '\n' ', ' | sed 's/,$//')."
fi
if [ -n "$src_files" ]; then
  if [ -n "$msg" ]; then
    msg="$msg Also has"
  else
    msg="Staged"
  fi
  msg="$msg source files that may relate to specs."
fi
msg="$msg Consider adding spec references to commit message (e.g., [spec:feature#2.1])."

if [ "$on_commit_enabled" = "true" ]; then
  # Strict mode (on_commit: true): block and require acknowledgment
  jq -n --arg msg "$msg" '{"hookSpecificOutput":{"permissionDecision":"ask"},"systemMessage":$msg}'
else
  # Advisory mode (on_commit: false, default): just inform
  jq -n --arg msg "$msg" '{"systemMessage":$msg}'
fi
