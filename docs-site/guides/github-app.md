# GitHub App Setup

The Canon GitHub App is the primary integration point. It receives webhooks for pushes, pull requests, and issue comments, enabling automated PR analysis and doc maintenance.

## Creating the GitHub App

1. Go to **Settings > Developer settings > GitHub Apps > New GitHub App**
2. Configure:
   - **Name**: `Canon` (or any name)
   - **Homepage URL**: Your deployment URL
   - **Webhook URL**: `https://<your-domain>/webhook`
   - **Webhook secret**: Generate a random secret (`openssl rand -hex 32`)

3. **Permissions**:
   - Repository Contents: **Read & write** (code + docs, doc-update PRs)
   - Pull requests: **Read & write** (doc PRs, comments)
   - Issues: **Read & write** (generated tickets)
   - Metadata: **Read-only**
   - Members: **Read-only** (ownership graph)

4. **Events** — subscribe to all of these:
   - `push`
   - `pull_request`
   - `issues`
   - `issue_comment`
   - `installation`
   - `installation_repositories`

5. After creation:
   - Note the **App ID** from the app settings page
   - Generate a **private key** (PEM file) — download and save it
   - Install the app on your organization/repos

## Webhook Events

| Event | Actions | What Canon Does |
|-------|---------|---------------------|
| `push` | — | Watches for spec and doc changes on the default branch |
| `pull_request` | opened, synchronize, reopened, merged, closed | Runs PR analysis, posts spec context comments |
| `issues` | created, closed, labeled | Triggers reverse sync (ticket → spec status) |
| `issue_comment` | created | Handles `@canon` commands (dismiss, reanalyze, apply docs) |
| `installation` | created, suspended, deleted | App lifecycle management |
| `installation_repositories` | added, removed | Repo onboarding/offboarding |

## Auth0 Configuration (Optional)

If you want web login, CLI auth, or role-based access control:

1. **Create an Auth0 Application** (type: Regular Web Application)
   - Allowed Callback URLs: `https://<your-domain>/auth/callback`
   - Allowed Logout URLs: `https://<your-domain>`

2. **Enable connections** (under Authentication > Social / Enterprise):
   - GitHub (social connection) — for developer login
   - Google Workspace (enterprise OIDC) — for org SSO
   - Passwordless email (magic link) — fallback for non-SSO users

3. **Enable Device Authorization Grant** (under Application Settings > Advanced > Grant Types) — required for `canon login` CLI auth

4. **Configure refresh token rotation** (under Application Settings > Refresh Token Rotation):
   - Rotation: enabled
   - Absolute lifetime: 7 days
   - Reuse interval: 0 (rotate on every use)

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AUTH0_DOMAIN` | Yes (if auth enabled) | Auth0 tenant domain (e.g. `your-tenant.auth0.com`) |
| `AUTH0_CLIENT_ID` | Yes (if auth enabled) | Auth0 application client ID |
| `AUTH0_CLIENT_SECRET` | Yes (if auth enabled) | Auth0 application client secret |
| `AUTH0_AUDIENCE` | Yes (if auth enabled) | Auth0 API identifier (e.g. `https://canon.yourcompany.com/api`). Required for JWT access token validation — without it, Auth0 returns opaque tokens that can't be verified server-side. |
| `AUTH0_DEVICE_CLIENT_ID` | No | Separate Native app client ID for CLI device auth. If not set, falls back to `AUTH0_CLIENT_ID`. |

All secrets should be managed via Doppler or K8s secrets — never in config files.

### Auth0 API Resource Server

For JWT-based auth (required for CLI login and server-proxied ticket sync), you need an Auth0 API:

1. Go to **Auth0 Dashboard > Applications > APIs > Create API**
2. Set the **Identifier** (audience) to your deployment URL + `/api` (e.g. `https://canon.yourcompany.com/api`)
3. Enable **RBAC** and **Add Permissions in the Access Token** if you want role-based access control
4. Use this identifier as the `AUTH0_AUDIENCE` environment variable

## Database Tables

Auth requires two additional tables (`sessions` and `org_members`). These are created automatically on startup via `ensure_schema`. If creation fails (e.g., insufficient DB permissions), the server will fail to start — check pod logs for SQL errors.
