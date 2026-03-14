# Claude Code Skills

The Canon plugin for Claude Code provides slash commands for spec-driven development.

## Installation

```bash
claude plugin add canonhq/canon
```

## Commands

### `/sw:context` — Load Spec Context

Load spec context for your current task. Automatically identifies relevant specs from git changes or a user-provided topic.

**Usage:**
```
/sw:context
/sw:context auth migration
```

**What it does:**
- Scans git diff to find changed files
- Matches changes against spec sections
- Loads relevant specs, ACs, and ticket links into context

### `/sw:task` — Work on a Task

Pick up a spec-driven task, work through its acceptance criteria, and mark it done.

**Usage:**
```
/sw:task
```

**What it does:**
- Lists available tasks from spec acceptance criteria
- Guides you through implementation of each AC
- Marks ACs as realized with code evidence
- Updates spec status when all ACs are done

### `/sw:verify` — Verify Implementation

Verify code against spec acceptance criteria. Use after implementing a feature or during code review.

**Usage:**
```
/sw:verify
/sw:verify docs/specs/auth-hardening.md
```

**What it does:**
- Evaluates each AC as realized, partial, or conflicting
- Reports evidence (file, line numbers) for each evaluation
- Suggests spec or code updates for conflicts

### `/sw:new` — Create a Spec

Create a new spec document from a template.

**Usage:**
```
/sw:new
/sw:new "User Notifications"
```

**What it does:**
- Walks through structured creation with prompts for title, team, tags
- Creates spec file from template
- Optionally commits to git

### `/sw:review` — Review Against Docs

Review code changes against all documentation — specs, ADRs, READMEs, architecture docs.

**Usage:**
```
/sw:review
```

**What it does:**
- Scans all indexed docs for conflicts with current changes
- Flags stale documentation
- Suggests doc updates

### `/sw:status` — Coverage Dashboard

Show spec coverage dashboard.

**Usage:**
```
/sw:status
```

**What it does:**
- Displays per-spec and per-section coverage metrics
- Shows realized vs. total acceptance criteria
- Highlights stale or blocked sections

### `/sw:plan` — Spec-Driven Planning

Start a spec-driven planning workflow from exploration through spec creation to implementation tasks.

**Usage:**
```
/sw:plan
```

**What it does:**
- Explores codebase to understand current state
- Proposes spec structure
- Creates spec with sections and ACs
- Generates implementation tasks

### `/sw:update` — Update Spec Statuses

Update spec statuses based on code implementation evidence.

**Usage:**
```
/sw:update
/sw:update docs/specs/auth-hardening.md
```

**What it does:**
- Scans codebase for implementation evidence
- Proposes status transitions for spec sections
- Applies updates with realization evidence

### `/sw:audit` — Full Spec Audit

Full audit workflow: scan all specs against the codebase, update statuses, sync to ticket system, and commit. Combines `/sw:update` + `canon sync` into a single command.

**Usage:**
```
/sw:audit
```

**What it does:**
- Discovers all specs and audits each against the codebase in parallel
- Updates section statuses based on implementation evidence
- Runs `canon sync` to create/update GitHub Issues for actionable sections
- Commits and pushes the changes
