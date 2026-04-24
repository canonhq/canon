---
title: Changelog
---

# Changelog

Notable changes to Canon, grouped by minor release.

## v1.57

### Features

- Sync UI for ticket mapping and sync management
- Fix UserPromptSubmit hook blocking fresh repos + add canon-interrogate skill

### Bug Fixes

- Address review findings — grep fallback, variable naming, test gaps (plugin)

## v1.56

### Features

- Automatic Jira OAuth token refresh on 401 and via cron
- Add refresh-tokens CronJob (every 30 min) to Helm chart

### Bug Fixes

- Disable refreshTokensCronJob in preview values (chart)

### Documentation

- Update CLAUDE.md with current project structure and gotchas

## v1.55

### Features

- CLI integration management, doctor command, and guided onboarding

### Bug Fixes

- Suppress misleading org_id warning for device-flow tokens (doctor)

## v1.54

### Features

- Plugin ecosystem Phase 2-3 — adapters, catalog, hooks, MCP tools, agents

### Bug Fixes

- Exclude non-package directories from sdist to stay under PyPI 100MB limit
- Allow bearer tokens without org_id to access org-scoped routes
- Resolve org_login from request URL when JWT lacks org_id

### Documentation

- Add extension system documentation pages and testing extensions locally guide

## v1.53

### Features

- Plugin ecosystem with extension system and Slack extraction

## v1.52

### Features

- Expand integration test coverage to 192 tests + fix 3 auth bugs

### Bug Fixes

- Sync missing OSS modules and guard cloud-only imports
- Fix choose-org page showing no orgs due to SPA intercepting JSON fetch
- Cast IPv4Address to str in audit event response (admin)
- Resolve ticket sync adapters using GitHub App token and DB credentials
- Env var / auth_profile credentials take precedence over installation token
- Add cancel-in-progress to Release & Publish workflow (ci)
- Skip reverse sync commit when file content is unchanged (cron)

## v1.51

### Features

- Canon plugin product polish + dev-to-PR evidence pipeline

### Bug Fixes

- PostHog reliability gaps — schema, JWT, instrumentation, security

## v1.50

### Features

- GitHub Actions Suite — 14 actions, 2 reusable workflows, full V1.2 spec

### Bug Fixes

- Upgrade to Sonnet 4.6 + dynamic prompt budgeting (agent)

## v1.49

### Features

- User & organization management — P0 admin spec implementation

### Bug Fixes

- Address review findings from admin UI PR

## v1.48

### Features

- Per-spec sync events with adapter tagging for ticket sync dashboard (observability)

## v1.47

### Features

- Apply tracked_cron to 6 missing crons + instrument device auth flow (observability)

## v1.46

### Features

- Centralize Jira/Linear sync through Canon backend

### Bug Fixes

- OIDC live-provider smoke harness, Basic auth at device endpoint, localhost issuer exception, CI job
- Robust parser for Claude analysis responses + structured failure reporting (agent)
- Fix Jira search endpoint and parser start_line off-by-one
- Stop pytest from spawning chromium tabs on every run (cli)

## v1.45

### Features

- Admin UI enhancements — user deactivation, org suspension, auth fixes

### Bug Fixes

- Enable GitHub/Google/email connections for CLI client (auth0)
- Resolve org in device auth flow for multi-org tenants
- Wire class-based dark mode in Tailwind v4 (ui)

## v1.44

### Features

- Super admin interface for platform management

### Bug Fixes

- Resolve org in device auth flow for multi-org tenants

### Documentation

- Add admin-actions spec (impersonation, deactivation, suspension)

## v1.43

### Features

- Development execution workflow skills for Canon plugin

### Bug Fixes

- Close auth bypass allowing any user to access any org

## v1.42

### Features

- Integration management UI with OAuth for Jira and Linear

## v1.41

### Bug Fixes

- Wire GitHub OAuth App into Auth0 social connection (infra)
- Import core infra into Terraform state (infra)

## v1.40

### Features

- Migrate Auth0 from gv-os to canonhq tenant (infra)

## v1.39

### Features

- Complete Slack product experience — 57 ACs across 9 systems

## v1.38

### Features

- Complete Slack App spec — 68/68 ACs implemented

## v1.37

### Features

- Implement /canon slash command handlers (slack)
- Web app UX polish

### Bug Fixes

- Add Helm repo before dependency build in publish workflow (ci)
- Fix Starlette Request handler instead of raw ASGI mount (slack)

### Documentation

- Fix Claude Code plugin installation instructions

## v1.36

### Features

- Add interactive Slack app (§2-§9)

### Documentation

- Add multi-org & personal account support spec

## v1.35

### Features

- Add LLM observability via PostHog $ai_generation events

### Bug Fixes

- Handle empty SMTP_PORT env var to prevent startup crash

## v1.34

### Features

- Multi-target forward sync with shadow ticket creation
- Cross-system drift detection for multi-target sync
- Configure multi-target routing rules in CANON.yaml
- Wire multi-target sync into push handler
- Make sync failures loud with PostHog tracking and detailed logging
- Auto-commit spec updates directly to default branch on merge

### Bug Fixes

- Prevent project_key mutation from bleeding into fallback path
- Use original file SHA for auto-commit to prevent data loss
- Log warning when section not found during shadow sync

## v1.33

### Features

- Add Stripe, SMTP, and Auth0 M2M secrets to Helm chart and deploy workflow

### Bug Fixes

- Add Zitadel Helm repo before dependency build in CI workflows

### Documentation

- Add web-app-ux-polish spec for Tasks, Explorer, Nav, Editor, and Global UX improvements

## v1.32

### Features

- Analytics dashboard with health score, events, and frontend
- Add Canon-owned infrastructure (Terraform + SaaS automation)
- Add GitHub API client integration tests (spec section 3)

### Bug Fixes

- Retry on stale SHA conflict (409) in reverse sync webhook processor
- Make 0002 migration idempotent when target column already exists
- Remove canon-github-tickets secret ref that breaks deploy

### Documentation

- Add spec for closing SDLC loop + multi-target ticket sync
- Expand slack-integration spec into full Slack app design
- Add analytics dashboard spec and infrastructure independence spec

## v1.31

### Bug Fixes

- Reduce PostHog log noise from opaque tokens and missing web_org
- Add comment-posting tools to Claude code review workflow
- Increase Claude code review max-turns from 15 to 25
- Make Claude code review more robust

### Documentation

- Expand infrastructure independence spec with Stripe, PostHog, Auth0 provisioning, and GitHub App sections

## v1.30

### Features

- Add changelog automation for docs site
- Add Auth0 M2M credentials to deploy and preview workflows

### Bug Fixes

- Detect opaque JWT tokens and add GitHub ticket sync Helm plumbing

### Documentation

- Add platform observability coverage spec
- Add infrastructure independence spec

## v1.29

### Features

- Complete user profile page spec

### Bug Fixes

- Strip libpq-only params (channel_binding) from asyncpg URLs
- Restore allowedTools for claude code review gh commands

## v1.28

### Features

- Add vite-ssg prerendering, SSG route serving, and integration tests

## v1.27

### Bug Fixes

- Set imagePullPolicy Always for preview deployments (helm)

### Documentation

- Add changelog automation spec
- Add preview environment Auth0 configuration spec
- Update SRE alerting spec section statuses

## v1.26

### Features

- Implement remaining OIDC migration + pricing gaps

### Bug Fixes

- Add lockfile check to pre-push hook
- Improve claude code review prompt with project-specific context
- Remove allowedTools override that blocked default claude review tools
- Remove inline comment tool from claude review to prevent comment spam
- Reduce claude code review noise with sticky comments and focused prompt
- Add helm dependency build to deploy, publish, and preview workflows
- Use core.hooksPath so git hooks work in worktrees automatically
- Use single event loop for all specs + fresh ticket sync (sync)

### Documentation

- Add infra enablement spec for billing, email, and auth0 m2m
- Add enterprise adoption and scale infrastructure specs
- Add SRE alerting & monitoring spec
- Audit and update spec statuses for auth-hardening and canon-rebrand

## v1.25

### Features

- Rename auth0_sub/auth0_org_id to oidc_sub/oidc_org_id, add users.role (db)

### Bug Fixes

- Migration tests — use cfg.attributes for schema, run Alembic in thread

### Documentation

- Update OIDC migration spec statuses to reflect implementation

## v1.24

### Features

- Implement ticket sync reliability spec (§2-§6)

### Bug Fixes

- Resolve critical bugs found in PR review

## v1.23

### Features

- Implement IDE Agent Integration spec (§2-§6)

### Bug Fixes

- Update list_specs tests for paginated response format

### Documentation

- Add IDE Agent Integration spec
- Add OIDC migration spec for Auth0 to open-source auth
- Add ticket links for ticket-sync-reliability spec (#376-#383)
- Add ticket sync reliability spec
- Remove duplicate ticket links and close stale issues
- Sync spec ticket links and clean up issue tracking
- Update spec statuses based on codebase audit

## v1.22

### Features

- Add setup, install-cli, and setup-claude targets to Makefiles

### Bug Fixes

- Differentiate oss setup-claude from setup, add --force to install-cli

## v1.21

### Features

- Add logo SVG as favicon across all sites

### Documentation

- Regenerate API/CLI/MCP reference docs (58 → 74 endpoints)

## v1.20

### Features

- Filter org dropdown by Auth0 membership in multi-tenant mode

### Bug Fixes

- OSS CI, broken logo, quick start rewrite; license MIT → BSL 1.1
- Replace internal registry URL with public ghcr.io reference in FAQ
- Update stale plugin paths missed during plugin directory flattening
- Explicitly remove sensitive specs and stale plugin dirs from OSS target
- Flatten plugin structure and consolidate OSS sync
- Prepare canonhq/canon for public visibility
- Change webhook endpoints to fail-closed when secrets are unconfigured
- Handle unknown sslmode values safely, document allow→require upgrade
- Set OTel service.name to "canon" instead of "unknown_service"

### Documentation

- Add FAQ, troubleshooting, example specs page, and improve CONTRIBUTING

## v1.19

### Features

- Implement managed cloud pricing with Stripe billing and BYOK support

### Bug Fixes

- Update plugin config to GitHub repo, fix setup crash on dangling symlink
- Clean stale files from FOSS repo, add CI and .gitignore
- Align billing routes with org-scoped URL pattern and fix response field mismatches

### Documentation

- Add schema migration for nullable stripe_customer_id and update spec

## v1.18

### Features

- Prepare for canonhq org migration and open-source split

### Bug Fixes

- Repair FOSS export pipeline for canonhq/canon
- Add --extra cloud to local dev install and use bash in Makefile
- Format _local.py after config class rename
- Rename SpecwrightApiAdapter to CanonApiAdapter in test file
- Remove duplicate wheel force-include causing PyPI upload rejection
- Add verbose logging to PyPI publish for debugging
- Update Dockerfile COPY path for restructured plugin directory
- Create all target directories in export script
- Create target directories before rsync in export script
- Add cloud extra to CI workflows and format test files
- Update plugin_data/skills symlink to new plugin directory

### Documentation

- Remove outdated specwright/openspec references from docs site

## v1.17

### Features

- Add GitHub App post-install redirect flow

### Bug Fixes

- Add Home link in docs nav bar pointing to marketing site

## v1.16

### Features

- Rebrand Claude Code plugin and skills to canon:*
- Rebrand GitHub Action from Specwright to Canon
- Rebrand HTML templates from Specwright to Canon
- Rebrand Vue SPA marketing components and app UI to Canon
- Update all user-facing strings and test assertions to Canon
- CTA section dark background inversion (ui)
- Redesign hero section — left-aligned, solid saffron CTA (ui)
- Replace @theme tokens with Warm Machine palette (ui)
- Replace all marketing gradients with solid saffron (ui)
- Sweep remaining hardcoded color values (ui)
- Update brand.css tokens to Warm Machine palette (ui)
- Update font loading to Fraunces/DM Sans/IBM Plex Mono (ui)
- Update LoginView scoped styles to warm palette (ui)
- Update Monaco editor font to IBM Plex Mono (ui)
- Update navigation and footer to solid saffron wordmarks (ui)

### Bug Fixes

- Correct broken specwright references in Makefile, Dockerfile.dev, setup.py, routes
- Correct GitHub App install URLs to use canon-hq slug
- Lint issues
- Sync window.__CANON__ global and plugin MCP config

### Documentation

- Add Canon rebrand Phase 2 implementation plan
- Canon "Warm Machine" visual identity design
- Mark GitHub App creation as done (App ID: 3012101)
- Mark PyPI reservation as done in Canon rebrand spec
- Rebrand all documentation to Canon
- Update docs/specs/new-spec.md
- Update docs/specs/new-spec.md
- Warm Machine visual identity implementation plan

## v1.15

### Features

- Add Canon brand assets — icon, favicon, OG image

### Documentation

- Add gv-infra infrastructure rebrand section to Canon spec
- Add setup UX improvements spec
- Update domain to canonhq.co, mark as acquired

## v1.14

### Features

- Improve ticket sync product experience

### Documentation

- Add Canon rebrand design document
- Add Canon rebrand spec with acceptance criteria
- Add repo transfer section, mark canonhq org as done

## v1.13

### Features

- Auto-advance section status to done on PR merge

### Bug Fixes

- Harden auto-advance on PR merge, mark ticket mapping spec done
- Exclude blocked sections from auto-advance, guard duplicate ACs

### Documentation

- Mark ticket mapping model spec as done
- Mark ticket sync §3 (real-time reverse sync) as done

## v1.12

### Features

- Surface preview deployment URL in Specwright bot comment

### Bug Fixes

- Unify preview workflow trigger and fix comment formatting

### Documentation

- Preview deployment design and spec status updates

## v1.11

### Features

- Real-time reverse sync via webhooks for all ticket systems

### Bug Fixes

- Base64-encode embedded analysis JSON to prevent HTML comment leak

## v1.10

### Features

- Structured spec detail view with collapsible section cards

### Documentation

- Check off verified ACs across 6 specs (11% → 58% coverage)

## v1.9

### Features

- Add issue type labels and title prefix for hierarchy visibility

### Bug Fixes

- GitHub reverse sync bug, auto-parent warning, review nits

## v1.8

### Features

- Auto-generate CLI, MCP, and API reference docs at build time
- Configurable spec paths, sitemap/SEO, and versioned docs (§2, §11, §10)

### Bug Fixes

- Skip gen-refs prebuild when uv is not available

### Documentation

- Add cross-links to concept pages and verify content migration
- Update spec statuses based on codebase audit

## v1.7

### Features

- Audit checks off realized ACs and inserts evidence comments

### Bug Fixes

- Apply AC updates even when section status is unchanged

### Documentation

- Fix ticket links and set ticket_project on all specs
- Update spec statuses based on codebase audit

## v1.6

### Features

- Add production hardening for web app

## v1.5

### Features

- Add /sw-audit skill for full spec audit workflow
- Add `specwright audit` CLI command for Claude-powered spec status auditing

### Documentation

- Add ticket links from specwright sync
- Mark Background sections as done, fix parent section statuses
- Update spec statuses based on codebase implementation audit

## v1.4

### Features

- Server-proxied ticket sync via GitHub App tokens

### Bug Fixes

- Decouple auth0_orgs_enabled from auth0_audience (auth)
- Remove unused SyncResult import in test_engine (lint)
- Only create tickets for todo/in_progress sections (sync)
- Resolve org for device auth JWTs without org_id claim (auth)
- Include AUTH0_AUDIENCE in K8s secret (deploy)
- Fail fast on missing AUTH0_AUDIENCE and use correct status codes (auth)

### Documentation

- Fix configuration reference to match actual parser
- Update docs for server-proxied sync, device auth, and AUTH0_AUDIENCE

## v1.2

### Features

- Add Specwright web app links to PR comments

### Bug Fixes

- Default platform_url to empty, use module-level Settings, drop redundant path

## v1.1

### Features

- **docs-site**: Logo links to main site + gradient wordmark

### Documentation

- Update install commands to use gv-specwright package name

## v1.0

### Bug Fixes

- Add AUTH0_DEVICE_CLIENT_ID to deploy K8s secret
- Rename PyPI package to gv-specwright (specwright was taken)
- Use version tag for pypi-publish action (Docker-based, SHA pinning unsupported)
