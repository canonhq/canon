---
title: "Canon Actions — Backend API Contract"
status: draft
owner: ng
team: platform
ticket_project: null
created: 2026-04-11
updated: 2026-04-11
tags: [api, backend, github-actions, ai-gateway, auth]
depends_on: [github-actions-suite]
---

# Canon Actions — Backend API Contract

Companion design doc for `github-actions-suite.md` §3.2. Defines the backend
endpoints that GitHub Actions call to run Claude-powered operations without
requiring users to hold their own Anthropic API keys.

## 1. Background

The `canon audit` CLI currently calls Claude directly using a local
`ANTHROPIC_API_KEY`. This works for self-hosted deployments but is the wrong
default for the GitHub Actions suite because:

1. **Cost policy**: Claude spend needs to sit on the Canon managed-cloud bill
   (or the customer's Canon subscription), not on each user's personal
   Anthropic account.
2. **Key hygiene**: Distributing `ANTHROPIC_API_KEY` as a GitHub secret for
   every repo that wants Canon in CI multiplies the surface area of a
   credential that should be tightly held.
3. **Observability**: Runs going through the backend can be tracked against
   a Canon org, tagged with the triggering repo/PR/workflow, and surfaced in
   the Canon dashboard. Direct-to-Anthropic calls are invisible to Canon.
4. **Failover and routing**: The backend owns AI Gateway routing, provider
   failover, and rate limiting. Actions that call Claude directly bypass
   all of it.

This spec defines the minimum endpoint set the Canon backend must expose for
the Actions suite to function, plus the CLI-level switch that routes between
backend-mediated and local Anthropic calls.

## 2. Scope

**In scope**

- `POST /v1/audit` — run `canon audit` semantics on a repo snapshot and return
  structured drift + proposed updates.
- `POST /v1/verify` — run Claude-powered AC evaluation against a codebase
  snapshot (the "audit-lite" operation used when a caller wants evaluation
  without the full drift-reconciliation flow).
- Authentication contract: `CANON_TOKEN` bearer, OIDC-compatible issuance,
  self-hosted override via `canon-api-url`.
- CLI-level routing: when does `canon audit` / `canon verify` hit the backend
  vs. call Anthropic locally.

**Out of scope**

- `/v1/sync`, `/v1/status`, and other read-only endpoints — not needed by the
  Actions suite, tracked separately.
- Billing metering details — covered by `managed-cloud-pricing.md`.
- Backend infra (hosting, scaling, caching) — implementation detail.
- OAuth app flows — Actions use static `CANON_TOKEN` secrets, not interactive
  OAuth. User-interactive OAuth is a separate concern.

## 3. Requirements

### 3.1 Authentication Model
<!-- canon:system:3.1 status:draft -->

Actions authenticate with a `CANON_TOKEN` bearer. Tokens are issued by the
Canon backend and scoped to a single Canon org (or a single repo, for
fine-grained access).

#### Acceptance Criteria

- [ ] `POST /v1/audit` and `POST /v1/verify` require `Authorization: Bearer <CANON_TOKEN>` headers.
- [ ] Tokens are scoped to a Canon org; the backend resolves `org_id` from the token.
- [ ] The token claim includes an optional `repo` scope field (`owner/repo`). When set,
      the backend rejects requests whose `repo` body field doesn't match.
- [ ] Token issuance is covered by a new CLI path: `canon auth tokens create --name <name> --scope repo:<owner/repo>`
      returns a token suitable for storing as a GitHub secret.
- [ ] Tokens can be revoked via `canon auth tokens revoke <name>` and via the Canon dashboard.
- [ ] Expired or revoked tokens return `401 Unauthorized` with a machine-readable error code
      (`auth.token_expired`, `auth.token_revoked`, `auth.token_not_found`).
- [ ] Rate limiting is per-org, not per-token — so multiple repos sharing an org token
      can't trivially circumvent limits by cycling tokens.

### 3.2 `POST /v1/audit` Endpoint
<!-- canon:system:3.2 status:draft -->

Runs full `canon audit` semantics: analyzes specs against a codebase snapshot,
identifies drift between code reality and spec statuses, and proposes
structured updates.

#### Request

```
POST /v1/audit
Authorization: Bearer <CANON_TOKEN>
Content-Type: application/json

{
  "repo": "owner/name",
  "ref": "commit-sha-or-branch",
  "specs": [
    {
      "path": "docs/specs/oidc-migration.md",
      "content": "...raw markdown..."
    }
  ],
  "context": {
    "recent_commits": [
      {"sha": "...", "message": "...", "files": ["..."]}
    ],
    "changed_files": ["src/canon/auth/oidc.py"]
  },
  "options": {
    "dry_run": true,
    "update_acs": true,
    "spec_filter": "oidc-migration"
  }
}
```

#### Response

```
200 OK
Content-Type: application/json

{
  "run_id": "uuid",
  "drift": [
    {
      "spec": "docs/specs/oidc-migration.md",
      "section_id": "3-token-exchange",
      "current_status": "todo",
      "evaluated_status": "done",
      "evidence": [
        {"pr": 386, "file": "src/canon/auth/oidc.py", "lines": "42-58"}
      ],
      "confidence": "high"
    }
  ],
  "proposed_updates": [
    {
      "spec": "docs/specs/oidc-migration.md",
      "section_id": "3-token-exchange",
      "changes": [
        {"type": "status_comment", "from": "status:todo", "to": "status:done"},
        {"type": "realization_comment", "section_id": "3.1", "insert_after_line": 45,
         "text": "<!-- canon:realized-in:PR#386 file:src/canon/auth/oidc.py -->"}
      ]
    }
  ],
  "usage": {
    "input_tokens": 12450,
    "output_tokens": 820,
    "model": "claude-sonnet-4-6",
    "cost_usd": 0.042
  }
}
```

#### Acceptance Criteria

- [ ] Endpoint accepts JSON request with `repo`, `ref`, `specs[]`, `context`, `options`
      and validates against a pydantic request model.
- [ ] Spec payloads are limited to 500KB each and 50 specs per request;
      larger payloads return `413 Payload Too Large`.
- [ ] The endpoint runs Claude via the internal AI SDK / AI Gateway wiring
      and returns structured drift + proposed_updates arrays.
- [ ] Response includes a `run_id` that appears in the Canon dashboard for traceability.
- [ ] Response includes `usage` breakdown (tokens, model, cost_usd) so CLI/action
      callers can log cost per run.
- [ ] When `options.dry_run` is true, the backend does not persist any side-effects
      beyond logging the run.
- [ ] When `options.dry_run` is false, the backend may additionally update Canon's
      realization database with the evidence found; the *action* is still responsible
      for applying the proposed edits to the user's repo via PR or issue.
- [ ] Long-running requests stream SSE with interim progress events (`phase: analyzing`,
      `phase: evaluating`, `phase: complete`) so action step summaries can show progress.
- [ ] 5xx responses include a `retry_after` hint when transient (Claude rate limit,
      gateway 503), and actions retry with backoff.

### 3.3 `POST /v1/verify` Endpoint
<!-- canon:system:3.3 status:draft -->

Runs a lighter variant of audit: evaluates a specific set of ACs against a
code snapshot without proposing spec edits. Used by the `verify` action when
Claude-powered evaluation is explicitly requested (the default `verify` action
flow is static-only and never hits this endpoint).

#### Acceptance Criteria

- [ ] Same auth model as `/v1/audit`.
- [ ] Request body accepts a subset: `repo`, `ref`, `acs[]` (each with
      `spec_path`, `section_id`, `text`), and `context.changed_files`.
- [ ] Response returns one `evaluation` object per input AC with
      `{status: realized | partial | not_realized | unclear, evidence, reasoning}`.
- [ ] Evaluation is read-only — no drift, no proposed updates, no persistence.
- [ ] Usage breakdown included (same shape as /v1/audit).

### 3.4 CLI Routing Switch
<!-- canon:system:3.4 status:draft -->

The `canon audit` and `canon verify` CLI commands must transparently switch
between backend-mediated and local Anthropic calls based on environment
configuration.

#### Acceptance Criteria

- [ ] When `CANON_TOKEN` is set in the environment (or stored in the CLI
      credential store via `canon login`), `canon audit` POSTs to
      `${CANON_API_URL}/v1/audit` instead of calling Anthropic directly.
- [ ] When `CANON_TOKEN` is unset and `ANTHROPIC_API_KEY` is set, the CLI
      falls back to the local code path (today's default — unchanged for
      self-hosted users).
- [ ] When neither is set, the CLI errors with a clear message listing both
      options and links to docs.
- [ ] `CANON_API_URL` defaults to `https://api.canonhq.co` and can be
      overridden via `canon login --api-url` or the `CANON_API_URL` env var.
- [ ] The switch is a single point in `src/canon/cli/audit.py` (and the equivalent
      in `verify.py`), not scattered across call sites.
- [ ] An integration test mocks the backend endpoint and verifies the CLI
      sends the expected request shape.

### 3.5 Self-Hosted Backend Compatibility
<!-- canon:system:3.5 status:draft -->

Self-hosted Canon deployments must be able to serve the same `/v1/audit` and
`/v1/verify` endpoints so GitHub Actions work against them via `canon-api-url`.

#### Acceptance Criteria

- [ ] The endpoint handlers live in the OSS-eligible `src/canon/web/` or equivalent
      path so they ship with the self-hosted distribution.
- [ ] Self-hosted deployments that lack an AI Gateway configuration gracefully
      fall back to calling Anthropic via `ANTHROPIC_API_KEY` server-side,
      with a runtime warning logged.
- [ ] The minimum configuration for a self-hosted backend to serve the Actions
      suite is documented in `docs/self-hosting.md` and linked from the
      github-actions docs section.
- [ ] A smoke test against a locally-run self-hosted backend is part of the
      CI matrix.

### 3.6 Usage Metering and Cost Attribution
<!-- canon:system:3.6 status:draft -->

#### Acceptance Criteria

- [ ] Every request is metered against the authenticated org with tags:
      `repo`, `ref`, `workflow_name` (from request body), `run_id`, `model`.
- [ ] Metering data is persisted for ≥90 days and queryable via
      `canon auth usage --since <date>`.
- [ ] Rate limiting per org returns `429 Too Many Requests` with a
      `Retry-After` header; actions surface this as a neutral check result,
      not a failure.
- [ ] The `usage.cost_usd` field in the response reflects true marginal cost
      including any markup; this is the number shown to users in the
      dashboard.

## 4. Technical Design

<!-- canon:system:4 status:draft -->

### 4.1 Endpoint implementation layer

Endpoints live in `src/canon/web/api/v1/actions.py` (new), registered on the
existing FastAPI app. They are thin handlers that:

1. Authenticate the `CANON_TOKEN`, resolve `org_id`.
2. Enforce rate limits and payload size limits.
3. Construct a `canon.agent.analyzer.AuditRun` (or equivalent for verify) and
   delegate to the existing internal analyzer module. The analyzer module
   already knows how to call Claude via the agent client — it does not need
   to be rewritten.
4. Stream the run via SSE or return a single JSON blob on completion.
5. Emit a usage record via the existing analytics pipeline
   (`canon.analytics`), tagged with `surface: github-action`.

### 4.2 Analyzer reuse

The existing `canon.agent.analyzer` and `canon.cli.audit.run_audit` functions
contain the audit logic. The backend endpoint should **call into the same
analyzer code** that the CLI already uses, not duplicate the logic. The
refactor required:

- Extract the "run analysis, return structured drift" core from `run_audit`
  into a pure function that takes parsed specs + a codebase snapshot +
  options, and returns a typed result.
- The CLI command becomes a thin wrapper: discover local specs, build the
  snapshot, call the core, format for the terminal.
- The backend endpoint becomes another thin wrapper: parse the request,
  build a snapshot from the payload, call the core, serialize to JSON.

This refactor is tracked as a prerequisite in §5 Rollout.

### 4.3 CLI switch location

```python
# src/canon/cli/audit.py
def run_audit(...):
    if _should_use_backend():
        return _run_audit_via_backend(...)
    return _run_audit_local(...)


def _should_use_backend() -> bool:
    return (
        os.environ.get("CANON_TOKEN")
        or load_credential_store().has_token()
    )
```

The two internal functions share the same analyzer core (§4.2) but differ in
**how they produce the codebase snapshot**:

- `_run_audit_local` walks the filesystem and calls Claude directly.
- `_run_audit_via_backend` serializes the specs and git-diff-based context
  into a request, POSTs to `/v1/audit`, and streams the response.

### 4.4 Error handling and idempotency

- Every request carries an optional `Idempotency-Key` header. If present, the
  backend deduplicates identical requests within a 10-minute window. This
  protects against action retries re-running Claude and double-billing.
- Transient failures (5xx, 429) are surfaced with `retry_after` hints so the
  action can back off rather than hard-failing.
- Persistent failures (4xx other than 429, or 5xx after retries) result in a
  neutral check-run conclusion with the error message in the step summary.
  The action does not mark the check as failed unless the user opts in via
  `fail-on: error`.

## 5. Rollout Plan

<!-- canon:system:5 status:draft -->

### Phase 1 — Analyzer refactor (unblocks everything)

Extract the pure analyzer core from `run_audit` so both the CLI and the new
backend endpoint can call it without duplicating logic. No new endpoints yet.
No observable change to users.

### Phase 2 — `/v1/audit` endpoint (MVP)

Ship the endpoint, the CLI switch, token issuance via `canon auth tokens`,
and basic rate limiting. Self-hosted fallback works by default. Dogfooded by
the `canon audit` CLI — same command, new code path when a token is present.

### Phase 3 — `/v1/verify` endpoint

Added after the audit endpoint is stable. Lighter-weight, narrower surface
area. Needed by the optional Claude-powered mode of the `verify` action.

### Phase 4 — SSE streaming + idempotency keys

Incremental hardening after the basic endpoint is in production for a week
or two. Actions that poll for long-running audit runs start consuming the
SSE stream. Idempotency keys ship in this phase.

## 6. Open Questions

- **Token issuance UX**: should `canon auth tokens create` open a browser flow
  (like `gh auth login`), or accept a flag-driven invocation for CI-friendly
  provisioning? Lean toward supporting both.
- **Spec payload size**: 500KB per spec / 50 specs per request is a guess.
  Needs validation against the largest real canon-private specs.
- **SSE vs. polling**: some orgs block long-lived connections through their
  outbound proxies. Polling is the fallback. Which ships first?
- **Org-scoped vs repo-scoped tokens**: org-scoped is simpler but less
  granular. For enterprise customers with multi-tenant Canon orgs, per-repo
  scoping may be required from day one.
