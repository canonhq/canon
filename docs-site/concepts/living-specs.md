# Living Specs

The core engine that makes "documentation that keeps up" real is the feedback loop — a continuous cycle from spec authoring through code implementation back to spec updates.

## The Feedback Loop

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
Agent analyzes PR against ALL indexed docs                 │
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

## Why Ticket Status Isn't Enough

The key insight: ticket status is a proxy. Code is the truth.

When a PR merges that implements §3.2 Retry Handling, the agent should verify the implementation against the acceptance criteria — not just check whether someone moved a Jira ticket to "Done."

A ticket might be closed because:
- The feature was actually implemented correctly
- Someone clicked "Done" by mistake
- The scope was reduced without updating the spec
- The implementation was partial but "good enough" for the sprint

Canon's agent reads the code and evaluates whether each acceptance criterion is actually satisfied, with evidence (file paths, line numbers, PR references).

## Spec Realization

This is what separates Canon from spec management tools. The agent doesn't just track whether tickets are closed — it evaluates whether **code actually implements what the spec says**.

### How It Works

1. **PR opens** — Agent loads all indexed docs + specs relevant to the changed files
2. **Code analysis** — Agent reads the diff and evaluates it against spec acceptance criteria
3. **Realization assessment** — For each spec section:
   - **Realized**: Code implements the requirement (with evidence: file, line, PR)
   - **Partially realized**: Some but not all acceptance criteria met
   - **Conflicting**: Code contradicts the spec (suggests updating spec or code)
   - **Unrelated**: PR doesn't touch this spec area
4. **Auto-transition** — When all AC in a section are realized, spec status moves to `done` and the linked ticket is closed
5. **Evidence trail** — The agent records which PRs and code locations realize each section

### What the Engineer Sees

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

## Replacing Confluence

Every "Confluence replacement" pitch starts with "import your wiki." That's wrong. You're importing a graveyard.

The adoption path is gradual:

1. **Shadow mode** (Month 1-2) — Install on 5-10 repos. New features get spec files instead of Confluence pages. Confluence stays as-is.
2. **Gravity shift** (Month 3-4) — Engineers ask Canon instead of searching Confluence. PMs notice their specs auto-update when code ships.
3. **The flip** (Month 5-6) — "Just update the spec" replaces "update the Confluence page." Confluence becomes read-only archive.

You don't migrate content. You migrate *workflows*. When the workflow lives in Canon, the content follows naturally. And because Canon verifies docs against code, the content stays accurate — which is why Confluence failed in the first place.

## Related

- **Concept**: [Spec Coverage](/concepts/coverage) — how realization is measured and tracked
- **Concept**: [Agent Mesh](/concepts/agent-mesh) — architecture of the agents that power living specs
- **Concept**: [Delta Tracking](/concepts/delta-tracking) — how status transitions and evidence are recorded
- **Guide**: [Ticket Sync](/guides/ticket-sync) — configuring bidirectional sync with Jira, Linear, GitHub Issues
- **Reference**: [CLI](/reference/cli) — `canon verify` and `canon audit` commands
- **Reference**: [Claude Code Skills](/reference/skills) — `/sw:verify`, `/sw:audit` for agent-assisted verification
