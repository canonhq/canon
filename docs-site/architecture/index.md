# Architecture

Canon's architecture is designed around three tiers — repo agents, agent mesh, and org brain — with a modular component structure.

## System Overview

```mermaid
graph TB
    subgraph "Tier 1: Repo Agents"
        WH[GitHub Webhooks] --> APP[FastAPI App]
        APP --> PARSE[Spec Parser]
        APP --> AGENT[Claude Agent]
        APP --> SYNC[Ticket Sync]
        PARSE --> KB[Knowledge Base]
        KB --> AGENT
        AGENT --> GH[GitHub API]
        SYNC --> JIRA[Jira]
        SYNC --> LINEAR[Linear]
        SYNC --> GHI[GitHub Issues]
    end

    subgraph "Dev Tools"
        MCP[MCP Server] --> KB
        CLI[CLI] --> PARSE
        PLUGIN[Claude Code Plugin] --> MCP
    end

    subgraph "Tier 2: Agent Mesh"
        MESH[Event Bus] --> APP
    end

    subgraph "Tier 3: Org Brain"
        BRAIN[Knowledge Graph] --> MESH
        DASH[Dashboards] --> BRAIN
    end
```

## Component Map

| Component | Role | Key Files |
|-----------|------|-----------|
| [FastAPI App](./system-design#fastapi-app) | Webhook routes, health checks | `src/specwright/main.py` |
| [Spec Parser](./system-design#spec-parser) | Markdown parsing, frontmatter extraction | `src/specwright/parser/` |
| [Claude Agent](./system-design#agent-runtime) | PR analysis, realization checking | `src/specwright/agent/` |
| [Ticket Sync](./system-design#ticket-sync) | Bidirectional ticket synchronization | `src/specwright/sync/` |
| [GitHub Client](./system-design#github-client) | GitHub API, webhook verification | `src/specwright/github/` |
| [Config Parser](./system-design#config-parser) | CANON.yaml validation | `src/specwright/config/` |

## Further Reading

- [System Design](./system-design) — Detailed component breakdown
- [Data Flow](./data-flow) — Key workflow diagrams
- [Components](./components) — Per-module documentation
