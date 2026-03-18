---
title: "Developer Documentation Site"
status: in_progress
owner: ng
team: platform
ticket_project: canonhq/canon
created: 2026-02-26
updated: 2026-02-26
tags: [docs, vitepress, developer-experience, onboarding]
---

# Developer Documentation Site

Build a comprehensive developer documentation site for Canon using VitePress, covering all facets of the platform: concepts, guides, API reference, CLI reference, MCP/plugin integration, and architecture. The site lives in-repo at `docs-site/` and deploys to `docs.canonhq.co` (or a `/docs` path on the main domain).

## 1. Background

Canon is a spec-driven development platform with a growing surface area: a FastAPI backend, Vue 3 frontend, CLI with 8 subcommands, MCP server with 11 tools, 8 Claude Code skills, GitHub App webhooks, ticket sync adapters, and a structured spec parser. Despite being a documentation-first product, Canon lacks a proper developer documentation site.

Current documentation lives in scattered locations:
- `docs/vision.md`, `docs/agent-behavior.md`, `docs/self-hosting.md` — good conceptual docs, but not discoverable
- `plugin/README.md` — basic CLI/skill reference
- Root `README.md` — quickstart + architecture overview
- `docs/specs/*.md` — living specs (not user-facing docs)
- OpenAPI is explicitly disabled (`docs_url=None` in FastAPI)

Developers evaluating or adopting Canon have no single place to learn how it works, how to configure it, or how to extend it. A VitePress docs site solves this by providing a structured, searchable, version-controlled documentation portal built with the same toolchain (Vite) the frontend already uses.

<!-- specwright:ticket:github:275 -->
<!-- specwright:ticket:github:286 -->
## 2. Configurable Spec Paths (Prerequisite)

<!-- specwright:system:2 status:in_progress -->

Before moving docs into VitePress, fix the incomplete `doc_paths` configuration. CANON.yaml already has a `specs.doc_paths` field (default: `["docs/specs/*.md"]`), but 24+ hardcoded `docs/specs/` references throughout the codebase bypass it. These must be refactored so that spec discovery, creation, classification, and sync all respect the configured paths.

### 2.1 Hardcoded References to Fix

Key files with hardcoded `docs/specs/` paths:

| File | Issue |
|------|-------|
| `github/spec_utils.py` | `SPEC_FILE_RE` regex + `load_repo_specs()` hardcodes directory listing |
| `parser/classify.py` | `startswith("docs/specs/")` check for spec classification |
| `mcp/server.py` | `list_specs` tool + `create_spec` always writes to `docs/specs/` |
| `agent/analyzer.py` | Hardcoded path check to differentiate specs from other docs |
| `cron/sync_status.py` | Only syncs specs from `docs/specs/` |
| `web/editor_routes.py` | Hardcoded directory listing for spec picker |
| `web/services.py` | Hardcoded filter for spec vs. non-spec docs |
| `cli/init.py` + `setup.py` | Default paths and template creation |
| `github/handlers/*.py` | `filter_spec_files()` uses hardcoded regex |

### 2.2 Approach

- Replace `SPEC_FILE_RE` with a pattern-matching function that reads from `doc_paths` config
- Update `load_repo_specs()` to use configured patterns instead of hardcoded directory
- Update `create_spec` in MCP to write to the first configured spec directory
- Update `classify.py` to check against configured patterns
- Thread config through all call sites that need it
- Default behavior remains `docs/specs/*.md` when no config is present (backward compatible)

### Acceptance Criteria

- [x] All spec discovery uses `doc_paths` from CANON.yaml (no hardcoded `docs/specs/` in app code)
<!-- specwright:realized-in:PR#292 file:src/specwright/web/services.py -->
<!-- specwright:realized-in:PR#292 file:src/specwright/cron/sync_status.py -->
<!-- specwright:realized-in:PR#292 file:src/specwright/github/handlers/on_pull_request.py -->
- [ ] `canon init` creates template in the first configured spec directory
- [ ] MCP `create_spec` writes to the configured spec directory
- [x] MCP `list_specs` reads from configured spec directories
<!-- specwright:realized-in:PR#292 file:src/specwright/mcp/server.py -->
- [x] `filter_spec_files()` matches against configured patterns
- [x] Spec classification uses configured patterns instead of hardcoded path prefix
- [x] Cron jobs (sync, coverage) use configured patterns
- [x] Default behavior (`docs/specs/*.md`) is preserved when no `doc_paths` is configured
- [ ] Existing tests pass after refactor

## 3. VitePress Site Scaffold

<!-- specwright:system:3 status:done -->

Set up the VitePress project structure, build pipeline, and local dev workflow.

### 3.1 Project Structure

Create a `docs-site/` directory at the repo root with VitePress configuration. Existing docs (`docs/vision.md`, `docs/agent-behavior.md`, `docs/self-hosting.md`, `docs/examples/`) will be moved into VitePress content directories. Specs remain in `docs/specs/` (or whatever `doc_paths` is configured to).

```
docs-site/
  .vitepress/
    config.ts          # VitePress config (nav, sidebar, theme, versioning)
    theme/
      index.ts         # Custom theme extensions
      custom.css       # Brand styling (Canon colors, fonts)
    scripts/
      gen-cli-ref.ts   # Auto-generate CLI reference from --help
      gen-mcp-ref.ts   # Auto-generate MCP tool reference from server metadata
      gen-openapi.ts   # Export OpenAPI schema from FastAPI
  public/
    logo.svg           # Canon logo
    og-image.png       # Open Graph image
  index.md             # Home page
  getting-started/
    index.md           # Overview
    installation.md    # Prerequisites + install
    quickstart.md      # First spec in 5 minutes
    configuration.md   # CANON.yaml reference
  concepts/
    index.md           # Concepts overview
    openspec.md        # OpenSpec framework (migrated from docs/vision.md)
    living-specs.md    # Specs as living programs (migrated from docs/vision.md)
    delta-tracking.md  # Change tracking
    agent-mesh.md      # Agent architecture (migrated from docs/agent-behavior.md)
    coverage.md        # Spec coverage model
  guides/
    index.md           # Guides overview
    writing-specs.md   # Spec authoring guide for PMs/engineers
    self-hosting.md    # K8s deployment (migrated from docs/self-hosting.md)
    github-app.md      # GitHub App setup
    ticket-sync.md     # Jira/Linear/GitHub Issues configuration
    ci-integration.md  # Using canon in CI/CD pipelines
  reference/
    index.md           # Reference overview
    cli.md             # CLI command reference (auto-generated)
    mcp.md             # MCP server tools reference (auto-generated)
    skills.md          # Claude Code skills reference
    api.md             # REST API reference (OpenAPI, auto-generated)
    spec-format.md     # Spec markdown format specification
    config.md          # CANON.yaml full schema
    parser-models.md   # Parser data models
  architecture/
    index.md           # Architecture overview
    system-design.md   # High-level system design
    data-flow.md       # Request flows (webhook → agent → comment)
    components.md      # Component breakdown
  contributing/
    index.md           # Contributing overview
    development.md     # Local dev setup for contributors
    testing.md         # Test strategy and running tests
    code-style.md      # Linting, formatting, conventions
  package.json         # VitePress as devDependency
```

### 3.2 Build & Dev Commands

- `npm run docs:dev` — Start VitePress dev server with hot reload
- `npm run docs:build` — Build static site to `docs-site/.vitepress/dist/`
- `npm run docs:preview` — Preview built site locally
- Add `make docs-dev`, `make docs-build` targets to the root Makefile

### 3.3 Branding & Theme

Apply Canon's visual identity:
- Use the existing brand colors from `static/brand.css` as VitePress theme tokens
- Custom home page layout matching the marketing site aesthetic
- Light/dark mode support (VitePress has this built in)
- Canon logo in the nav bar

### Acceptance Criteria

- [x] `docs-site/` directory exists with VitePress config and directory structure
- [x] `npm run docs:dev` starts a local dev server on a configurable port
- [x] `npm run docs:build` produces a static site in `.vitepress/dist/`
- [x] Site uses Canon brand colors and logo
- [x] Light/dark mode toggle works
- [x] Sidebar navigation reflects the directory structure above
- [x] Top nav includes links to: GitHub repo, main app, and marketing site
- [x] `make docs-dev` and `make docs-build` work from the repo root

## 4. Getting Started

<!-- specwright:system:4 status:done -->

Write the onboarding documentation that gets a new user from zero to productive.

### 4.1 Installation

Cover all installation paths:
- **GitHub App**: Install from GitHub Marketplace or self-host
- **CLI**: `pip install canonhq` or `uvx --from canonhq canon`
- **Claude Code Plugin**: `claude install gh:canonhq/canon`
- **MCP Server**: Configure in `.mcp.json` with `uvx --from canonhq canon-mcp`

### 4.2 Quickstart

A "first spec in 5 minutes" tutorial:
1. Run `canon init` to create `CANON.yaml` and template
2. Write a simple spec with 2 sections and 3 ACs
3. Run `canon status` to see the coverage dashboard
4. Run `canon verify` to check implementation
5. See the spec in the web UI

### 4.3 Configuration Reference

Document every field in `CANON.yaml`:
- `team`, `ticket_system`, `project_key`
- `specs.auto_tickets`, `specs.require_review`
- `agents.doc_updates`, `agents.pr_analysis`, `agents.stale_detection`
- Default values, valid options, and examples

### Acceptance Criteria

- [x] Installation page covers GitHub App, CLI, Claude Code plugin, and MCP server setup
- [x] Quickstart walks through creating and verifying a spec end-to-end in under 5 minutes
- [x] Configuration reference documents every `CANON.yaml` field with defaults and examples
- [ ] All code examples are copy-pasteable and tested

## 5. Concepts

<!-- specwright:system:5 status:done -->

Explain the mental models behind Canon. Migrate and expand content from `docs/vision.md`.

### 5.1 Content

- **OpenSpec Framework**: The spec-as-code philosophy — structured markdown, acceptance criteria, status tracking, delta markers
- **Living Specs**: How specs stay in sync with code through agents, verification, and ticket sync
- **Delta Tracking**: Added/modified/removed markers and how they drive agent behavior
- **Agent Mesh**: Per-repo agents, PR analysis pipeline, how agents coordinate
- **Spec Coverage**: The coverage model — what it measures, how scores are calculated, what "realized" means

### Acceptance Criteria

- [x] Each concept has its own page with clear explanations and diagrams
- [x] Content from `docs/vision.md` is migrated and restructured (not just copy-pasted)
- [x] Each concept page links to relevant guides and reference docs
<!-- specwright:realized-in:PR#292 file:docs-site/concepts/openspec.md -->
<!-- specwright:realized-in:PR#292 file:docs-site/concepts/living-specs.md -->
<!-- specwright:realized-in:PR#292 file:docs-site/concepts/delta-tracking.md -->
<!-- specwright:realized-in:PR#292 file:docs-site/concepts/agent-mesh.md -->
<!-- specwright:realized-in:PR#292 file:docs-site/concepts/coverage.md -->
<!-- specwright:realized-in:PR#TBD file:docs-site/concepts/openspec.md -->
<!-- specwright:realized-in:PR#TBD file:docs-site/concepts/living-specs.md -->
<!-- specwright:realized-in:PR#TBD file:docs-site/concepts/delta-tracking.md -->
<!-- specwright:realized-in:PR#TBD file:docs-site/concepts/agent-mesh.md -->
<!-- specwright:realized-in:PR#TBD file:docs-site/concepts/coverage.md -->
- [x] Diagrams use Mermaid (VitePress supports it natively)

## 6. Guides

<!-- specwright:system:6 status:done -->

Task-oriented documentation for common workflows.

### 6.1 Writing Specs

The most important guide — teach PMs and engineers how to write effective specs:
- Spec structure (frontmatter, sections, ACs, status comments)
- Writing good acceptance criteria (specific, testable, independent)
- Using strength keywords (MUST/SHOULD/MAY)
- BDD scenarios (GIVEN/WHEN/THEN)
- Linking tickets to sections
- Status lifecycle (draft → todo → in_progress → done)
- Examples from the `docs/examples/` directory

### 6.2 Self-Hosting

Migrate `docs/self-hosting.md` into the VitePress site with improvements:
- Better structure with step-by-step sections
- Architecture diagram of the deployed system
- Troubleshooting section with common issues

### 6.3 Ticket Sync

How to configure bidirectional ticket sync:
- Supported systems (Jira, Linear, GitHub Issues)
- Forward sync (spec → tickets) and reverse sync (ticket status → spec status)
- Status mapping configuration
- Handling conflicts

### 6.4 CI Integration

Using Canon in CI/CD pipelines:
- Running `canon verify` in CI to gate merges
- Generating coverage reports
- Automating spec status updates on merge

### Acceptance Criteria

- [x] Writing Specs guide covers spec structure, ACs, BDD, tickets, and status lifecycle with examples
- [x] Self-hosting guide is migrated from `docs/self-hosting.md` with improved structure
- [x] Ticket sync guide covers all three adapters (Jira, Linear, GitHub Issues) with configuration examples
- [x] CI integration guide shows GitHub Actions workflow examples
- [x] Each guide is task-oriented (not reference-oriented) with clear steps

<!-- specwright:ticket:github:262 -->
## 7. Reference

<!-- specwright:system:7 status:done -->

Comprehensive reference documentation for all Canon interfaces. CLI, MCP, and API references are auto-generated at build time.

### 7.1 CLI Reference (Auto-Generated)

Auto-generate from CLI introspection at build time via `docs-site/.vitepress/scripts/gen-cli-ref.ts`:
- Run `canon <cmd> --help` for each subcommand
- Parse output into structured markdown (synopsis, description, options, examples)
- Include exit codes and error messages
- Regenerated on every `docs:build` — no manual maintenance

### 7.2 MCP Server Reference (Auto-Generated)

Auto-generate from MCP server tool metadata via `docs-site/.vitepress/scripts/gen-mcp-ref.ts`:
- Import tool definitions from the MCP server (tool name, description, JSON Schema parameters)
- Format as reference pages with parameter tables and return value descriptions
- Include usage examples showing Claude Code interactions
- Configuration section (`uvx canon-mcp`, `.mcp.json` setup) is hand-written

### 7.3 Claude Code Skills Reference

Document all 8 `/sw:*` skills (hand-written, since skills are defined in markdown):
- What each skill does, when to use it
- Arguments and options
- Example interactions showing input/output

### 7.4 REST API Reference (Auto-Generated)

Auto-generate from FastAPI's OpenAPI schema via `docs-site/.vitepress/scripts/gen-openapi.ts`:
- Export OpenAPI JSON from the FastAPI app at build time (no need to re-enable `/docs` endpoint)
- Render with a VitePress-compatible OpenAPI viewer (e.g., `vitepress-openapi` plugin or custom component)
- Document authentication (API key, OAuth, session) in a hand-written intro section
- Include request/response examples for key endpoints

### 7.5 Spec Format Reference

Formal specification of the spec markdown format:
- Frontmatter fields (required vs. optional, valid values)
- Section numbering rules
- Status comment syntax (`<!-- canon:system:ID status:STATE -->`)
- Ticket link syntax (`<!-- canon:ticket:SYSTEM:ID -->`)
- Realization evidence syntax (`<!-- canon:realized-in:PR#N file:PATH lines:L1-L2 -->`)
- AC checkbox format with strength keywords
- Delta markers
- Document types (spec, proposal, design, adr)

### 7.6 Configuration Reference

Full `CANON.yaml` schema with JSON Schema or table format.

### Acceptance Criteria

- [x] CLI reference is auto-generated at build time from `canon --help` output
<!-- specwright:realized-in:PR#292 file:docs-site/.vitepress/scripts/gen-cli-ref.py -->
<!-- specwright:realized-in:PR#TBD file:docs-site/.vitepress/scripts/gen-cli-ref.py -->
- [x] MCP reference is auto-generated from MCP server tool metadata
<!-- specwright:realized-in:PR#292 file:docs-site/.vitepress/scripts/gen-mcp-ref.py -->
<!-- specwright:realized-in:PR#TBD file:docs-site/.vitepress/scripts/gen-mcp-ref.py -->
- [x] Skills reference documents all 8 `/sw:*` commands with usage examples
- [x] API reference is auto-generated from FastAPI OpenAPI schema at build time
<!-- specwright:realized-in:PR#292 file:docs-site/.vitepress/scripts/gen-api-ref.py -->
<!-- specwright:realized-in:PR#TBD file:docs-site/.vitepress/scripts/gen-api-ref.py -->
- [x] Spec format reference fully documents the markdown syntax including all comment types
- [x] Configuration reference documents the complete `CANON.yaml` schema
- [ ] Auto-generated pages include a "generated on" timestamp and link to source

<!-- specwright:ticket:github:263 -->
## 8. Architecture

<!-- specwright:system:8 status:done -->

Technical documentation for contributors and advanced users.

### 8.1 System Design

High-level architecture overview:
- Component diagram (FastAPI app, GitHub webhooks, Claude agent, spec parser, ticket sync, search index, MCP server)
- Deployment architecture (K8s, Helm, ingress, secrets)
- Technology choices and rationale

### 8.2 Data Flow

Request flow diagrams for key workflows:
- PR opened → webhook → agent analysis → comment posted
- `canon verify` → parser → code search → realization report
- Spec section updated → ticket sync → Jira/Linear/GitHub updated
- Search query → vector embeddings + BM25 → ranked results

### 8.3 Component Breakdown

Per-module documentation:
- `parser/` — How the spec parser works, regex patterns, edge cases
- `agent/` — Claude API integration, prompt construction, response formatting
- `sync/` — Ticket sync engine, adapter pattern, conflict resolution
- `search/` — Hybrid search implementation, indexing pipeline
- `github/` — GitHub App auth flow, webhook routing, API client

### Acceptance Criteria

- [x] System design page includes a component diagram (Mermaid)
- [x] Data flow page documents at least 3 key workflows with diagrams
- [x] Component breakdown covers parser, agent, sync, search, and GitHub modules
- [x] Architecture docs are useful for new contributors understanding the codebase

## 9. Contributing Guide

<!-- specwright:system:9 status:done -->

Documentation for open-source contributors.

### 9.1 Development Setup

- Prerequisites (Python 3.12+, Node 22+, uv, Docker)
- Clone, install, and run locally
- Environment variables (`.env.example` walkthrough)
- Running backend + frontend together

### 9.2 Testing

- Test structure (mirrors `src/` layout)
- Running tests (`uv run pytest`, `uv run pytest -v`)
- Writing tests (pytest patterns, `pytest-httpx` for mocking)
- CI pipeline expectations

### 9.3 Code Style

- Python: ruff (lint + format), mypy (strict)
- TypeScript/Vue: ESLint + vue-tsc
- Commit message conventions
- PR process and review expectations

### Acceptance Criteria

- [x] Development setup guide gets a new contributor running locally from scratch
<!-- canon:realized-in:PR#322 file:Makefile -->
<!-- canon:realized-in:PR#322 file:CLAUDE.md -->
- [x] Testing guide explains how to write and run tests with examples
- [x] Code style guide documents linting, formatting, and type checking requirements
- [ ] All commands in contributing docs are tested and work

<!-- specwright:ticket:github:264 -->
<!-- specwright:ticket:github:287 -->
## 10. Versioned Documentation

<!-- specwright:system:10 status:todo -->

Support versioned documentation so users on older releases can reference the correct docs.

### 10.1 Versioning Strategy

Use VitePress multi-version support (via directory-based versioning or a plugin like `vitepress-versioning`):
- Each release tag (e.g., `v0.1`, `v0.2`) gets a snapshot of the docs
- `latest` always points to the current `main` branch
- Version selector in the nav bar lets users switch between versions
- Auto-generated reference pages (CLI, MCP, API) are version-specific since they reflect the code at that release

### 10.2 Implementation

- Directory structure: `docs-site/v0.1/`, `docs-site/v0.2/`, or use git tags + CI to build versioned snapshots
- Canonical URLs point to `latest` to avoid SEO fragmentation
- Older versions show a banner: "You are viewing docs for version X. [View latest →]"
- Version snapshots are created as part of the release process (CI workflow)

### Acceptance Criteria

- [x] Version selector in nav bar allows switching between doc versions
- [ ] Each release creates a versioned docs snapshot
- [x] `latest` always reflects the current `main` branch
- [x] Older versions display a banner linking to latest
- [x] Canonical URLs point to latest version
- [ ] Auto-generated reference pages are version-specific

<!-- specwright:ticket:github:265 -->
<!-- specwright:ticket:github:288 -->
## 11. Deployment & Hosting

<!-- specwright:system:11 status:in_progress -->

Set up automated deployment for the docs site.

### 11.1 GitHub Actions Workflow

Add a CI workflow that:
- Builds the VitePress site on every PR (validates no broken links/builds)
- Deploys to hosting on merge to `main`

### 11.2 Hosting Options

Choose one:
- **GitHub Pages**: Free, simple, deploy from `gh-pages` branch or Actions artifact
- **Subdomain**: `docs.canonhq.co` via nginx-ingress on the existing DOKS cluster
- **Subpath**: Serve from `/docs` on the main domain via FastAPI static mount

### 11.3 Custom Domain & SEO

- Canonical URL configuration
- Sitemap generation (VitePress built-in)
- `robots.txt`
- Open Graph meta tags on all pages

### Acceptance Criteria

- [x] GitHub Actions workflow builds docs on PR and deploys on merge to `main`
- [x] Docs site is accessible at a public URL
- [x] Sitemap is generated and `robots.txt` allows crawling
- [x] Build failures block PR merge (CI check required)

## 12. Design

### 12.1 Why VitePress

- Same build tool (Vite) as the existing Vue 3 frontend — team familiarity
- Vue component support means we can embed interactive examples
- Markdown-first with built-in search, dark mode, sidebar nav
- Static output deploys anywhere (GitHub Pages, CDN, K8s)
- Active ecosystem and strong defaults for technical documentation

### 12.2 Content Strategy

- **Migrate, don't duplicate**: Move existing docs from `docs/` into VitePress pages. Remove or redirect the originals to avoid drift.
- **Auto-generate where possible**: CLI reference from argparse, API reference from OpenAPI schema, config reference from Pydantic models
- **Examples over explanations**: Every reference page should have copy-pasteable examples
- **Link specs to docs**: Reference pages should link to the specs that defined them

### 12.3 Information Architecture

```
Home
├── Getting Started
│   ├── Installation
│   ├── Quickstart
│   └── Configuration
├── Concepts
│   ├── OpenSpec Framework
│   ├── Living Specs
│   ├── Delta Tracking
│   ├── Agent Mesh
│   └── Spec Coverage
├── Guides
│   ├── Writing Specs
│   ├── Self-Hosting
│   ├── Ticket Sync
│   └── CI Integration
├── Reference
│   ├── CLI
│   ├── MCP Server
│   ├── Claude Code Skills
│   ├── REST API
│   ├── Spec Format
│   └── Configuration
├── Architecture
│   ├── System Design
│   ├── Data Flow
│   └── Components
└── Contributing
    ├── Development
    ├── Testing
    └── Code Style
```

## 13. Rollout Plan

1. **Phase 0 — Configurable Paths**: Refactor hardcoded `docs/specs/` references to use `doc_paths` config (Section 2)
2. **Phase 1 — Scaffold**: VitePress project setup, branding, nav/sidebar, home page, CI workflow (Section 3)
3. **Phase 2 — Getting Started + Concepts**: Migrate existing docs from `docs/` into VitePress, write quickstart (Sections 4-5)
4. **Phase 3 — Guides**: Writing specs guide, migrate self-hosting, ticket sync, CI integration (Section 6)
5. **Phase 4 — Reference + Auto-Gen**: Build-time generation scripts for CLI, MCP, API; hand-write skills + spec format + config (Section 7)
6. **Phase 5 — Architecture + Contributing**: System design, data flows, contributor onboarding (Sections 8-9)
7. **Phase 6 — Versioning**: Version selector, release snapshots, banners for old versions (Section 10)
8. **Phase 7 — Deploy**: CI workflow, hosting setup, SEO, production URL (Section 11)

## 14. Resolved Questions

- **Auto-generate reference pages**: Yes — CLI, MCP, and API reference pages are auto-generated at build time via scripts in `.vitepress/scripts/`. Skills and spec format are hand-written.
- **Move existing docs**: Yes — migrate `docs/vision.md`, `docs/agent-behavior.md`, `docs/self-hosting.md`, and `docs/examples/` into VitePress content directories. Specs stay in `docs/specs/` (configurable via `doc_paths`). Remove originals after migration. Prerequisite: make spec paths configurable (Section 2).
- **Versioned docs**: Yes — directory-based or tag-based versioning with a nav selector, version banners, and canonical URLs pointing to latest.
