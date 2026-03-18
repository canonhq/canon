# FAQ

Common questions about Canon.

## General

### What is Canon?

Canon is a spec-driven development platform. You write structured specs in markdown, and AI agents automate PR reviews, ticket sync, and code verification — closing the loop between what you planned to build and what actually shipped.

### How is Canon different from Notion or Confluence?

Notion and Confluence are general-purpose wikis. Canon is purpose-built for structured specs:

- **Specs live in your repo** — versioned with git, reviewed in PRs, never out of sync with code
- **AI agents maintain docs** — Canon detects when code changes affect specs and flags stale documentation
- **Bidirectional ticket sync** — spec sections become Jira/Linear/GitHub tickets and status flows both ways
- **Code verification** — agents verify that acceptance criteria are implemented, not just that tickets were closed

### Can I use Canon without the GitHub App?

Yes. Canon has several deployment paths:

| Path | Requirements |
|------|-------------|
| **CLI** (`pip install canonhq`) | Python 3.12+, Anthropic API key |
| **MCP Server** | Any MCP-compatible editor (Claude Code, Cursor, Windsurf) |
| **Claude Code Plugin** | Claude Code |
| **GitHub App** | GitHub organization |
| **Self-Hosted** | Kubernetes cluster |

The CLI and MCP server work standalone. The GitHub App adds automated PR analysis and webhook-driven features.

### What AI models does Canon use?

Canon uses Claude (Anthropic) for agent capabilities. You provide your own API key via `ANTHROPIC_API_KEY`, or the managed GitHub App uses Canon's key.

### Is Canon open source?

Yes. Canon is MIT licensed. The full source code is at [github.com/canonhq/canon](https://github.com/canonhq/canon).

## Specs

### What does a spec look like?

A spec is a markdown file with YAML frontmatter and numbered sections containing acceptance criteria:

```markdown
---
title: User Authentication
status: in-progress
priority: high
---

## 1. Login Flow

Users can log in with email and password.

- [ ] POST /auth/login accepts email + password
- [ ] Returns JWT token on success
- [ ] Rate-limits to 5 attempts per minute
```

See the [Spec Format Reference](/reference/spec-format) for the full schema.

### Where do specs live?

By default, in `docs/specs/` in your repository. You can configure this in `CANON.yaml`:

```yaml
specs:
  doc_paths:
    - "docs/specs/*.md"
    - "docs/features/**/*.md"
```

### Can I use Canon with existing specs?

Yes. If your specs already use markdown with numbered sections and checklists, Canon can parse them with minimal changes. The main requirement is YAML frontmatter with a `title` field.

## Ticket Sync

### Which ticket systems does Canon support?

- **Jira**
- **Linear**
- **GitHub Issues**

### Does sync go both ways?

Yes. When you create a spec section, Canon creates a ticket. When a ticket status changes, Canon updates the spec. When a PR closes with spec evidence, both the spec and ticket update.

### Can I disable automatic ticket creation?

Yes. In `CANON.yaml`:

```yaml
specs:
  auto_tickets: false
```

You can then run `canon sync` manually when you're ready.

## Self-Hosting

### What are the infrastructure requirements?

- Kubernetes cluster (1.24+)
- PostgreSQL database
- Redis (optional, for caching)
- GitHub App credentials

See the [Self-Hosting Guide](/guides/self-hosting) for full details.

### Can I run Canon without Kubernetes?

Yes. You can run the Docker image directly:

```bash
docker build -t canon .
docker run -p 3000:3000 \
  -e DATABASE_URL=postgresql://... \
  -e GH_APP_ID=... \
  -e GH_PRIVATE_KEY=... \
  -e GH_WEBHOOK_SECRET=... \
  -e ANTHROPIC_API_KEY=... \
  canon
```

The Helm chart is recommended for production but not strictly required. See the [Self-Hosting Guide](/guides/self-hosting) for full details.
