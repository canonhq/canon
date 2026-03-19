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

<!-- specwright:system:1 status:done -->

Enhance the 3-way theme toggle button with a tooltip so users know which mode is active and what the effective appearance is.

### Acceptance Criteria

- [x] Tooltip shows on hover with the active mode label: "Light", "Dark", or "System (light)" / "System (dark)"
- [x] Tooltip displays the effective appearance when in system mode (e.g., "System (dark)" if OS prefers dark)
- [x] Toggle continues to cycle system → light → dark → system on click
- [x] Tooltip has appropriate styling for both light and dark modes
- [x] Accessible: tooltip content available via `aria-label` on the button

## 2. Light Mode Surface Tokens

<!-- specwright:system:2 status:done -->

Define light-mode equivalents for the surface color tokens so components can use consistent brand-tinted backgrounds instead of stock grays.

### Acceptance Criteria

- [x] Add `--color-surface-light`, `--color-surface-light-alt`, `--color-surface-light-elevated` to the Tailwind `@theme` block (or equivalent approach)
- [x] Light surfaces use subtle brand-tinted whites/grays (not pure gray-50/white) to give light mode a cohesive identity
- [x] Update `style.css` `--theme-bg`, `--theme-bg-alt`, `--theme-bg-elevated` CSS vars to use the new tokens

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

<!-- specwright:system:4 status:done -->

Improve light mode appearance across the logged-in app views.

### Acceptance Criteria

- [x] App nav (`AppNav`) has sufficient visual weight in light mode (not washed out)
- [x] Dashboard cards and repo list items have clear visual boundaries in light mode
- [x] Spec detail view sections, AC checkboxes, and status badges are clearly readable
- [x] Search view results and facet pills have sufficient contrast
- [x] Form inputs (search bar, editor) have clear borders and focus states in light mode
- [x] Status badges (`style.css`) maintain good contrast in both modes

## 5. Spec Prose & Code Blocks in Light Mode

<!-- specwright:system:5 status:done -->

Ensure rendered spec content (`.spec-prose`) looks polished in light mode.

### Acceptance Criteria

- [x] Code blocks (`pre`, `code`) have a distinct but subtle light background (brand-tinted, not stock gray-100)
- [x] Blockquotes have visible left border and appropriate text contrast
- [x] Table borders and header styling are clear in light mode
- [x] Search highlights (`mark`) are clearly visible without being garish
