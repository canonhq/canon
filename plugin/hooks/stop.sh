#!/usr/bin/env bash
# Canon Stop hook — suggest spec verification if spec-related files were modified.
# Respects ide.auto_verify.on_stop config.
set -euo pipefail

CANON_YAML="${CLAUDE_PROJECT_DIR}/CANON.yaml"

# Quick exit if not a Canon repo
if [ ! -f "$CANON_YAML" ]; then
  exit 0
fi

# Check if on_stop is disabled
# Naive grep — may match outside ide section; acceptable tradeoff for hook speed.
if grep -q 'on_stop:.*false' "$CANON_YAML" 2>/dev/null; then
  exit 0
fi

# Get spec doc_paths patterns from CANON.yaml (default: docs/specs/*.md)
# Simple extraction — only matches double-quoted YAML list entries.
# Unquoted or single-quoted doc_paths will be missed, falling back to default.
spec_dirs=""
if grep -q 'doc_paths:' "$CANON_YAML" 2>/dev/null; then
  # Extract directory prefixes from doc_paths patterns
  spec_dirs=$(grep -A 20 'doc_paths:' "$CANON_YAML" \
    | grep '^\s*-\s*"' \
    | sed 's/.*"\(.*\)".*/\1/' \
    | sed 's|\*.*||' \
    | sort -u || true)
fi

# Fall back to default spec directory
if [ -z "$spec_dirs" ]; then
  spec_dirs="docs/specs/"
fi

# Check git diff for modified files (unstaged, then staged)
changed_files=$(git -C "$CLAUDE_PROJECT_DIR" diff --name-only 2>/dev/null || true)
if [ -z "$changed_files" ]; then
  changed_files=$(git -C "$CLAUDE_PROJECT_DIR" diff --name-only --cached 2>/dev/null || true)
fi

if [ -z "$changed_files" ]; then
  exit 0
fi

# Check if any changed files match spec directories
matched_specs=""
while IFS= read -r dir; do
  [ -z "$dir" ] && continue
  matches=$(echo "$changed_files" | grep "^${dir}" || true)
  if [ -n "$matches" ]; then
    matched_specs="$matched_specs $matches"
  fi
done <<< "$spec_dirs"

# Also check for source files that might relate to specs
# (files in src/, lib/, etc. that specs reference)
has_src_changes=$(echo "$changed_files" | grep -E '^(src/|lib/|app/)' || true)

if [ -n "$matched_specs" ]; then
  echo "You modified spec files:${matched_specs}. Run /canon:verify to check spec compliance or /canon:update to sync statuses."
elif [ -n "$has_src_changes" ]; then
  echo "You modified source files that may relate to specs. Consider running /canon:review to check for documentation drift."
fi
