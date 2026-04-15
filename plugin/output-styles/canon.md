---
name: canon
description: Spec-driven formatting — AC references, section markers, realization comments, coverage tables
keep-coding-instructions: true
---

# Canon Output Style

You are working in a Canon repo that uses spec-driven development. Beyond Claude Code's default coding behavior, follow these formatting and content rules so spec context, status changes, and verification evidence are recorded consistently.

## Referencing acceptance criteria

When you reference an AC from a spec, use the form `[spec:<slug>:<section>]` followed by the AC text. Example:

> `[spec:auth-hardening:2.1]` Rate limit: max 3 resets per hour

When citing implementation evidence for an AC, use a realization comment immediately after the AC checkbox:

```markdown
- [x] Rate limit: max 3 resets per hour
<!-- canon:realized-in:PR#42 file:src/auth/rate_limit.py:42-60 -->
```

The realization-evidence format is:

```
<!-- canon:realized-in:<source> file:<path>:<line-range> [file:<path>:<line-range> ...] -->
```

`<source>` is one of `audit`, `phase-X`, `PR#N`, or a free-form label. Always include at least one `file:` reference.

## Spec section status

When you change a section's status, emit (or update) the section-level status comment that immediately follows the section heading:

```markdown
## 2.1 Login Flow

<!-- canon:system:2.1 status:in_progress -->
```

Valid status values: `todo`, `draft`, `in_progress`, `done`, `blocked`, `moved`. If you mark a section as `moved`, briefly explain where the work went.

## Coverage tables

When you produce a coverage table, use this five-column shape so it lines up with `canon status`:

| Spec | Status | Sections | ACs | Coverage |
|------|--------|----------|-----|----------|
| Auth Hardening | in_progress | 3/12 | 21/48 | 44% |

When summarizing a single section or AC group, prefer counts over prose (e.g., `7/9 ACs realized` rather than "most of the criteria are done").

## Showing spec content

When you display a spec section to the user, lead with the acceptance criteria, not the prose. Users can read the prose themselves; the ACs are what they need to act on.

When you display multiple specs at once, summarize by section count and AC count rather than dumping full content. If the user wants depth, they will ask for a specific spec.

## When in doubt

If a piece of information is structured (status, AC, section ID, file path, line range), keep it structured. Reach for prose only when explaining why something happened, not what it is.
