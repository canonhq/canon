#!/usr/bin/env bash
# Canon PreToolUse hook — evidence persistence on git push.
# Matched on the Bash tool, so this runs for every shell command.
# Exits early for non-push commands to minimize fork overhead.
# Respects ide.evidence_pipeline.commit_on_push from CANON.yaml.
set -euo pipefail

# Read tool input from stdin
input=$(cat)

# Only process git push commands
tool_input=$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null || true)
if [[ "$tool_input" != *"git push"* ]]; then
  exit 0
fi

CANON_YAML="${CLAUDE_PROJECT_DIR}/CANON.yaml"

# Quick exit if not a Canon repo
if [ ! -f "$CANON_YAML" ]; then
  exit 0
fi

# Read evidence_pipeline config; require canon CLI + jq for the structured path.
if ! command -v canon >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

ide_config=$(cd "$CLAUDE_PROJECT_DIR" && canon ide-config --json 2>/dev/null || echo '{}')
ev_enabled=$(echo "$ide_config" | jq -r '.evidence_pipeline.enabled // false' 2>/dev/null)
if [ "$ev_enabled" != "true" ]; then
  exit 0
fi

commit_on_push=$(echo "$ide_config" | jq -r '.evidence_pipeline.commit_on_push // "ask"' 2>/dev/null)

# Quick exit if no evidence file exists
if [ ! -f "${CLAUDE_PROJECT_DIR}/.canon/session-evidence.json" ]; then
  exit 0
fi

case "$commit_on_push" in
  always)
    # Silently stage and commit before push proceeds.
    (cd "$CLAUDE_PROJECT_DIR" && canon evidence push --mode always 2>&1) || true
    ;;
  ask)
    # Emit an ask permissionDecision so the user is prompted before push.
    msg="Canon evidence captured at .canon/session-evidence.json. Commit it before pushing? Set evidence_pipeline.commit_on_push: always to skip this prompt."
    jq -n --arg msg "$msg" '{"hookSpecificOutput":{"permissionDecision":"ask"},"systemMessage":$msg}'
    ;;
  never)
    # No file persistence — exit silently.
    exit 0
    ;;
  *)
    # Unknown value — fall back to ask behavior.
    msg="canon: unknown evidence_pipeline.commit_on_push value '$commit_on_push'; treating as 'ask'"
    jq -n --arg msg "$msg" '{"systemMessage":$msg}'
    ;;
esac
