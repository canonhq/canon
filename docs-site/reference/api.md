---
# This file is auto-generated. Do not edit manually.
# Generated: 2026-03-18 18:07 UTC
---

# REST API Reference

::: tip Auto-Generated
This page was auto-generated from the FastAPI OpenAPI schema on 2026-03-18 18:07 UTC.
See [source script](https://github.com/canonhq/canon/blob/main/docs-site/.vitepress/scripts/gen-api-ref.py).
:::

## Base URL

- **Hosted**: `https://canonhq.co`
- **Self-hosted**: `https://<your-domain>`

## Authentication

API requests use Bearer token authentication:

```
Authorization: Bearer <token>
```

Tokens can be:
- **JWT access tokens** from Auth0 login
- **API keys** prefixed with `sw_` (create via Settings > API Keys)
- **Session cookies** for browser-based access

## Endpoints (74)

### Public

#### `GET /`

Landing

Marketing landing page — served via Vue SPA with minimal session data.

**Responses:**

- **200**: Successful Response

---

#### `GET /changelog`

Public Changelog

Public changelog.

**Responses:**

- **200**: Successful Response

---

#### `GET /pricing`

Pricing

Dedicated pricing page.

**Responses:**

- **200**: Successful Response

---

### JSON API

#### `POST /api/contact/enterprise`

Enterprise Contact

Handle enterprise contact form submission.

**Request Body** (`EnterpriseContactRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes |  |
| `email` | `string` | Yes |  |
| `company` | `string` | Yes |  |
| `team_size` | `string` | Yes |  |
| `message` | `string` | No |  |
| `honeypot` | `string` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /api/waitlist`

Waitlist Signup

Capture waitlist email signup (fires PostHog event, no DB needed).

**Responses:**

- **200**: Successful Response

---

#### `POST /api/webhooks/stripe`

Stripe Webhook

Handle Stripe webhook events.

**Responses:**

- **200**: Successful Response

---

#### `GET /app/admin/api/indexing`

Api Admin Indexing

JSON indexing overview for the Vue SPA admin page.

**Responses:**

- **200**: Successful Response

---

#### `POST /app/admin/api/reindex/{installation_id}`

Api Admin Reindex

Trigger re-index via JSON API for the Vue SPA.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `installation_id` | path | `integer` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/billing/ai-ops`

Get Ai Ops Usage

Get AI operation usage for the current billing period.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/api/billing/portal`

Create Portal Session

Create a Stripe Billing Portal session for self-service management.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/billing/seats`

Get Seat Info

Get seat count and active user count for the current billing period.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/api/billing/start-trial`

Start Trial

Start a 14-day Pro trial. No credit card required.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/billing/subscription`

Get Subscription

Get current subscription details.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/api/checkout`

Create Checkout

Create a Stripe Checkout Session for a per-seat subscription.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Request Body** (`CheckoutRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `plan` | `Plan` | Yes |  |
| `billing_cycle` | `BillingCycle` | No |  |
| `seat_count` | `integer` | No |  |
| `success_url` | `string` | Yes |  |
| `cancel_url` | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/coverage`

Api Coverage

JSON coverage API — aggregate metrics and trend data.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `repo` | query | `string` | No |  |
| `team` | query | `string` | No |  |
| `days` | query | `integer` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/dashboard`

Api Dashboard

JSON org dashboard data for the Vue SPA.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/docs/{owner}/{repo}/{file_path}`

Api Doc Detail

JSON doc detail for the Vue SPA.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |
| `file_path` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/repos/{owner}/{repo}`

Api Repo Detail

JSON repo detail for the Vue SPA.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/search`

Api Search

JSON search API for autocomplete and programmatic access.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `q` | query | `string` | No |  |
| `team` | query | `string` | No |  |
| `status` | query | `string` | No |  |
| `tag` | query | `string` | No |  |
| `repo` | query | `string` | No |  |
| `limit` | query | `integer` | No |  |
| `offset` | query | `integer` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/session`

Api Session

JSON session data for the Vue SPA.

Note: posthog_key and posthog_host are intentionally included without
auth — PostHog project API keys are designed to be public (write-only,
no read access to analytics data).

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/settings/anthropic-key`

Get Anthropic Key Status

Get the status of the stored Anthropic API key (never returns the key).

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/api/settings/anthropic-key`

Submit Anthropic Key

Submit and validate an Anthropic API key for BYOK.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Request Body** (`AnthropicKeyRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `api_key` | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `DELETE /app/{org}/api/settings/anthropic-key`

Delete Anthropic Key

Remove the stored Anthropic API key.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/specs/{owner}/{repo}/{file_path}`

Api Spec Detail

JSON spec detail for the Vue SPA.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |
| `file_path` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/tasks`

Api Tasks

JSON tasks data — actionable work items from all specs.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `status` | query | `string` | No |  |
| `repo` | query | `string` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/api/welcome`

Api Welcome

JSON welcome/onboarding data for the Vue SPA.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

### Web UI

#### `GET /app/`

Dashboard Redirect

Redirect /app/ to /app/{default_org}/.

**Responses:**

- **200**: Successful Response

---

#### `GET /app/setup/complete`

Setup Complete

Handle redirect from GitHub after app installation.

GitHub sends the user here with ?installation_id=X after they install
the app. We look up which org that installation belongs to and redirect
to their welcome page.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `installation_id` | query | `integer` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{full_path}`

Spa Catchall

Catch-all for SPA routes that don't match any other /app/* route.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `full_path` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/`

Org Dashboard

Org dashboard — all repos and specs.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/docs/{owner}/{repo}/{file_path}`

Org Doc Detail

Full doc detail with rendered markdown.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |
| `file_path` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/repos/{owner}/{repo}`

Org Repo Detail

Single repo view with specs and config.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/search`

Org Search

Search specs — returns HTMX partial or full page.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `q` | query | `string` | No |  |
| `team` | query | `string` | No |  |
| `status` | query | `string` | No |  |
| `tag` | query | `string` | No |  |
| `repo` | query | `string` | No |  |
| `review_status` | query | `string` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/specs/{owner}/{repo}/{file_path}`

Org Spec Detail

Full spec detail with rendered content.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |
| `file_path` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/welcome`

Org Welcome

First-run onboarding page with setup checklist.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

### Admin

#### `GET /app/admin/indexing`

Admin Indexing

Admin page showing indexing status across all installations.

**Responses:**

- **200**: Successful Response

---

#### `POST /app/admin/reindex/{installation_id}`

Admin Reindex

Trigger a re-index for a specific installation.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `installation_id` | path | `integer` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

### Profile

#### `GET /app/{org}/api/profile`

Api Profile

Return the current user's profile information.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

### Ticket Proxy

#### `POST /app/{org}/api/tickets/batch-status`

Batch Ticket Status

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Request Body** (`ProxiedBatchStatusRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | `string` | Yes |  |
| `repo` | `string` | Yes |  |
| `ticket_ids` | `array` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/api/tickets/create`

Create Ticket

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Request Body** (`ProxiedCreateRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | `string` | Yes |  |
| `repo` | `string` | Yes |  |
| `input` | `CreateTicketInput` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/api/tickets/link-pr`

Link Pr

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Request Body** (`ProxiedLinkPRRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | `string` | Yes |  |
| `repo` | `string` | Yes |  |
| `ticket_id` | `string` | Yes |  |
| `pr_url` | `string` | Yes |  |
| `pr_title` | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/api/tickets/status`

Get Ticket Status

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Request Body** (`ProxiedStatusRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | `string` | Yes |  |
| `repo` | `string` | Yes |  |
| `ticket_id` | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/api/tickets/update`

Update Ticket

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Request Body** (`ProxiedUpdateRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `owner` | `string` | Yes |  |
| `repo` | `string` | Yes |  |
| `input` | `UpdateTicketInput` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

### Editor

#### `GET /app/{org}/editor/`

Editor Index

List repos and specs available for editing.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/editor/repos`

Api Editor Repos

JSON list of repos for the Vue SPA editor.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/editor/{owner}/{repo}/ai-edit`

Api Ai Edit

Stream AI-assisted section editing via SSE.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/editor/{owner}/{repo}/generate`

Api Generate Spec

Stream AI-generated spec content via SSE.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/editor/{owner}/{repo}/new`

Editor New

New spec from template.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/editor/{owner}/{repo}/new/template`

Api New Spec Template

Return a new spec template pre-filled with user info.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/editor/{owner}/{repo}/parse`

Editor Parse

Parse spec content and return structured sections as JSON.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/editor/{owner}/{repo}/preview`

Editor Preview

Render markdown preview — returns JSON or HTMX partial based on Accept header.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/editor/{owner}/{repo}/{file_path}`

Editor Load

Load a spec file for editing.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |
| `file_path` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /app/{org}/editor/{owner}/{repo}/{file_path}/json`

Api Editor File

JSON file content for the Vue SPA editor.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |
| `file_path` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/editor/{owner}/{repo}/{file_path}/save`

Editor Save

Save spec via direct commit to default branch.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |
| `file_path` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/editor/{owner}/{repo}/{file_path}/save-pr`

Editor Save Pr

Save spec via new branch + PR.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `owner` | path | `string` | Yes |  |
| `repo` | path | `string` | Yes |  |
| `file_path` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

### Settings

#### `GET /app/{org}/settings/api-keys/`

List Api Keys

List API keys for the current user in this org.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /app/{org}/settings/api-keys/`

Create Api Key

Create a new API key scoped to this org.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |

**Request Body** (`CreateApiKeyRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `label` | `string` | No |  |
| `scopes` | `array` | No |  |
| `expires_in_days` | `` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `DELETE /app/{org}/settings/api-keys/{key_id}`

Revoke Api Key

Revoke an API key.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | path | `string` | Yes |  |
| `key_id` | path | `integer` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

### Authentication

#### `GET /auth/callback`

Auth Callback

Handle Auth0 callback — exchange code for tokens, set session.

**Responses:**

- **200**: Successful Response

---

#### `GET /auth/login`

Login

Redirect to Auth0 Universal Login.

If ``?org=<slug>`` is provided and Auth0 Organizations mode is enabled,
the user authenticates into that specific org so the returned token
contains ``org_id`` and ``permissions`` claims.

| Name | In | Type | Required | Description |
|------|-----|------|----------|-------------|
| `org` | query | `string` | No |  |
| `connection` | query | `string` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `GET /auth/logout`

Logout

Clear session and redirect to Auth0 logout.

**Responses:**

- **200**: Successful Response

---

#### `POST /auth/refresh`

Refresh Token

Exchange a refresh token for a new access token.

The refresh token can come from:
1. An httpOnly cookie ``sw_refresh`` (web clients)
2. The JSON body ``{"refresh_token": "..."}`` (CLI clients)

On success the refresh hash is rotated in the DB and new tokens are
returned.  For cookie-sourced requests the new refresh token is set
as a cookie; for body-sourced requests it is included in the response
JSON.

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /auth/revoke`

Revoke Session

Revoke a refresh-token session.

Accepts the refresh token via cookie or body (same dual-source as refresh).
Marks the session as revoked in the DB so the token can no longer be used.

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

### Device Authorization

#### `POST /auth/device/code`

Request Device Code

Start the device authorization flow by requesting a code from Auth0.

**Request Body** (`DeviceCodeRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `org` | `string` | No |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

#### `POST /auth/device/token`

Poll Device Token

Poll Auth0 for the device token.  Returns status + tokens on approval.

**Request Body** (`DeviceTokenRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `device_code` | `string` | Yes |  |

**Responses:**

- **200**: Successful Response
- **422**: Validation Error

---

### GitHub OAuth

#### `GET /auth/github/callback`

Github Callback

Handle GitHub OAuth callback — exchange code for token.

**Responses:**

- **200**: Successful Response

---

#### `GET /auth/github/disconnect`

Github Disconnect

Clear GitHub session data.

**Responses:**

- **200**: Successful Response

---

#### `GET /auth/github/login`

Github Login

Redirect to GitHub OAuth authorize page.

**Responses:**

- **200**: Successful Response

---

### Infrastructure

#### `GET /healthz`

Healthz

Liveness probe.

**Responses:**

- **200**: Successful Response

---

#### `GET /readyz`

Readyz

Readiness probe — checks DB health when pool is configured.

**Responses:**

- **200**: Successful Response

---

#### `POST /webhook`

Webhook

Receive and process GitHub webhook events.

**Responses:**

- **200**: Successful Response

---

### webhooks

#### `POST /webhooks/asana`

Asana Webhook

Handle Asana webhook events for reverse sync.

Currently only supports the webhook handshake (X-Hook-Secret).
Task status processing requires an Asana API adapter to fetch
actual completion status — not yet implemented.

**Responses:**

- **200**: Successful Response

---

#### `POST /webhooks/jira`

Jira Webhook

Handle Jira webhook events for reverse sync.

Triggered by: jira:issue_updated

**Responses:**

- **200**: Successful Response

---

#### `POST /webhooks/linear`

Linear Webhook

Handle Linear webhook events for reverse sync.

Triggered by: Issue updates

**Responses:**

- **200**: Successful Response

---
