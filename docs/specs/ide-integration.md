---
title: "IDE Agent Integration"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon-private
created: 2026-03-18
updated: 2026-03-18
tags: [plugin, ide, hooks, mcp, multi-agent, security]
depends_on: []
---

# IDE Agent Integration

Make Canon spec awareness automatic in AI coding agents — hooks inject context, MCP serves content on demand, and CANON.yaml controls everything.

## 1. Background

<!-- canon:system:1 status:done -->

Canon's Claude Code plugin currently provides 9 skills that users must explicitly invoke (`/canon:context`, `/canon:verify`, etc.). This means spec-driven development only happens when the developer remembers to use it. No other AI coding agent (Cursor, Copilot, Codex, Gemini CLI) gets any spec awareness at all.

The GitHub App handles PR-time concerns (analysis, realization tracking, doc-update PRs). This spec covers **dev-time** concerns — the gap between when a developer starts coding and when they open a PR.

**Problems today:**

1. **Opt-in only** — skills require explicit invocation; developers forget
2. **Claude Code only** — no integration with Cursor, Copilot, Codex, Gemini
3. **No context injection** — the agent doesn't know specs exist unless told
4. **No security controls** — all spec content goes to AI providers without filtering
5. **No dev→PR evidence pipeline** — work done in IDE doesn't feed into the GitHub App's PR analysis
6. **Push vs pull confusion** — `auto_context: true` exists in settings but isn't implemented; a static context file approach would create staleness, merge conflicts, token waste, and security exposure

**Design principles:**

- **Pull, not push** — spec content served on demand via MCP, never persisted into generated context files
- **Agent-agnostic config** — CANON.yaml `ide:` section works for any coding agent, not just Claude
- **Tiny committed footprint** — only CANON.yaml and thin agent config wrappers committed; no large generated files
- **Graceful degradation** — MCP-capable agents get full experience; others get index + CLI
- **Security by default** — `ai_exposure` controls enforced at MCP layer before content reaches any AI provider

## 2. CANON.yaml `ide:` Section

<!-- canon:system:2 status:done -->

Add a new `ide:` top-level section to CANON.yaml that controls client-side AI agent behavior. This complements the existing `agents:` section which controls server-side behavior (PR analysis, doc updates).

```yaml
# Existing server-side config (unchanged)
agents:
  pr_analysis: true
  doc_updates: true

# NEW: Client-side agent behavior
ide:
  auto_context:
    enabled: true              # inject spec awareness automatically
    on_session_start: true     # load spec summary when session begins
    on_prompt: true            # match user intent to relevant specs
    max_specs: 5               # cap specs loaded per query to control tokens

  auto_verify:
    enabled: true
    on_stop: true              # suggest spec updates before session ends
    on_commit: false           # gate commits on spec compliance (opt-in, strict)
    confidence: "medium"       # medium | high — threshold for suggestions

  ai_exposure:
    default: "full"            # full | metadata | none
    restricted_tags: []        # auto-restrict specs with these tags
```

### 2.1 Configuration Schema

The `ide:` section must be validated by the existing CANON.yaml parser (`src/canon/config/parse.py`) using a new `IdeConfig` Pydantic model with nested models for `auto_context`, `auto_verify`, and `ai_exposure`.

All fields have defaults that match current behavior (no breaking change). A repo with no `ide:` section behaves exactly as today.

### 2.2 Agent-Agnostic Design

The section is named `ide:` (not `claude:` or `cursor:`) because any coding agent implementation reads the same config. The Claude Code plugin translates `ide:` settings into hooks; a future Cursor extension would read the same `ide:` section and implement equivalent behavior.

### Acceptance Criteria

- [ ] `IdeConfig` Pydantic model added to `src/canon/config/parse.py` with nested `AutoContextConfig`, `AutoVerifyConfig`, `AiExposureConfig`
- [ ] All fields have defaults: `auto_context.enabled=true`, `auto_verify.enabled=true`, `ai_exposure.default="full"`
- [ ] Missing `ide:` section returns defaults (no error)
- [ ] Unknown keys in `ide:` generate warnings (consistent with existing parser behavior)
- [ ] `confidence` validates to `"medium"` or `"high"` only
- [ ] `ai_exposure.default` validates to `"full"`, `"metadata"`, or `"none"` only
- [ ] `restricted_tags` must be a list of strings
- [ ] Parser tests cover valid config, defaults, unknown keys, and invalid values
- [ ] Existing CANON.yaml files without `ide:` section continue to parse without changes

## 3. AI Exposure Controls

<!-- canon:system:3 status:done -->

Add per-spec `ai_exposure` frontmatter field that controls what content is sent to AI providers via MCP tools. Enforced at the MCP server layer so all consumers (Claude Code, Cursor, Copilot, any MCP client) respect the same restrictions.

### 3.1 Spec Frontmatter Field

```yaml
---
title: Security Vulnerability Assessment
ai_exposure: metadata    # full (default) | metadata | none
---
```

- **`full`** (default) — all spec content available to AI providers via MCP tools
- **`metadata`** — only title, status, section titles, AC counts exposed; section content and AC text redacted in MCP responses
- **`none`** — spec does not appear in MCP tool results at all

### 3.2 CANON.yaml Defaults

The `ide.ai_exposure.default` field sets the org/repo-wide default. The `restricted_tags` field auto-restricts specs matching any of the listed tags, overriding the default to `metadata`.

```yaml
ide:
  ai_exposure:
    default: full
    restricted_tags: [security, pricing, legal]
```

Resolution order: spec frontmatter `ai_exposure` > `restricted_tags` match > `ide.ai_exposure.default` > `"full"`.

### 3.3 MCP Server Enforcement

Filtering is applied in the MCP server (`src/canon/mcp/server.py`) at the tool response level:

- `list_specs` — omits specs with `ai_exposure: none`; includes metadata-only entries for `metadata` specs
- `get_spec` — returns error for `none` specs; redacts section content and AC text for `metadata` specs
- `get_section` — returns error for `none` specs; redacts content for `metadata` specs
- `search` — excludes `none` specs from results; omits body snippets for `metadata` specs
- `get_doc` — respects `ai_exposure` if the doc is a spec file

### 3.4 GitHub App Enforcement

The agent prompt builder (`src/canon/agent/prompts.py`) must also respect `ai_exposure` when building the user message for PR analysis. Specs marked `metadata` should appear in the analysis as title/status only. Specs marked `none` should be omitted entirely.

### Acceptance Criteria

- [ ] `ai_exposure` field added to `SpecDocument` frontmatter model (`src/canon/parser/models.py`)
- [ ] Parser recognizes `ai_exposure` with values `full`, `metadata`, `none`; defaults to `full` if absent
- [ ] MCP `list_specs` omits `none` specs and redacts `metadata` spec content
- [ ] MCP `get_spec` returns error for `none`, redacts content for `metadata`
- [ ] MCP `search` excludes `none`, omits snippets for `metadata`
- [ ] `restricted_tags` in CANON.yaml overrides default to `metadata` for matching specs
- [ ] Resolution order: frontmatter > restricted_tags > CANON.yaml default > full
- [ ] Agent prompt builder respects `ai_exposure` when including specs in PR analysis
- [ ] Tests cover all three levels and resolution precedence

## 4. MCP Server Enhancements

<!-- canon:system:4 status:done -->

Add `summary_only` mode and pagination to the MCP server to support token-budget-aware context loading.

### 4.1 `summary_only` Parameter for `get_spec`

Add an optional `summary_only: bool = False` parameter to the `get_spec` MCP tool. When `true`, returns only:

- Frontmatter (title, status, owner, team, tags)
- Section list with: number, title, status, depth, AC count (checked/total)
- No section content, no AC text, no raw markdown

This reduces a 25KB spec response to ~500 bytes of structured metadata. Skills and hooks should prefer `summary_only=true` for initial context loading and only request full content when the agent needs deep analysis.

### 4.2 Pagination for `list_specs`

Add optional `page: int = 1` and `per_page: int = 50` parameters to `list_specs`. For repos with 100+ specs, loading all metadata in a single response consumes unnecessary context.

### 4.3 Section Status Filter for `get_spec`

Add optional `status_filter: list[str] | None = None` parameter to `get_spec`. When provided, only sections matching the given statuses are included. Example: `status_filter=["todo", "in_progress"]` returns only actionable sections.

### Acceptance Criteria

- [ ] `get_spec` accepts `summary_only` parameter; when true, returns frontmatter + section metadata only (no content, no AC text)
- [ ] `list_specs` accepts `page` and `per_page` parameters with defaults (1, 50)
- [ ] `list_specs` returns total count alongside paginated results
- [ ] `get_spec` accepts `status_filter` parameter; when set, only matching sections included
- [ ] Existing callers unaffected (all new parameters are optional with backward-compatible defaults)
- [ ] MCP tool schemas updated with new parameter descriptions

## 5. Claude Code Plugin Hooks

<!-- canon:system:5 status:done -->

Add hooks to the Canon Claude Code plugin that make spec awareness automatic. Hooks read `ide:` config from CANON.yaml to determine behavior.

### 5.1 SessionStart Hook

**Trigger**: Session startup, resume, clear, compact.

**Behavior**:
1. Check for CANON.yaml in project root (fast `test -f` check)
2. If missing, exit silently (not a Canon repo)
3. Parse `ide.auto_context` config (via `yq` or simple grep)
4. If `on_session_start` is enabled, inject a short context message into the session:
   - "This repo uses Canon specs. Use Canon MCP tools or /canon skills for spec context."
   - Optionally include spec count and coverage summary from `canon status --json` (if fast enough < 2s)
5. Set `CANON_REPO=true` environment variable for downstream hooks

**Performance target**: < 2 seconds. Must not block session startup.

### 5.2 UserPromptSubmit Hook

**Trigger**: User submits a prompt.

**Behavior**:
1. If `ide.auto_context.on_prompt` is disabled, exit
2. Use a prompt-type hook that instructs Claude to check if the user's message relates to any spec
3. If related, Claude calls MCP `search` with relevant keywords and injects matching spec context
4. Cap at `max_specs` (default 5) specs loaded per prompt

**Implementation**: Prompt-type hook (not command) — lets the LLM decide relevance rather than keyword matching.

### 5.3 Stop Hook

**Trigger**: Session is about to end.

**Behavior**:
1. If `ide.auto_verify.on_stop` is disabled, exit
2. Check `git diff --name-only` for modified files
3. Match modified files against spec `doc_paths` patterns
4. If spec-related files were changed, suggest: "You modified files related to [spec names]. Run `/canon:verify` to check spec compliance or `/canon:update` to update statuses."
5. Do not auto-apply changes — suggest only

### 5.4 PreToolUse Hook (Bash: git commit)

**Trigger**: Before a `git commit` command executes.

**Behavior**:
1. If `ide.auto_verify.on_commit` is disabled, exit
2. Check staged files against spec patterns
3. If spec-related files are staged, prompt: "Staged files relate to specs [list]. Consider adding spec references to commit message (e.g., `[spec:auth#2.1]`)."
4. Do not block the commit — advisory only unless `on_commit: true` in config (strict mode)

### 5.5 Hook Configuration

Hooks are defined in `plugin/hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup|resume",
      "hooks": [{
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh",
        "timeout": 5
      }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "prompt",
        "prompt": "If this repo has Canon specs (check CANON.yaml), search for relevant specs using MCP search and inject context. Only inject if directly relevant. Cap at 5 specs.",
        "timeout": 10
      }]
    }],
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/stop.sh",
        "timeout": 5
      }]
    }]
  }
}
```

### Acceptance Criteria

- [ ] `hooks/hooks.json` created with SessionStart, UserPromptSubmit, and Stop hooks
- [ ] `hooks/session-start.sh` detects CANON.yaml and injects awareness message
- [ ] `hooks/stop.sh` checks git diff against spec patterns and suggests verification
- [ ] SessionStart completes in < 2 seconds
- [ ] All hooks respect `ide:` config from CANON.yaml (disabled = no-op)
- [ ] Hooks degrade gracefully if CANON.yaml is missing or malformed (silent exit, no errors)
- [ ] PreToolUse hook for commit is advisory-only by default; blocks only when `on_commit: true`
- [ ] Hook scripts are executable and use `${CLAUDE_PLUGIN_ROOT}` for portable paths

## 6. Multi-Agent Setup

<!-- canon:system:6 status:done -->

Add a `canon setup --agent <platform>` CLI command that generates thin agent-config wrapper files for each supported AI coding agent platform.

### 6.1 Supported Platforms

| Platform | Config File | Content |
|---|---|---|
| `claude` | `.claude/CLAUDE.md` | Points to CANON.yaml, describes MCP tools available |
| `cursor` | `.cursorrules` | Same content adapted for Cursor format |
| `copilot` | `.github/copilot-instructions.md` | Same content adapted for Copilot format |
| `codex` | `AGENTS.md` | Same content adapted for Codex format |
| `gemini` | `GEMINI.md` | Same content adapted for Gemini CLI format |

### 6.2 Generated File Content

Each file is 10-20 lines containing:

1. A note that this repo uses Canon for spec-driven development
2. Location of `CANON.yaml` configuration
3. How to access specs (MCP tools if available, CLI fallback)
4. Instruction to check spec context before modifying code in `docs/specs/` paths
5. A note that the file was auto-generated by `canon setup`

These files are **committed to the repo** and rarely change. They contain instructions, not data. They only need regeneration when Canon's skill definitions change (i.e., a new Canon version), not when spec content changes.

### 6.3 CLI Interface

```bash
canon setup --agent claude     # generates .claude/CLAUDE.md
canon setup --agent cursor     # generates .cursorrules
canon setup --agent all        # generates all supported platforms
canon setup --agent claude --force  # overwrites existing file
```

If the target file already exists and contains non-Canon content, warn and require `--force`. If it contains a previous Canon-generated block (identified by `<!-- canon:agent-config -->` marker), replace only that block.

### Acceptance Criteria

- [ ] `canon setup --agent <platform>` command implemented in CLI
- [ ] Generates correct config files for claude, cursor, copilot, codex, gemini
- [ ] Generated files are < 30 lines each
- [ ] Generated files include `<!-- canon:agent-config -->` marker for safe re-generation
- [ ] Existing files with Canon marker are safely updated (only Canon block replaced)
- [ ] Existing files without Canon marker trigger warning and require `--force`
- [ ] `--agent all` generates all supported platforms
- [ ] Generated content references CANON.yaml and MCP tools, not spec content

## 7. Plugin-to-GitHub-App Evidence Pipeline

<!-- canon:system:7 status:draft -->

When a developer works on spec-related code in their IDE, the plugin could pre-populate realization evidence so the GitHub App's PR analysis is faster and more accurate. This section is exploratory.

### 7.1 Concept

During a dev session, the Stop hook could write a `.canon/session-evidence.json` file tracking which spec sections were worked on, which ACs were addressed, and which files were modified. When a PR is opened, the GitHub App reads this file from the branch and uses it as hints for the agent analysis.

### 7.2 Open Questions

- Should evidence be committed (discoverable by GitHub App) or communicated via MCP/API?
- How to handle multiple dev sessions contributing to one PR?
- Does this create a coupling between plugin and GitHub App that's hard to maintain?
- Is the improvement in PR analysis quality worth the complexity?

This section is intentionally left as `draft` — it requires validation of the core hooks (§5) before exploring this optimization.

## 8. Rollout Plan

<!-- canon:system:8 status:draft -->

### Phase 1: Foundation (CANON.yaml + MCP)

1. Add `IdeConfig` to CANON.yaml parser (§2)
2. Add `ai_exposure` to spec frontmatter and MCP filtering (§3)
3. Add `summary_only` and pagination to MCP server (§4)
4. Ship as Canon CLI/MCP update — no plugin changes yet

### Phase 2: Plugin Hooks

1. Add SessionStart hook (§5.1)
2. Add Stop hook (§5.3)
3. Ship as plugin v0.2.0
4. Validate with internal usage before adding UserPromptSubmit

### Phase 3: Multi-Agent + UserPromptSubmit

1. Add `canon setup --agent` CLI command (§6)
2. Add UserPromptSubmit hook (§5.2) — most complex, needs tuning
3. Add PreToolUse commit hook (§5.4)
4. Ship as plugin v0.3.0

### Phase 4: Evidence Pipeline (Exploratory)

1. Validate §7 concept based on Phase 2/3 learnings
2. Implement if warranted

## 9. Open Questions

- Should `ai_exposure` support per-section granularity (not just per-spec)?
- Should the UserPromptSubmit hook use vector similarity or just keyword matching for spec relevance?
- How should `restricted_tags` interact with team-based access control in multi-tenant deployments?
- Should hooks be configurable per-developer via `.canon.local.md` overrides?
