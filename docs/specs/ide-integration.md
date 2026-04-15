---
title: "IDE Agent Integration"
status: in_progress
owner: ng
team: canon
ticket_project: canonhq/canon-private
created: 2026-03-18
updated: 2026-04-11
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

- [x] `IdeConfig` Pydantic model added to `src/canon/config/parse.py` with nested `AutoContextConfig`, `AutoVerifyConfig`, `AiExposureConfig`
<!-- canon:realized-in:audit file:src/canon/config/parse.py:54-86 -->
- [x] All fields have defaults: `auto_context.enabled=true`, `auto_verify.enabled=true`, `ai_exposure.default="full"`
<!-- canon:realized-in:audit file:src/canon/config/parse.py:54-86 -->
- [x] Missing `ide:` section returns defaults (no error)
<!-- canon:realized-in:audit file:tests/test_config/test_parse.py:276 -->
- [x] Unknown keys in `ide:` generate warnings (consistent with existing parser behavior)
<!-- canon:realized-in:audit file:src/canon/config/parse.py:654 -->
- [x] `confidence` validates to `"medium"` or `"high"` only
<!-- canon:realized-in:audit file:src/canon/config/parse.py:63 -->
- [x] `ai_exposure.default` validates to `"full"`, `"metadata"`, or `"none"` only
<!-- canon:realized-in:audit file:src/canon/config/parse.py:69-70 -->
- [x] `restricted_tags` must be a list of strings
<!-- canon:realized-in:audit file:src/canon/config/parse.py:73 -->
- [x] Parser tests cover valid config, defaults, unknown keys, and invalid values
<!-- canon:realized-in:audit file:tests/test_config/test_parse.py:247-287 -->
- [x] Existing CANON.yaml files without `ide:` section continue to parse without changes
<!-- canon:realized-in:audit file:tests/test_config/test_parse.py:276 -->

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

- [x] `ai_exposure` field added to `SpecDocument` frontmatter model (`src/canon/parser/models.py`)
<!-- canon:realized-in:audit file:src/canon/parser/models.py:110 -->
- [x] Parser recognizes `ai_exposure` with values `full`, `metadata`, `none`; defaults to `full` if absent
<!-- canon:realized-in:audit file:tests/test_parser/test_parse.py:69-106 -->
- [x] MCP `list_specs` omits `none` specs and redacts `metadata` spec content
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:470-492 -->
- [x] MCP `get_spec` returns error for `none`, redacts content for `metadata`
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:288-294 -->
- [x] MCP `search` excludes `none`, omits snippets for `metadata`
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:219-231 -->
- [x] `restricted_tags` in CANON.yaml overrides default to `metadata` for matching specs
<!-- canon:realized-in:audit file:src/canon/parser/models.py:146-165 -->
- [x] Resolution order: frontmatter > restricted_tags > CANON.yaml default > full
<!-- canon:realized-in:audit file:src/canon/parser/models.py:146-165 -->
- [x] Agent prompt builder respects `ai_exposure` when including specs in PR analysis
<!-- canon:realized-in:audit file:src/canon/agent/prompts.py:148-241 -->
- [x] Tests cover all three levels and resolution precedence
<!-- canon:realized-in:audit file:tests/test_parser/test_parse.py:69-106 file:tests/test_agent/test_prompts.py -->

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

- [x] `get_spec` accepts `summary_only` parameter; when true, returns frontmatter + section metadata only (no content, no AC text)
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:264,313 -->
- [x] `list_specs` accepts `page` and `per_page` parameters with defaults (1, 50)
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:450-451 -->
- [x] `list_specs` returns total count alongside paginated results
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:496-506 -->
- [x] `get_spec` accepts `status_filter` parameter; when set, only matching sections included
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:265,315-325 -->
- [x] Existing callers unaffected (all new parameters are optional with backward-compatible defaults)
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:264-265 -->
- [x] MCP tool schemas updated with new parameter descriptions
<!-- canon:realized-in:audit file:src/canon/mcp/server.py:252-258 -->

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

- [x] `hooks/hooks.json` created with SessionStart, UserPromptSubmit, and Stop hooks
<!-- canon:realized-in:audit file:plugin/hooks/hooks.json:1-53 -->
- [x] `hooks/session-start.sh` detects CANON.yaml and injects awareness message
<!-- canon:realized-in:audit file:plugin/hooks/session-start.sh:1-42 -->
- [x] `hooks/stop.sh` checks git diff against spec patterns and suggests verification
<!-- canon:realized-in:audit file:plugin/hooks/stop.sh:1-66 -->
- [x] SessionStart completes in < 2 seconds
<!-- canon:realized-in:audit file:plugin/hooks/session-start.sh:32 -->
- [x] All hooks respect `ide:` config from CANON.yaml (disabled = no-op)
<!-- canon:realized-in:audit file:plugin/hooks/session-start.sh:16-18 file:plugin/hooks/stop.sh:15-17 -->
- [x] Hooks degrade gracefully if CANON.yaml is missing or malformed (silent exit, no errors)
<!-- canon:realized-in:audit file:plugin/hooks/session-start.sh:10-12 file:plugin/hooks/stop.sh:9-11 -->
- [x] PreToolUse hook for commit is advisory-only by default; blocks only when `on_commit: true`
<!-- canon:realized-in:audit file:plugin/hooks/pre-commit.sh:61-66 -->
- [x] Hook scripts are executable and use `${CLAUDE_PLUGIN_ROOT}` for portable paths
<!-- canon:realized-in:audit file:plugin/hooks/hooks.json:10,34,46 -->

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

- [x] `canon setup --agent <platform>` command implemented in CLI
<!-- canon:realized-in:audit file:src/canon/cli/setup_cmd.py:30-32 file:src/canon/cli/agent_setup.py:78-139 -->
- [x] Generates correct config files for claude, cursor, copilot, codex, gemini
<!-- canon:realized-in:audit file:src/canon/cli/agent_setup.py:11-20 -->
- [x] Generated files are < 30 lines each
<!-- canon:realized-in:audit file:tests/test_cli/test_agent_setup.py:52 -->
- [x] Generated files include `<!-- canon:agent-config -->` marker for safe re-generation
<!-- canon:realized-in:audit file:tests/test_cli/test_agent_setup.py:64 file:src/canon/cli/agent_setup.py:8-9 -->
- [x] Existing files with Canon marker are safely updated (only Canon block replaced)
<!-- canon:realized-in:audit file:src/canon/cli/agent_setup.py:99-106 -->
- [x] Existing files without Canon marker trigger warning and require `--force`
<!-- canon:realized-in:audit file:src/canon/cli/agent_setup.py:108-113 -->
- [x] `--agent all` generates all supported platforms
<!-- canon:realized-in:audit file:src/canon/cli/agent_setup.py:126-139 -->
- [x] Generated content references CANON.yaml and MCP tools, not spec content
<!-- canon:realized-in:audit file:tests/test_cli/test_agent_setup.py:129 -->

## 7. Plugin-to-GitHub-App Evidence Pipeline

<!-- canon:system:7 status:moved -->

**Moved to its own spec:** `docs/specs/plugin-evidence-pipeline.md`

The dev→PR evidence pipeline grew large enough during planning to warrant its own
spec. The original concept (Stop hook writes `.canon/session-evidence.json`,
GitHub App reads it at PR time) is preserved there with full design and rollout.

## 8. Rollout Plan

<!-- canon:system:8 status:done -->

### Phase 1: Foundation (CANON.yaml + MCP) — DONE

1. ✅ Add `IdeConfig` to CANON.yaml parser (§2)
2. ✅ Add `ai_exposure` to spec frontmatter and MCP filtering (§3)
3. ✅ Add `summary_only` and pagination to MCP server (§4)
4. ✅ Shipped as Canon CLI/MCP update

### Phase 2: Plugin Hooks — DONE

1. ✅ Add SessionStart hook (§5.1)
2. ✅ Add Stop hook (§5.3)
3. Pending plugin v0.2.0 release tag

### Phase 3: Multi-Agent + UserPromptSubmit — DONE

1. ✅ Add `canon setup --agent` CLI command (§6)
2. ✅ Add UserPromptSubmit hook (§5.2)
3. ✅ Add PreToolUse commit hook (§5.4)
4. Pending plugin v0.3.0 release tag

### Phase 4: Evidence Pipeline — MOVED

§7 has been moved to `plugin-evidence-pipeline.md` for full design and rollout.

## 9. Open Questions

- Should `ai_exposure` support per-section granularity (not just per-spec)?
- Should the UserPromptSubmit hook use vector similarity or just keyword matching for spec relevance?
- How should `restricted_tags` interact with team-based access control in multi-tenant deployments?
- Should hooks be configurable per-developer via `.canon.local.md` overrides?
