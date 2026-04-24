---
title: "Web App UX Polish"
status: draft
owner: ng
team: platform
ticket_project: canonhq/canon
created: 2026-03-26
updated: 2026-03-26
tags: [frontend, ux, ui, vue, dashboard, tasks, editor, navigation]
---

# Web App UX Polish

Improve the Canon web app across all pages — fix broken flows, add missing
navigation context, redesign the Tasks board, make the Explorer more useful
without click-through, and polish global UX patterns. This spec covers gaps
NOT addressed by existing specs (analytics-dashboard, spec-view-redesign,
spec-explorer-web-app).

## 1. Background

<!-- canon:system:1 status:done -->

The Canon web app at `canonhq.co/app/{org}/` has six authenticated pages:
Explorer (dashboard), Tasks, Analytics, Editor, Billing, and Profile. Several
UX gaps reduce the app's usefulness:

- **Tasks board is a flat table** with basic status/repo filters. No grouping
  by spec, no board view, no inline AC visibility, and most items show 0/0 ACs
  because the API only counts direct section ACs (not nested subsection ACs).
- **Editor shows "No repositories found"** with no guidance on how to fix it.
  The GitHub OAuth connection is a separate auth flow from OIDC login, and
  there's no indication that it's required.
- **Navigation lacks context** — no breadcrumbs, no active-page indicator, no
  way to jump between a spec and its tasks or editor view.
- **Explorer requires click-through** to see any detail about a spec. Cards
  show title, status badge, tags, and AC count but no section breakdown or
  progress visualization.
- **No global UX patterns** for loading states (just a spinner), empty states,
  user feedback (toasts), responsive layout, or keyboard shortcuts.

### Related specs

- `spec-explorer-web-app.md` — done (88%). Covers the Explorer page itself.
- `spec-view-redesign.md` — draft (0%). Covers the spec detail view.
- `analytics-dashboard.md` — in_progress (84%). Covers the analytics page.
- `user-profile-page.md` — done (100%). Covers the profile page.
- `theme-toggle-light-mode.md` — done (96%). Covers dark/light mode.

This spec fills the gaps between those specs.

## 2. Tasks Board Redesign

<!-- canon:system:2 status:todo -->

<!-- canon:ticket:github:595 -->
Redesign the Tasks page from a flat table into a multi-view board with
grouping, inline detail, and actionable ticket links.

### 2.1 Grouped View (Default)

<!-- canon:system:2.1 status:todo -->

<!-- canon:ticket:github:596 -->
#### Acceptance Criteria

- [ ] Tasks grouped by parent spec as collapsible sections
- [ ] Each spec group header shows: spec title, overall AC progress bar, count of todo/in_progress/blocked sections
- [ ] Groups are collapsed by default; clicking the header toggles open/closed
- [ ] Within each group, sections listed with section number, title, status badge, AC progress, and ticket link
- [ ] Group sort order: specs with in_progress sections first, then todo, then blocked

### 2.2 View Toggle

<!-- canon:system:2.2 status:todo -->

<!-- canon:ticket:github:597 -->
#### Acceptance Criteria

- [ ] Toggle buttons (List / Board / Grouped) in the page header, persisted to localStorage
- [ ] List view: current flat table with sortable column headers (section, spec, status, ACs, ticket)
- [ ] Board view: Kanban columns (Todo, In Progress, Blocked) with cards showing section title, spec name, and AC progress bar
- [ ] Board view cards are NOT draggable (status comes from spec files, not the UI)
- [ ] Grouped view: spec-grouped collapsible sections (§2.1)

### 2.3 Inline AC Expansion

<!-- canon:system:2.3 status:todo -->

<!-- canon:ticket:github:598 -->
#### Acceptance Criteria

- [ ] Clicking a task row (in any view) expands an inline detail panel below the row
- [ ] Detail panel shows the section's acceptance criteria as a checklist (read-only, reflecting spec state)
- [ ] Checked ACs show with strikethrough or muted styling
- [ ] If the section has a ticket link, show it as a clickable badge (e.g., "github#412" links to `github.com/canonhq/canon/issues/412`)
- [ ] Expanding one row auto-collapses any previously expanded row
- [ ] Detail panel includes a "View in spec" link to the spec view page

### 2.4 Ticket Link Badges

<!-- canon:system:2.4 status:todo -->

<!-- canon:ticket:github:599 -->
#### Acceptance Criteria

- [ ] Ticket references (e.g., `github#412`) rendered as clickable links opening in a new tab
- [ ] Link URL constructed from ticket_system and ticket_id: `github#{id}` → `github.com/{ticket_project}/issues/{id}`
- [ ] Badge styled with the ticket system icon (GitHub octocat) or text prefix

## 3. Explorer Inline Expansion

<!-- canon:system:3 status:todo -->

<!-- canon:ticket:github:600 -->
Add expandable detail to spec cards on the Explorer dashboard without
requiring navigation to the spec view.

### 3.1 Expandable Spec Cards

<!-- canon:system:3.1 status:todo -->

<!-- canon:ticket:github:601 -->
#### Acceptance Criteria

- [ ] Each spec card has a chevron/expand button
- [ ] Expanding a card reveals: section list with status indicators (colored dot or icon per status), AC progress bar per section, ticket link per section
- [ ] Expanding one card auto-collapses any previously expanded card
- [ ] Expanded state is NOT persisted (always starts collapsed on page load)

### 3.2 Card Enhancements

<!-- canon:system:3.2 status:todo -->

<!-- canon:ticket:github:602 -->
#### Acceptance Criteria

- [ ] Each spec card shows a mini AC progress bar (thin bar below the title, colored by completion percentage)
- [ ] Cards show "Updated X days ago" timestamp derived from spec file's git last-modified date or frontmatter `updated` field
- [ ] Hover state reveals quick-action buttons: "View" (spec detail), "Edit" (editor), "Tasks" (tasks filtered to this spec)
- [ ] Progress bar color: green when >80%, amber when 40-80%, red when <40%

### 3.3 Sticky Filter Bar

<!-- canon:system:3.3 status:todo -->

<!-- canon:ticket:github:603 -->
#### Acceptance Criteria

- [ ] Status and repo filter dropdowns stick to the top of the viewport when scrolling past them
- [ ] Sticky bar has a subtle bottom border/shadow to distinguish it from content
- [ ] Sticky behavior disabled on mobile (filters stack vertically and scroll normally)

## 4. Navigation & Cross-linking

<!-- canon:system:4 status:todo -->

<!-- canon:ticket:github:604 -->
Add contextual navigation so users always know where they are and can quickly
move between related views.

### 4.1 Breadcrumbs

<!-- canon:system:4.1 status:todo -->

<!-- canon:ticket:github:605 -->
#### Acceptance Criteria

- [ ] Breadcrumb bar displayed below the top nav on all app pages (not marketing pages)
- [ ] Breadcrumb segments are clickable links: org → page → repo → spec → section
- [ ] Dashboard: `{org}`; Tasks: `{org} / Tasks`; Spec view: `{org} / {repo} / {spec_title}`
- [ ] Breadcrumb component is generic (`Breadcrumb.vue` already exists) — extend with route-aware auto-generation
- [ ] Truncate long spec titles with ellipsis after 40 characters

### 4.2 Active Page Indicator

<!-- canon:system:4.2 status:todo -->

<!-- canon:ticket:github:606 -->
#### Acceptance Criteria

- [ ] Current nav item (Explorer, Tasks, Analytics, Editor, Billing) has a visible underline or highlight
- [ ] Active state derived from current route, not manual prop passing
- [ ] Profile and Logout in the top-right corner are excluded from the active indicator (they're account actions, not pages)

### 4.3 Cross-linking Between Views

<!-- canon:system:4.3 status:todo -->

<!-- canon:ticket:github:607 -->
#### Acceptance Criteria

- [ ] Spec view page includes links: "View tasks" (→ Tasks filtered by this spec), "Edit" (→ Editor with file loaded)
- [ ] Tasks page section links scroll to the correct section anchor in the spec view (not just the top of the page)
- [ ] Editor file list shows a "View" link next to each spec file (→ Spec view)
- [ ] Analytics page (future): link from health score to the specs contributing to each pillar

### 4.4 Spec-Level Sub-Navigation

<!-- canon:system:4.4 status:todo -->

<!-- canon:ticket:github:608 -->
#### Acceptance Criteria

- [ ] When viewing a spec, a tab bar or pill nav appears below the breadcrumb: Overview | Tasks | (History — future) | (Analytics — future)
- [ ] "Overview" tab shows the current spec view (rendered markdown with sections)
- [ ] "Tasks" tab shows only tasks for this spec (reuses TasksView with a spec filter prop)
- [ ] Future tabs (History, Analytics) show as disabled/greyed with "Coming soon" tooltip
- [ ] Active tab state persisted in the URL query parameter (`?tab=tasks`)

## 5. Editor Fix & Improvements

<!-- canon:system:5 status:todo -->

<!-- canon:ticket:github:609 -->
Fix the broken Editor empty state and add quality-of-life improvements.

### 5.1 Actionable Empty States

<!-- canon:system:5.1 status:todo -->

<!-- canon:ticket:github:610 -->
#### Acceptance Criteria

- [ ] When GitHub OAuth is not connected: show "Connect your GitHub account to edit specs" with a CTA button linking to `/auth/github`
- [ ] Detection: check if the user's session includes a `github_token` or call a lightweight API to check GitHub connection status
- [ ] When GitHub is connected but no repos found: show "No repositories with Canon installed" with a link to the GitHub App installation page
- [ ] Both states include a brief explanation of what the Editor does (create/edit spec files via GitHub API)

### 5.2 Autosave Indicator

<!-- canon:system:5.2 status:todo -->

<!-- canon:ticket:github:611 -->
#### Acceptance Criteria

- [ ] Editor toolbar shows save status: "Saved" (green dot), "Unsaved changes" (amber dot), "Saving..." (spinner)
- [ ] Status updates reactively based on the editor store's dirty state
- [ ] "Unsaved changes" state triggers a browser `beforeunload` warning when navigating away

### 5.3 Markdown Preview Pane

<!-- canon:system:5.3 status:todo -->

<!-- canon:ticket:github:612 -->
#### Acceptance Criteria

- [ ] Toggle button to show side-by-side source and rendered preview
- [ ] Preview renders the spec markdown with the same styling as the spec view page
- [ ] Preview updates on each keystroke (debounced to 300ms)
- [ ] Split pane position adjustable via drag handle
- [ ] Default to source-only on narrow screens (<1024px)

### 5.4 Spec Validation Warnings

<!-- canon:system:5.4 status:todo -->

<!-- canon:ticket:github:613 -->
#### Acceptance Criteria

- [ ] Inline warnings displayed in the editor gutter or as a panel below the editor
- [ ] Warnings for: sections without `<!-- canon:system:N status:... -->` comments, unchecked ACs in sections marked `done`, frontmatter missing required fields (`title`, `status`)
- [ ] Warnings are non-blocking — the user can still save
- [ ] Warning count shown in the toolbar (e.g., "3 warnings")

### 5.5 Quick-Create from Dashboard

<!-- canon:system:5.5 status:todo -->

<!-- canon:ticket:github:614 -->
#### Acceptance Criteria

- [ ] "+ New Spec" button on the Explorer dashboard navigates to the editor new-spec flow
- [ ] If only one repo is available, skip the repo selection and go directly to the template
- [ ] If multiple repos, show a repo picker modal before navigating to the editor

## 6. Global UX Polish

<!-- canon:system:6 status:todo -->

<!-- canon:ticket:github:615 -->
Cross-cutting UX improvements that affect the entire app.

### 6.1 Skeleton Loading States

<!-- canon:system:6.1 status:todo -->

<!-- canon:ticket:github:616 -->
#### Acceptance Criteria

- [ ] Replace `LoadingSpinner` with contextual skeleton loaders on: Tasks (skeleton table rows), Explorer (skeleton cards), Analytics (skeleton chart placeholders), Editor (skeleton file list)
- [ ] Skeleton components use pulsing animation matching the current theme (dark/light)
- [ ] Skeleton layout matches the final rendered layout to prevent content shift
- [ ] `LoadingSpinner` retained only for inline/small loading indicators (e.g., button loading state)

### 6.2 Purposeful Empty States

<!-- canon:system:6.2 status:todo -->

<!-- canon:ticket:github:617 -->
#### Acceptance Criteria

- [ ] Every page has a designed empty state with: an icon or illustration, a brief explanation, a primary CTA button
- [ ] Tasks empty: "All caught up — no open tasks" (when filtered) or "Create your first spec to generate tasks" (when no specs exist)
- [ ] Search empty: "No specs match your search" with a "Clear filters" button
- [ ] Analytics empty: "Not enough data yet — Canon needs at least 7 days of activity to compute health scores"

### 6.3 Responsive Layout

<!-- canon:system:6.3 status:todo -->

<!-- canon:ticket:github:618 -->
#### Acceptance Criteria

- [ ] Tables (Tasks, Explorer) collapse to stacked card layouts on screens <768px
- [ ] Top nav collapses to a hamburger menu on screens <640px
- [ ] Filter dropdowns stack vertically on mobile
- [ ] Charts in Analytics resize gracefully (already handled by Chart.js responsive option — verify)
- [ ] Editor hides preview pane on screens <1024px (source-only default)

### 6.4 Toast Notification System

<!-- canon:system:6.4 status:todo -->

<!-- canon:ticket:github:619 -->
#### Acceptance Criteria

- [ ] Global toast component renders in a fixed position (top-right)
- [ ] Toast types: success (green), error (red), info (blue), warning (amber)
- [ ] Toasts auto-dismiss after 5 seconds with a progress bar; can be manually dismissed
- [ ] Exposed via a composable: `useToast().success('Spec saved')`, `useToast().error('Failed to sync')`
- [ ] Toasts stack vertically when multiple are active (max 3 visible, oldest dismissed first)

### 6.5 Keyboard Shortcuts

<!-- canon:system:6.5 status:todo -->

<!-- canon:ticket:github:620 -->
#### Acceptance Criteria

- [ ] `/` or `Cmd+K` focuses the global search input
- [ ] `g t` (go-to Tasks), `g a` (go-to Analytics), `g e` (go-to Editor) — vim-style two-key combos
- [ ] `Escape` closes any open modal, expanded card, or inline detail panel
- [ ] Keyboard shortcuts suppressed when focus is inside a text input or the editor
- [ ] `?` shows a keyboard shortcuts help modal listing all available shortcuts

## 7. Technical Design

<!-- canon:system:7 status:draft -->

### 7.1 Component Architecture

New components to create:

| Component | Location | Purpose |
|-----------|----------|---------|
| `TasksGroupedView.vue` | `components/tasks/` | Spec-grouped task list |
| `TasksBoardView.vue` | `components/tasks/` | Kanban column layout |
| `TaskDetailPanel.vue` | `components/tasks/` | Inline AC expansion |
| `SpecCardExpanded.vue` | `components/dashboard/` | Expandable spec card detail |
| `BreadcrumbAuto.vue` | `components/layout/` | Route-aware breadcrumb generator |
| `SkeletonTable.vue` | `components/common/` | Skeleton loader for tables |
| `SkeletonCard.vue` | `components/common/` | Skeleton loader for cards |
| `EmptyState.vue` | `components/common/` | Reusable empty state with icon + CTA |
| `ToastContainer.vue` | `components/common/` | Global toast notification container |
| `Toast.vue` | `components/common/` | Individual toast component |
| `ShortcutsModal.vue` | `components/common/` | Keyboard shortcuts help modal |
| `MarkdownPreview.vue` | `components/editor/` | Rendered markdown preview pane |
| `ValidationPanel.vue` | `components/editor/` | Spec validation warnings panel |

Modified components:

| Component | Change |
|-----------|--------|
| `AppNav.vue` | Add active page indicator, responsive hamburger |
| `SpecCard.vue` | Add expand chevron, progress bar, hover actions |
| `TasksView.vue` | Add view toggle, use grouped view as default |
| `EditorView.vue` | Add empty state logic, autosave indicator |
| `EditorLayout.vue` | Add preview pane toggle, validation panel |
| `App.vue` | Mount `ToastContainer` globally |

### 7.2 API Changes

The Tasks API needs one enhancement:

- `GET /app/api/tasks` should include `acceptance_criteria` in the response when `?expand=acs` query param is passed (for inline AC expansion). This avoids fetching the full spec just to show ACs.

No other backend API changes required — all other improvements are frontend-only.

### 7.3 Composables

| Composable | Purpose |
|------------|---------|
| `useToast()` | Global toast state management (provide/inject pattern) |
| `useKeyboardShortcuts()` | Register and handle keyboard shortcuts |
| `useViewPreference(key)` | Persist view toggle state to localStorage |

## 8. Rollout Plan

<!-- canon:system:8 status:draft -->

### Phase 1: Foundation (§6 Global UX)
1. Toast notification system (6.4)
2. Skeleton loaders (6.1)
3. Empty state component (6.2)
4. Keyboard shortcuts (6.5)

### Phase 2: Navigation (§4)
5. Breadcrumbs (4.1)
6. Active page indicator (4.2)
7. Cross-linking (4.3)

### Phase 3: Tasks Board (§2)
8. Grouped view (2.1)
9. View toggle (2.2)
10. Inline AC expansion (2.3)
11. Ticket link badges (2.4)

### Phase 4: Explorer & Editor (§3, §5)
12. Expandable spec cards (3.1, 3.2)
13. Sticky filter bar (3.3)
14. Editor empty state fix (5.1)
15. Autosave indicator (5.2)
16. Markdown preview (5.3)
17. Validation warnings (5.4)
18. Quick-create flow (5.5)

### Phase 5: Polish (§4.4, §6.3)
19. Spec-level sub-navigation (4.4)
20. Responsive layout (6.3)

## 9. Open Questions

- Should the Tasks board view support drag-and-drop status changes that write back to the spec file via the editor API? (Currently proposed as read-only.)
- Should keyboard shortcuts be configurable, or is a fixed set sufficient for v1?
- Should the Tasks page support assigning sections to users (requires a new `assignee` field in spec comments)?
- Should the Editor validation warnings run client-side only, or also call a server-side validation endpoint?
