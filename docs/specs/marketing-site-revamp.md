---
title: "Marketing Site Revamp"
status: done
owner: ng
team: platform
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-03-03
tags: [frontend, marketing, seo, vue]
---

# Marketing Site Revamp

Migrate the landing page from a monolithic Jinja2 HTML template into the Vue 3 SPA, rewrite the messaging to position Canon as a spec-driven development platform (not just documentation tooling), add missing sections (CLI showcase, interactive demo, pricing), and ensure SEO parity via build-time prerendering.

## 1. Background

The current marketing site is a single 1,247-line HTML file (`templates/landing.html`) with ~850 lines of inline CSS. It was written as a quick landing page and has several problems:

- **Stale messaging**: Positions Canon primarily as a documentation tool. The product has evolved into a spec-driven development platform with a CLI, MCP integration, Claude Code skills, ticket sync, and agent-assisted verification.
- **Stale content**: References deprecated infrastructure (PostgreSQL + pgvector, GCP Vertex AI) in setup instructions.
- **No build tooling**: Inline CSS can't use Tailwind, no component reuse, no minification.
- **No analytics**: Landing page lacks PostHog tracking (the Vue app has it).
- **Missing sections**: No CLI showcase, no interactive demo, no pricing/plans, no updated screenshots.
- **Maintenance burden**: Changes require editing raw HTML rather than composable Vue components.

Moving into the Vue SPA with prerendering gives us: Tailwind CSS, component reuse with the dashboard, PostHog analytics, and the ability to iterate faster on marketing content.

## 2. Migrate to Vue SPA with Prerendering

<!-- specwright:system:2 status:done -->

Move the landing page from `templates/landing.html` into the Vue 3 frontend as a prerendered route.

### 2.1 Vue Route & Layout

Create a new `/` route in the Vue router that uses a dedicated `MarketingLayout` (no authenticated nav/sidebar). The layout should include:

- Sticky nav with wordmark, anchor links (How It Works, Capabilities, Pricing), Dashboard link, GitHub link, and Install CTA
- Theme toggle (light/dark/system) matching the existing implementation
- Mobile hamburger menu
- Footer with links to self-hosting guide, GitHub, and canonhq.co

### 2.2 Build-Time Prerendering (SEO)

Use `vite-ssg` (or `vite-plugin-ssr-prerender`) to generate static HTML for the landing page at build time. This ensures:

- Full HTML content in the initial response (no JS required for crawlers)
- Proper `<title>`, `<meta description>`, Open Graph, and Twitter Card tags
- Zero runtime cost — the prerendered HTML is served directly by FastAPI

The FastAPI route at `GET /` serves the SPA shell with injected meta tags and session data. If the SPA is not built, it falls back to the Jinja2 template.

### Acceptance Criteria

- [x] Landing page renders at `/` as a Vue route with `MarketingLayout`
<!-- specwright:realized-in:PR#104 file:frontend/src/views/LandingView.vue -->
<!-- specwright:realized-in:PR#104 file:frontend/src/router/index.ts -->
- [ ] `vite-ssg` (or equivalent) generates static HTML at build time with full page content
- [x] HTML includes `<title>`, `<meta name="description">`, `og:title`, `og:description`, `og:image`, `twitter:card` tags
<!-- specwright:realized-in:PR#104 file:src/specwright/web/routes.py -->
- [x] FastAPI serves the prerendered HTML at `GET /` (replaces the Jinja2 template route)
- [x] Theme toggle works (light/dark/system) with `localStorage` persistence
<!-- specwright:realized-in:PR#104 file:frontend/src/components/marketing/MarketingNav.vue -->
- [x] Mobile nav works with hamburger menu
- [ ] Page loads with zero layout shift (fonts preloaded, critical CSS inlined by Vite)

## 3. Rewrite Hero & Messaging

<!-- specwright:system:3 status:done -->

Reposition Canon from "documentation that keeps up" to a spec-driven development platform. The new messaging should convey:

- **Specs are the source of truth** for what you're building
- **Agents verify** that code matches specs
- **Tickets, PRs, and docs stay in sync** automatically
- **Works in your existing tools** (GitHub, CLI, Claude Code, Cursor)

### 3.1 Hero Section

New hero should include:

- Tagline that positions as a platform, not just docs (e.g., "Spec-driven development, automated.")
- Subtitle explaining the value proposition in one sentence
- Two CTAs: "Install on GitHub" (primary) and "View Demo" (secondary, scrolls to interactive demo)
- Animated or interactive element below the hero (see Section 5 for the demo)

### 3.2 Problem / Solution

Update the comparison cards:

- **Without Canon**: Focus on the gap between specs and reality — specs drift, PRs lack context, nobody knows what's shipped vs. planned
- **With Canon**: Agents bridge the gap — specs verified against code, PRs analyzed against all docs, tickets auto-synced, coverage dashboards

### Acceptance Criteria

- [x] Hero tagline positions Canon as a spec-driven development platform
<!-- specwright:realized-in:PR#104 file:frontend/src/components/marketing/HeroSection.vue -->
- [x] Subtitle explains the value proposition in one clear sentence
- [x] Two CTAs: primary (Install on GitHub) and secondary (scroll to demo)
- [x] Problem/Solution cards updated with current product positioning
<!-- specwright:realized-in:PR#104 file:frontend/src/components/marketing/ProblemSolution.vue -->
- [x] No references to deprecated infrastructure (pgvector, Vertex AI, Voyage AI)

## 4. CLI Showcase Section

<!-- specwright:system:4 status:done -->

Add a new section showcasing the `canon` CLI as a first-class developer tool. This is a major capability that the current landing page doesn't mention at all.

### 4.1 Content

Show the CLI workflow in a terminal-style mockup:

```
$ canon setup
  Created docs/specs/_template.md
  Created CANON.yaml

$ canon plan docs/specs/payments-overhaul.md
  Payments Overhaul — 3 sections, 9 acceptance criteria

  Section 3.2 Retry Logic         [todo]    3 ACs
  Section 3.3 Idempotency Keys    [todo]    4 ACs
  Section 4.1 Monitoring           [todo]    2 ACs

$ canon verify docs/specs/payments-overhaul.md
  Section 3.2 Retry Logic
    AC1 Exponential backoff       [realized]  src/payments/retry.ts:42
    AC2 Max 3 retries             [conflict]  code uses max 5
    AC3 Idempotency key preserved [not found]

$ canon status
  Payments Overhaul    ██████░░░░  62%  (5/8 ACs realized)
  Auth Migration       ██████████  100% (all ACs realized)
```

### 4.2 Claude Code Integration

Show the MCP + skills workflow side-by-side:

- Left: Terminal showing `/sw:verify`, `/sw:status`, `/sw:task` commands
- Right: Claude Code responding with spec context, verification results, task guidance

### Acceptance Criteria

- [x] Terminal mockup component shows realistic CLI output with syntax highlighting
<!-- specwright:realized-in:PR#104 file:frontend/src/components/marketing/CliShowcase.vue -->
- [x] At least 4 CLI commands demonstrated: `init`, `plan`, `verify`, `status`
- [x] Claude Code / MCP integration shown alongside CLI
- [x] Section positioned after the "How It Works" loop to show the developer experience

## 5. Interactive Demo

<!-- specwright:system:5 status:done -->

Replace the static PR comment mockup with an interactive, animated demonstration.

### 5.1 Animated PR Analysis

Create a step-by-step animation that shows:

1. A PR diff appears (code change)
2. Canon bot comment materializes with typing animation
3. Spec sections light up as realized/conflicting/pending
4. Action buttons appear (Update spec, Create doc PR, Reanalyze)

The animation should auto-play on scroll (intersection observer) and be replayable.

### 5.2 Screenshot Showcase

Update the tabbed screenshot section with current screenshots:

- **Dashboard**: Org overview with repos, specs, coverage
- **Search**: Full-text search with faceted filters
- **Editor**: Structured spec editor with AI actions
- **Tasks**: Task board with spec-driven work items

### Acceptance Criteria

- [x] PR analysis demo animates on scroll using IntersectionObserver
<!-- specwright:realized-in:PR#104 file:frontend/src/components/marketing/InteractiveDemo.vue -->
- [x] Animation shows: diff appears, bot comment types in, ACs evaluate, actions appear
- [x] Demo is replayable (replay button or scroll-triggered restart)
- [ ] Screenshot tabs updated with 4 views: Dashboard, Search, Editor, Tasks
- [x] Screenshots are current (taken from the live application)

## 6. Pricing Section

<!-- specwright:system:6 status:done -->

Add a pricing section with two tiers: self-hosted (free) and managed cloud.

### 6.1 Self-Hosted (Free)

- Open source, deploy on your infrastructure
- Helm chart for Kubernetes, Docker Compose for local
- Full feature set, no limits
- Community support via GitHub Issues

### 6.2 Managed Cloud (Coming Soon)

- Hosted by Gerner Ventures
- No infrastructure to manage
- Automatic updates
- Priority support + SLA
- "Join waitlist" CTA with email capture

### 6.3 Comparison Table

Feature comparison between self-hosted and managed, showing both tiers get the full feature set but managed adds convenience + support.

### Acceptance Criteria

- [x] Two pricing cards: Self-Hosted (free) and Managed Cloud (coming soon)
<!-- specwright:realized-in:PR#104 file:frontend/src/components/marketing/PricingSection.vue -->
- [x] Self-hosted card has "View Setup Guide" CTA linking to self-hosting docs
- [x] Managed cloud card has "Join Waitlist" CTA with email input
- [x] Feature comparison table shows full feature set for both tiers
- [x] "Coming Soon" badge on managed cloud card

## 7. Updated Capabilities & Integrations

<!-- specwright:system:7 status:done -->

Refresh the capabilities grid and integrations section to reflect the current product.

### 7.1 Capabilities

Update the 6 feature cards to accurately describe current capabilities:

1. **Spec Parser** — Structured markdown with frontmatter, sections, acceptance criteria, status tracking
2. **PR Analysis** — Claude agent analyzes diffs against all indexed docs, not just specs
3. **Spec Verification** — Code-aware AC realization checking via CLI and agent
4. **Ticket Sync** — Bidirectional sync with Jira, Linear, GitHub Issues
5. **Coverage Dashboard** — Org-wide spec coverage with per-repo, per-team breakdown
6. **CLI & Agent Skills** — `canon` CLI + Claude Code skills for spec-driven workflows

### 7.2 Integrations

Update to reflect actual integration status:

- **Source Control**: GitHub (native) — remove planned GitLab/Bitbucket unless actively planned
- **Tickets**: Jira, Linear, GitHub Issues (all shipped)
- **Dev Tools**: Claude Code (MCP + skills), Cursor (MCP) — both shipped
- **Observability**: PostHog (analytics + logs via OpenTelemetry) — shipped

### Acceptance Criteria

- [x] 6 capability cards reflect current product (not aspirational features)
<!-- specwright:realized-in:PR#104 file:frontend/src/components/marketing/CapabilitiesGrid.vue -->
- [x] Integration grid shows only shipped integrations (no "planned" unless actively in development)
<!-- specwright:realized-in:PR#104 file:frontend/src/components/marketing/IntegrationsGrid.vue -->
- [x] Each capability card links to relevant docs or demo section

## 8. Analytics & Performance

<!-- specwright:system:8 status:done -->

Ensure the new landing page has proper analytics tracking and meets performance targets.

### 8.1 PostHog Analytics

Track key events on the landing page:

- Page view with UTM parameters
- CTA clicks (Install, Dashboard, View Demo, Join Waitlist)
- Section scroll depth (which sections do visitors see?)
- Demo interaction (play/replay)
- Pricing tab switches
- Time on page

### 8.2 Performance

- Lighthouse score >= 90 for Performance, Accessibility, Best Practices, SEO
- First Contentful Paint < 1.5s
- Largest Contentful Paint < 2.5s
- Cumulative Layout Shift < 0.1
- Total bundle size for landing page < 100KB (excluding images)

### Acceptance Criteria

- [x] PostHog initialized on landing page with `pageview` event
- [x] CTA clicks tracked as PostHog events with labels
<!-- specwright:realized-in:PR#104 file:frontend/src/components/marketing/CtaSection.vue -->
- [x] Section visibility tracked via IntersectionObserver
- [ ] Lighthouse Performance score >= 90
- [ ] Lighthouse SEO score >= 95
- [ ] LCP < 2.5s on simulated 4G

## 9. Design

### 9.1 Architecture

```
frontend/src/
  layouts/
    MarketingLayout.vue    # Nav + footer for public pages
  views/
    LandingView.vue        # Main landing page (assembles sections)
  components/
    marketing/
      HeroSection.vue
      ProblemSolution.vue
      FeedbackLoop.vue
      CliShowcase.vue
      InteractiveDemo.vue
      CapabilitiesGrid.vue
      DxSection.vue
      PricingSection.vue
      IntegrationsGrid.vue
      SetupSteps.vue
      CtaSection.vue
      TerminalMockup.vue   # Reusable terminal display component
      ScreenshotTabs.vue   # Tabbed screenshot browser mockup
```

### 9.2 Styling

Use Tailwind CSS (already in the Vue app) with the existing brand.css design tokens. Extract key values into `tailwind.config.ts` theme extensions so Tailwind classes align with the design system.

### 9.3 SEO Integration

```
vite.config.ts additions:
  - Proxy backend routes to :3000 (not :8000)
  - Proxy /static for backend-served assets

FastAPI changes:
  - GET / serves SPA shell via _serve_public_spa with runtime meta injection
  - Falls back to templates/landing.html when SPA not built
  - Keep brand.css + screenshots in /static/
```

### 9.4 Waitlist Backend

Add a minimal endpoint for the managed cloud waitlist:

```
POST /api/waitlist
  Body: { "email": "..." }
  Response: 201 Created
  Storage: PostHog event (no database needed initially)
```

## 10. Rollout Plan

1. **Phase 1 — Scaffold**: Create Vue route, layout, and component structure. Migrate existing content into Vue components with Tailwind.
2. **Phase 2 — Content**: Rewrite messaging, add CLI showcase, update capabilities/integrations.
3. **Phase 3 — Interactive**: Build animated PR demo, update screenshots, add pricing section.
4. **Phase 4 — SEO & Analytics**: Add vite-ssg prerendering, PostHog events, meta tags.
5. **Phase 5 — Polish**: Lighthouse audit, mobile QA, remove old `templates/landing.html`.

## 11. Resolved Questions

- **Docs route**: Create dedicated `/docs` public routes (not just a link to the GitHub self-hosting guide)
- **Changelog**: Yes, add a `/changelog` page linked from the footer
- **Waitlist**: PostHog event capture only for now (no mailing list integration)
- **Social proof**: None available yet — skip testimonials section for v1
