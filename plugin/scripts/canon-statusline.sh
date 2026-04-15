#!/usr/bin/env bash
# Canon reference statusline — emits a one-line summary of spec health for
# the active project. Wire into ~/.claude/settings.json statusLine field:
#
#   { "statusLine": { "type": "command", "command": "~/.claude/canon-statusline.sh" } }
#
# Claude Code's plugin system does not support shipping statuslines from a
# plugin (see plugin-product-polish.md §6 platform limitation). Copy or
# symlink this script into ~/.claude/ to enable it globally.
#
# The script consumes Claude's session JSON on stdin (and ignores it),
# resolves the project directory from $CLAUDE_PROJECT_DIR (falling back to
# $PWD), and emits a single line. Exits 0 with empty output in non-Canon
# repos so other statuslines can take over.
set -euo pipefail

# Consume stdin (Claude pipes session JSON here).
cat >/dev/null

project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"

if [ ! -f "$project_dir/CANON.yaml" ]; then
  echo ""
  exit 0
fi

if ! command -v canon >/dev/null 2>&1; then
  echo "canon: cli not found"
  exit 0
fi

stats=$(cd "$project_dir" && canon status --json 2>/dev/null || echo '{}')

if ! command -v jq >/dev/null 2>&1; then
  echo "canon: stats unavailable (jq missing)"
  exit 0
fi

specs=$(echo "$stats" | jq -r '.total_specs // 0')
pct=$(echo "$stats" | jq -r '.overall_pct // "—"')
in_progress=$(echo "$stats" | jq -r '.in_progress_specs // 0')
open_acs=$(echo "$stats" | jq -r '.open_acs // 0')

echo "canon: ${specs} specs · ${pct} · ${in_progress} in_progress · ${open_acs} open ACs"
