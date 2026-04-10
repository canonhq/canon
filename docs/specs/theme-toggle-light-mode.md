---
title: Theme Toggle Fix & Light Mode UI Polish
status: done
owner: "@nick"
team: frontend
tags: [ui, theme, light-mode, marketing, app]
---

# Theme Toggle Fix & Light Mode UI Polish

## Background

The app supports three theme modes (system, light, dark) via a Pinia store and Tailwind `dark:` classes. The dark mode UI is polished with a cohesive deep-navy identity. However:

1. The theme toggle cycles through modes without telling the user which mode is active
2. Light mode uses stock Tailwind grays with no brand identity — it feels like an afterthought
3. Surface color tokens (`--color-surface`, `--color-surface-alt`, `--color-surface-elevated`) only have dark mode values

## 1. Theme Toggle UX Improvement

<!-- canon:system:1 status:done -->

Enhance the 3-way theme toggle button with a tooltip so users know which mode is active and what the effective appearance is.

### Acceptance Criteria

- [x] Tooltip shows on hover with the active mode label: "Light", "Dark", or "System (light)" / "System (dark)"
- [x] Tooltip displays the effective appearance when in system mode (e.g., "System (dark)" if OS prefers dark)
- [x] Toggle continues to cycle system → light → dark → system on click
- [x] Tooltip has appropriate styling for both light and dark modes
- [x] Accessible: tooltip content available via `aria-label` on the button

## 2. Light Mode Surface Tokens

<!-- canon:system:2 status:done -->

Define light-mode equivalents for the surface color tokens so components can use consistent brand-tinted backgrounds instead of stock grays.

### Acceptance Criteria

- [x] Add `--color-surface-light`, `--color-surface-light-alt`, `--color-surface-light-elevated` to the Tailwind `@theme` block (or equivalent approach)
- [x] Light surfaces use subtle brand-tinted whites/grays (not pure gray-50/white) to give light mode a cohesive identity
- [x] Update `style.css` `--theme-bg`, `--theme-bg-alt`, `--theme-bg-elevated` CSS vars to use the new tokens

<!-- canon:ticket:github:431 -->
## 3. Marketing Page Light Mode Polish

<!-- canon:system:3 status:in_progress -->

Improve light mode appearance across all marketing/landing page components.

### Acceptance Criteria

- [x] Hero section has a more visible light-mode gradient (stronger accent-tinted bg)
- [x] Card components (`ProblemSolution`, `CapabilitiesGrid`, `IntegrationsGrid`, `PricingSection`) use brand-tinted light backgrounds instead of `bg-gray-50`
- [x] Terminal mockups (`TerminalMockup`, `CliShowcase`) have a distinct light-mode identity (e.g., light chrome with subtle brand tint)
- [ ] Section alternation creates visual rhythm in light mode (alternating subtle background tints)
- [x] CTA buttons and secondary buttons have clear visual hierarchy in light mode
- [x] Footer maintains readable contrast in light mode

## 4. App Pages Light Mode Polish

<!-- canon:system:4 status:done -->

Improve light mode appearance across the logged-in app views.

### Acceptance Criteria

- [x] App nav (`AppNav`) has sufficient visual weight in light mode (not washed out)
- [x] Dashboard cards and repo list items have clear visual boundaries in light mode
- [x] Spec detail view sections, AC checkboxes, and status badges are clearly readable
- [x] Search view results and facet pills have sufficient contrast
- [x] Form inputs (search bar, editor) have clear borders and focus states in light mode
- [x] Status badges (`style.css`) maintain good contrast in both modes

## 5. Spec Prose & Code Blocks in Light Mode

<!-- canon:system:5 status:done -->

Ensure rendered spec content (`.spec-prose`) looks polished in light mode.

### Acceptance Criteria

- [x] Code blocks (`pre`, `code`) have a distinct but subtle light background (brand-tinted, not stock gray-100)
- [x] Blockquotes have visible left border and appropriate text contrast
- [x] Table borders and header styling are clear in light mode
- [x] Search highlights (`mark`) are clearly visible without being garish

## 6. Tailwind v4 Class-Based Dark Variant

<!-- canon:system:6 status:done -->

Register class-based dark mode in Tailwind CSS v4. The earlier sections of this
spec assumed `dark:*` utilities respond to the `.dark` class the theme store
toggles on `<html>`, but that assumption is only true on Tailwind v3 (or v4
with an explicit `@custom-variant` declaration). On v4 the default strategy is
`@media (prefers-color-scheme: dark)`, so the user-facing toggle silently did
nothing across the marketing site *and* the logged-in app — every `dark:bg-*`
and `dark:text-*` utility was wired to the OS preference instead of the Pinia
theme store. The docs site was unaffected because it's a separate VitePress
build with its own theme system.

### Acceptance Criteria

- [x] `frontend/src/style.css` declares `@custom-variant dark (&:where(.dark, .dark *));` immediately after `@import "tailwindcss";`
- [x] Clicking the `ThemeToggle` in `MarketingNav.vue` visibly swaps light/dark across all marketing sections (hero, problem/solution, capabilities, pricing, CTA, footer)
- [x] Clicking the `ThemeToggle` in `AppNav.vue` visibly swaps light/dark across the logged-in app chrome, dashboard, admin views, and spec/doc views
- [x] `localStorage['sw-theme']` persistence continues to work across reloads
- [x] System mode still follows the OS `prefers-color-scheme` change event

## 7. Auth Flow Views Use Theme-Aware Styling

<!-- canon:system:7 status:done -->

Replace scoped `<style>` blocks on the auth-flow views (`NoOrgView`,
`LoginView`, `ChooseOrgView`) with Tailwind `dark:*` utilities so they respond
to the theme toggle like the rest of the app. Previously these three views
used undefined CSS variables (`var(--color-bg, #0a0a0a)`,
`var(--color-surface, #111)`, etc.) with hardcoded dark fallbacks — the
variable names were never defined anywhere, so the fallbacks always won and
the cards stayed dark in both modes, visibly clashing with the warm-parchment
light surface around them.

### Acceptance Criteria

- [x] `NoOrgView.vue` renders inside the standard `AppNav` + `<main>` chrome using `bg-surface-light-elevated dark:bg-surface-alt`, `border-border-light dark:border-slate-700`, and `text-slate-*` / `dark:text-slate-*` utilities matching `WelcomeChecklist.vue`
- [x] `ChooseOrgView.vue` uses the same token set as `NoOrgView.vue`
- [x] `LoginView.vue` keeps its own full-bleed wrapper (it's a public route outside `AppNav`) but uses `bg-surface-light dark:bg-surface` for the page background and the same card tokens for the panel
- [x] No scoped `<style>` blocks remain in any of the three views
- [x] No references to undefined `--color-bg`, `--color-surface`, `--color-text`, `--color-bg-primary`, `--color-bg-secondary`, `--color-bg-hover`, or `--color-border-hover` variables remain in `frontend/src/`
