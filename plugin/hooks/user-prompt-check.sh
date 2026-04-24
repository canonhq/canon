#!/usr/bin/env bash
# Canon UserPromptSubmit hook — suggest relevant specs when the user's prompt
# might relate to documented work.
#
# Deterministic guard: exits silently when CANON.yaml doesn't exist or the
# feature is disabled, so that fresh/bootstrapping repos are never blocked.
# Only emits a systemMessage prompt instruction when the repo is Canon-enabled
# and has specs to search.
set -euo pipefail

# Guard: CLAUDE_PROJECT_DIR must be set by the plugin host
if [ -z "${CLAUDE_PROJECT_DIR:-}" ]; then
  exit 0
fi

CANON_YAML="${CLAUDE_PROJECT_DIR}/CANON.yaml"

# Quick exit if not a Canon repo — this is the key fix.
# A freshly created but uncommitted CANON.yaml still passes this check,
# but we additionally require specs to exist before suggesting searches.
if [ ! -f "$CANON_YAML" ]; then
  exit 0
fi

# Check if specs directory exists and has any .md files
spec_dir="${CLAUDE_PROJECT_DIR}/docs/specs"
if [ ! -d "$spec_dir" ]; then
  exit 0
fi
first_spec=$(find "$spec_dir" -maxdepth 1 -name '*.md' -type f -print -quit 2>/dev/null)
if [ -z "$first_spec" ]; then
  exit 0
fi

# Read ide config — respect on_prompt opt-out
if command -v canon >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  ide_config=$(cd "$CLAUDE_PROJECT_DIR" && canon ide-config --json 2>/dev/null || echo '{}')
  on_prompt=$(echo "$ide_config" | jq -r '.auto_context.on_prompt' 2>/dev/null)
  if [ "$on_prompt" = "false" ]; then
    exit 0
  fi
else
  # Fallback: legacy grep when canon CLI or jq is unavailable.
  if grep -q 'on_prompt:.*false' "$CANON_YAML" 2>/dev/null; then
    exit 0
  fi
fi

# All guards passed — emit the spec-search instruction as a systemMessage.
# This is interpreted by Claude as context, not as a blocking gate.
cat <<'MSG'
This repo uses Canon specs. If the user's message relates to a documented feature or spec topic, use the Canon MCP 'search' tool with relevant keywords to find matching specs, then briefly mention which specs are relevant (cap at 5). If the message is clearly unrelated to specs (e.g., general questions, git operations, unrelated code), skip the search.
MSG
