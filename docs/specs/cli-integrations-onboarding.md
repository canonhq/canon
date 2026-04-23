---
title: "CLI Integration Management & Guided Onboarding"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-04-22
updated: 2026-04-22
tags: [cli, integrations, onboarding, dx]
---

# CLI Integration Management & Guided Onboarding

## 1. Background

<!-- canon:system:1 status:draft -->

Canon integrates with ticket systems (Jira, Linear, GitHub Issues), VCS providers
(GitHub), and notification platforms (Slack). Today, integration management has
two disconnected paths:

1. **Web UI** — OAuth flows at `/app/:org/settings/integrations` (specified in
   `integration-management.md`, partially built)
2. **Manual config** — editing `CANON.yaml` auth_profiles and environment
   variables directly

Neither path is discoverable from the CLI. A user who runs `canon setup` picks a
ticket system but never actually _connects_ it. `canon sync` then fails with
opaque credential errors. There is no CLI command to list what's configured, test
connections, or add new integrations.

Meanwhile, `canon setup` is a single-pass wizard that writes config files but
doesn't validate them, doesn't check authentication, and doesn't help the user
reach a working state. The `setup-ux-improvements.md` spec identified several
gaps (login awareness, MCP validation, doctor command) but treats them as
incremental fixes rather than a cohesive onboarding flow.

This spec replaces `canon setup` with a guided multi-step onboarding wizard and
adds `canon integrations` commands for ongoing integration management.

### Goals

- Let CLI users list, add, remove, and test integrations without touching config
  files or the web UI
- Replace `canon setup` with a progressive wizard that walks through auth →
  integration → validation in one flow
- Support both backend-authenticated and local-only (self-hosted) operation
- Surface integration health in the CLI so credential issues are caught early

### Non-Goals

- Web UI integration management (covered by `integration-management.md`)
- New adapter implementations (Asana, GitLab, Bitbucket — future specs)
- Extension/plugin marketplace management (covered by `plugin-ecosystem.md`)
- Migrating existing env-var deployments — env vars continue to work

### Relationship to Existing Specs

| Spec | Relationship |
|------|-------------|
| `setup-ux-improvements.md` | This spec **supersedes** sections 2.2 (login awareness), 2.4 (MCP validation), and 3.x (doctor command). Sections 2.1 (next steps bug), 2.3 (--force), and 4.x (naming) remain independent. |
| `integration-management.md` | This spec is the **CLI counterpart**. Backend API routes and DB schema from that spec are dependencies. |
| `ticket-mapping-model.md` | Multi-target routing config is respected — `canon integrations add` for a secondary target uses the same CANON.yaml routing model. |

---

## 2. CLI Integration Management

<!-- canon:system:2 status:draft -->

New command group: `canon integrations` (alias: `canon int`).

### 2.1 `canon integrations list`

<!-- canon:system:2.1 status:todo -->

<!-- canon:ticket:github:523 -->
Show all configured integrations across all credential sources.

#### Output Format

```
Integrations for myorg/myrepo

  Provider         Source       Status       Details
  ─────────────────────────────────────────────────────────
  Jira Cloud       backend      connected    acme.atlassian.net (OAuth)
  Linear           env var      connected    CANON workspace
  GitHub Issues    canon.yaml   configured   canonhq/canon (API token)
  Slack            not configured

  3 connected, 1 not configured
  Run `canon integrations add <provider>` to connect a new integration.
```

#### Acceptance Criteria

- [ ] Lists integrations from all three credential sources: backend API (`GET /app/{org}/api/settings/integrations`), CANON.yaml auth_profiles, and detected environment variables
- [ ] Each row shows: provider name, credential source (backend / env var / canon.yaml), connection status, and one-line detail
- [ ] Backend integrations require authentication; if not logged in, only local sources shown with a hint to `canon login`
- [ ] Providers with no configuration in any source shown as "not configured"
- [ ] `--json` flag outputs machine-readable JSON
- [ ] `--source <backend|local|env>` flag filters to a single credential source
- [ ] Exit code 0 always (listing is informational)

### 2.2 `canon integrations add <provider>`

<!-- canon:system:2.2 status:todo -->

<!-- canon:ticket:github:524 -->
Guided flow to connect a ticket system or service. Routes to the appropriate
connection method based on authentication state.

#### Flow: Authenticated (logged into Canon backend)

1. Check provider is supported (`jira`, `linear`, `github`)
2. For OAuth providers (Jira, Linear):
   a. Open browser to backend OAuth initiation URL
   b. Backend handles OAuth dance, stores encrypted credentials
   c. CLI polls `GET /app/{org}/api/settings/integrations` until connection appears (timeout 120s)
   d. On success, print connection details
3. For GitHub Issues:
   a. Check if GitHub App is installed (via backend API)
   b. If not: open browser to GitHub App install URL, poll for installation
   c. Prompt for default repository selection from installed repos

#### Flow: Not Authenticated (local-only / self-hosted)

1. Check provider is supported
2. Prompt for auth method:
   - **API token** — prompt for token, store in env var reference, update CANON.yaml
   - **Environment variable** — prompt for env var name, validate it's set, update CANON.yaml
3. For Jira: prompt for site URL, project key, validate connection
4. For Linear: prompt for team key, validate connection
5. For GitHub Issues: prompt for repo (auto-detect from git remote), validate connection
6. Write `auth_profiles` section to CANON.yaml
7. Run connection test

#### Acceptance Criteria

- [ ] `canon integrations add jira` walks through Jira connection (OAuth when authenticated, API token when not)
- [ ] `canon integrations add linear` walks through Linear connection (OAuth when authenticated, API key when not)
- [ ] `canon integrations add github` walks through GitHub Issues connection
- [ ] Browser opened via `webbrowser.open()` for OAuth flows; fallback prints URL if browser unavailable
- [ ] CLI polls backend for connection completion with a spinner, times out after 120s with actionable message
- [ ] Local flow validates connection before writing config (calls adapter's test endpoint or makes a test API call)
- [ ] CANON.yaml is updated atomically (read → modify → write) preserving comments and formatting where possible
- [ ] If provider is already connected: show current connection and prompt to replace or cancel
- [ ] `--token <value>` flag skips interactive prompt for API token (for CI/scripting)
- [ ] `--non-interactive` flag fails with error if any prompts would be needed

### 2.3 `canon integrations remove <provider>`

<!-- canon:system:2.3 status:todo -->

<!-- canon:ticket:github:525 -->
Disconnect an integration with confirmation.

#### Acceptance Criteria

- [ ] Shows current connection details before prompting for confirmation
- [ ] If backend-connected: calls `DELETE /app/{org}/api/settings/integrations/{provider}` and removes from backend
- [ ] If locally configured: removes auth_profile from CANON.yaml and prints env var cleanup hint
- [ ] `--yes` flag skips confirmation prompt
- [ ] Does not delete tickets or spec links — only removes the credential
- [ ] Prints warning about impact: "Ticket sync for {provider} will stop working"

### 2.4 `canon integrations test [provider]`

<!-- canon:system:2.4 status:todo -->

<!-- canon:ticket:github:526 -->
Health check one or all configured integrations.

#### Acceptance Criteria

- [ ] With no argument: tests all configured integrations
- [ ] With provider argument: tests only that provider
- [ ] For backend integrations: calls `POST /app/{org}/api/settings/integrations/{provider}/test`
- [ ] For local integrations: instantiates adapter via factory, calls a lightweight API endpoint (Jira: `/myself`, Linear: `viewer` query, GitHub: `/user`)
- [ ] Output per provider: status (pass/fail), latency, error message if failed
- [ ] Exit code 0 if all pass, 1 if any fail
- [ ] `--json` flag for machine-readable output

---

## 3. Guided Onboarding Wizard

<!-- canon:system:3 status:draft -->

Replace `canon setup` with a progressive, multi-step wizard that gets the user
to a fully working Canon installation in one session.

### 3.1 Step 1: Repository Detection

<!-- canon:system:3.1 status:todo -->

<!-- canon:ticket:github:527 -->
Detect the current repository state and decide what to do.

#### Acceptance Criteria

- [ ] Detect git remote and extract owner/repo (existing logic from setup)
- [ ] If CANON.yaml exists: offer to reconfigure (preserving existing values as defaults) or skip
- [ ] If CANON.yaml does not exist: proceed to creation
- [ ] Auto-detect doc paths (scan for `docs/`, `specs/`, `doc/`, `documentation/`)
- [ ] Auto-detect existing spec files and report count
- [ ] Print a summary header: "Setting up Canon for {owner}/{repo}"

### 3.2 Step 2: Authentication

<!-- canon:system:3.2 status:todo -->

<!-- canon:ticket:github:528 -->
Check auth state and guide through login if needed.

#### Acceptance Criteria

- [ ] Check `~/.config/canon/credentials.json` for existing credentials
- [ ] If valid credentials: print "Authenticated as {email} ({org})" and continue
- [ ] If expired credentials: attempt token refresh, prompt re-login if refresh fails
- [ ] If no credentials: explain what login unlocks (OAuth integrations, org metrics, ticket sync via backend) and prompt: "Log in now? [Y/n]"
- [ ] If user chooses to log in: run device flow inline (existing `canon login` logic)
- [ ] If user skips login: continue with local-only mode, note limitations
- [ ] Non-interactive mode: skip login prompt, use whatever credentials exist

### 3.3 Step 3: Integration Connection

<!-- canon:system:3.3 status:todo -->

<!-- canon:ticket:github:529 -->
Walk through connecting a ticket system.

#### Acceptance Criteria

- [ ] Ask which ticket system to use: Jira / Linear / GitHub Issues / None (skip)
- [ ] If authenticated: use `canon integrations add` OAuth flow
- [ ] If not authenticated: use `canon integrations add` local flow (API token)
- [ ] After connection: run `canon integrations test` to validate
- [ ] If test fails: offer to retry, reconfigure, or skip with warning
- [ ] Store ticket_system choice in CANON.yaml
- [ ] If user picks "None": explain that ticket sync won't work but spec management still will

### 3.4 Step 4: Configuration

<!-- canon:system:3.4 status:todo -->

<!-- canon:ticket:github:530 -->
Set remaining CANON.yaml options with sensible defaults.

#### Acceptance Criteria

- [ ] Team name: prompt with default from org name or git remote
- [ ] Spec settings: auto_tickets (default: true), require_review (default: true), lifecycle_sync (default: true) — show current defaults, let user adjust
- [ ] Agent settings: doc_updates, pr_analysis, stale_detection — show defaults
- [ ] IDE settings: auto_context, auto_verify — show defaults
- [ ] Advanced users can accept all defaults with Enter (each prompt shows `[default]`)
- [ ] `--defaults` flag accepts all defaults without prompting (for CI)
- [ ] Write CANON.yaml atomically

### 3.5 Step 5: Environment Setup

<!-- canon:system:3.5 status:todo -->

<!-- canon:ticket:github:531 -->
Set up MCP server, agent configs, and IDE integration.

#### Acceptance Criteria

- [ ] Write `.mcp.json` with canon MCP server config (existing logic)
- [ ] Detect IDE/agent platform (Claude Code, Cursor, Copilot, Codex, Gemini) and write appropriate config files
- [ ] Install skills to `.claude/skills/` (or equivalent for other platforms)
- [ ] Attempt MCP server startup validation (spawn, send `tools/list`, check response within 5s)
- [ ] Report capability tier: full (backend + GitHub + DB), standard (GitHub only), local (spec parsing only)
- [ ] If validation fails: print warning with diagnostics, don't block setup

### 3.6 Step 6: First Spec & Validation

<!-- canon:system:3.6 status:todo -->

<!-- canon:ticket:github:532 -->
Create initial content and validate the full installation.

#### Acceptance Criteria

- [ ] If no spec files found: offer to create a template spec from `docs/specs/_template.md`
- [ ] If spec files found: print count and offer to run `canon lint` on them
- [ ] Run all `canon doctor` checks (see section 4) and print results inline
- [ ] Print summary: what was configured, what works, what needs attention

### 3.7 Step 7: Summary & Next Steps

<!-- canon:system:3.7 status:todo -->

<!-- canon:ticket:github:533 -->
Print a clear, actionable summary.

#### Acceptance Criteria

- [ ] Summary shows: files created/modified, integrations connected, validation results
- [ ] "Next steps" section with prioritized actions based on what was skipped or failed:
  - If no login: "Run `canon login` to enable ticket sync and org features"
  - If no integration: "Run `canon integrations add <provider>` to enable ticket sync"
  - If specs exist: "Run `canon sync --dry-run` to preview ticket creation"
  - If no specs: "Create your first spec: `canon new`"
  - Always: "Check health anytime: `canon doctor`"
- [ ] `--json` flag outputs structured summary for automation

---

## 4. `canon doctor` Command

<!-- canon:system:4 status:draft -->

Diagnostic command that checks the health of a Canon installation. Replaces
the doctor command from `setup-ux-improvements.md` with a more comprehensive
implementation.

### 4.1 Check Categories

<!-- canon:system:4.1 status:todo -->

<!-- canon:ticket:github:534 -->
#### Acceptance Criteria

- [ ] **Config checks**: CANON.yaml exists + parses, .mcp.json exists + has canon entry, skills directory exists with skills, doc_paths have spec files
- [ ] **Auth checks**: credentials file exists, token valid/expired, org resolved, GitHub CLI auth status
- [ ] **Integration checks**: for each configured integration, run health check (reuse `canon integrations test` logic)
- [ ] **MCP checks**: MCP server starts, tools/list responds, report capability tier
- [ ] Each check reports: PASS / WARN / FAIL with one-line fix suggestion
- [ ] Checks run in parallel where independent (auth + config can run together)

### 4.2 Output Format

<!-- canon:system:4.2 status:todo -->

<!-- canon:ticket:github:421 -->
#### Acceptance Criteria

- [ ] Default output: colored status table grouped by category
- [ ] `--json` flag: machine-readable JSON with check name, status, message, fix_hint
- [ ] Exit code: 0 = all pass, 1 = any fail, 2 = warnings only
- [ ] Summary line: "X passed, Y warnings, Z failures"
- [ ] `--fix` flag: attempt to auto-fix what's possible (e.g., refresh expired token, reinstall missing skills)

---

## 5. Technical Design

<!-- canon:system:5 status:draft -->

### 5.1 Command Registration

New commands registered in `src/canon/cli/__init__.py`:

```
canon setup          → replaced by guided wizard (backward compatible)
canon init           → alias for setup
canon doctor         → new diagnostic command
canon integrations   → new command group
  ├── list
  ├── add <provider>
  ├── remove <provider>
  └── test [provider]
canon int            → alias for integrations
```

### 5.2 Credential Source Abstraction

New module: `src/canon/cli/integration_manager.py`

```python
@dataclass
class IntegrationInfo:
    provider: str               # jira, linear, github
    source: str                 # "backend", "env_var", "canon_yaml"
    status: str                 # "connected", "configured", "needs_reauth", "error"
    details: str                # human-readable one-liner
    metadata: dict[str, Any]    # provider-specific (site URL, workspace, etc.)

class IntegrationManager:
    """Unified view across all credential sources."""

    async def list_all(self, org: str | None) -> list[IntegrationInfo]:
        """Merge backend + local + env var integrations."""

    async def add(self, provider: str, org: str | None, token: str | None) -> IntegrationInfo:
        """Route to OAuth or local flow based on auth state."""

    async def remove(self, provider: str, org: str | None) -> None:
        """Remove from appropriate source."""

    async def test(self, provider: str, org: str | None) -> TestResult:
        """Health check via backend API or local adapter."""
```

Resolution order for listing matches the adapter factory:
1. CANON.yaml auth_profiles (highest priority display)
2. Backend org_integrations (if authenticated)
3. Environment variables (detected by presence)

When multiple sources configure the same provider, show the active one (highest
priority) with a note about overrides.

### 5.3 OAuth Browser Flow

For `canon integrations add` with backend authentication:

1. Generate state token locally
2. Open browser to `{backend_url}/app/{org}/api/settings/integrations/{provider}/connect?state={state}&cli=true`
3. Backend OAuth callback writes to DB and redirects to a success page
4. CLI polls `GET /app/{org}/api/settings/integrations` every 2s for up to 120s
5. On connection detected: print success and return

The `cli=true` query parameter tells the backend callback to render a
"You can close this tab" page instead of redirecting to the settings UI.

### 5.4 Guided Wizard Architecture

Refactor `src/canon/cli/setup_cmd.py` into a step-based wizard:

```python
@dataclass
class WizardState:
    repo_owner: str | None = None
    repo_name: str | None = None
    authenticated: bool = False
    org: str | None = None
    ticket_system: str | None = None
    integration_connected: bool = False
    config: CanonConfig | None = None
    doctor_results: list[CheckResult] | None = None

class SetupWizard:
    steps: list[WizardStep] = [
        RepoDetectionStep(),
        AuthenticationStep(),
        IntegrationStep(),
        ConfigurationStep(),
        EnvironmentStep(),
        ValidationStep(),
        SummaryStep(),
    ]

    async def run(self, state: WizardState, non_interactive: bool = False):
        for step in self.steps:
            state = await step.execute(state, non_interactive)
```

Each step is independently testable and can be skipped via `--skip-<step>` flags.

### 5.5 Doctor Check Framework

New module: `src/canon/cli/doctor_cmd.py`

```python
@dataclass
class CheckResult:
    name: str
    category: str       # config, auth, integrations, mcp
    status: str         # pass, warn, fail
    message: str
    fix_hint: str | None = None
    fix_action: Callable | None = None  # for --fix mode

class DoctorRunner:
    checks: list[Check]

    async def run_all(self) -> list[CheckResult]:
        # Run independent checks in parallel
        ...
```

### 5.6 CANON.yaml Safe Update

For `canon integrations add` local flow, CANON.yaml updates must preserve
existing content. Use `ruamel.yaml` (already a dependency) for round-trip
YAML editing that preserves comments and formatting.

---

## 6. Rollout Plan

<!-- canon:system:6 status:draft -->

### Phase 1: Integration Commands (foundation)

1. `IntegrationManager` with credential source abstraction
2. `canon integrations list` (all sources)
3. `canon integrations test` (health checks)
4. `canon integrations add` — local flow only (API token, CANON.yaml)

### Phase 2: Backend-Connected Flow

5. `canon integrations add` — OAuth browser flow (requires backend API)
6. `canon integrations remove` (both sources)
7. Backend `cli=true` callback page

### Phase 3: Guided Onboarding

8. Wizard step framework
9. Steps 1-4 (repo detection, auth, integration, config)
10. Steps 5-7 (environment, validation, summary)
11. Replace `canon setup` entry point, keep `init` alias

### Phase 4: Doctor Command

12. Check framework with parallel execution
13. Config + auth + integration + MCP checks
14. `--fix` auto-remediation
15. Wire into wizard step 6

---

## 7. Open Questions

<!-- canon:system:7 status:draft -->

- Should `canon integrations add` support connecting multiple providers in one
  session (e.g., primary Jira + shadow GitHub Issues)?
- Should the wizard detect `.env` files and offer to import integration
  credentials from them?
- Should `canon doctor --fix` be able to run `canon login` if auth is missing,
  or just print the hint?
- Is `ruamel.yaml` acceptable as a dependency, or should we use a simpler
  approach for CANON.yaml updates (regex-based insertion)?
