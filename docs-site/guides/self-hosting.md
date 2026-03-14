# Self-Hosting

Deploy Canon to your own Kubernetes cluster using the provided Helm chart.

## Prerequisites

- Kubernetes 1.25+
- Helm 3.x
- A GitHub App (see [GitHub App Setup](./github-app))
- An Anthropic API key
- (Optional) Jira, Linear, or GitHub Issues for ticket sync

## 1. Create Kubernetes Secrets

Create secrets before installing the chart, or let the chart create them for you.

### Option A: Let the Chart Manage Secrets

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

### Option B: Use Existing Secrets (Recommended)

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

### Auth0 (Optional)

If you want web login, CLI auth (`canon login`), or role-based access control, configure an Auth0 tenant. See the [GitHub App Setup](./github-app) guide for Auth0 configuration, then create the secret:

```bash
kubectl create secret generic canon-auth0 \
  --from-literal=domain=your-tenant.auth0.com \
  --from-literal=client-id=your-client-id \
  --from-literal=client-secret=your-client-secret \
  --from-literal=audience=https://canon.yourcompany.com/api \
  --from-literal=device-client-id=your-device-client-id  # optional
```

`AUTH0_AUDIENCE` is **required** for JWT validation — without it, device auth (CLI login) and server-proxied ticket sync will not work.

```yaml
secrets:
  auth0:
    existingSecret: "canon-auth0"
```

## 2. Install with Helm

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

## 3. Build and Push the Docker Image

```bash
# Build
docker build -t canon:latest .

# Tag for your registry
docker tag canon:latest ghcr.io/your-org/canon:latest

# Push
docker push ghcr.io/your-org/canon:latest
```

## 4. Configure Target Repos

Add a `CANON.yaml` to each repo you want Canon to manage. See [Configuration](/getting-started/configuration) for the full reference.

Minimal:

```yaml
version: "1"

specs:
  paths:
    - "docs/specs/*.md"

agents:
  pr_analysis: true
```

## 5. Jira Setup

If using Jira for ticket sync:

1. Create a **service account** or use an existing Jira user
2. Generate an **API token** at `https://id.atlassian.com/manage-profile/security/api-tokens`
3. Ensure the Jira project has these workflow statuses (or map custom ones): `Backlog`, `To Do`, `In Progress`, `Done`
4. The service account needs project-level permissions to create and transition issues

## 6. Verify the Deployment

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

## Troubleshooting

### Webhooks Not Arriving

1. Check GitHub App webhook deliveries: **App Settings > Advanced > Recent Deliveries**
2. Verify the webhook URL matches your ingress hostname + `/webhook`
3. Check the webhook secret matches what's in your K8s secret
4. Ensure the GitHub App is installed on the target org/repos

### Signature Verification Failures

- The webhook secret in K8s must exactly match the one configured in GitHub App settings
- Check for trailing newlines in the secret value

### Cron Job Not Running

```bash
# Check CronJob status
kubectl get cronjobs -l app.kubernetes.io/name=canon

# Check recent Job runs
kubectl get jobs -l app.kubernetes.io/name=canon

# Check Job logs
kubectl logs job/canon-sync-status-<timestamp>
```

### Jira Connection Errors

- Verify `JIRA_HOST` doesn't include `https://` prefix (just `yourcompany.atlassian.net`)
- Test credentials: `curl -u email:api-token https://yourcompany.atlassian.net/rest/api/3/myself`
- Check the project key exists and the service account has access
