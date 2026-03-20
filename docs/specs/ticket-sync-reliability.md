---
title: "Ticket Sync Reliability"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon-private
created: 2026-03-18
updated: 2026-03-18
tags: [sync, tickets, reliability, dx]
---

# Ticket Sync Reliability

Harden the `canon sync` pipeline so that repeated runs are safe, lifecycle
transitions propagate to tickets, and the default mode works without server
proxy configuration.

## 1. Background

<!-- canon:system:1 status:todo -->

A full spec audit and issue cleanup on 2026-03-18 exposed several reliability
gaps in the ticket sync pipeline:

1. **Duplicate issues**: Repeated `canon sync` runs created 3 generations of
   duplicate GitHub Issues (~25 duplicates) because ticket link comments were
   not written back to spec files between runs. The dedup logic searches by
   title, but if the markdown isn't committed after sync, subsequent runs
   have no signal that an issue already exists.

2. **Stale issues for done sections**: Sections that moved from `todo` →
   `done` during the audit still had open GitHub Issues. The sync engine
   creates issues for `todo`/`in_progress` sections but never closes them
   when sections reach `done`. Manual cleanup of ~10 stale issues was
   required.

3. **Label prefix drift**: The rebrand from Specwright → Canon left GitHub
   labels using the old `specwright:*` prefix. The adapter still creates
   both `specwright:*` and `canon:*` labels for backward compatibility, but
   this doubles the label noise and the old prefix is no longer meaningful.

4. **Default adapter requires server proxy**: Running `canon sync` without
   `--local` routes through the Canon server proxy at `canonhq.co`, which
   returned 403 for issue creation. Most CLI users have `GITHUB_TOKEN` or
   `gh` auth available and expect direct GitHub API access.

5. **All-or-nothing review gate**: `require_review: true` in CANON.yaml
   blocked all syncs globally. No way to exempt individual specs or enable
   sync for `todo` sections while gating `in_progress` ones.

6. **No sync metadata**: After sync, the only evidence is a
   `<!-- canon:ticket:github:NNN -->` comment. No timestamp, no indication
   of when the link was created or last verified.

These issues compound: a user runs `canon sync`, forgets to commit, runs it
again, and ends up with duplicate issues they must manually close. Meanwhile,
completed work leaves orphaned open issues that clutter the backlog.

<!-- canon:ticket:github:376 -->
## 2. Lifecycle Sync: Auto-Close Done Sections

<!-- canon:system:2 status:todo -->

When a spec section transitions to `done` (or `deprecated`), forward sync
should close or transition the linked ticket rather than ignoring it.
Conversely, when a section moves back from `done` to `in_progress` or `todo`
(regression or scope change), sync should reopen the linked ticket.

Currently, `_SYNCABLE_STATES = {"todo", "in_progress"}` means done sections
are skipped entirely during forward sync. This leaves stale open issues in
the tracker.

Bidirectional lifecycle sync is enabled by default but configurable via
CANON.yaml `specs.lifecycle_sync` setting.

### Acceptance Criteria

- [x] Forward sync detects sections with `status: done` or `deprecated` that have an existing `ticket_link`
<!-- canon:realized-in:PR#385 file:src/canon/sync/engine.py -->
- [x] For those sections, sync calls `adapter.update_ticket()` to transition the ticket to its closed/done state
- [ ] GitHub adapter closes the issue and applies `canon:done` label (removes `canon:todo`/`canon:in-progress`)
- [ ] Jira adapter transitions to "Done" status
- [ ] Linear adapter transitions to "Done" state
- [x] Forward sync detects sections that moved back from `done`/`deprecated` to `todo`/`in_progress` and reopens the linked ticket
- [ ] GitHub adapter reopens the issue and applies the appropriate `canon:todo` or `canon:in-progress` label (removes `canon:done`)
- [ ] Sections in `draft` or `blocked` state are still skipped (no ticket interaction)
- [ ] `--dry-run` reports which tickets would be closed or reopened without acting
- [ ] SyncResult gains new `closed: list[SyncClosed]` and `reopened: list[SyncReopened]` fields
- [x] CANON.yaml `specs.lifecycle_sync` accepts `true` (default), `false`, or `"close_only"` (no reopen)
<!-- canon:realized-in:PR#385 file:src/canon/config/parse.py -->
- [ ] `canon sync --close-stale` explicitly closes tickets for all done/deprecated sections (same as lifecycle sync, but as a one-shot CLI flag independent of config)
- [ ] Test: section moves todo→done between syncs, second sync closes the ticket
- [ ] Test: section moves done→in_progress, sync reopens the ticket
- [ ] Test: `lifecycle_sync: false` skips all close/reopen actions
- [ ] Test: `--close-stale` works even when `lifecycle_sync: false`

<!-- canon:ticket:github:377 -->
## 3. Robust Dedup via Section Fingerprints

<!-- canon:system:3 status:todo -->

Add a secondary dedup signal beyond ticket link comments so that sync is
idempotent even when markdown isn't committed between runs.

The current dedup searches by title via `adapter.search_tickets()`, which is
fragile: titles can match unrelated issues, and the "first result = canonical"
heuristic assumes creation order. A fingerprint embedded in the issue body
provides an exact match.

<!-- canon:ticket:github:378 -->
### 3.1 Fingerprint Format

<!-- canon:system:3.1 status:todo -->

Generate a deterministic fingerprint from the spec file path and section
number, embedded as a hidden marker in the issue body.

#### Acceptance Criteria

- [x] Fingerprint format: `<!-- canon:section:{spec_slug}:{section_number} -->` embedded in issue description body
<!-- canon:realized-in:PR#385 file:src/canon/sync/templates.py -->
- [ ] `spec_slug` derived from spec file path relative to repo root (e.g., `docs/specs/auth-hardening` for `docs/specs/auth-hardening.md`)
- [x] Fingerprint is stable across section title renames (keyed on path + number, not title)
- [x] `render_description()` in `templates.py` includes the fingerprint in generated issue bodies
- [ ] Custom description templates can reference `{{fingerprint}}` variable

<!-- canon:ticket:github:379 -->
### 3.2 Fingerprint-Based Dedup

<!-- canon:system:3.2 status:todo -->

Use the fingerprint as the primary dedup signal, falling back to title search.

#### Acceptance Criteria

- [ ] Dedup first searches for fingerprint string in issue bodies (GitHub: `"canon:section:slug:num" in:body`)
- [ ] If fingerprint match found, link to that issue (skip creation)
- [x] If no fingerprint match, fall back to existing title-based search
- [ ] Dedup result distinguishes fingerprint matches from title matches in logging
- [ ] Test: rename section title, re-sync, dedup still finds the original issue via fingerprint
- [ ] Test: two sections with similar titles in different specs get distinct issues

<!-- canon:ticket:github:380 -->
### 3.3 Backfill Existing Issues

<!-- canon:system:3.3 status:todo -->

Add fingerprints to existing issue bodies so that dedup works for issues
created before fingerprints were introduced.

#### Acceptance Criteria

- [x] `canon sync --backfill-fingerprints` scans all spec sections with existing `ticket_link` comments
- [x] For each linked issue, appends the fingerprint comment to the issue body via `adapter.update_ticket()`
- [x] Skips issues that already contain a fingerprint comment (idempotent)
- [ ] `--dry-run` reports which issues would be updated without acting
- [ ] Backfill runs once as a migration; subsequent syncs only add fingerprints to newly created issues
- [ ] Test: backfill adds fingerprint to issue without one, skips issue that already has one

<!-- canon:ticket:github:381 -->
## 4. Remove Legacy Specwright Labels

<!-- canon:system:4 status:todo -->

Stop creating `specwright:*` labels on new issues and clean up references
in the adapter code.

The GitHub adapter currently applies both `canon:*` and `specwright:*` labels
for backward compatibility. The rebrand is complete and no external systems
depend on the old prefix.

### Acceptance Criteria

- [ ] GitHub adapter `create_ticket()` only applies `canon:*` labels (remove `specwright:*` from label list)
- [ ] GitHub adapter `_resolve_status()` still reads `specwright:*` labels for reverse sync (backward-compatible read)
- [ ] Reverse sync label detection order: `canon:*` first, `specwright:*` fallback, then issue state
- [ ] No new `specwright:*` labels are created by any code path
- [ ] Test: create ticket only produces `canon:*` labels

<!-- canon:ticket:github:382 -->
## 5. Default to Local Adapter

<!-- canon:system:5 status:todo -->

Make `--local` the default behavior when GitHub credentials are available,
and require `--remote` to explicitly use the server proxy.

Most CLI users authenticate via `gh auth login` or `GITHUB_TOKEN`. The server
proxy is primarily for the web app and CI environments where the Canon server
manages credentials.

### Acceptance Criteria

- [x] `canon sync` auto-detects local credentials: checks `GITHUB_TOKEN` env var, then `gh auth token` subprocess
<!-- canon:realized-in:PR#385 file:src/canon/cli/sync_cmd.py -->
- [x] If local credentials found, uses local adapter by default (no `--local` flag needed)
- [ ] If no local credentials, falls back to server proxy (current default behavior)
- [ ] New `--remote` flag forces server proxy mode (replaces implicit default)
- [ ] `--local` flag still works (explicit local, errors if no credentials instead of falling back)
- [ ] Credential detection logged at debug level so users can diagnose which mode was selected
- [ ] Test: GITHUB_TOKEN set → local adapter selected; unset + no gh → remote adapter selected

<!-- canon:ticket:github:383 -->
## 6. Per-Spec Sync Control

<!-- canon:system:6 status:todo -->

Allow individual specs to opt in or out of sync via frontmatter, overriding
the global `require_review` and `auto_tickets` settings.

### Acceptance Criteria

- [x] Spec frontmatter supports `sync: true | false | auto` field (default: `auto`, meaning use global config)
<!-- canon:realized-in:PR#385 file:src/canon/parser/models.py -->
- [x] `sync: false` skips the spec entirely during forward and reverse sync
- [x] `sync: true` syncs the spec regardless of global `require_review` setting
- [ ] `sync: auto` defers to global config (current behavior)
- [ ] `canon sync --dry-run` reports which specs were skipped due to `sync: false`
- [x] Parser extracts `sync` field from frontmatter into `SpecDocument` model
<!-- canon:realized-in:PR#385 file:src/canon/parser/parse.py -->
- [ ] Test: spec with `sync: false` is skipped even when global auto_tickets is true

## 7. Technical Design

<!-- canon:system:7 status:draft -->

### 7.1 Lifecycle Sync Changes

In `engine.py`, extend `forward_sync()`:

```python
_SYNCABLE_STATES = {"todo", "in_progress"}
_CLOSABLE_STATES = {"done", "deprecated"}
_REOPENABLE_STATES = {"todo", "in_progress"}

# After processing syncable sections, handle lifecycle transitions:
for section in sections:
    if not section.ticket_link:
        continue
    if section.state in _CLOSABLE_STATES and lifecycle_sync in (True, "close_only"):
        target_status = resolve_forward(system, section.state, status_map)
        await adapter.update_ticket(UpdateTicketInput(
            ticket_id=section.ticket_link.ticket_id,
            status=target_status,
        ))
        result.closed.append(SyncClosed(...))
    elif section.state in _REOPENABLE_STATES and lifecycle_sync is True:
        # Check if ticket is currently closed; if so, reopen
        current = await adapter.get_ticket_status(section.ticket_link.ticket_id)
        if current.is_closed:
            target_status = resolve_forward(system, section.state, status_map)
            await adapter.update_ticket(UpdateTicketInput(
                ticket_id=section.ticket_link.ticket_id,
                status=target_status,
            ))
            result.reopened.append(SyncReopened(...))
```

New CANON.yaml config in `SpecsConfig`:

```python
lifecycle_sync: bool | Literal["close_only"] = True
```

New CLI flag: `canon sync --close-stale` overrides `lifecycle_sync` to act
as a one-shot close pass.

### 7.2 Fingerprint Implementation

In `templates.py`:

```python
def _make_fingerprint(doc: SpecDocument, section: SpecSection) -> str:
    slug = doc.source_path.stem  # e.g., "auth-hardening"
    return f"<!-- canon:section:{slug}:{section.section_number} -->"
```

Embed at end of rendered description. For dedup, search with:
```
"canon:section:auth-hardening:3" in:body is:issue repo:owner/repo
```

### 7.3 Adapter Mode Selection

In `sync_cmd.py`, replace the current try-remote-first logic:

```python
if args.remote:
    adapter = create_remote_adapter(...)
elif args.local:
    adapter = create_local_adapter(...)  # error if no creds
else:
    # Auto-detect
    if _has_local_credentials():
        adapter = create_local_adapter(...)
    else:
        adapter = create_remote_adapter(...)
```

### 7.4 Fingerprint Backfill

New CLI flag: `canon sync --backfill-fingerprints`

```python
async def backfill_fingerprints(doc, adapter, project_key):
    for section in _flatten_sections(doc.sections):
        if not section.ticket_link:
            continue
        fingerprint = _make_fingerprint(doc, section)
        # Fetch current body
        ticket = await adapter.get_ticket(section.ticket_link.ticket_id)
        if fingerprint in ticket.body:
            continue  # Already has fingerprint
        updated_body = ticket.body + "\n\n" + fingerprint
        await adapter.update_ticket(UpdateTicketInput(
            ticket_id=section.ticket_link.ticket_id,
            description=updated_body,
        ))
```

This is a one-time migration. After backfill, all new issues get fingerprints
automatically via `render_description()`.

### 7.5 Per-Spec Sync Field

In `parser/models.py`, add to `SpecDocument`:

```python
sync: Literal["true", "false", "auto"] = "auto"
```

In `engine.py`, check before processing:

```python
if doc.sync == "false":
    return (raw, SyncResult(skipped=[SyncSkipped(reason="sync disabled")]))
if doc.sync == "auto" and require_review and doc.review_status != "approved":
    return (raw, SyncResult(skipped=[SyncSkipped(reason="review required")]))
# sync: "true" always proceeds
```

## 8. Rollout Plan

<!-- canon:system:8 status:draft -->

### Phase 1: Safety — prevent duplicates and stale issues
1. Section fingerprints in issue bodies (§3.1)
2. Fingerprint-based dedup (§3.2)
3. Backfill existing issues with fingerprints (§3.3)
4. Lifecycle sync for done/deprecated sections with bidirectional support (§2)

### Phase 2: Developer experience
5. Default to local adapter (§5)
6. Remove legacy specwright labels (§4)

### Phase 3: Granularity
7. Per-spec sync control (§6)

## 9. Resolved Questions

- **Bidirectional lifecycle sync**: Yes — sync handles both close (done/deprecated) and reopen (back to todo/in_progress). Configurable via `specs.lifecycle_sync: true | false | "close_only"` in CANON.yaml. Default is `true` (bidirectional).
- **Fingerprint backfill**: Yes — `canon sync --backfill-fingerprints` adds fingerprints to existing issue bodies as a one-time migration.
- **`--close-stale` flag**: Yes — explicit CLI flag that closes tickets for done sections regardless of `lifecycle_sync` config. Useful for one-shot cleanup.
