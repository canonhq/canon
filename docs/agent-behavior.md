# Agent Behavior

Canon's agent runtime analyzes pull requests against product specification documents and related context (ADRs, guides, READMEs). It posts structured comments on PRs with spec references, discrepancies, suggested doc updates, and acceptance-criteria realization status.

---

## Triggers & Skip Conditions

The agent runs when a `pull_request` webhook fires with action `opened`, `synchronize`, or `reopened`.

**Skip conditions** (analysis is not attempted):

| Condition | Reason |
|-----------|--------|
| All changed files match `CONFIG_ONLY_RE` | CI/config-only PRs (`.github/`, `.vscode/`, `*.yml`, `*.json`, `*.lock`, `*.toml`) have no spec impact |
| No spec files found in the repo | Nothing to analyze against |
| `ANTHROPIC_API_KEY` not set | Agent posts a fallback comment listing found specs instead |
| `agents.pr_analysis` set to `false` in `CANON.yaml` | Per-repo opt-out |

When specs exist but the agent is unavailable, a fallback comment lists the spec files and prompts the user to set the API key.

---

## Analysis Pipeline

```mermaid
flowchart TD
    A[pull_request webhook] --> B{Config-only files?}
    B -- yes --> Z[Skip — no comment]
    B -- no --> C[Load specs from base branch]
    C --> D{Specs found?}
    D -- no --> E{PR touches spec files?}
    E -- no --> Z
    E -- yes --> F[Post file-list comment]
    D -- yes --> G[Retrieve context docs]
    G --> H[Post "processing..." comment]
    H --> I[Build PRAnalysisContext]
    I --> J[build_user_message]
    J --> K[Claude API call]
    K --> L[Parse JSON response]
    L --> M[format_analysis_comment]
    M --> N[Upsert bot comment]
    N --> O[Store realizations]
```

### Step-by-step

1. **Webhook received** — `on_pull_request` extracts owner, repo, PR number.
2. **List changed files** — fetched via GitHub API. If all files match the config-only pattern, return immediately.
3. **Load repo specs** — all `docs/specs/*.md` files (or paths from `CANON.yaml` `specs.doc_paths`) are loaded and parsed from the PR's base branch.
4. **Retrieve context docs** — non-spec documents (ADRs, guides, READMEs) are retrieved via hybrid search (vector + BM25) from the search index. If the search index is unavailable, falls back to loading docs directly from GitHub using `doc_paths`. Context docs are capped at 8,000 characters.
5. **Post processing comment** — a placeholder "Analyzing N file(s) against M spec(s)..." comment is upserted.
6. **Build analysis context** — PR metadata, file patches, parsed specs (with sections, ACs, BDD scenarios), and context docs are assembled into a `PRAnalysisContext`.
7. **Call Claude** — the system prompt and user message are sent to the Anthropic API.
8. **Parse response** — JSON is extracted, with fallback handling for code fences and malformed responses.
9. **Format comment** — the result is rendered as a GitHub markdown comment with spec references, discrepancies, suggested updates, and realization status.
10. **Upsert comment** — the bot comment is created or updated on the PR.
11. **Store realizations** — if an `AgentStore` is available, realization data is persisted for coverage tracking.

---

## Prompt Architecture

The system prompt is assembled from three concatenated pieces:

### Base System Prompt

Establishes the agent's role and rules:

- Only include **direct** relationships (implements, modifies, contradicts) — never tangential or speculative connections
- Keep explanations to **short fragments** (5-10 words)
- Severity levels: `conflict` (PR directly contradicts spec) and `warning` (potential mismatch)
- **Never flag discrepancies** for sections with status `todo`, `draft`, or `blocked` — incomplete sections are expected gaps
- Doc updates must target real prose content, never metadata HTML comments (`<!-- specwright:system:... -->` or `<!-- specwright:ticket:... -->`)
- Context documents (ADRs, guides) are treated the same as specs for conflict detection
- Empty arrays are preferred over weak matches

### Realization Instructions

Appended when realization checking is enabled. Instructs the agent to evaluate each acceptance criterion:

| Status | Meaning |
|--------|---------|
| `realized` | Code fully implements this AC — provide `file:line` evidence |
| `partially_realized` | Partial implementation — explain what's missing |
| `conflicting` | Code contradicts the AC — explain how |
| `not_addressed` | PR doesn't touch this area — no evidence needed |

Only ACs from sections the PR actually touches are evaluated.

### JSON Schema

Enforces structured output with explicit instruction: "You MUST respond with raw JSON only. No markdown, no code fences, no explanation text outside the JSON."

### User Message Construction

Built by `build_user_message()` with these sections in order:

1. **PR metadata** — number, title, author, branch info, description (first 500 chars)
2. **Spec summaries** — for each spec: frontmatter metadata, section hierarchy with status/ticket links/deltas, acceptance criteria (checked/unchecked), and BDD scenarios with step keywords
3. **Related documents** — context docs with path, title, heading, and body
4. **Changed files list** — all files with status and line counts
5. **Diffs** — file patches sorted largest-first, included until the character budget is exhausted. Remaining files are noted as omitted.

---

## Diff Budgeting

The diff character budget is calculated as:

```
max_diff_chars = max((max_input_tokens - 2000) * 4, 4000)
```

With the default 128k input token limit, this yields ~504,000 characters for diffs. Files are sorted **largest-first** and included until the budget is hit. This prioritizes the most substantial changes. Files that exceed the remaining budget are skipped (not truncated), and a count of omitted files is appended.

---

## Response Format

The agent returns a JSON object with five fields:

| Field | Type | Description |
|-------|------|-------------|
| `summary` | `string` | 1-2 sentence summary of how the PR relates to specs |
| `specReferences` | `array` | Spec sections the PR directly relates to, with relevance (`high`/`medium`) and short explanation |
| `discrepancies` | `array` | Conflicts or warnings between spec and PR, with severity and suggested spec updates |
| `docUpdates` | `array` | Suggested prose changes to spec files, with current and replacement text |
| `realizations` | `array` | AC-level realization status with evidence file/line references |

### Parse Fallback Chain

1. Strip leading/trailing whitespace
2. Check for markdown code fences (` ```json ... ``` `) and extract inner content
3. Parse as JSON
4. Validate individual fields with type checks — missing fields get defaults (empty arrays, fallback summary)
5. Parse realizations individually — invalid entries are skipped rather than failing the whole response
6. If JSON parsing fails entirely and the response is short (<500 chars), use it as the summary text
7. Otherwise, return a generic "Unable to parse analysis response" fallback

---

## Comment Format

The bot comment follows this structure:

```markdown
<!-- canon-bot -->
## Canon

> {summary}

### Relevant Specs
**{spec-name}** · {spec-file}

| Section | |
|---------|---|
| {title} | {explanation} |

### Discrepancies

> [!CAUTION]
> **{section}** · {file} § {id}
>
> Spec says: {spec_says}
> PR does: {pr_does}

### Suggested Updates
**{spec-name}** · {file} § {id}

```diff
- {current text}
+ {suggested text}
```

### Realization Status
**{spec-name}** § {section}

| AC | Status | Evidence |
|----|--------|----------|
| {ac_text} | :white_check_mark: Realized | `src/file.py:42-60` |

---
<sub>canon · sonnet · 10.2k in, 1.5k out · $0.0531 · dismiss · reanalyze</sub>

<!-- canon-analysis: {embedded JSON data} -->
```

Key formatting details:

- **Heading**: "Relevant Specs" if all references are in `docs/specs/`, otherwise "Relevant Documents"
- **Discrepancies**: `[!CAUTION]` admonition for `conflict` severity, `[!WARNING]` for `warning`. Info-severity items are filtered out.
- **Suggested Updates**: diff blocks showing current vs. suggested text. No-op updates (identical text) are filtered out.
- **Realization Status**: grouped by spec file and section, with status icons and evidence links
- **Footer**: model family, token counts (formatted as e.g. "10.2k"), estimated cost, and action links
- **Embedded data**: a hidden HTML comment containing the full analysis JSON for use by interactive commands

---

## Interactive Commands

Users interact with the bot by commenting on PRs with `@canon` mentions:

| Command | Scope | Behavior |
|---------|-------|----------|
| `@canon dismiss` | PR or issue | Deletes the bot's analysis comment |
| `@canon reanalyze` | PR only | Re-runs the full analysis pipeline and updates the comment |
| `@canon apply docs` | PR only | Runs analysis, then creates a new branch and PR with the suggested doc updates applied as text replacements |
| `@canon` (anything else) | Any | Replies with a help message listing available commands |

### Apply Docs Flow

When `apply docs` is invoked:

1. The analysis is re-run to get fresh doc update suggestions
2. For each suggestion, the `current_text` is replaced with `suggested_text` in the spec file content
3. A new branch `canon/doc-update-pr-{N}` is created
4. A PR is opened with the changes and a body listing each update with its reason

---

## Configuration

Agent behavior is controlled via `CANON.yaml` in the repository root:

```yaml
agents:
  pr_analysis: true        # Enable/disable PR analysis comments
  doc_updates: true         # Enable/disable doc update suggestions
  realization_check: true   # Enable/disable AC realization tracking
  stale_detection: "30d"    # Duration before flagging stale sections (or false to disable)
```

All settings default to enabled. The `stale_detection` field accepts a duration string like `"30d"` or `"7d"`, or `false` to disable.

Additional relevant settings:

```yaml
specs:
  doc_paths:                # Glob patterns for spec/doc files
    - "docs/specs/*.md"     # (default)
    - "docs/adrs/*.md"
  auto_tickets: true        # Auto-create tickets from spec sections
  require_review: true      # Require review before ticket creation
```

---

## Token Budget & Cost

### Model Defaults

| Parameter | Value |
|-----------|-------|
| Model | `claude-sonnet-4-5-20250929` (Sonnet 4.5) |
| Max input tokens | 128,000 |
| Max output tokens | 16,000 |
| Temperature | 0 (deterministic) |

### Cost Estimation

The footer of each comment includes an estimated cost based on per-million-token pricing:

| Model family | Input ($/M) | Output ($/M) |
|-------------|-------------|--------------|
| Opus | $15.00 | $75.00 |
| Sonnet | $3.00 | $15.00 |
| Haiku | $0.80 | $4.00 |

Example: A typical PR analysis using ~10k input tokens and ~1.5k output tokens with Sonnet costs approximately **$0.05**.

---

## Error Handling

The agent degrades gracefully at each stage:

| Scenario | Behavior |
|----------|----------|
| `ANTHROPIC_API_KEY` not set | `ClaudeClient.is_available` returns `false`; fallback comment lists specs with setup instructions |
| API error (rate limit, server error) | `AgentAPIError` raised with status code; error comment posted: "Agent analysis encountered an error. Will retry on next update." |
| JSON parse failure | Fallback chain attempts code-fence stripping, partial field extraction, and raw-text summary before returning generic fallback |
| Individual realization parse error | Skipped silently — other realizations still included |
| Context doc retrieval failure | Logged at debug level; analysis proceeds without context docs |
| Realization storage failure | Logged as warning; the comment is already posted, storage is best-effort |
| Error posting comment | Caught and logged; no retry |

---

## Two-Phase Architecture Evaluation

### Background

Issue #11 was created when the codebase used TypeScript with **Haiku 4.5** as the default analysis model. The concern was that Haiku's quality was insufficient for nuanced PR-to-spec analysis, motivating a two-phase design:

1. **Triage phase** (Haiku) — quick relevance check to filter out irrelevant PRs
2. **Analysis phase** (Sonnet) — deep analysis only for relevant PRs

### Current State

The Python rewrite already addresses the core quality concern:

- **Default model is Sonnet 4.5** with 128k input tokens — the exact model the "analysis phase" would have used
- **Code-level skip conditions** already filter config-only PRs and repos without specs
- **No quality complaints** have been reported with the single-Sonnet approach

### Cost-Optimization Trade-offs

A Haiku triage layer would reduce costs by skipping Sonnet calls on irrelevant PRs, but:

| Pro | Con |
|-----|-----|
| Lower cost for irrelevant PRs | Increased latency for relevant PRs (two sequential API calls) |
| Cheaper pre-filtering than Sonnet | Added system complexity (two prompt chains, two response parsers) |
| | Uncertain ROI without usage data |

### Recommendation: Defer

The upgrade from Haiku to Sonnet already happened. A Haiku triage layer is a **cost optimization**, not a quality improvement, and should wait until usage data demonstrates significant wasted Sonnet costs on irrelevant PRs. The existing skip conditions provide first-order cost savings without added complexity.

**When to revisit:** If monitoring shows >30% of Sonnet calls produce "no relevant specs" responses, a triage phase becomes worthwhile.

---

## Source Files

| File | Role |
|------|------|
| `src/specwright/agent/client.py` | Anthropic SDK wrapper, model config, error types |
| `src/specwright/agent/analyzer.py` | Analysis orchestration, response parsing, comment formatting |
| `src/specwright/agent/prompts.py` | System prompt, user message builder, token estimation |
| `src/specwright/github/handlers/on_pull_request.py` | Webhook handler, context assembly, skip conditions |
| `src/specwright/github/handlers/on_issue_comment.py` | Interactive commands (`dismiss`, `reanalyze`, `apply docs`) |
| `src/specwright/github/spec_utils.py` | Spec file detection, `CONFIG_ONLY_RE`, doc loading |
| `src/specwright/config/parse.py` | `CANON.yaml` parsing and validation |
