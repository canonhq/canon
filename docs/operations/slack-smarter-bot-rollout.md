# Slack Smarter-Bot v1 Rollout Runbook

Covers the `work_context` coordinator path added in PR #671. The feature is
flag-gated (default OFF). Production behavior is unchanged until the flag is
flipped.

---

## Pre-flight checklist

- [ ] **Slack App manifest scopes**: `channels:history` and `groups:history`
  added (see _Slack App manifest update_ below)
- [ ] **Env vars present on the deployment**:
  - `GITHUB_OWNER` — GitHub org/owner for context fetches
  - `GITHUB_REPO` — default repo for PR/commit context
  - `SLACK_BOT_ENABLED` / `SLACK_BOT_TOKEN` + `SLACK_SIGNING_SECRET` — bot
    must already be running
- [ ] **DB migration applied**: `0016_slack_dm_prompts` — run
  `uv run python -m canon.db.migrations` or confirm via `canon doctor`
- [ ] Image version includes the PR #671 changes (check pod image digest)

---

## Slack App manifest update

The `work_context` loaders need read access to channel/group history to fetch
thread context. Two new OAuth scopes are required:

| Scope | Reason |
|---|---|
| `channels:history` | Read messages in public channels the bot is in |
| `groups:history` | Read messages in private channels the bot is invited to |

**Steps:**

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and select the Canon
   app.
2. Navigate to **OAuth & Permissions** → **Scopes** → **Bot Token Scopes**.
3. Add `channels:history` and `groups:history`.
4. Click **Save Changes**.
5. Slack will prompt you to **reinstall** the app to your workspace — click
   **Allow** to issue a new bot token with the expanded scopes. The existing
   `SLACK_BOT_TOKEN` remains valid until reinstallation; once you reinstall,
   update the token in Doppler if it rotated.
6. For workspaces where Canon was distributed via Slack App Directory or
   org-wide install, users will see a re-authorization prompt. See
   [Slack docs: Adding scopes to a distributed app](https://api.slack.com/authentication/oauth-v2#asking-for-permissions).

> Note: adding scopes to an existing production app requires re-authorization.
> Coordinate with customers before flipping the feature flag so they aren't
> surprised by the permission prompt.

---

## Per-customer enablement

Two ways to enable the flag. Use whichever matches your deployment pattern:

### A. CANON.yaml (per-repo, preferred for customer-specific config)

Add or update the `slack` section in the customer's `CANON.yaml`:

```yaml
slack:
  work_context:
    enabled: true
```

This takes effect on the next app startup (or if hot-reload is configured).

### B. Env var via Helm / Doppler (cluster-wide, faster for A/B testing)

Set `SLACK_WORK_CONTEXT_ENABLED_OVERRIDE=true` in Doppler (project `canon/prd`)
or via Helm values:

```yaml
# values-production.yaml or customer override
slack:
  workContextEnabledOverride: "true"
```

Then redeploy:

```bash
helm upgrade canon chart/canon -f chart/canon/values-production.yaml \
  --set slack.workContextEnabledOverride=true
```

The env var takes **precedence over CANON.yaml**, making it the fastest way to
flip the flag without a code change.

---

## Rollout sequence

1. **Dogfood** (internal) — enable for `canonhq` workspace. Monitor for 1 week.
2. **Design partners** (2–3 customers) — enable via CANON.yaml or env override.
   Collect feedback on response quality and latency.
3. **Default-on flip** — set `work_context.enabled: true` in the base
   `CANON.yaml` shipped in the image (or flip `workContextEnabledOverride` to
   `"true"` in `values-production.yaml`). At this point all customers get the
   coordinator path.

Between steps 1→2 and 2→3, validate PostHog metrics (see _Validation checks_).

---

## Validation checks per customer

Run these PostHog HogQL queries after enabling for each customer. Replace
`7d` with your monitoring window.

### Mention success rate by intent (7d)

```sql
SELECT
  properties.intent AS intent,
  countIf(properties.success = true) AS successes,
  count() AS total,
  round(100.0 * countIf(properties.success = true) / count(), 1) AS success_pct
FROM events
WHERE event = 'slack_mention_handled'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY intent
ORDER BY total DESC
```

### Work context source fetch duration + errors (7d)

```sql
SELECT
  properties.source AS source,
  quantile(0.50)(properties.duration_ms) AS p50_ms,
  quantile(0.95)(properties.duration_ms) AS p95_ms,
  countIf(properties.error_type IS NOT NULL) AS errors,
  properties.error_type AS error_type
FROM events
WHERE event = 'work_context_source_fetched'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY source, error_type
ORDER BY source, errors DESC
```

### Work context assembly — items after cap (7d)

```sql
SELECT
  quantile(0.50)(properties.total_items_after_cap) AS p50_items,
  quantile(0.95)(properties.total_items_after_cap) AS p95_items,
  count() AS total_assemblies
FROM events
WHERE event = 'work_context_assembled'
  AND timestamp >= now() - INTERVAL 7 DAY
```

### Slash command usage by subcommand (30d)

```sql
SELECT
  properties.subcommand AS subcommand,
  count() AS invocations
FROM events
WHERE event = 'slack_command_invoked'
  AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY subcommand
ORDER BY invocations DESC
```

### Identity link adoption (30d)

```sql
SELECT
  toStartOfDay(timestamp) AS day,
  count() AS links
FROM events
WHERE event = 'slack_identity_linked'
  AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day
ORDER BY day
```

> These are copy-paste queries for ad-hoc exploration. Build a saved PostHog
> dashboard once the feature is in general availability.

---

## Rollback procedure

No DB rollback is needed. The feature is additive and stateless at the flag
boundary.

**To disable:**

- **Env override**: set `SLACK_WORK_CONTEXT_ENABLED_OVERRIDE=false` in Doppler
  or Helm, then redeploy.
- **CANON.yaml**: set `slack.work_context.enabled: false` and push.

Either change takes effect on pod restart. The coordinator path is skipped;
existing mention handling falls back to the pre-v1 path immediately.

---

## Migration notes

**`/canon link` identity re-link required for existing users.** The identity
store (`SlackIdentityStore`) was not persisting links before PR #671 — rows
were being written but the lookup path had a bug. Existing users who ran
`/canon link` before this deploy will need to run it again. This is a one-time
communication, not a regression. Suggested customer message:

> "We fixed a bug where your Slack-GitHub identity link wasn't being saved.
> Please run `/canon link` once to re-establish the connection — this enables
> Canon to fetch your open PRs and commits for richer answers."

---

## Known v1 limitations

4 of the 6 work context source loaders are **stubs** (return empty results
without calling external APIs). Only two are active:

| Source | Status |
|---|---|
| `canon_specs` | Active — fetches relevant spec sections |
| `slack_threads` | Active — fetches recent thread context |
| `canon_pr_analysis` | Stub — returns `[]` |
| `github_prs` | Stub — returns `[]` |
| `github_commits` | Stub — returns `[]` |
| `tickets` | Stub — returns `[]` |

The remaining loaders are tracked in the smarter-bot spec. They will be
activated in subsequent PRs. The cap logic (`total_items_after_cap`) already
accounts for empty stub results.
