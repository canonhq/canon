#!/usr/bin/env bash
# Canon SessionStart hook — inject spec awareness when CANON.yaml is present.
# Respects ide.auto_context.on_session_start config.
# Target: < 2 seconds.
set -euo pipefail

CANON_YAML="${CLAUDE_PROJECT_DIR}/CANON.yaml"

# Quick exit if not a Canon repo
if [ ! -f "$CANON_YAML" ]; then
  exit 0
fi

# Check if on_session_start is disabled in CANON.yaml
# Naive grep — may match outside ide section; acceptable tradeoff for hook speed.
if grep -q 'on_session_start:.*false' "$CANON_YAML" 2>/dev/null; then
  exit 0
fi

# Persist CANON_REPO env var for downstream hooks.
# CLAUDE_ENV_FILE is set by Claude Code during SessionStart events.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export CANON_REPO=true" >> "$CLAUDE_ENV_FILE"
fi

# Build awareness message
msg="This repo uses Canon specs for spec-driven development."
msg="$msg Use Canon MCP tools (search, get_spec, list_specs) or /canon skills for spec context."

# Try to get quick stats if canon CLI is available (timeout 2s)
if command -v canon >/dev/null 2>&1; then
  stats=$(timeout 2 canon status --json 2>/dev/null || true)
  if [ -n "$stats" ]; then
    spec_count=$(echo "$stats" | grep -o '"total_specs":[0-9]*' | grep -o '[0-9]*' || true)
    if [ -n "$spec_count" ]; then
      msg="$msg ($spec_count specs tracked)"
    fi
  fi
fi

echo "$msg"
