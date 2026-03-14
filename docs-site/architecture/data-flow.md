# Data Flow

Key workflows showing how data moves through the Canon system.

## PR Analysis Flow

The primary workflow — from webhook to PR comment:

```mermaid
sequenceDiagram
    participant GH as GitHub
    participant APP as FastAPI
    participant PARSE as Parser
    participant AGENT as Claude Agent
    participant API as GitHub API

    GH->>APP: pull_request webhook
    APP->>APP: Verify HMAC signature
    APP->>API: List changed files
    alt Config-only files
        APP-->>APP: Skip (no comment)
    else Has code changes
        APP->>API: Load specs from base branch
        PARSE->>PARSE: Parse specs → sections + ACs
        APP->>API: Retrieve context docs
        APP->>API: Post "Analyzing..." comment
        APP->>AGENT: Send PR context + specs
        AGENT->>AGENT: Evaluate ACs against diff
        AGENT-->>APP: JSON response
        APP->>APP: Format markdown comment
        APP->>API: Upsert bot comment
        APP->>APP: Store realizations
    end
```

## Ticket Sync Flow

### Forward Sync (Spec → Tickets)

```mermaid
sequenceDiagram
    participant PM as PM
    participant GH as GitHub
    participant APP as Canon
    participant JIRA as Jira/Linear

    PM->>GH: Push spec with new section
    GH->>APP: push webhook
    APP->>APP: Parse spec, find new sections
    APP->>JIRA: Create ticket for each section
    APP->>GH: Update spec with ticket links
    Note over GH: <!-- canon:ticket:jira:PAY-142 -->
```

### Reverse Sync (Tickets → Spec)

```mermaid
sequenceDiagram
    participant ENG as Engineer
    participant JIRA as Jira/Linear
    participant CRON as CronJob
    participant GH as GitHub

    ENG->>JIRA: Close ticket PAY-143
    CRON->>JIRA: Poll for status changes
    CRON->>CRON: Map ticket status → spec status
    CRON->>GH: Update spec status comment
    Note over GH: status:in_progress → status:done
```

### Realization Sync (Code → Spec)

```mermaid
sequenceDiagram
    participant ENG as Engineer
    participant GH as GitHub
    participant APP as Canon
    participant AGENT as Claude Agent

    ENG->>GH: Merge PR implementing §3.1
    GH->>APP: pull_request (merged)
    APP->>AGENT: Analyze merged code vs ACs
    AGENT-->>APP: AC1: realized, AC2: realized
    APP->>GH: Update spec (status:done)
    APP->>GH: Add realization evidence
    Note over GH: <!-- canon:realized-in:PR#412 src/keys.ts -->
```

## Interactive Command Flow

When a user comments `@canon apply docs` on a PR:

```mermaid
sequenceDiagram
    participant USER as User
    participant GH as GitHub
    participant APP as Canon
    participant AGENT as Claude Agent

    USER->>GH: Comment "@canon apply docs"
    GH->>APP: issue_comment webhook
    APP->>APP: Parse command
    APP->>AGENT: Re-run analysis
    AGENT-->>APP: Doc update suggestions
    APP->>GH: Create branch canon/doc-update-pr-N
    APP->>GH: Commit doc changes
    APP->>GH: Open PR with update summary
    APP->>GH: Reply to original comment with PR link
```

## Diff Budgeting

The agent has a limited context window. Diffs are included using a budget-based approach:

```mermaid
flowchart TD
    A[Calculate budget: max_input_tokens - 2000 × 4] --> B[Sort files largest-first]
    B --> C{File fits in remaining budget?}
    C -- yes --> D[Include full diff]
    D --> E{More files?}
    E -- yes --> C
    C -- no --> F[Skip file]
    F --> E
    E -- no --> G[Append count of omitted files]
```

With the default 128k input token limit, this yields ~504,000 characters for diffs. Files are sorted **largest-first** to prioritize the most substantial changes.
