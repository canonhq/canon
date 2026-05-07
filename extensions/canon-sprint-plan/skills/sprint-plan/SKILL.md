---
name: sprint-plan
description: "Plan sprints based on spec coverage gaps and team velocity. Use when the user asks to plan a sprint, identify what to work on next, or prioritize spec sections."
---

# Sprint Planning

You are helping the user plan their next sprint using Canon spec coverage data. Your goal is to identify the highest-value work items, estimate effort, and propose a plan that fits the team's velocity.

## Configuration

Read sprint config from CANON.yaml if available:

```yaml
extensions:
  sprint-plan:
    sprint_length_days: 14    # Default: 14
    velocity_points: 40       # Default: 40 story points per sprint
```

If no config exists, use the defaults above.

## Steps

### 1. Gather Coverage Data

Use the Canon MCP tools to understand current state:

```
1. Call `list_specs` to get all specs
2. Call `get_coverage` to get overall coverage metrics
3. For specs with low coverage, call `get_spec` to load sections and ACs
```

### 2. Identify Candidate Work Items

From the spec data, collect all sections with status `todo` or `in_progress`. For each:

- **Section title** — what the work is
- **Spec name** — which spec it belongs to
- **AC count** — number of unchecked acceptance criteria (proxy for effort)
- **Depth** — section depth (depth 2 = epic-level, depth 3 = story-level, depth 4 = task-level)
- **Dependencies** — check if the section references other sections or has blockers noted in the content

### 3. Estimate Effort

Use this heuristic for story points based on AC count:

| Unchecked ACs | Estimated Points | T-shirt Size |
|---------------|-----------------|--------------|
| 1-2           | 1-2             | XS/S         |
| 3-5           | 3-5             | M            |
| 6-8           | 8               | L            |
| 9+            | 13              | XL           |

Adjust estimates up for sections that:
- Touch infrastructure or deployment
- Require cross-team coordination
- Have ambiguous or complex ACs
- Are blocked by external dependencies

### 4. Prioritize

Rank work items by:

1. **Blocked items first** — sections marked `in_progress` that are almost done (few ACs left)
2. **High-coverage-impact** — sections in specs with the lowest coverage (biggest bang for the buck)
3. **Dependencies** — items that unblock other items
4. **Depth** — prefer depth-3 (story-level) items over depth-2 (epic-level) for sprint-sized work

### 5. Propose Sprint Plan

Present the plan as a markdown table:

```markdown
## Sprint Plan — [Sprint Name]

**Duration:** 14 days | **Velocity:** 40 points | **Capacity used:** 38/40

| # | Section | Spec | ACs | Points | Status | Notes |
|---|---------|------|-----|--------|--------|-------|
| 1 | 3.2 Retry Handling | payment-processing | 4 | 5 | in_progress | 2/4 ACs done |
| 2 | 2.1 Branch Parsing | git-lifecycle-sync | 3 | 3 | todo | Unblocks 2.2-2.4 |
| 3 | 5. Metrics Export | enterprise-adoption | 6 | 8 | todo | |
| ...

**Stretch goals** (if velocity allows):
| Section | Spec | Points |
|---------|------|--------|

**Deferred** (won't fit this sprint):
| Section | Spec | Points | Why |
|---------|------|--------|-----|
```

### 6. Discuss with User

After presenting the plan:
- Ask if the priorities match their intuition
- Ask if any items should be swapped in or out
- Ask about team availability (PTO, on-call, etc.)
- Adjust the plan based on feedback

## Output Format

Always output:
1. A summary line: "Sprint plan: X points across Y items from Z specs"
2. The prioritized table
3. Stretch goals
4. Deferred items with reasons
5. Risk callouts (blocked items, ambiguous ACs, cross-team dependencies)
