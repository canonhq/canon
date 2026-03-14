# Self-Hosting Canon

This guide covers deploying Canon to a Kubernetes cluster using the provided Helm chart.

## Prerequisites

- Kubernetes 1.25+
- Helm 3.x
- A GitHub App (see below)
- An Anthropic API key
- (Optional) Jira, Linear, or GitHub Issues for ticket sync

## 1. Create a GitHub App

1. Go to **Settings > Developer settings > GitHub Apps > New GitHub App**
2. Configure:
   - **Name**: `Canon` (or any name)
   - **Homepage URL**: Your deployment URL
   - **Webhook URL**: `https://<your-domain>/webhook`
   - **Webhook secret**: Generate a random secret (`openssl rand -hex 32`)
3. **Permissions**:
   - Repository: Contents (Read & write), Issues (Read & write), Pull requests (Read & write), Metadata (Read-only)
4. **Events** — subscribe to all of these:
   - `push`
   - `pull_request`
   - `issues`
   - `issue_comment`
5. After creation:
   - Note the **App ID** from the app settings page
   - Generate a **private key** (PEM file) — download and save it
   - Install the app on your organization/repos

## 2. Create Kubernetes Secrets

Create secrets before installing the chart, or let the chart create them for you.

### Option A: Let the chart manage secrets

Set values directly in your `values.yaml` (not recommended for production):

```yaml
secrets:
  githubApp:
    appId: "123456"
    privateKey: |
      -----BEGIN RSA PRIVATE KEY-----
      ...
      -----END RSA PRIVATE KEY-----
    webhookSecret: "your-webhook-secret"
    installationId: "789012"
  anthropic:
    apiKey: "sk-ant-..."
```

### Option B: Use existing secrets (recommended)

Create secrets manually, then reference them:

```bash
# GitHub App credentials
kubectl create secret generic canon-github \
  --from-literal=app-id=123456 \
  --from-file=private-key=./your-app.pem \
  --from-literal=webhook-secret=$(openssl rand -hex 32) \
  --from-literal=installation-id=789012

# Anthropic API key
kubectl create secret generic canon-anthropic \
  --from-literal=api-key=sk-ant-...

# Jira credentials (if using Jira)
kubectl create secret generic canon-jira \
  --from-literal=host=yourcompany.atlassian.net \
  --from-literal=email=canon@yourcompany.com \
  --from-literal=api-token=your-jira-api-token
```

Then in `values.yaml`:

```yaml
secrets:
  githubApp:
    existingSecret: "canon-github"
  anthropic:
    existingSecret: "canon-anthropic"
  jira:
    existingSecret: "canon-jira"
```

### Auth0 (optional — required for web login, CLI auth, or RBAC)

If you want web login, CLI auth, or role-based access control, configure an Auth0 tenant:

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

Create the Auth0 secret:

```bash
kubectl create secret generic canon-auth0 \
  --from-literal=domain=your-tenant.auth0.com \
  --from-literal=client-id=your-client-id \
  --from-literal=client-secret=your-client-secret
```

Then in `values.yaml`:

```yaml
secrets:
  auth0:
    existingSecret: "canon-auth0"
```

### Database Tables

Auth hardening requires two additional tables (`sessions` and `org_members`). These are created automatically on startup via `ensure_schema` — the same mechanism used for all other tables. If `ensure_schema` fails (e.g., insufficient DB permissions), the server will fail to start — check pod logs for SQL errors. Be aware of the new tables when planning upgrades:

- `sessions` — per-device session tracking with refresh token hashes, device labels, and revocation support
- `org_members` — per-org role assignments (viewer/editor/admin) with an `assigned_by` audit trail

### Additional Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AUTH0_DOMAIN` | Yes (if auth enabled) | Auth0 tenant domain |
| `AUTH0_CLIENT_ID` | Yes (if auth enabled) | Auth0 application client ID |
| `AUTH0_CLIENT_SECRET` | Yes (if auth enabled) | Auth0 application client secret |
| `AUTH0_DEVICE_CLIENT_ID` | No | Separate client ID for device auth, if using a dedicated Auth0 app for CLI |

All secrets should be managed via K8s secrets or your preferred secret manager — never in config files.

## 3. Install with Helm

Minimal install:

```bash
helm install canon chart/canon/ \
  --set secrets.githubApp.appId=123456 \
  --set secrets.githubApp.webhookSecret=your-secret \
  --set secrets.githubApp.installationId=789012 \
  --set secrets.anthropic.apiKey=sk-ant-... \
  --set-file secrets.githubApp.privateKey=./your-app.pem
```

Production install with custom values:

```bash
helm install canon chart/canon/ -f values-production.yaml
```

Example `values-production.yaml`:

```yaml
image:
  registry: ghcr.io
  repository: your-org/canon
  tag: "latest"

ingress:
  enabled: true
  hostname: canon.yourcompany.com
  ingressClassName: nginx
  tls: true
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod

secrets:
  githubApp:
    existingSecret: canon-github
  anthropic:
    existingSecret: canon-anthropic
  jira:
    existingSecret: canon-jira

cronJob:
  enabled: true
  schedule: "*/15 * * * *"

resources:
  limits:
    cpu: 500m
    memory: 256Mi
  requests:
    cpu: 100m
    memory: 128Mi
```

## 4. Build and Push the Docker Image

```bash
# Build
docker build -t canon:latest .

# Tag for your registry
docker tag canon:latest ghcr.io/your-org/canon:latest

# Push
docker push ghcr.io/your-org/canon:latest
```

## 5. Configure Target Repos

Add a `CANON.yaml` to the root of each repo you want Canon to manage:

```yaml
version: "1"

specs:
  paths:
    - "docs/specs/*.md"

agents:
  pr_analysis: true
  auto_doc_update: true

sync:
  system: jira          # or: linear, github
  project_key: PROJ     # Jira project key, Linear team key, or GitHub repo
  create_tickets: true
  reverse_sync: true
```

### Advanced Configuration

For enterprise teams with custom Jira workflows, multiple ticket systems, or org-wide defaults, use the `ticket_systems` key instead of the simple `sync` block. Note: this schema is defined in the [Ticket Mapping Model spec](specs/ticket-mapping-model.md) and requires the config parser to be updated before use — until then, these keys will produce "Unknown config key" warnings.

```yaml
specs:
  doc_paths:
    - "docs/specs/*.md"

agents:
  pr_analysis: true
  doc_updates: true

ticket_systems:
  engineering:
    system: jira
    project: ENG
    status_map:
      draft: "Backlog"
      todo: "Open"
      in_progress: "In Development"
      done: "Closed"
      blocked: "On Hold"
      deprecated: "Won't Fix"
    hierarchy:
      2: "Epic"
      3: "Story"
      4: "Sub-task"
    auto_parent: true
  oss:
    system: github
    repo: org/public-repo

routing:
  - match:
      tags: ["open-source"]
    target: oss
  - match:
      default: true
    target: engineering
```

The legacy `sync` block continues to work. Note that the legacy config uses `project_key` (top-level), while the new `ticket_systems` schema uses `project` (per-system) — both refer to the Jira project key, Linear team key, or GitHub repo. See the [Ticket Mapping Model spec](specs/ticket-mapping-model.md) for the full schema.

## 6. Jira Setup

If using Jira for ticket sync:

1. Create a **service account** or use an existing Jira user
2. Generate an **API token** at https://id.atlassian.com/manage-profile/security/api-tokens
3. Ensure the Jira project has these workflow statuses (or map custom ones):
   - `Backlog`, `To Do`, `In Progress`, `Done`
4. The service account needs project-level permissions to create and transition issues

## 7. Verify the Deployment

```bash
# Check pods are running
kubectl get pods -l app.kubernetes.io/name=canon

# Check health endpoint
kubectl port-forward svc/canon 8080:80
curl http://localhost:8080/healthz

# Check logs
kubectl logs -l app.kubernetes.io/name=canon -f

# Run Helm tests
helm test canon
```

## 8. Dev Environment (DevSpace)

For contributors developing Canon itself, you can use [DevSpace](https://devspace.sh) to provide isolated dev environments on a Kubernetes cluster. Each developer gets their own namespace and ingress hostname.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [DevSpace CLI](https://devspace.sh/docs/getting-started/installation) (v6+)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- A Kubernetes cluster with ingress configured

### One-time setup

```bash
# Authenticate with your container registry
docker login <your-registry>

# Configure kubectl for your cluster
kubectl config use-context <your-cluster>
```

### How it works

- **Namespace isolation**: Each dev deploys with release name `canon-dev-{username}`
- **Secrets**: DevSpace syncs secrets into the dev namespace via the `sync-secrets` pipeline
- **Hot reload**: `Dockerfile.dev` uses an editable install (`uv pip install -e .`). DevSpace syncs `src/`, `templates/`, and `static/` into the pod. uvicorn runs with `--reload`
- **Port forwarding**: `localhost:3000` maps to the pod's port 3000

### Usage

```bash
export DEVSPACE_USERNAME=your-name   # or set in .envrc

# Full dev mode (secrets + build + deploy + sync + port-forward)
devspace dev

# Build image only
devspace build

# Deploy without dev mode
devspace deploy

# Useful commands
devspace run logs             # tail pod logs
devspace run sync-secrets     # re-sync secrets
devspace run sync-trigger     # manually run reverse sync cron

# Tear down
devspace purge
```

### Key files

| File | Purpose |
|------|---------|
| `devspace.yaml` | DevSpace v6 config (vars, images, deployments, dev, pipelines) |
| `Dockerfile.dev` | Dev image with editable install and uvicorn --reload |
| `chart/canon/values-dev.yaml` | Helm overrides for dev (debug logging, no cron, relaxed security) |

## 9. Troubleshooting

### Webhooks not arriving

1. Check GitHub App webhook deliveries: **App Settings > Advanced > Recent Deliveries**
2. Verify the webhook URL matches your ingress hostname + `/webhook`
3. Check the webhook secret matches what's in your K8s secret
4. Ensure the GitHub App is installed on the target org/repos

### Signature verification failures

- The webhook secret in K8s must exactly match the one configured in GitHub App settings
- Check for trailing newlines in the secret value

### Cron job not running

```bash
# Check CronJob status
kubectl get cronjobs -l app.kubernetes.io/name=canon

# Check recent Job runs
kubectl get jobs -l app.kubernetes.io/name=canon

# Check Job logs
kubectl logs job/canon-sync-status-<timestamp>
```

### Session cleanup CronJob not running

If auth hardening is enabled, the Helm chart deploys an additional CronJob for session cleanup (expired sessions, revoked refresh tokens). This reuses the same pattern as the reverse sync CronJob above. To verify:

```bash
kubectl get cronjobs -l app.kubernetes.io/component=session-cleanup
```

### Jira connection errors

- Verify JIRA_HOST doesn't include `https://` prefix (just `yourcompany.atlassian.net`)
- Test credentials: `curl -u email:api-token https://yourcompany.atlassian.net/rest/api/3/myself`
- Check the project key exists and the service account has access
