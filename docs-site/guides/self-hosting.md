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

### Authentication (Optional)

Canon supports four authentication modes. Choose the one that fits your deployment.

**Option A: Bundled Zitadel** (recommended for teams without an IDP)

Two-step bootstrap — first deploy Zitadel, then enable the setup job:

```bash
# 1. Deploy Canon + Zitadel (without setup job)
helm install canon chart/canon/ --set zitadel.enabled=true

# 2. Create an admin service account in Zitadel Console, then:
kubectl create secret generic canon-zitadel-admin \
  --from-literal=client-secret=<your-admin-sa-secret>

helm upgrade canon chart/canon/ \
  --set zitadel.enabled=true \
  --set zitadel.setup=true \
  --set zitadel.adminClientId=<your-admin-sa-client-id> \
  --set zitadel.adminSecretName=canon-zitadel-admin
```

The setup job auto-provisions a Canon project, web app, and CLI device auth app.

**Option B: Bring Your Own OIDC Provider** (Keycloak, Okta, Zitadel, Google Workspace, Entra ID, etc.)

```bash
kubectl create secret generic canon-oidc \
  --from-literal=OIDC_ISSUER=https://your-idp.example.com \
  --from-literal=OIDC_CLIENT_ID=your-client-id \
  --from-literal=OIDC_CLIENT_SECRET=your-client-secret
```

```yaml
secrets:
  oidc:
    existingSecret: "canon-oidc"
```

Configure your provider with redirect URI: `https://<your-domain>/auth/callback`

**Option C: Auth0** (legacy — existing deployments)

```bash
kubectl create secret generic canon-auth0 \
  --from-literal=domain=your-tenant.auth0.com \
  --from-literal=client-id=your-client-id \
  --from-literal=client-secret=your-client-secret
```

```yaml
secrets:
  auth0:
    existingSecret: "canon-auth0"
```

**Option D: No Auth** (dev/trusted network)

No auth secrets configured — anonymous access with all permissions.

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
