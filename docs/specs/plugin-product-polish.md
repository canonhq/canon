---
title: "Canon Plugin Product Polish"
status: in_progress
owner: ng
team: canon
ticket_project: canonhq/canon-private
created: 2026-04-11
updated: 2026-04-11
tags: [plugin, claude-code, dx, marketplace, polish]
depends_on:
  - ide-integration
  - superpowers-parity
  - setup-ux-improvements
---

# Canon Plugin Product Polish

Close the gap between "Canon plugin works" and "Canon plugin feels like a product."
This spec collects the marketplace, discoverability, hook quality, and skill
enforcement gaps surfaced during the April 2026 plugin enhancement audit. It does
not introduce new core capabilities — those live in `plugin-evidence-pipeline.md`
(Workstream C) and the existing `ide-integration.md` and `superpowers-parity.md`.

## 1. Background

<!-- canon:system:1 status:done -->

The Canon Claude Code plugin shipped 13 skills, 4 hooks, a `canon-reviewer`
agent, and an MCP server through the `ide-integration` and `superpowers-parity`
specs. The April 2026 audit found those skills satisfy most ACs but the
**product surface** around them is rough:

1. `plugin/settings.json` uses an old flat schema that diverged from the `ide:`
   nested config in `CANON.yaml`. The plugin and the repo config disagree.
2. `plugin/.claude-plugin/plugin.json` lists `canonhq/canon-claude-plugin` as
   the repository, but that repo was archived in March 2026 (see memory #3348).
3. Hooks parse `CANON.yaml` with naive `grep` (`session-start.sh:21`,
   `stop.sh:15`, `pre-commit.sh:28`) which silently ignores `ide:` config when
   the YAML structure varies. The hooks promised to read `ide:` config but
   actually only look for top-level keys.
4. The marketplace listing in `plugin/.claude-plugin/marketplace.json` has no
   screenshots, no featured flag, and a one-line tagline. New users have no
   visual sense of what the plugin does.
5. `plugin/README.md` lists 12 skills (correct) but doesn't include the decision
   tree from `setup-ux-improvements.md` §4.2 explaining when to use the CLI vs
   marketplace install path.
6. `canon-meta` exists as a skill but the SessionStart hook only emits a flat
   skill list — the rationalization table never reaches the session, so users
   skip Canon skills the same way they did before the hook existed.
7. There are no slash commands in `plugin/commands/`. Slash commands have better
   discoverability than skills (they show up in `/` autocomplete) and would give
   users a more familiar surface for the highest-traffic flows.
8. There is no statusline script and no output style. The plugin has no ambient
   product presence in the terminal — users have to remember Canon exists.
9. `canon-implement` mentions reviewer dispatch conceptually but does not
   actually invoke the `canon-reviewer` agent via the Agent tool after each
   task (gap from `superpowers-parity.md` §6).
10. There is no end-to-end integration test exercising the full plan execution
    flow against a toy spec.

These are individually small but compound: a new user installing the plugin
today gets a working tool, but doesn't feel like they're using a product.

## 2. Settings & Manifest Hygiene

<!-- canon:system:2 status:done -->

Bring the plugin manifest, settings file, and marketplace metadata in line with
reality.

### Acceptance Criteria

- [x] `plugin/settings.json` is either deleted (in favor of `CANON.yaml ide:`
      as the single source of truth) or rewritten to match the nested `ide:`
      schema from `ide-integration.md` §2 — no flat `auto_context: true` keys
<!-- canon:realized-in:phase-a file:plugin/settings.json (deleted) file:tests/test_cli/test_skills_content.py:41 (test_settings_exists removed) -->
- [x] `plugin/.claude-plugin/plugin.json` `repository` field updated to point
      to a non-archived repo (either `canonhq/canon-private` or a new public
      mirror); decision recorded in this spec
<!-- canon:realized-in:phase-a file:plugin/.claude-plugin/plugin.json:8 -->
- [x] `plugin/.claude-plugin/plugin.json` version bumped to `0.2.0` to match the
      `ide-integration` Phase 2 rollout label
<!-- canon:realized-in:phase-a file:plugin/.claude-plugin/plugin.json:4 file:.claude-plugin/marketplace.json:13 -->
- [x] `plugin/.claude-plugin/marketplace.json` gains: refined tagline and
      `featured: false` documented as intentional (not absent)
<!-- canon:realized-in:phase-a file:plugin/.claude-plugin/marketplace.json:4,7 -->
- [ ] **Deferred to follow-up after Phase C ships:** at least 3 screenshots
      (skill in action, coverage dashboard, review output) — captured against
      the polished plugin with slash commands and statusline in place. See §11
      Decisions for rationale.
- [x] `plugin/README.md` includes the installation decision tree from
      `setup-ux-improvements.md` §4.2: when to use `canon setup` (CLI) vs
      `claude plugin install canon` (marketplace) and what each produces
<!-- canon:realized-in:phase-a file:plugin/README.md:5-31 -->
- [x] `plugin/README.md` describes the multi-agent setup path
      (`canon setup --agent <claude|cursor|copilot|codex|gemini>`) shipped via
      `ide-integration.md` §6
<!-- canon:realized-in:phase-a file:plugin/README.md:33-46 -->

## 3. Hook YAML Parsing

<!-- canon:system:3 status:done -->

Replace fragile `grep`-based YAML parsing in the hook scripts with a single
`canon ide-config --json` subcommand that emits a normalized JSON document hooks
can `jq` against.

### 3.1 New CLI Subcommand

Add `canon ide-config` to the Canon CLI. With `--json` it emits:

```json
{
  "auto_context": {
    "enabled": true,
    "on_session_start": true,
    "on_prompt": true,
    "max_specs": 5
  },
  "auto_verify": {
    "enabled": true,
    "on_stop": true,
    "on_commit": false,
    "confidence": "medium"
  },
  "ai_exposure": {
    "default": "full",
    "restricted_tags": []
  }
}
```

The subcommand reuses the existing `IdeConfig` Pydantic model from
`src/canon/config/parse.py` (added by `ide-integration.md` §2) so there is one
parser, not two.

### 3.2 Hook Refactor

Each hook script (`session-start.sh`, `stop.sh`, `pre-commit.sh`) replaces its
`grep` calls with:

```bash
config=$(canon ide-config --json 2>/dev/null || echo '{}')
on_session_start=$(echo "$config" | jq -r '.auto_context.on_session_start // true')
```

### Acceptance Criteria

- [x] `canon ide-config --json` subcommand added; emits the JSON shape above
<!-- canon:realized-in:phase-b file:src/canon/cli/ide_config.py:1-42 file:src/canon/cli/__init__.py:23,49,141 -->
- [x] Subcommand exits 0 even when `CANON.yaml` is missing (emits defaults)
<!-- canon:realized-in:phase-b file:src/canon/cli/ide_config.py:25-41 file:tests/test_cli/test_ide_config.py:24-31 -->
- [x] Subcommand exits 0 even when `CANON.yaml` has no `ide:` section (emits
      defaults via the existing `IdeConfig` model)
<!-- canon:realized-in:phase-b file:src/canon/cli/ide_config.py:32-41 file:tests/test_cli/test_ide_config.py:41-49 -->
- [x] Subcommand reuses `IdeConfig` from `src/canon/config/parse.py` — no
      duplicate parser
<!-- canon:realized-in:phase-b file:src/canon/cli/ide_config.py:9,33,40 -->
- [x] `plugin/hooks/session-start.sh` replaces its `grep -q 'on_session_start'`
      check with a `canon ide-config --json | jq` lookup
<!-- canon:realized-in:phase-b file:plugin/hooks/session-start.sh:20-39 -->
- [x] `plugin/hooks/stop.sh` replaces its `grep -q 'on_stop'` check the same way
<!-- canon:realized-in:phase-b file:plugin/hooks/stop.sh:13-32 -->
- [x] `plugin/hooks/pre-commit.sh` replaces its `grep -A 20 '^ide:'` check the
      same way
<!-- canon:realized-in:phase-b file:plugin/hooks/pre-commit.sh:24-32 -->
- [x] Each refactored hook still completes in under 2 seconds (the original
      performance target from `ide-integration.md` §5.1)
<!-- canon:realized-in:phase-b file:tests/test_cli/test_skills_content.py:266-269,294-298 -->
<!-- note: measured ~477ms for session-start.sh on this machine -->
- [x] Hook tests cover: missing `CANON.yaml`, missing `ide:`, fully populated
      `ide:`, and `enabled: false` for each setting
<!-- canon:realized-in:phase-b file:tests/test_cli/test_ide_config.py:24-91 -->
- [x] If `canon` CLI is not on PATH, hooks fall back to current grep behavior
      (graceful degradation)
<!-- canon:realized-in:phase-b file:plugin/hooks/session-start.sh:21-26,34-38 file:plugin/hooks/stop.sh:14-19,27-31 file:plugin/hooks/pre-commit.sh:27-32 -->

## 4. SessionStart Skill Enforcement

<!-- canon:system:4 status:done -->

Make the SessionStart hook actually enforce skill use, not just enumerate skills.
Carry forward the gap from `superpowers-parity.md` §2 ("hook injects canon-meta
rules inline").

### Acceptance Criteria

- [x] `plugin/hooks/session-start.sh` injects the `canon-meta` rationalization
      rules inline (not just the skill list) when `docs/specs/` is non-empty
<!-- canon:realized-in:phase-b file:plugin/hooks/session-start.sh:79-95 -->
- [x] Inline content stays well under the byte cap (full output ~1923 bytes
      including skill list, under the 2500 cap)
<!-- canon:realized-in:phase-b file:tests/test_cli/test_skills_content.py:286-291 -->
- [x] Injected content includes the four Iron Laws style rules (e.g., "Before
      any non-trivial change, run `/canon:context` first")
<!-- canon:realized-in:phase-b file:plugin/hooks/session-start.sh:81-91 -->
- [x] When `docs/specs/` is empty, the inline rules block is omitted (only the
      "no specs found, run `/canon:new`" hint is emitted)
<!-- canon:realized-in:phase-b file:plugin/hooks/session-start.sh:113-121 file:tests/test_cli/test_skills_content.py:279-284 -->
- [x] Test verifies the injected output is valid and under the byte cap on a
      typical Canon repo
<!-- canon:realized-in:phase-b file:tests/test_cli/test_skills_content.py:272-298 -->

## 5. Slash Commands

<!-- canon:system:5 status:done -->

Add a `plugin/commands/` directory with thin slash-command wrappers around the
highest-traffic skills. Slash commands appear in `/` autocomplete and are the
primary discovery surface in Claude Code; skills currently rely on description
matching.

### 5.1 Commands to Ship

| Command | Wraps skill | Why |
|---|---|---|
| `/canon` | `canon-meta` | Top-level entry point — opens the skill discovery table |
| `/canon-context` | `canon-context` | Most-used skill, deserves a fast keystroke |
| `/canon-plan` | `canon-plan` | Planning is the entry point for spec-driven work |
| `/canon-task` | `canon-task` | Single-task execution path |
| `/canon-verify` | `canon-verify` | Highest-frequency check during development |
| `/canon-status` | `canon-status` | Coverage dashboard, useful for "where are we?" |

Each command file is a thin frontmatter wrapper:

```markdown
---
description: Verify code against spec acceptance criteria
---

Use the canon-verify skill to verify the current branch against linked spec ACs.
```

### Acceptance Criteria

- [x] `plugin/commands/canon.md` created — entry-point command that opens
      skill discovery (canon-meta)
<!-- canon:realized-in:phase-c file:plugin/commands/canon.md -->
- [x] `plugin/commands/canon-context.md` created
<!-- canon:realized-in:phase-c file:plugin/commands/canon-context.md -->
- [x] `plugin/commands/canon-plan.md` created
<!-- canon:realized-in:phase-c file:plugin/commands/canon-plan.md -->
- [x] `plugin/commands/canon-task.md` created
<!-- canon:realized-in:phase-c file:plugin/commands/canon-task.md -->
- [x] `plugin/commands/canon-verify.md` created
<!-- canon:realized-in:phase-c file:plugin/commands/canon-verify.md -->
- [x] `plugin/commands/canon-status.md` created
<!-- canon:realized-in:phase-c file:plugin/commands/canon-status.md -->
- [x] Each command file is short and just delegates to its skill
<!-- canon:realized-in:phase-c file:tests/test_cli/test_skills_content.py:319-329 -->
- [ ] Commands appear in `/` autocomplete after plugin install (manual smoke
      test deferred to a real Claude Code session — files are auto-discovered
      by the plugin runtime per claude-code-guide lookup)
<!-- canon:gap: cannot test from automated suite; verified by file presence + frontmatter -->
- [x] `plugin/README.md` "Skills" section gains a "Commands" subsection listing
      the 6 slash commands
<!-- canon:realized-in:phase-c file:plugin/README.md:48-61 -->

## 6. Statusline & Output Style

<!-- canon:system:6 status:in_progress -->

<!-- canon:ticket:github:588 -->
Give Canon ambient product presence in the terminal.

> **Platform limitation (2026-04-11):** Claude Code's plugin system does not
> currently support shipping a statusline directly from a plugin (verified
> via `claude-code-guide` lookup; statuslines are user-level only via
> `~/.claude/settings.json statusLine`). Canon ships a reference script at
> `plugin/scripts/canon-statusline.sh` that users wire into their settings
> manually; see `plugin/README.md` "Statusline (optional)" for instructions.
> The auto-registration ACs below are deferred until Claude Code adds plugin
> statusline support.

### 6.1 Statusline

`plugin/statusline.sh` runs each prompt cycle and emits one line summarizing
spec health for the current repo:

```
specs: 42 │ coverage: 68% │ in_progress: 7 │ open ACs: 17
```

It must:
- Exit silently in non-Canon repos (no `CANON.yaml`)
- Cache results for at least 60 seconds (avoid running `canon status --json`
  every prompt)
- Complete in under 100ms when cached, under 2s when refreshing

### 6.2 Output Style

`plugin/output-styles/canon.md` defines a Canon-flavored output style that
formats AC references, spec links, and realization evidence consistently. Users
opt in via `/output-style canon`.

### Acceptance Criteria

- [ ] ~~`plugin/statusline.sh` created and registered in `plugin/.claude-plugin/plugin.json`~~
      **Deferred** (platform limitation): plugins cannot register statuslines.
      Reference script ships at `plugin/scripts/canon-statusline.sh` instead.
<!-- canon:realized-in:phase-c file:plugin/scripts/canon-statusline.sh (reference script, not auto-registered) -->
- [x] Statusline exits silently when `CANON.yaml` is absent
<!-- canon:realized-in:phase-c file:plugin/scripts/canon-statusline.sh:24-27 file:tests/test_cli/test_skills_content.py:387-401 -->
- [ ] ~~Statusline caches output to a temp file keyed by repo path; refreshes
      every 60 seconds~~
      **Deferred** with the auto-registration AC: `canon status --json` runs
      fast enough (<200ms on 44-spec repo) that explicit caching isn't needed
      for the manual wire-up path. Revisit if `canon status` slows down.
- [ ] ~~Statusline completes in <100ms on cached path, <2s on uncached path~~
      **Deferred** — relevant only if the cache layer ships
- [x] `plugin/output-styles/canon.md` created with rendering rules for AC
      checkboxes, spec links, and realization comments
<!-- canon:realized-in:phase-c file:plugin/output-styles/canon.md -->
- [x] Output style auto-discovered from `plugin/output-styles/` (no explicit
      registration needed per Claude Code's plugin auto-discovery)
<!-- canon:realized-in:phase-c file:plugin/output-styles/canon.md -->
- [x] `plugin/README.md` documents both surfaces and how to enable them
<!-- canon:realized-in:phase-c file:plugin/README.md:63-99 -->
- [x] `canon status --json` subcommand emits aggregate metrics (latent bug
      fix: session-start.sh:66 already referenced this flag)
<!-- canon:realized-in:phase-c file:src/canon/cli/status_cmd.py:14-18,109-126 file:tests/test_cli/test_status_json.py -->

## 7. canon-reviewer Auto-Dispatch

<!-- canon:system:7 status:done -->

Close the `superpowers-parity.md` §6 gap: `canon-implement` should actually
invoke the `canon-reviewer` agent via the Agent tool after each task, not just
mention it.

### Acceptance Criteria

- [x] `plugin/skills/canon-implement/SKILL.md` Step 3f.5 explicitly dispatches
      the `canon-reviewer` agent via the Agent tool with: the diff of the
      just-completed task, the linked spec section, and project conventions
<!-- canon:realized-in:phase-d file:plugin/skills/canon-implement/SKILL.md:138-159 -->
- [x] If the reviewer reports any Spec Gaps or Spec Conflicts, the plan
      execution stops at that task and presents the gaps to the user
<!-- canon:realized-in:phase-d file:plugin/skills/canon-implement/SKILL.md:148-153 -->
- [x] Quality Issues and Suggestions are printed but do not stop execution
<!-- canon:realized-in:phase-d file:plugin/skills/canon-implement/SKILL.md:151-153 -->
- [x] `plugin/skills/canon-review/SKILL.md` is updated to document its
      relationship to the `canon-reviewer` agent (the standalone path)
<!-- canon:realized-in:phase-d file:plugin/skills/canon-review/SKILL.md:69-83 -->
- [ ] An end-to-end smoke test runs canon-implement on a toy plan and confirms
      the reviewer was dispatched
<!-- canon:gap: requires a real Claude Code session to invoke the canon-implement skill; the e2e test in §8 covers the CLI dependencies but cannot dispatch agents. Defer to manual smoke testing in dogfood. -->

## 8. End-to-End Integration Test

<!-- canon:system:8 status:done -->

Carry the `superpowers-parity.md` §5 trailing gap: the plan execution engine
has no automated test.

### Acceptance Criteria

- [x] A toy fixture spec is created under `tests/fixtures/toy_spec/` with 2
      sections, 4 ACs total, and a stub source file
<!-- canon:realized-in:phase-d file:tests/fixtures/toy_spec/CANON.yaml file:tests/fixtures/toy_spec/docs/specs/toy.md file:tests/fixtures/toy_spec/src/toy.py -->
- [x] A test script generates a plan with `canon plan`, simulates the
      canon-implement workflow against it, and asserts: gate fails before
      realization, gate passes after, status reflects coverage
<!-- canon:realized-in:phase-d file:tests/test_plugin/test_implement_workflow_e2e.py -->
<!-- note: cannot dispatch the actual canon-implement skill (Claude Code only); the test exercises the CLI dependencies the skill orchestrates instead -->
- [x] Test runs in the standard test suite
<!-- canon:realized-in:phase-d file:tests/test_plugin/__init__.py file:tests/test_plugin/test_implement_workflow_e2e.py -->
- [x] Test completes in under 60 seconds (~1.2s on this machine)
<!-- canon:realized-in:phase-d file:tests/test_plugin/test_implement_workflow_e2e.py -->
- [x] `canon verify --gate` flag added to support the test (latent CLI gap
      where canon-verify skill documented a flag the CLI didn't have)
<!-- canon:realized-in:phase-d file:src/canon/cli/verify.py:18-26,33-38,90-104 file:src/canon/cli/__init__.py:121 -->

## 9. Companion-Skill Opportunism

<!-- canon:system:9 status:done -->

Carry the `superpowers-parity.md` §9 gap: when a task fails, `canon-implement`
should suggest available debugging skills, not just dump diagnostic context.

### Acceptance Criteria

- [x] `plugin/skills/canon-implement/SKILL.md` failure path (Step 3f) checks
      whether a debugging skill is available in the session and, if so,
      suggests invoking it before retrying
<!-- canon:realized-in:phase-d file:plugin/skills/canon-implement/SKILL.md:130-136 -->
- [x] Detection is opportunistic (look for `superpowers:systematic-debugging`
      or similar in the loaded skill list); never hard-depend
<!-- canon:realized-in:phase-d file:plugin/skills/canon-implement/SKILL.md:131-136 file:plugin/skills/canon-task/SKILL.md:117-129 -->
- [x] Same pattern documented in `plugin/skills/canon-task/SKILL.md` for the
      single-task path
<!-- canon:realized-in:phase-d file:plugin/skills/canon-task/SKILL.md:117-129 -->
<!-- note: canon-task/SKILL.md already had this section before Phase D; canon-implement was the gap that Phase D closed -->

## 10. Rollout Plan

<!-- canon:system:10 status:draft -->

### Phase A: Manifest & Settings (1 day)
- §2 Settings & manifest hygiene
- Quick wins; no behavior change
- Ships as plugin v0.2.0 release tag

### Phase B: Hook Quality (1-2 days)
- §3 `canon ide-config` subcommand + hook refactor
- §4 SessionStart inline meta-skill injection
- These two should ship together so hook tests cover both changes

### Phase C: Discovery Surface (1-2 days)
- §5 Slash commands
- §6 Statusline + output style
- These are independent of hooks; can be a separate PR

### Phase D: Workflow Closure (1 day)
- §7 canon-reviewer auto-dispatch
- §8 End-to-end integration test
- §9 Companion-skill opportunism
- Ships as plugin v0.3.0 release tag

## 11. Decisions and Open Questions

### Decisions (2026-04-11)

- **`plugin/settings.json`**: deleted entirely. `CANON.yaml ide:` is the
  single source of truth for Canon config. The flat-schema file was not read
  by any code path; only a test asserted its existence (also deleted).
- **Repository URL**: `canonhq/canon`. The standalone
  `canonhq/canon-claude-plugin` repo was archived in March 2026; plugin source
  lives in `canon-private/plugin/` and is mirrored to the public `canon` repo.
- **Marketplace screenshots**: deferred to follow-up after Phase C ships, so
  screenshots reflect the polished plugin (slash commands, statusline). Real
  captures of an unfinished surface would just need recapturing later.

### Open Questions

- Should the statusline pull from `canon status --json` or from a faster
  `canon status --statusline` endpoint that returns just the four numbers?
- For slash commands: do we duplicate the skill content into the command file
  or keep commands as one-line delegations? One-line keeps source-of-truth in
  the skill; duplication makes commands self-contained for users who land on
  `/canon-verify --help`.
- Should the `canon-reviewer` agent dispatch be configurable (some users may
  not want a reviewer pass on every task) via a new `ide.auto_review` flag?
