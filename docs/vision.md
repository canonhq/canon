# Canon Vision: AI-Native Enterprise Documentation

## The Core Thesis

Documentation fails because it's a **write-once artifact**. Canon treats docs as **living programs** — all markdown is input, AI agents are the runtime, code is the ground truth, and the repo is the execution environment.

Specs define **intent** — what should be built. Code reveals **reality** — what actually shipped. Other docs (ADRs, guides, READMEs) provide **context** — why decisions were made. The platform closes the loop across all three, continuously evaluating whether intent matches reality and keeping context accurate.

---

## The Spec Framework

Canon adopts an [OpenSpec](https://github.com/Fission-AI/OpenSpec)-inspired structured artifact model. Specs are not freeform wiki pages — they're structured programs that the platform can parse, track, and verify.

### Artifact Types

Each feature or change can be expressed through complementary artifacts:

| Artifact | Purpose | File Pattern |
|----------|---------|-------------|
| **Proposal** | Why this change is needed, scope, impact | `docs/specs/<name>.md` (frontmatter + problem section) |
| **Spec Sections** | What the system must do (requirements + acceptance criteria) | Numbered sections within spec files |
| **Design** | How to implement it (architecture, trade-offs, migration) | `docs/decisions/*.md`, `docs/architecture.md` |
| **Tasks** | Implementation checklist with live ticket links | Acceptance criteria (`- [ ]`) + synced Jira/Linear/GitHub tickets |

### Delta Tracking

Rather than rewriting specs, Canon tracks changes through status transitions and hidden comments:

```markdown
## 3. Idempotency Layer
<!-- canon:system:idempotency status:done -->
<!-- canon:ticket:jira:PAY-142 -->

All payment endpoints must support idempotency keys...

### 3.1 Key Generation
<!-- canon:system:key-gen status:done -->
<!-- canon:ticket:jira:PAY-143 -->
<!-- canon:realized-in:PR#412 src/payments/keys.ts -->

- [x] Generate UUID v4 idempotency keys on client
- [x] Store keys in Redis with 24h TTL
```

The `realized-in` comment is the critical addition — the agent writes it when it verifies that code actually implements the spec section, not just when a ticket is closed.

---

## The Feedback Loop

This is the engine that makes "documentation that keeps up" real:

```
PM writes spec (structured markdown) ─────────────────────┐
  │                                                        │
  ▼                                                        │
Agent indexes all markdown (specs + docs + READMEs)        │
  │                                                        │
  ▼                                                        │
Agent creates tickets from spec sections                   │
  │                                                        │
  ▼                                                        │
Engineer writes code, opens PR                             │
  │                                                        │
  ▼                                                        │
Agent analyzes PR against ALL indexed docs ◄───────────────┤
  │                                                        │
  ▼                                                        │
Agent evaluates: does code realize spec intent?            │
  │  • Compares implementation against acceptance criteria  │
  │  • Checks for conflicts with existing docs             │
  │  • Flags undocumented behavior                         │
  │                                                        │
  ▼                                                        │
Coverage updates, spec status auto-transitions             │
  │  • Section marked "done" based on code analysis        │
  │  • Ticket closed when spec is realized                 │
  │                                                        │
  ▼                                                        │
Doc-update PRs generated for all affected markdown         │
  │  • Specs, READMEs, guides, ADRs — not just specs      │
  │                                                        │
  ▼                                                        │
Stale docs flagged when code changes but docs don't        │
  │                                                        │
  ▼                                                        │
Better indexed knowledge ──────────────────────────────────┘
  (richer context for the next PR analysis)
```

**The key insight:** ticket status is a proxy. Code is the truth. When a PR merges that implements §3.2 Retry Handling, the agent should verify the implementation against the acceptance criteria — not just check whether someone moved a Jira ticket to "Done."

---

## All-Markdown Knowledge Base

Canon indexes **every markdown file** in the repository, not just specs. All docs become part of the platform's knowledge and feed into agent analysis.

### What Gets Indexed

| Doc Type | Examples | How the Agent Uses It |
|----------|---------|----------------------|
| **Specs** | `docs/specs/*.md` | Primary intent — tracks sections, AC, tickets, realization |
| **ADRs** | `docs/decisions/*.md` | Context for "why was it built this way?" queries |
| **Architecture docs** | `docs/architecture.md` | System context for cross-cutting PR analysis |
| **READMEs** | `README.md`, `docs/*.md` | Onboarding context, API docs, usage guides |
| **Changelogs** | `CHANGELOG.md` | Release history for staleness detection |
| **Runbooks** | `docs/runbooks/*.md` | Operational context the agent can surface |
| **Contributing guides** | `CONTRIBUTING.md` | Process docs the agent keeps current |

### Configuring Doc Paths

```yaml
# CANON.yaml
specs:
  doc_paths:
    - "docs/specs/*.md"          # specs (always)
    - "docs/**/*.md"             # all docs recursively
    - "README.md"                # root readme
    - "CHANGELOG.md"             # changelog
    - "CONTRIBUTING.md"          # contributing guide
```

The default (`docs/specs/*.md`) covers specs only. Teams opt in to broader indexing as they see value.

---

## Spec Realization: Code as Ground Truth

This is what separates Canon from spec management tools. The agent doesn't just track whether tickets are closed — it evaluates whether **code actually implements what the spec says**.

### How It Works

1. **PR opens** — Agent loads all indexed docs + specs relevant to the changed files
2. **Code analysis** — Agent reads the diff and evaluates it against spec acceptance criteria
3. **Realization assessment** — For each spec section, the agent determines:
   - **Realized**: Code implements the requirement (with evidence: file, line, PR)
   - **Partially realized**: Some but not all acceptance criteria met
   - **Conflicting**: Code contradicts the spec (suggests updating spec or code)
   - **Unrelated**: PR doesn't touch this spec area
4. **Auto-transition** — When all AC in a section are realized, spec status moves to `done` and the linked ticket is closed
5. **Evidence trail** — The agent records which PRs and code locations realize each section

### PR Comment (Enhanced)

```
Spec Context

This PR relates to:
  payments-overhaul.md §3.2 (Retry Handling) — PAY-144

Realization:
  ✅ §3.2 AC1: "Exponential backoff" — implemented in src/payments/retry.ts:42
  ✅ §3.2 AC2: "Max 3 retries" — BUT implementation uses max 5. Spec or code?
  ⬜ §3.2 AC3: "Preserve idempotency key across retries" — not addressed in this PR

Other docs affected:
  docs/architecture.md §Retry Strategy — references "3 retries", now stale
  README.md §Error Handling — doesn't mention PaymentTimeoutError

[Update spec] [Create doc PR] [Dismiss]
```

---

## Architecture: Three Tiers

```
┌─────────────────────────────────────────────────┐
│              ORG BRAIN (Tier 3)                  │
│                                                  │
│  Knowledge graph · Cross-repo search · Patterns  │
│  "Who owns payments?" · "What decided X?"        │
│  Org-wide spec coverage · Dependency map          │
│  Executive dashboards · Compliance reports        │
├─────────────────────────────────────────────────┤
│              AGENT MESH (Tier 2)                 │
│                                                  │
│  Agent-to-agent communication · Event bus         │
│  "Repo A's spec references Repo B's API"         │
│  Cross-team impact analysis · Conflict detection  │
│  Shared vocabulary / taxonomy enforcement         │
├─────────────────────────────────────────────────┤
│              REPO AGENTS (Tier 1)                │
│                                                  │
│  All-markdown indexing · PR analysis · Doc PRs    │
│  Spec realization · Ticket sync · Stale detection │
│  MCP server · Slack Q&A · Coverage metrics        │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐           │
│  │Repo 1│ │Repo 2│ │Repo 3│ │ ×300 │           │
│  └──────┘ └──────┘ └──────┘ └──────┘           │
└─────────────────────────────────────────────────┘
```

**Tier 1** is where you start (the MVP). **Tier 2** is the moat. **Tier 3** is the platform.

### Platform Components

```
┌──────────────┐  ┌──────────────┐  ┌─────────────┐
│  Doc Engine   │  │ Agent Runner │  │  Knowledge  │
│               │  │              │  │    Base     │
│ Parse all md  │  │ Claude calls │  │ Vector DB   │
│ Track specs   │  │ PR analysis  │  │ BM25 index  │
│ Diff & delta  │  │ Realization  │  │ Hybrid      │
│ Verify intent │  │ Doc gen      │  │ search      │
└───────────────┘  └──────────────┘  └─────────────┘
         │               │               │
    ┌────┴───┐     ┌─────┴────┐    ┌─────┴────┐
    │ Tickets│     │  Comms   │    │Dev Tools │
    │        │     │          │    │          │
    │ Jira   │     │ Slack    │    │ MCP      │
    │ Linear │     │ Teams    │    │ VS Code  │
    │ GitHub │     │ Email    │    │ Cursor   │
    └────────┘     └──────────┘    └──────────┘
```

---

## Replacing Confluence: Don't Migrate. Outgrow.

Every "Confluence replacement" pitch starts with "import your wiki." That's wrong. You're importing a graveyard. 80% of Confluence pages are stale, undiscoverable, and nobody knows who owns them.

**Month 1-2: Shadow mode** — Install on 5-10 repos. New features get spec files instead of Confluence pages. Confluence stays as-is. All repo markdown is indexed and searchable from day one.

**Month 3-4: Gravity shift** — Engineers ask Canon instead of searching Confluence. PMs notice their specs auto-update when code ships. The agent catches stale docs before anyone reads them.

**Month 5-6: The flip** — "Just update the spec" replaces "update the Confluence page." Confluence becomes read-only archive. Canon is the source of truth because it's the only system that actually knows what's implemented.

**The key insight:** You don't migrate content. You migrate *workflows*. When the workflow lives in Canon, the content follows naturally. And because Canon verifies docs against code, the content stays accurate — which is why Confluence failed in the first place.

---

## The GitHub App

### Webhooks

- `push` — watches all configured markdown changes (specs + docs)
- `pull_request` — opened, synchronize, merged, closed
- `issues` — created, closed, labeled (reverse sync trigger)
- `issue_comment` — `@canon` commands
- `installation` — app lifecycle (install, suspend, remove)
- `installation_repositories` — repos added/removed

### Permissions

- Contents: read/write (code + docs, doc-update PRs)
- Pull requests: read/write (doc PRs, comments)
- Issues: read/write (generated tickets)
- Metadata: read
- Members: read (ownership graph)

---

## Ticket Sync: Bidirectional, Not Just Export

Canon maintains a **live link** between spec sections and tickets.

### Spec → Tickets (forward sync)

```markdown
## 3. Idempotency Layer
<!-- canon:ticket:jira:PAY-142 -->
<!-- canon:system:idempotency status:in_progress -->

All payment endpoints must support idempotency keys...

### 3.1 Key Generation
<!-- canon:ticket:jira:PAY-143 -->
<!-- canon:system:key-gen status:done -->
<!-- canon:realized-in:PR#412 src/payments/keys.ts -->

### 3.2 Retry Handling
<!-- canon:ticket:jira:PAY-144 -->
<!-- canon:system:retry status:in_progress -->
```

Hidden HTML comments track the bidirectional link. Engineers never think about this — the agent manages it.

### Tickets → Spec (reverse sync)

- Engineer closes PAY-143 → agent verifies against code, updates spec status
- PM adds acceptance criteria in Jira → agent opens PR to update spec section
- Unmapped ticket created → agent asks: "Should I add a spec section, or is this out of scope?"

### Code → Spec (realization sync)

- PR merges implementing §3.1 → agent analyzes code, marks section as realized
- Code changes contradict §3.2 → agent flags conflict, suggests spec or code update
- New behavior introduced without spec → agent asks: "Should I add a spec section for this?"

### Enterprise Mapping

The default sync path is simple — one ticket system, one project, fixed status mappings. But enterprise orgs need more:

- **Custom workflows**: Map spec states to org-specific ticket statuses (e.g., "In QA", "Awaiting Deployment") instead of the built-in defaults
- **Field mapping**: Flow spec metadata (team, tags, owner) into ticket fields (component, labels, assignee) and Jira custom fields
- **Hierarchy templates**: Map spec section depth to issue types (h2 → Epic, h3 → Story, h4 → Sub-task) with auto-parenting
- **Multi-system routing**: Route sections to different ticket systems based on tags, team, or file path — e.g., eng work to Jira, OSS to GitHub Issues
- **Org-wide defaults**: Org-level config that repos inherit and override, so 300 repos don't each repeat the same status mapping

All of this is optional. Repos without custom config behave identically to the simple path. See the [Ticket Mapping Model spec](specs/ticket-mapping-model.md) for the full design.

### Adapter Pattern

```
┌──────────────────────────────────┐
│        Canon Core           │
│   (speaks "spec items")         │
├──────────────────────────────────┤
│    Ticket Adapter Interface      │
│                                  │
│  create_ticket(spec_item)        │
│  update_ticket(id, changes)      │
│  sync_status(id) → status        │
│  link_pr(ticket_id, pr_url)      │
│  close_ticket(id, evidence)      │
│  query_tickets(filter)           │
├────────┬────────┬────────┬───────┤
│  Jira  │ Linear │ GitHub │ Azure │
│Adapter │Adapter │Issues  │DevOps │
│        │        │Adapter │Adapter│
└────────┘────────┘────────┘───────┘
```

---

## Access Control

Canon supports multiple authentication surfaces and role-based authorization.

### Authentication

- **Web**: Auth0 Universal Login with multiple identity providers (GitHub, Google Workspace, email magic link). Short-lived access tokens (in memory) with rotating refresh token cookies.
- **CLI**: Device Authorization Grant (RFC 8628) via `canon login`. Tokens stored locally at `~/.config/canon/credentials.json`. API keys supported for CI/headless use.
- **API**: Bearer tokens (JWT or API key with `sw_` prefix). GitHub App JWT for webhook verification.

### Authorization

The platform defines three roles — **Viewer**, **Editor**, **Admin** — each mapping to a permission set (specs read, specs write, org manage). Roles are assigned per-org via an `org_members` table, seeded from Auth0 claims on first login and overridable by org admins.

All auth events (login, logout, token refresh, role changes, permission denials) are logged to a structured audit trail for security review.

See the [Auth Hardening spec](specs/auth-hardening.md) for the full design.

---

## Developer Experience

### Repo Structure

```
my-service/
├── src/
├── tests/
├── docs/
│   ├── specs/
│   │   ├── payments-overhaul.md    ← living spec (tracked, ticketed)
│   │   └── auth-migration.md       ← living spec
│   ├── decisions/
│   │   └── 2026-01-datastore.md    ← ADR (indexed, searchable)
│   ├── architecture.md             ← agent-maintained
│   ├── runbooks/
│   │   └── deploy-payments.md      ← operational doc (indexed)
│   └── onboarding.md               ← agent-generated
├── README.md                        ← indexed, staleness-tracked
├── CHANGELOG.md                     ← indexed
├── CANON.yaml                  ← config
└── ...
```

### CANON.yaml

```yaml
team: payments
ticket_system: jira
project_key: PAY
slack_channel: "#payments-eng"
specs:
  auto_tickets: true
  require_review: true
  doc_paths:
    - "docs/**/*.md"
    - "README.md"
    - "CHANGELOG.md"
    - "CONTRIBUTING.md"
agents:
  doc_updates: true
  pr_analysis: true
  stale_detection: 30d
  realization_check: true
```

### PR Comments

Engineer opens a PR. Within 60 seconds, the bot comments:

```
Spec Context

This PR relates to:
  payments-overhaul.md §3.2 (Retry Handling) — PAY-144

Realization:
  ✅ AC1: Exponential backoff — implemented (src/payments/retry.ts:42)
  ⚠️ AC2: Max 3 retries — code uses max 5. Update spec or code?
  ⬜ AC3: Preserve idempotency key — not addressed in this PR

Other docs affected:
  README.md §Error Handling — missing PaymentTimeoutError
  docs/architecture.md §Retry — references "3 retries", now stale

[Update spec] [Create doc PR] [Dismiss]
```

Not a wall of noise. Contextual, actionable, dismissible.

### MCP Server (Coding Agent Integration)

Coding agents (Claude Code, Cursor, VS Code Copilot) connect via MCP to query the Canon knowledge base:

```
> "What does the spec say about retry handling?"

  From docs/specs/payments-overhaul.md §3.2:
  Failed payments retry with exponential backoff, max 3 retries,
  with jitter. Idempotency key must be preserved across retries.

  Current implementation (src/payments/retry.ts:42):
  Max retries is set to 5, which conflicts with the spec.

  Related ticket: PAY-144 (in progress, assigned to @marcus)

  Related docs:
  • docs/architecture.md §Retry Strategy
  • docs/decisions/2026-01-retry-policy.md
```

---

## PM Workflows

### 1. Web Editor (Notion-like, Git-backed)

PMs edit in a rich editor. Under the hood, it commits to Git. They never see a terminal, branch, or merge conflict.

### 2. Claude Chat (AI PM partner)

Claude knows the entire org's doc corpus — specs, ADRs, architecture docs, everything indexed. When a PM starts a new spec, Claude surfaces: existing related work, relevant ADRs, compliance requirements, open epics to coordinate with.

### 3. Spec Reviews (async, in-platform)

Engineering leads review for feasibility. Design reviews for UX. Other PMs review for cross-team conflicts. Claude generates review summaries.

---

## Slack / Teams Integration

### Philosophy: Pull, not push.

**Does NOT:** Spam channels, post walls of text, notify on routine activity.

**DOES:**

1. **Answer questions** — `@canon how does our rate limiting work?` → cited answer from specs + docs + code
2. **Targeted alerts** — only when humans need to decide (spec conflicts, stale detection, realization failures)
3. **Weekly digests** — opt-in, per team, spec coverage + realization progress + stale doc summary
4. **Microsoft Teams parity** — Adaptive Cards, Teams tab app, Copilot integration

---

## The Network Effect

```
1 repo   → nice spec workflow, all docs searchable
10 repos → cross-repo references, shared knowledge base
50 repos → the agent mesh becomes indispensable
300 repos → the org brain knows more than any human
            about how the company's software works
```

Each new repo makes every existing repo's agent smarter. Each indexed doc enriches the knowledge base. Each PR analysis teaches the platform what changed. This is the moat.

---

## The Integration Map

```
                        ┌──────────────┐
                        │  Canon   │
                        │   Platform    │
                        └──────┬───────┘
               ┌───────────────┼───────────────┐
               │               │               │
        ┌──────▼──────┐ ┌─────▼─────┐ ┌───────▼───────┐
        │   Source     │ │  Tickets  │ │ Communication │
        │              │ │           │ │               │
        │ GitHub ✦     │ │ Jira      │ │ Slack         │
        │ GitLab       │ │ Linear    │ │ Teams         │
        │ Bitbucket    │ │ GH Issues │ │ Email digest  │
        │ Azure DevOps │ │ Shortcut  │ │               │
        └──────────────┘ └───────────┘ └───────────────┘
               │               │               │
        ┌──────▼──────┐ ┌─────▼─────┐ ┌───────▼───────┐
        │   Dev Tools  │ │  PM Tools │ │   Identity    │
        │              │ │           │ │               │
        │ Claude Code  │ │ Figma*    │ │ Okta/Azure AD │
        │ VS Code ext  │ │ Miro*     │ │ GitHub SSO    │
        │ JetBrains    │ │ Loom*     │ │ SCIM          │
        │ Cursor       │ │           │ │               │
        └──────────────┘ └───────────┘ └───────────────┘

        ✦ = launch integration    * = future / community
```

---

## Pricing

No per-seat pricing. Ever. That's the positioning wedge against Atlassian.

| Tier | Target | Pricing |
|------|--------|---------|
| Repo Agents (Tier 1) | Individual teams | Free for 3 repos, $50/repo/mo |
| Agent Mesh (Tier 2) | Engineering orgs | $500/mo base + $20/repo/mo |
| Org Brain (Tier 3) | Enterprise | Custom — $5-15k/mo |

---

## What This Means for the Experiment

The platform vision is big. But the test is still small:

1. **Prove the feedback loop works** — does code-aware spec realization actually keep docs accurate?
2. **Prove all-markdown indexing creates a gravity well** — do teams start relying on Canon as the single search surface?
3. **Prove PMs will write structured specs** — this is the input bottleneck
4. **Prove the PR integration feels natural to engineers** — not another notification to ignore

If those hold, the mesh and brain are engineering problems, not market-risk problems. The hard question is adoption, not architecture.
