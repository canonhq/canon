---
name: canon-branch
description: >
  Complete a development branch: verify specs, update statuses, and merge/PR/cleanup.
  Use when done with a feature branch or after canon-implement finishes.
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - mcp__canon__get_spec
  - mcp__canon__get_section
  - mcp__canon__update_section_status
  - mcp__canon__sync_spec_status
---

# Complete a Development Branch

You are guiding the user through completing a development branch — verifying spec
compliance, updating spec statuses, and merging or creating a PR.

## Step 1: Identify Scope

Determine which spec sections were addressed on this branch:

```bash
# What specs were touched?
git log --oneline main..HEAD
git diff --name-only main..HEAD | grep -E '(docs/specs/|\.md$)'
```

If commit messages include `[spec:<slug>:<section>]` references, use those.
Otherwise, ask the user which spec sections this branch addresses.

## Step 2: Verify

Run `canon verify` (gate mode) for all spec sections touched on this branch.

```bash
canon verify --gate --section <id>
```

Or invoke the canon-verify skill in gate mode.

If verification **passes**, proceed to Step 3.

If verification **fails**, present the gaps:
```
Verification failed:
  - Section 2.1: 2/4 ACs lack realization evidence
  - Section 3.1: tests failing

Fix these before completing the branch, or proceed anyway (not recommended).
```

Ask the user how to proceed: fix now, proceed anyway, or abort.

## Step 3: Update Spec Statuses

For sections where all ACs are realized, update status to `done`:

Via MCP:
```
mcp__canon__update_section_status(
  section_id="2.1",
  status="done"
)
```

Or edit the spec file directly:
```markdown
<!-- canon:system:2.1 status:done -->
```

**Commit the spec status changes** so they're included in the merge/PR:
```bash
git add docs/specs/*.md
git commit -m "docs: update spec statuses for <spec-slug>"
```

## Step 4: Choose Completion Action

Present options to the user:

```
Branch work complete. Choose an option:
  1. Merge to base branch
  2. Push and create PR
  3. Keep branch as-is (resume later)
  4. Discard branch and worktree
```

### Option 1: Merge

```bash
# Try fast-forward first
git checkout <base-branch>
git merge --ff-only <feature-branch> || git merge <feature-branch>
```

Clean up:
```bash
git worktree remove <worktree-path> 2>/dev/null  # if in a worktree
git branch -d <feature-branch>
```

### Option 2: Push and Create PR

```bash
git push -u origin <feature-branch>
```

Generate PR description from spec context:

```markdown
## Summary
<Brief description of changes>

## Spec Coverage
Addresses acceptance criteria from `docs/specs/<spec>.md`:

| Section | AC | Status |
|---------|-----|--------|
| 2.1 | Rate limiting | Realized — `src/auth/rate_limit.py:42-60` |
| 2.1 | Token expiry | Realized — `src/auth/tokens.py:15-25` |
| ... | ... | ... |

## Changes
<Git log summary>
```

Create the PR:
```bash
gh pr create --title "<title>" --body "<body>"
```

Report the PR URL to the user.

### Option 3: Keep As-Is

```
Branch preserved:
  Branch: <branch-name>
  Worktree: <path> (if applicable)

Resume later with: cd <path> && /canon:implement
```

### Option 4: Discard

Confirm with the user — this is destructive:
```
This will delete the branch and worktree. Changes will be lost.
Are you sure? (yes/no)
```

If confirmed:
```bash
git worktree remove <worktree-path> 2>/dev/null
git branch -D <feature-branch>
```

## Workflow Tips

- Always run verification before completing — catching gaps now is cheaper than in review
- Commit spec status updates before merging so the PR includes spec changes
- PR descriptions with spec coverage make reviews faster and more focused
- If keeping the branch, note the worktree path for easy resumption
