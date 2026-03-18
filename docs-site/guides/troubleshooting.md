# Troubleshooting

Common issues and how to resolve them.

## CLI

### `canon: command not found`

The CLI isn't on your PATH. If you installed with `pip install canonhq`:

```bash
# Check if it's installed
pip show canonhq

# If using uv
uvx canon --help
```

### `canon setup` fails with permission error

Ensure you have write access to the current directory. Canon needs to create `CANON.yaml`.

### `canon sync` fails with authentication error

Check your ticket system credentials:

```bash
# For GitHub Issues
export GITHUB_TOKEN=ghp_...

# For Jira
export JIRA_HOST=https://your-org.atlassian.net
export JIRA_EMAIL=you@example.com
export JIRA_API_TOKEN=...

# For Linear
export LINEAR_API_KEY=lin_api_...
```

## GitHub App

### Canon bot doesn't comment on PRs

1. **Check installation**: Visit your org's GitHub App settings and verify Canon is installed on the target repository
2. **Check CANON.yaml**: The repo needs a `CANON.yaml` (PR analysis is enabled by default; check it hasn't been explicitly disabled with `agents.pr_analysis: false`)
3. **Check specs exist**: The bot only comments when relevant specs are found in the configured `doc_paths`

### Canon bot comments are not useful

The bot analyzes PRs against specs in `doc_paths`. If your specs are too high-level or don't have acceptance criteria (checklist items), the analysis will be shallow. Add specific acceptance criteria to your spec sections.

## MCP Server

### MCP server doesn't start

```bash
# Test directly
canon-mcp

# Check for port conflicts if using HTTP transport
# Default stdio transport doesn't need a port
```

### No results from search

The MCP server indexes markdown files in the paths configured in `CANON.yaml`. Verify:

1. `CANON.yaml` exists with `specs.doc_paths` configured
2. The paths contain markdown files
3. Files have valid frontmatter

## Self-Hosted

### Pod crashes with `DATABASE_URL` error

Ensure your database URL is correctly formatted:

```
postgresql://user:password@host:5432/dbname
```

For asyncpg (used internally), the scheme is handled automatically — you don't need to change `postgresql://` to `postgresql+asyncpg://`.

### Webhook events not received

1. **Check the webhook URL**: Should be `https://your-domain/webhook`
2. **Check the webhook secret**: Must match the `GH_WEBHOOK_SECRET` environment variable
3. **Check TLS**: GitHub requires HTTPS for webhook endpoints
4. **Check logs**: Look for `signature verification failed` in application logs

### Health check failing

The health endpoint is `GET /healthz` (default port 3000, configurable via `PORT` env var). Common causes:

- Database connection not established
- Port 3000 not exposed in your service/ingress configuration
- Readiness probe timing — the app needs a few seconds to start
