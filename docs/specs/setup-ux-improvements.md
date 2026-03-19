---
title: "Setup UX Improvements"
status: draft
owner: ng
team: canon
ticket_project: canonhq/canon
created: 2026-03-04
updated: 2026-03-04
tags: [cli, plugin, onboarding, dx]
---

# Setup UX Improvements

Improve the CLI setup flow and Claude Code plugin onboarding experience so that
new users go from zero to a fully working Canon integration in one pass,
with clear diagnostics when something is misconfigured.

## 1. Background

Canon has two installation paths — the CLI (`canon setup`) and the
Claude Code plugin marketplace — but neither produces a fully validated
configuration on its own. Users can complete setup without logging in, end up
with a broken MCP server they don't know how to debug, and have no way to
update skills without manually deleting them. The "Next steps" hint in setup
has an unreachable code bug. Documentation references `canon init` but the
command is actually `canon setup`.

These friction points compound: a new user's first experience is often
confusion about what worked and what didn't, with no single command to diagnose
the state of their installation.

## 2. Fix `canon setup` Flow

<!-- specwright:system:2 status:todo -->

Improve the interactive setup command to produce a fully working configuration
and give users clear next steps.

### 2.1 Fix Unreachable "Next Steps" Hint

<!-- specwright:system:2.1 status:todo -->

The setup flow writes `docs/specs/_template.md` before checking
`template_path.exists()`, so the "Next steps" block never prints on a clean
install.

#### Acceptance Criteria

- [ ] Capture `template_existed = template_path.exists()` before writing the template file
- [ ] "Next steps" block prints on a fresh repo with no prior config or template
- [ ] "Next steps" block does not print when reconfiguring an existing setup
- [ ] Test covers fresh-install and reconfigure paths

### 2.2 Add Login Awareness to Setup

<!-- specwright:system:2.2 status:todo -->

After writing config files, check for existing credentials and prompt or hint
about `canon login` when credentials are missing.

#### Acceptance Criteria

- [ ] After config write, check `~/.config/canon/credentials.json` existence
- [ ] If no credentials: print hint with `canon login` command and explain what it unlocks (ticket sync, org metrics, MCP write-back)
- [ ] If credentials exist: print "Authenticated as <org>" confirmation
- [ ] Non-interactive mode skips the hint (no blocking prompt)

### 2.3 Add `--force` Flag for Skill Reinstall

<!-- specwright:system:2.3 status:todo -->

Allow users to update skills without manually deleting them.

#### Acceptance Criteria

- [ ] `canon setup --force` overwrites existing skill files in `.claude/skills/`
- [ ] Without `--force`, existing skills are still skipped (preserving current behavior)
- [ ] When overwriting, back up the old file to `SKILL.md.bak` before writing
- [ ] Print count of skills updated vs. skipped vs. newly installed
- [ ] `--force` works with both interactive and non-interactive modes

### 2.4 Post-Setup MCP Server Validation

<!-- specwright:system:2.4 status:todo -->

After writing `.mcp.json`, verify that the MCP server can actually start.

#### Acceptance Criteria

- [ ] After writing `.mcp.json`, attempt to resolve the `uvx` command (check package availability)
- [ ] If `uvx` resolution fails: print warning with install instructions, still complete setup
- [ ] If resolution succeeds: attempt a quick MCP server startup and report capability tier (full / local-only / unavailable)
- [ ] Validation is skipped in non-interactive mode with `--skip-validation` flag
- [ ] Total validation adds no more than 5 seconds to setup

## 3. Add `canon doctor` Command

<!-- specwright:system:3 status:todo -->

A single diagnostic command that checks the health of a Canon installation
and reports actionable fixes.

### 3.1 Configuration Checks

<!-- specwright:system:3.1 status:todo -->

#### Acceptance Criteria

- [ ] Check `CANON.yaml` exists and parses without errors
- [ ] Check `.mcp.json` exists and contains a `canon` server entry
- [ ] Check `.claude/skills/` directory exists with at least one `sw-*` skill
- [ ] Report skill versions vs. bundled versions (detect stale skills)
- [ ] Check `docs/specs/` contains at least one `.md` file (not just the template)

### 3.2 Authentication Checks

<!-- specwright:system:3.2 status:todo -->

#### Acceptance Criteria

- [ ] Check `~/.config/canon/credentials.json` exists
- [ ] If OAuth: verify token is not expired, report org and email
- [ ] If API key: attempt `GET /app/api/me` to verify key is valid
- [ ] Check `gh auth status` for GitHub CLI authentication
- [ ] Report each check as PASS / WARN / FAIL with one-line fix suggestion

### 3.3 MCP Server Health

<!-- specwright:system:3.3 status:todo -->

#### Acceptance Criteria

- [ ] Start the MCP server in a subprocess and send a `tools/list` request
- [ ] Report which tools are available (indicates which backends initialized)
- [ ] Classify capability tier: full (search + GitHub + DB), standard (GitHub only), local (file parsing only)
- [ ] If server fails to start: report the error and suggest fixes
- [ ] Timeout after 10 seconds if server doesn't respond

### 3.4 Output Format

<!-- specwright:system:3.4 status:todo -->

#### Acceptance Criteria

- [ ] Default output is a human-readable status table with colored PASS/WARN/FAIL indicators
- [ ] `--json` flag outputs machine-readable JSON for CI integration
- [ ] Exit code 0 if all checks pass, 1 if any FAIL, 2 if only WARNings
- [ ] Summary line at the end: "X passed, Y warnings, Z failures"

## 4. Unify Documentation and Naming

<!-- specwright:system:4 status:todo -->

Fix naming inconsistencies and clarify the two installation paths.

### 4.1 Fix Command Name Drift

<!-- canon:system:4.1 status:in_progress -->

#### Acceptance Criteria

- [ ] Replace all references to `canon init` with `canon setup` across docs/specs/*.md
- [ ] Replace all references to `canon init` in plugin/README.md and plugin skills
- [ ] Add `init` as a CLI alias for `setup` (so both work, setup is canonical)

### 4.2 Clarify Installation Paths in Plugin README

<!-- canon:system:4.2 status:in_progress -->

#### Acceptance Criteria

- [ ] README has a clear decision tree: "Use CLI setup if you want repo-level config. Use marketplace install for Claude Code plugin only."
- [ ] Both paths list what they produce (which files, which capabilities)
- [ ] Note that `canon setup` installs skills AND writes `.mcp.json`, so marketplace install is not needed after CLI setup

### 4.3 Add Environment Variable Reference

<!-- canon:system:4.3 status:in_progress -->

#### Acceptance Criteria

- [ ] Create `.env.example` in project root with all MCP server environment variables, grouped and commented
- [ ] Include: DATABASE_URL, GOOGLE_CLOUD_PROJECT, GCP_SERVICE_ACCOUNT_KEY, GH_APP_ID, GH_PRIVATE_KEY, GH_INSTALLATION_ID, SPECWRIGHT_URL, MCP_API_KEY
- [ ] Each variable has a one-line comment explaining what it enables

## 5. Technical Design

<!-- specwright:system:5 status:draft -->

### 5.1 Setup Flow Changes

Changes to `src/specwright/setup.py` and `src/specwright/cli/setup_cmd.py`:

- Extract template existence check before `create_template()` call
- Add `check_credentials()` helper that reads credential file and returns status
- Add `validate_mcp_server()` helper that shells out to test `uvx` resolution
- `install_skills()` gains a `force: bool` parameter; when true, writes `.bak` and overwrites
- `setup_cmd.py` gains `--force` and `--skip-validation` argparse flags

### 5.2 Doctor Command

New file: `src/specwright/cli/doctor_cmd.py`

Structured as a list of `Check` dataclass instances, each with:
- `name: str` — display label
- `category: str` — grouping (config, auth, mcp)
- `run: Callable` — returns `CheckResult(status, message, fix_hint)`

The command iterates checks, prints results, and returns appropriate exit code.
`--json` serializes `CheckResult` list.

### 5.3 CLI Alias

Add `init` as an alias in `src/specwright/cli/__init__.py` subparser registration,
pointing to the same handler as `setup`.

## 6. Rollout Plan

<!-- specwright:system:6 status:draft -->

### Phase 1: Bug fixes and quick wins
1. Fix "Next steps" bug (2.1)
2. Fix `init` → `setup` naming (4.1)
3. Add `init` alias (4.1)
4. Add `--force` skill reinstall (2.3)

### Phase 2: Setup flow improvements
5. Login awareness hint (2.2)
6. Post-setup MCP validation (2.4)
7. `.env.example` (4.3)
8. README decision tree (4.2)

### Phase 3: Doctor command
9. Implement `canon doctor` with all checks (3.1–3.4)
10. Wire into setup flow as optional post-setup step

## 7. Open Questions

- Should `canon doctor` be runnable without `CANON.yaml` (to help users who haven't run setup yet)?
- Should the `--force` backup use `.bak` or a timestamped suffix?
- Should `doctor` check for Claude Code version compatibility?
