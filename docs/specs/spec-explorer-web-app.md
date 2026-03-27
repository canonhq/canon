---
title: "Spec Explorer Web App"
status: done
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-02-12
updated: 2026-02-13
tags: [web, mvp, dogfooding]
---

# Spec Explorer Web App

A read-only dashboard that provides centralized discovery and viewing of specifications across all repositories in a GitHub organization. The application uses server-side rendering with Jinja2 templates and HTMX for progressive enhancement, eliminating the complexity of single-page applications while maintaining a responsive user experience.

## 1. Background

<!-- canon:system:1 status:done -->

Specifications are distributed across multiple repositories in `docs/specs/*.md` files. This distribution forces product managers and engineers to manually navigate GitHub directory structures to locate specifications, verify their status, or identify work in progress. The Spec Explorer consolidates this information into a unified interface, providing organization-wide visibility into all specifications and their current state.

## 2. Org Dashboard

<!-- canon:system:2 status:done -->

The root page (`/`) displays all repositories accessible through the GitHub App installation. Repositories are partitioned into two groups: those containing specifications and those without.

For each specification, the dashboard displays:

- Status badges with color coding
- Owner information and team assignment
- Tags for categorization
- Progress indicators reflecting section completion

### Acceptance Criteria

- [x] Lists all repos accessible to the GitHub App installation
<!-- canon:realized-in:PR#75 file:src/specwright/auth/middleware.py -->
<!-- canon:realized-in:PR#80 file:templates/dashboard.html -->
<!-- canon:realized-in:PR#84 file:frontend/src/components/dashboard/OrgDashboard.vue -->
<!-- canon:realized-in:PR#84 file:frontend/src/components/dashboard/SpecList.vue -->
- [x] Partitions repos into "with specs" and "without specs"
- [x] Shows spec count, section progress, and AC completion per spec
<!-- canon:realized-in:PR#68 file:src/specwright/web/services.py -->
<!-- canon:realized-in:PR#68 file:src/specwright/web/models.py -->
<!-- canon:realized-in:PR#68 file:src/specwright/db/agent_store.py -->
- [x] Status badges color-coded (done=green, in_progress=yellow, blocked=red, draft=gray, todo=blue, deprecated=purple)
<!-- canon:realized-in:PR#84 file:frontend/src/style.css -->
<!-- canon:realized-in:PR#84 file:frontend/src/components/common/StatusBadge.vue -->
- [x] Team and status filter dropdowns (Vue reactive, client-side filtering)
<!-- canon:realized-in:PR#73 file:templates/dashboard.html -->
- [x] Dashboard displays owner information for each specification
- [x] Dashboard displays team assignment for each specification
- [x] Dashboard shows tags for categorization on each specification
- [x] Dashboard displays progress indicators reflecting section completion
<!-- canon:realized-in:PR#296 file:frontend/src/components/common/SpecProgressIndicator.vue -->
<!-- canon:realized-in:PR#296 file:frontend/src/components/dashboard/SpecList.vue -->
- [x] Repositories without specifications are clearly separated from those with specifications
- [x] Each specification entry is clickable and navigates to its detail page
<!-- canon:realized-in:PR#96 file:frontend/src/views/TasksView.vue -->

## 3. Repo Detail Page

<!-- canon:system:3 status:done -->

The repository detail page (`/repos/{owner}/{repo}`) presents all specifications and documentation within a single repository. Documentation is classified by type: ADR, README, changelog, and runbook.

The page displays:

- A summary of the repository's CANON.yaml configuration
- Links to standard documentation files
- All specifications with their metadata and progress indicators

### Acceptance Criteria

- [x] Breadcrumb navigation back to dashboard
<!-- canon:realized-in:PR#75 file:src/specwright/web/routes.py -->
<!-- canon:realized-in:PR#84 file:frontend/src/components/layout/Breadcrumb.vue -->
<!-- canon:realized-in:PR#84 file:frontend/src/views/RepoView.vue -->
- [x] CANON.yaml config displayed (team, ticket system, feature flags)
<!-- canon:realized-in:PR#84 file:frontend/src/components/repo/RepoDetail.vue -->
- [x] All specs listed with tags, owner, status, progress
<!-- canon:realized-in:PR#68 file:src/specwright/cron/coverage_snapshot.py -->
<!-- canon:realized-in:PR#84 file:frontend/src/components/repo/SpecCard.vue -->
- [x] "Other documentation" section lists README, CHANGELOG, CONTRIBUTING, and non-spec docs
<!-- canon:realized-in:PR#80 file:templates/repo.html -->
<!-- canon:realized-in:PR#84 file:frontend/src/components/repo/DocCard.vue -->

## 4. Spec Detail Page

<!-- canon:system:4 status:done -->

The specification detail page (`/specs/{owner}/{repo}/{path}`) renders the complete specification with parsed section hierarchy, status indicators, ticket references, and acceptance criteria. All content is presented in read-only format with sanitized markdown rendering.

The page includes:

- Frontmatter metadata display
- Hierarchical section rendering
- Ticket links with automatic hyperlinking
- Acceptance criteria with checkbox visualization
- Sanitized markdown rendering

### Acceptance Criteria

- [x] Frontmatter metadata displayed (title, status, owner, team, dates, tags)
<!-- canon:realized-in:PR#73 file:templates/spec.html -->
<!-- canon:realized-in:PR#84 file:frontend/src/components/spec/SpecHeader.vue -->
<!-- canon:realized-in:PR#296 file:frontend/src/components/spec/SpecSummary.vue -->
- [x] Nested sections rendered with hierarchy (h2 → h3 → h4)
<!-- canon:realized-in:PR#70 file:src/specwright/web/render.py -->
<!-- canon:realized-in:PR#84 file:frontend/src/components/spec/SpecContent.vue -->
<!-- canon:realized-in:PR#296 file:frontend/src/components/spec/SpecSectionCard.vue -->
- [x] Per-section status badges
- [x] Ticket links rendered as hyperlinks (Jira, Linear, GitHub Issues)
<!-- canon:realized-in:PR#84 file: -->
- [x] Blocked-by indicators shown in red
- [x] Acceptance criteria as readonly checkboxes (checked items struck-through)
<!-- canon:realized-in:PR#296 file:frontend/src/components/spec/SpecAcceptanceCriteria.vue -->
- [x] Markdown content rendered via mistune (backend), sanitized with DOMPurify (frontend)
- [x] "View on GitHub" link

## 5. Live Search

<!-- canon:system:5 status:done -->

The search functionality indexes all specifications and documentation (ADRs, guides, READMEs) across the organization. The hybrid search index supports PR analysis by retrieving relevant context documents based on PR metadata and file changes.

The search API endpoint (`GET /{org}/api/search`) returns paginated results with multiple filter options:

- Query parameters: `q` (search query), `team`, `status`, `tag`, `repo`, `limit`, `offset`
- Response fields: `results`, `total`, `facets`

The dashboard UI displays facet counts and provides filtering controls.

The current implementation uses client-side filtering with HTMX-powered debounced search. Migration to server-side search with Voyage AI embeddings and Neon DB is planned to enable improved performance and semantic search capabilities.

### Acceptance Criteria

- [x] Navbar search input with HTMX debounce (300ms)
<!-- canon:realized-in:PR#102 file:frontend/src/components/layout/SearchBar.vue -->
- [x] Results render in dropdown partial (max 396px scroll)
<!-- canon:realized-in:PR#80 file:templates/partials/search_results.html -->
<!-- canon:realized-in:PR#84 file:frontend/src/components/layout/SearchResults.vue -->
<!-- canon:realized-in:PR#102 file:frontend/src/components/layout/SearchResults.vue -->
- [x] Filter by team, status, tag query params
<!-- canon:realized-in:PR#84 file:frontend/src/api/search.ts -->
<!-- canon:realized-in:PR#96 file:src/specwright/web/routes.py -->
<!-- canon:realized-in:PR#102 file:frontend/src/views/SearchView.vue -->
<!-- canon:realized-in:PR#102 file:src/specwright/web/services.py -->
- [x] Section-level search with keyword matching across headings, content, and ACs (replaces Voyage AI hybrid search — §7 deprecated)
- [x] Faceted filter counts in sidebar
<!-- canon:realized-in:PR#102 file:src/specwright/web/models.py -->
- [x] Paginated results for large orgs

## 6. Caching

<!-- canon:system:6 status:done -->

An in-memory TTL cache reduces GitHub API calls and stores search and facet results. Webhook push events trigger cache invalidation for affected resources, including repositories, specifications, documentation, search results, and facets.

Cache invalidation uses prefix-based matching to efficiently clear all related entries when a repository is updated.

### Acceptance Criteria

- [x] TTL-based per-key expiration (default 300s, configurable via `CACHE_TTL_SECONDS`)
- [x] Prefix-based invalidation for repo-scoped keys
- [x] Push webhook invalidates org overview and affected repo caches
- [x] Cache bypass for fresh data on cache miss

## 7. Search Infrastructure

<!-- canon:system:7 status:deprecated -->

The search infrastructure provides semantic search capabilities through Neon Postgres with pgvector extension, Voyage AI embedding service, and an automated indexing pipeline triggered by repository push events.

The indexing pipeline processes specifications through the following stages:

1. Webhook push event received
2. Specifications parsed and chunked
3. Content embedded via Voyage AI
4. Embeddings upserted to database

The search API returns ranked results with snippet highlights for improved discoverability.

### Acceptance Criteria

- [ ] Neon DB provisioned with `spec_chunks` and `spec_documents` tables
- [ ] Voyage AI integration for embedding spec content
- [ ] Indexing pipeline: webhook push → parse specs → chunk → embed → upsert
- [ ] Full re-index command for backfilling
- [ ] Search API returns ranked results with snippet highlights

## 8. Production Hardening

<!-- canon:system:8 status:done -->

Production readiness requirements include HTTP caching headers, structured logging, error handling, and deployment configuration updates for web-specific settings.

These improvements ensure the application performs reliably under production load and provides appropriate observability for debugging and monitoring.

### Acceptance Criteria

- [x] Cache-Control headers on static assets
- [x] Custom 404/500 error pages
- [x] Structured JSON logging for web requests
- [x] Rate limiting on search endpoint
- [x] Helm values for web_org and cache_ttl_seconds