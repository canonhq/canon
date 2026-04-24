---
title: "Web App UI/UX Overhaul"
status: in_progress
owner: ng
team: platform
ticket_project: canonhq/canon
created: 2026-04-23
updated: 2026-04-23
tags: [frontend, ux, ui, vue, design-system, navigation, sidebar]
---

# Web App UI/UX Overhaul

Overhaul the Canon web app's visual design and navigation architecture to
deliver a first-class, crisp product experience. Replace the flat top-nav with
a persistent sidebar, consolidate the two conflicting design systems (warm
amber vs teal/cyan) into one unified warm-amber brand, refresh component
styling, and update the landing page and Jinja2 fallback templates.

This spec covers the **visual and structural** overhaul. Functional UX
improvements (tasks board redesign, editor fixes, keyboard shortcuts) are
covered separately in `web-app-ux-polish.md`.

## 1. Background

<!-- canon:system:1 status:done -->

### Current state

The Canon web app has several visual and structural problems:

- **Navigation is a flat horizontal bar** with text links (Explorer, Tasks,
  Sync, Analytics, Editor, Settings). No icons, no grouping, no spatial
  memory. Users forget where they are.
- **Two conflicting design systems**: `brand.css` defines warm amber tokens
  (Fraunces/DM Sans) while Jinja2 templates use Inter/Space Grotesk with
  teal/cyan accent gradients. The Vue SPA has warm tokens in `style.css`
  but some components still reference teal patterns.
- **Generic card/table styling** with minimal hierarchy — bordered divs that
  all look the same regardless of content importance.
- **No persistent sidebar** — every navigation action requires reading the
  top bar and clicking text links.
- **Layout feels like a blog, not a product** — `max-w-7xl` centered
  container with a thin accent bar.

### Design references

- Linear: speed, density, clean sidebar
- Vercel: minimalism, clear hierarchy
- Notion: warm tones, sidebar navigation, clarity
- GitHub: familiarity, information density

## 2. Sidebar Navigation

<!-- canon:system:2 status:todo -->

Replace the flat top-nav with a persistent left sidebar and a slim top bar.

### 2.1 Sidebar Component

<!-- canon:system:2.1 status:todo -->

#### Acceptance Criteria

- [ ] Persistent left sidebar (`w-60` / 240px) visible on all authenticated pages
- [ ] Sidebar header contains: Canon wordmark/logo and org switcher dropdown
- [ ] Main nav section with icon + label for each page: Explorer, Tasks, Sync, Analytics, Editor
- [ ] Bottom nav section with: Settings, Admin (visible only to users with `specs:admin` permission)
- [ ] Footer section with: theme toggle, user email, logout link
- [ ] Active nav item has a visible highlight (accent background or left border)
- [ ] Active state derived from current route name, not manual props
- [ ] Nav items use SVG icons (inline, not icon library) for each page

### 2.2 Sidebar Collapse

<!-- canon:system:2.2 status:todo -->

#### Acceptance Criteria

- [ ] Collapse toggle button in sidebar header (chevron icon)
- [ ] Collapsed state: `w-14` (56px), icon-only, no labels
- [ ] Collapsed state shows tooltip on hover with nav item label
- [ ] Collapse state persisted to localStorage via `useViewPreference`
- [ ] Keyboard shortcut `[` toggles sidebar collapse
- [ ] Smooth transition animation (width + opacity on labels)

### 2.3 Top Bar

<!-- canon:system:2.3 status:todo -->

#### Acceptance Criteria

- [ ] Slim top bar spans the content area (right of sidebar)
- [ ] Left side: breadcrumb component (route-aware)
- [ ] Right side: global search input, user avatar/initials
- [ ] Height: `h-14` (56px), matching sidebar header height
- [ ] Border-bottom separator, backdrop-blur background

### 2.4 Mobile Sidebar

<!-- canon:system:2.4 status:todo -->

#### Acceptance Criteria

- [ ] On screens < 768px, sidebar is hidden by default
- [ ] Hamburger button in a mobile top bar triggers slide-out sidebar overlay
- [ ] Overlay has backdrop dim (click outside closes)
- [ ] Sidebar slides in from left with transition
- [ ] Clicking a nav item closes the sidebar overlay
- [ ] Mobile top bar shows: hamburger, Canon wordmark, search icon

### 2.5 App Layout Shell

<!-- canon:system:2.5 status:todo -->

#### Acceptance Criteria

- [ ] `App.vue` renders: sidebar (left) + content area (right) for authenticated pages
- [ ] Content area has its own scroll context (sidebar stays fixed)
- [ ] No `max-w-7xl` wrapper in App.vue — each page sets its own max-width
- [ ] Marketing/public pages bypass sidebar layout entirely (unchanged behavior)
- [ ] Footer moves inside the content area scroll context

## 3. Design System Consolidation

<!-- canon:system:3 status:todo -->

Unify the warm-amber design system across SPA and Jinja2 templates.

### 3.1 Color Token Cleanup

<!-- canon:system:3.1 status:todo -->

#### Acceptance Criteria

- [ ] All teal/cyan accent references removed from `style.css`
- [ ] All teal/cyan gradient references removed from Jinja2 `base.html`
- [ ] Accent color is saffron/amber (`#D4880A` / `accent-500`) everywhere
- [ ] Progress bars use warm gradient (amber-400 → accent-500) instead of teal → cyan
- [ ] Top accent bar uses `bg-accent-500` (solid saffron, not gradient)

### 3.2 Typography Alignment

<!-- canon:system:3.2 status:todo -->

#### Acceptance Criteria

- [ ] Jinja2 templates load DM Sans, Fraunces, IBM Plex Mono (matching SPA)
- [ ] Remove Inter, Space Grotesk, JetBrains Mono references from `base.html`
- [ ] Font family tokens in `base.html` Tailwind config match `style.css` `@theme` values
- [ ] Display headings use `font-display` (Fraunces) consistently across both systems

### 3.3 Jinja2 Template Brand Update

<!-- canon:system:3.3 status:todo -->

#### Acceptance Criteria

- [ ] `base.html` nav uses warm background tokens (not `bg-gray-50`/`bg-[#111827]`)
- [ ] Nav wordmark uses saffron gradient (not teal → cyan)
- [ ] Form inputs and selects use warm border/focus colors
- [ ] Cards use warm surface/border tokens
- [ ] Footer branding uses saffron accent

## 4. Component Design Refresh

<!-- canon:system:4 status:todo -->

Update shared components for a crisper, more polished visual style.

### 4.1 Card Styling

<!-- canon:system:4.1 status:todo -->

#### Acceptance Criteria

- [ ] Cards use `rounded-xl` (was `rounded-lg`)
- [ ] Cards have subtle left-border accent on hover (`border-l-2 border-accent-500`)
- [ ] Increased internal padding (`p-5` → `p-6`)
- [ ] Card hover state: slight shadow elevation + border color shift
- [ ] Repo cards and spec cards share consistent base styling

### 4.2 Status Badges

<!-- canon:system:4.2 status:todo -->

#### Acceptance Criteria

- [ ] Status badges show a colored dot (6px circle) + text label
- [ ] Dot colors match status: done=emerald, in_progress=amber, blocked=red, draft=slate, todo=blue
- [ ] Badge background is subtle (10% opacity of status color)
- [ ] Dark mode badges use warm-shifted status colors (already defined in style.css)

### 4.3 Progress Indicators

<!-- canon:system:4.3 status:todo -->

#### Acceptance Criteria

- [ ] Progress bars are `h-2` with `rounded-full`
- [ ] Fill color: warm gradient `from-accent-400 to-accent-500`
- [ ] Track color: warm slate-200 (light) / slate-700 (dark)
- [ ] Mini progress bars on spec cards use `h-1.5`

### 4.4 Empty States & Skeletons

<!-- canon:system:4.4 status:todo -->

#### Acceptance Criteria

- [ ] Empty state illustrations use warm accent color (not teal)
- [ ] Skeleton loaders match new card border-radius (`rounded-xl`)
- [ ] Skeleton pulse animation uses warm tones

## 5. Page Layout Updates

<!-- canon:system:5 status:todo -->

Update all page views to work within the sidebar layout.

### 5.1 Content Area Width

<!-- canon:system:5.1 status:todo -->

#### Acceptance Criteria

- [ ] Dashboard: `max-w-6xl` centered within content area
- [ ] Tasks: `max-w-6xl` centered
- [ ] Analytics: `max-w-7xl` centered (charts need width)
- [ ] Settings: `max-w-3xl` centered (forms)
- [ ] Editor: full width (no max-width constraint)
- [ ] Profile: `max-w-2xl` centered
- [ ] Sync: `max-w-6xl` centered
- [ ] All pages have consistent horizontal padding (`px-6 lg:px-8`)

### 5.2 Admin Section

<!-- canon:system:5.2 status:todo -->

#### Acceptance Criteria

- [ ] Admin tab bar remains as in-page tabs (not moved to sidebar)
- [ ] Admin nav item in sidebar links to `/app/admin`
- [ ] Admin section content area matches other page widths

## 6. Landing Page Refresh

<!-- canon:system:6 status:todo -->

Update the landing page and marketing components for brand consistency.

### 6.1 Jinja2 Landing Page

<!-- canon:system:6.1 status:todo -->

#### Acceptance Criteria

- [ ] Hero gradient uses saffron/amber (not teal)
- [ ] CTA buttons use `brand-btn-primary` (saffron background)
- [ ] Solution card gradient uses warm amber tones
- [ ] Step number circles use saffron gradient
- [ ] All accent colors reference `--color-accent` CSS variables

### 6.2 Vue Marketing Components

<!-- canon:system:6.2 status:todo -->

#### Acceptance Criteria

- [ ] `HeroSection.vue` uses warm amber gradient for headline accent
- [ ] `MarketingNav.vue` wordmark uses saffron gradient
- [ ] `PricingSection.vue` featured plan card uses saffron accent
- [ ] All marketing components audited for teal/cyan — replaced with saffron/amber
- [ ] Marketing footer matches app footer branding

## 7. Technical Design

<!-- canon:system:7 status:draft -->

### New components

| Component | Location | Purpose |
|-----------|----------|---------|
| `AppSidebar.vue` | `components/layout/` | Persistent left sidebar |
| `AppTopBar.vue` | `components/layout/` | Slim top bar with breadcrumb + search |

### Modified components

| Component | Change |
|-----------|--------|
| `App.vue` | Sidebar + content area layout shell |
| `AppNav.vue` | Deprecated (replaced by AppSidebar + AppTopBar) |
| `MobileMenu.vue` | Slide-out sidebar overlay |
| `OrgSwitcher.vue` | Moved into sidebar header |
| `SearchBar.vue` | Moved into top bar |
| `ThemeToggle.vue` | Moved into sidebar footer |
| `StatusBadge.vue` | Dot + text styling |
| `SpecProgressIndicator.vue` | Warm gradient |
| `RepoCard.vue` | Card redesign |
| `SpecCardExpanded.vue` | Card redesign |

### Composables reused

- `useViewPreference` — sidebar collapse state persistence
- `useKeyboardShortcuts` — sidebar collapse shortcut (`[`)

### No backend changes required

This is a pure frontend overhaul. All API endpoints remain unchanged.

## 8. Rollout Plan

<!-- canon:system:8 status:draft -->

### Phase 1: Design System Foundation (S3.1, S3.2, S3.3)
### Phase 2: Sidebar Navigation (S2.1–S2.5)
### Phase 3: Component Refresh (S4.1–S4.4)
### Phase 4: Page Layouts (S5.1–S5.2)
### Phase 5: Landing Page & Templates (S6.1–S6.2)
