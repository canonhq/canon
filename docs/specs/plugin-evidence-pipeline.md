---
title: "Plugin → GitHub App Evidence Pipeline"
status: in_progress
owner: ng
team: canon
ticket_project: canonhq/canon-private
created: 2026-04-11
updated: 2026-04-11
tags: [plugin, github-app, evidence, mcp, ide, strategic]
depends_on:
  - ide-integration
  - plugin-product-polish
---

# Plugin → GitHub App Evidence Pipeline

Close the loop between IDE-time work and GitHub App PR-time analysis by
recording structured evidence during dev sessions and feeding it into PR review
as hint input.

This is the strategic unlock that competitors structurally cannot ship: only
Canon owns both the IDE plugin (which sees what was actually edited) and the
GitHub App (which analyzes PRs against specs). Connecting the two produces
PR analysis that is faster, cheaper, and more accurate than starting from cold.

## 1. Background

<!-- canon:system:1 status:done -->

Today, the Canon GitHub App analyzes PRs from cold:

1. PR opens → webhook fires → analyzer reads the diff
2. Analyzer searches for related specs (no hint about which sections were touched)
3. Analyzer asks the LLM to map diff hunks to ACs (expensive token cost)
4. Analyzer writes back realization comments and a coverage delta

Meanwhile, in the IDE, the developer just spent two hours working against
specific spec sections and ACs. The plugin already knows which sections they
loaded via `canon-context`, which ACs `canon-verify` evaluated, and which files
they edited. **None of that signal reaches the PR analyzer.**

The original concept lived in `ide-integration.md` §7 as draft. Workstream C
of the April 2026 plugin polish promotes it to its own spec because it's the
biggest product unlock and has enough open questions to deserve real design.

### Why this matters

- **Cost**: PR analysis is the largest LLM-spend line item in Canon. Every
  token of hint we can prepend reduces the LLM's search space.
- **Accuracy**: Cold analysis sometimes maps a diff to the wrong spec section
  because grep-and-guess. Dev-session evidence eliminates that ambiguity.
- **Speed**: Faster PR comments mean Canon feels alive in PR review. Slow
  Canon = ignored Canon.
- **Defensibility**: Any competitor can ship a GitHub App that reads specs and
  PRs. Only Canon ships an IDE plugin that captures the dev session for the
  GitHub App to consume. That coupling is the moat.

## 2. Evidence Schema

<!-- canon:system:2 status:done -->

Define the on-disk and over-the-wire format for session evidence.

### 2.1 File Format

`.canon/session-evidence.json` is a JSON document with the following shape:

```json
{
  "version": 1,
  "session_id": "20260411-164600-a7b3",
  "started_at": "2026-04-11T16:46:00Z",
  "ended_at": "2026-04-11T18:12:30Z",
  "git_branch": "canon/auth-hardening/2.1",
  "git_base": "main",
  "specs_touched": [
    {
      "spec": "auth-hardening",
      "sections": ["2.1", "2.2"],
      "loaded_via": ["canon-context", "canon-task"]
    }
  ],
  "acs_addressed": [
    {
      "spec": "auth-hardening",
      "section": "2.1",
      "ac_text": "Rate limit: max 3 resets per hour",
      "files": ["src/auth/rate_limit.py"],
      "line_ranges": ["42-60"],
      "verify_status": "realized",
      "verified_at": "2026-04-11T17:54:12Z"
    }
  ],
  "files_modified": [
    "src/auth/rate_limit.py",
    "tests/test_auth/test_rate_limit.py"
  ],
  "verify_runs": [
    {
      "at": "2026-04-11T17:54:12Z",
      "section": "2.1",
      "mode": "gate",
      "result": "pass"
    }
  ]
}
```

### 2.2 Multi-Session Aggregation

A single PR may span multiple dev sessions across days. Sessions append to the
file rather than overwriting. The file becomes a list of session records:

```json
{
  "version": 1,
  "sessions": [
    { "session_id": "...", ... },
    { "session_id": "...", ... }
  ]
}
```

The GitHub App reads the union when analyzing the PR.

### Acceptance Criteria

- [x] JSON schema documented in `docs/specs/plugin-evidence-pipeline.md` (this
      file) and validated by a Pydantic model `SessionEvidence` in
      `src/canon/evidence/models.py`
<!-- canon:realized-in:phase-c-evidence file:src/canon/evidence/models.py -->
- [x] Schema versioning: top-level `version: 1` field; future analyzer can
      reject unknown versions
<!-- canon:realized-in:phase-c-evidence file:src/canon/evidence/models.py symbol:SessionEvidence -->
- [x] Multi-session append works: existing file is read, new session appended,
      file rewritten atomically (temp file + rename)
<!-- canon:realized-in:phase-c-evidence file:src/canon/cli/evidence.py symbol:_append_session_record -->
- [x] Schema includes a "verify_runs" log so the verification trail gap from
      `superpowers-parity.md` §8 is closed by this spec
<!-- canon:realized-in:phase-c-evidence file:src/canon/evidence/models.py symbol:VerifyRun -->
- [x] Pydantic model validates: required fields present, types enforced
<!-- canon:realized-in:phase-c-evidence file:tests/test_cli/test_evidence.py symbol:TestEvidenceModels -->
- [x] Test fixtures cover: empty file, single-session file, multi-session file,
      malformed file (read returns empty record, no crash)
<!-- canon:realized-in:phase-c-evidence file:tests/test_cli/test_evidence.py symbol:TestParseEvidencePayload -->
<!-- note: malformed-file fallback is handled by ValueError catch in _append_session_record -->
- [x] PR analyzer rejection of unknown versions
<!-- canon:realized-in:phase-followup file:src/canon/github/handlers/on_pull_request.py:_load_session_evidence (logs warning + falls back to cold analysis when version != 1) -->

## 3. Stop Hook Evidence Writer

<!-- canon:system:3 status:done -->

Extend `plugin/hooks/stop.sh` to write a session record on session end.

### 3.1 What the Hook Records

When the Stop hook fires:

1. Read the current git branch and base via `git rev-parse` and `git merge-base`
2. Read modified files via `git diff --name-only`
3. Read recent canon-verify gate results from a hook-managed log file (see §4)
4. Compose a `SessionRecord` and append to `.canon/session-evidence.json`
5. Exit silently if the user has not explicitly opted in (`ide.evidence_pipeline: true`)

### 3.2 Opt-in by Default Off

The first release ships with `ide.evidence_pipeline: false` (off). Users opt
in per-repo via `CANON.yaml`:

```yaml
ide:
  evidence_pipeline:
    enabled: true
    persist: file        # file | mcp | both
    commit_on_push: ask  # ask | always | never
```

### Acceptance Criteria

- [x] `IdeConfig` Pydantic model in `src/canon/config/parse.py` gains an
      `evidence_pipeline` field with `enabled`, `persist`, `commit_on_push`
      sub-fields
<!-- canon:realized-in:phase-c-evidence file:src/canon/config/parse.py symbol:EvidencePipelineConfig symbol:IdeConfig -->
- [x] `canon ide-config --json` (from `plugin-product-polish.md` §3) includes
      `evidence_pipeline` in its output
<!-- canon:realized-in:phase-c-evidence file:src/canon/config/parse.py symbol:_merge_with_defaults file:tests/test_cli/test_evidence.py symbol:TestIdeConfigEvidencePipeline -->
<!-- note: required adding explicit evidence_pipeline parsing in _merge_with_defaults -->
- [x] `plugin/hooks/stop.sh` reads `evidence_pipeline.enabled`; exits silently
      when false (no-op when not enabled)
<!-- canon:realized-in:phase-c-evidence file:plugin/hooks/stop.sh -->
- [x] When enabled, `stop.sh` invokes `canon evidence record` rather than
      writing JSON inline — keeps shell scripting minimal
<!-- canon:realized-in:phase-c-evidence file:plugin/hooks/stop.sh file:src/canon/cli/evidence.py -->
- [x] `canon evidence record` reads git state, reads the canon-verify log,
      composes a `SessionRecord`, appends to `.canon/session-evidence.json`
<!-- canon:realized-in:phase-c-evidence file:src/canon/cli/evidence.py symbol:run_record symbol:_compose_session_record -->
- [x] Atomic write: temp file + rename
<!-- canon:realized-in:phase-c-evidence file:src/canon/cli/evidence.py symbol:_append_session_record -->
- [x] `.canon/` is added to `.gitignore` automatically when
      `commit_on_push: ask` or `never` (idempotent; first `canon evidence
      record` adds the marker block)
<!-- canon:realized-in:phase-5-evidence file:src/canon/cli/evidence.py symbol:_ensure_gitignore_entry -->
- [x] Tests cover: opt-out path, opt-in path, multi-session append
<!-- canon:realized-in:phase-c-evidence file:tests/test_cli/test_evidence.py symbol:TestEvidenceRecord -->

## 4. canon-verify Trail Logging

<!-- canon:system:4 status:done -->

Carry the gap from `superpowers-parity.md` §8: "Gate results are logged so the
user can see the verification trail." This spec implements that as the input
the Stop hook reads when composing session evidence.

### Acceptance Criteria

- [x] `canon verify --gate` appends a JSONL record to
      `.canon/verify-log.jsonl` for each gate run when evidence pipeline is
      enabled: `{at, section, mode, result, gaps, conflicts}`
<!-- canon:realized-in:phase-c-evidence file:src/canon/cli/verify.py symbol:_record_gate_run -->
- [x] Log file is created if missing; append-only
<!-- canon:realized-in:phase-c-evidence file:src/canon/cli/verify.py symbol:_record_gate_run -->
- [x] Skill documentation updated to mention the trail file location
<!-- canon:realized-in:phase-followup file:plugin/skills/canon-verify/SKILL.md (Verification Trail section) -->
- [x] Helper `canon evidence list-verify-runs --since <ts>` reads the log and
      emits the records the Stop hook will use
<!-- canon:realized-in:phase-c-evidence file:src/canon/cli/evidence.py symbol:run_list_verify_runs symbol:_read_verify_log_since -->
- [x] Log rotates: when the file exceeds 1 MB, rename to `verify-log.jsonl.1`
      and start fresh
<!-- canon:realized-in:phase-c-evidence file:src/canon/cli/verify.py symbol:_record_gate_run -->

## 5. PreToolUse git push Persistence Prompt

<!-- canon:system:5 status:done -->

When the user pushes a branch, offer to persist the session evidence to a
location the GitHub App can read.

### 5.1 Two Persistence Modes

1. **File mode** (`persist: file`): commit `.canon/session-evidence.json` to
   the branch so the GitHub App can read it from the PR ref
2. **MCP mode** (`persist: mcp`): POST the evidence to the Canon backend via
   the existing MCP server's new `record_session_evidence` tool; the GitHub
   App fetches it by branch SHA at PR-time
3. **Both** (`persist: both`): commit and POST

### 5.2 PreToolUse Hook

A new `plugin/hooks/pre-push.sh` script triggers on `git push` (matched via
the existing PreToolUse Bash hook, extended to recognize `git push`):

- If `evidence_pipeline.commit_on_push: ask`: prompt the user inline
- If `always`: silently `git add .canon/session-evidence.json && git commit`
- If `never`: skip file persistence; if MCP mode, still POST

### Acceptance Criteria

- [x] `plugin/hooks/pre-push.sh` added to match `git push` commands; wired
      into `hooks.json` as a second PreToolUse Bash hook
<!-- canon:realized-in:phase-5-evidence file:plugin/hooks/pre-push.sh file:plugin/hooks/hooks.json -->
- [x] When `commit_on_push: ask`, hook emits a JSON ask response that prompts
      the user to acknowledge committing evidence
<!-- canon:realized-in:phase-5-evidence file:plugin/hooks/pre-push.sh -->
- [x] When `commit_on_push: always`, hook silently stages and commits the
      evidence file before push proceeds
<!-- canon:realized-in:phase-5-evidence file:plugin/hooks/pre-push.sh file:src/canon/cli/evidence.py symbol:_commit_evidence_file -->
- [x] When `commit_on_push: never`, hook is a no-op for file mode
<!-- canon:realized-in:phase-5-evidence file:plugin/hooks/pre-push.sh -->
- [ ] MCP mode: hook calls `canon evidence push --remote` which uses the
      existing MCP server credentials to POST the evidence
<!-- canon:gap: stubbed — `canon evidence push` emits a warning when persist=mcp; full MCP integration deferred to §6 -->
- [x] Tests cover happy path and "no evidence file exists" path
<!-- canon:realized-in:phase-5-evidence file:tests/test_cli/test_evidence.py symbol:TestEvidencePush symbol:TestPrePushHook -->
- [x] Hook completes in <2 seconds (does not block push perceptibly)
<!-- canon:realized-in:phase-5-evidence file:tests/test_cli/test_evidence.py (subprocess timeout 5s, observed completion well under 1s) -->
- [x] `.canon/` is added to `.gitignore` automatically when `commit_on_push`
      is not `always` (closes the deferred AC from §3)
<!-- canon:realized-in:phase-5-evidence file:src/canon/cli/evidence.py symbol:_ensure_gitignore_entry file:tests/test_cli/test_evidence.py symbol:TestGitignoreAutoUpdate -->

## 6. MCP Tool: record_session_evidence

<!-- canon:system:6 status:done -->

Add a new MCP tool that lets any client (Claude Code, Cursor, custom agents)
push session evidence to the Canon backend without going through the file path.

### 6.1 Tool Surface

```
mcp__canon__record_session_evidence(
  branch: str,
  session: SessionRecord  # validated by Pydantic
) -> { recorded: bool, session_id: str }
```

### 6.2 Storage

The Canon backend stores evidence in a new `session_evidence` table keyed by
`(repo_id, branch, session_id)`. The PR analyzer queries this table by
`(repo_id, branch_sha)` at PR-open time.

### Acceptance Criteria

- [x] `mcp__canon__record_session_evidence` tool registered in
      `src/canon/mcp/server.py`
<!-- canon:realized-in:phase-6-evidence file:src/canon/mcp/server.py symbol:record_session_evidence -->
- [x] Tool validates input against `SessionRecord` Pydantic model
<!-- canon:realized-in:phase-6-evidence file:src/canon/mcp/server.py symbol:_record_session_evidence_impl -->
- [x] Tool writes to a new `session_evidence` table (migration added)
<!-- canon:realized-in:phase-6-evidence file:src/canon/db/migrations/versions/0007_session_evidence.py file:src/canon/db/session_evidence_store.py -->
- [x] Table indexed by `(repo, branch)` for fast PR-time lookup
<!-- canon:realized-in:phase-6-evidence file:src/canon/db/migrations/versions/0007_session_evidence.py -->
- [x] Tool respects `ai_exposure` filtering — repo-level "none" rejects evidence
<!-- canon:realized-in:phase-6-evidence file:src/canon/mcp/server.py symbol:_record_session_evidence_impl (ai_exposure block, fail-closed per PR #501 review) -->
- [x] Tool is rate-limited per repo (max 60 records per hour) to prevent abuse
<!-- canon:realized-in:phase-6-evidence file:src/canon/mcp/server.py symbol:_record_session_evidence_impl (rate limit block, fail-closed per PR #501 review) -->
- [x] Tests cover: valid record, invalid record, rate-limit enforcement
<!-- canon:realized-in:phase-6-evidence file:tests/test_cli/test_evidence.py (TestRecordSessionEvidenceMcpTool — registration, invalid, accept-and-insert, rate-limit) -->

## 7. GitHub App Analyzer Hint Input

<!-- canon:system:7 status:done -->

Make the PR analyzer read session evidence and use it as hint input when
building the LLM prompt.

### 7.1 Where Evidence is Loaded

In `src/canon/agent/analyzer.py` (or wherever the PR analyzer composes its
input), before calling `prompts.build_user_message()`:

1. Look for `.canon/session-evidence.json` in the PR branch tree
2. If absent, query the `session_evidence` table by `(repo_id, branch_sha)`
3. If both absent, fall back to cold analysis (current behavior)

### 7.2 How Evidence Shapes the Prompt

The user message gains a new "Dev Session Evidence" section:

```
The developer worked on this branch across N sessions. They explicitly
loaded these spec sections: <list>. They reported the following ACs as
realized via canon-verify: <list>. Treat these as high-confidence hints
when mapping the diff to ACs, but verify against the actual code.
```

The analyzer is instructed to **trust but verify** — evidence is a hint, not
a fact, because the developer might be wrong.

### 7.3 Token Savings

Track per-PR token usage with and without evidence to validate the cost
hypothesis. Add a counter to the analyzer output: `evidence_used: bool`,
`tokens_saved_estimate: int`.

### Acceptance Criteria

- [x] PR analyzer flow checks both file and database paths for session
      evidence at PR-open time (loader lives in the PR webhook handler)
<!-- canon:realized-in:phase-7-evidence file:src/canon/github/handlers/on_pull_request.py:_load_session_evidence -->
- [x] When evidence is found, it is rendered into the user message as a "Dev
      Session Evidence" section
<!-- canon:realized-in:phase-7-evidence file:src/canon/agent/prompts.py:_render_session_evidence file:src/canon/agent/prompts.py:build_user_message -->
- [x] Analyzer telemetry tracks `evidence_used: bool` and `evidence_session_count`
<!-- canon:realized-in:phase-7-evidence file:src/canon/github/handlers/on_pull_request.py (analytics.track pr_analyzed properties) -->
- [x] Cold analysis (no evidence) remains the default fallback — never errors
      on missing evidence
<!-- canon:realized-in:phase-7-evidence file:src/canon/github/handlers/on_pull_request.py:_load_session_evidence (returns [] on any failure) -->
- [x] Test asserts the prompt contains the evidence section when evidence is
      provided
<!-- canon:realized-in:phase-7-evidence file:tests/test_cli/test_evidence.py (TestAnalyzerEvidenceRendering — includes section, omits when empty) -->
- [x] When `ai_exposure: metadata` or `none` applies to a referenced spec,
      evidence content is filtered the same way the spec content is
<!-- canon:realized-in:phase-followup file:src/canon/agent/prompts.py:_render_session_evidence,_spec_exposure_map file:tests/test_cli/test_evidence.py (TestEvidenceAiExposureFiltering) -->
- [ ] Telemetry shows whether token cost dropped on PRs with evidence vs cold
      (acceptance: at least 15% reduction on average across 20 sample PRs)
<!-- canon:gap: this is a measurement, not a unit test; observed in dogfood after the foundation lands -->

## 8. Rollout Plan

<!-- canon:system:8 status:draft -->

### Phase 1: Foundation (Schema + Trail)
1. §2 Evidence schema + Pydantic model
2. §4 canon-verify trail logging (independent of evidence file; ships first)

### Phase 2: Capture (Stop Hook + CLI)
3. §3 Stop hook records evidence locally
4. `canon evidence record` and `canon evidence list-verify-runs` CLI subcommands
5. Ships behind `evidence_pipeline.enabled: false` flag
6. Internal dogfood for 1-2 weeks before widening

### Phase 3: Persistence (Push + MCP)
7. §5 PreToolUse git push prompt
8. §6 `record_session_evidence` MCP tool + `session_evidence` table
9. Both modes ship together so users can choose

### Phase 4: Consumption (PR Analyzer)
10. §7 PR analyzer reads evidence and uses it as hint input
11. Telemetry to validate token cost hypothesis
12. Once validated, flip the default flag to `evidence_pipeline.enabled: true`
    in next major plugin release

## 9. Risks

<!-- canon:system:9 status:draft -->

| Risk | Mitigation |
|---|---|
| Evidence file becomes a merge-conflict source | Default `commit_on_push: ask`, default `.canon/` to .gitignore, only commit when user opts in |
| Multi-session append corrupts file under concurrent writes | Atomic temp-file rename; document that two concurrent Claude sessions on the same branch may race (rare) |
| Developer evidence is wrong (claimed AC not actually realized) | Analyzer instructed to "trust but verify"; evidence is a hint, not a fact |
| PR analyzer regressions when evidence is malformed | Strict schema validation; fall back to cold analysis on any parse error |
| Plugin → GitHub App coupling becomes hard to maintain | Schema versioning (`version: 1`); analyzer rejects unknown versions; plugin and analyzer can deploy independently as long as they agree on the version field |
| Telemetry shows no token savings | Roll back §7; keep §2-§6 as the verification trail feature, which has independent value |
| Users confused about file vs MCP mode | Default to `persist: both`; if either fails the other still works |

## 10. Open Questions

- Should the evidence file include the full diff or just file paths and line
  ranges? Full diff makes the PR analyzer more useful but bloats the file and
  raises the AI exposure question.
- For MCP mode, do we need a per-user auth token or does the existing repo-level
  MCP credential suffice?
- How long does the `session_evidence` table retain records? 90 days?
  Forever? Per-repo retention policy?
- Should the verification trail (`verify-log.jsonl`) be part of evidence or a
  separate concern? Currently §4 frames it as input to evidence; could also
  frame it as a standalone debugging artifact.
- For the "trust but verify" prompt — do we need an A/B test to confirm the
  LLM doesn't just rubber-stamp evidence without checking?
- Should `canon evidence record` be exposed as a slash command
  (`/canon-evidence`) for users who want to manually checkpoint a session?
