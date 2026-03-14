# Delta Tracking

Rather than rewriting specs when things change, Canon tracks changes through status transitions and hidden HTML comments embedded in the spec markdown.

## How It Works

Each spec section has a hidden status comment that the agent manages:

```markdown
## 3. Idempotency Layer
<!-- canon:system:idempotency status:done -->
<!-- canon:ticket:jira:PAY-142 -->

All payment endpoints must support idempotency keys...

### 3.1 Key Generation
<!-- canon:system:key-gen status:done -->
<!-- canon:ticket:jira:PAY-143 -->
<!-- canon:realized-in:PR#412 src/payments/keys.ts -->

- [x] Generate UUID v4 idempotency keys on client
- [x] Store keys in Redis with 24h TTL
```

## Comment Types

Canon uses three types of hidden HTML comments:

### Status Comments

```markdown
<!-- canon:system:<section-id> status:<status> -->
```

Tracks the current status of a section. Valid statuses:

| Status | Meaning |
|--------|---------|
| `draft` | Initial state — requirements not yet finalized |
| `todo` | Ready for implementation |
| `in_progress` | Work has started |
| `done` | All acceptance criteria verified against code |
| `blocked` | Waiting on a dependency (optionally: `blocked:TICKET-ID`) |
| `deprecated` | No longer relevant |

### Ticket Links

```markdown
<!-- canon:ticket:<system>:<ticket-id> -->
```

Links a spec section to a ticket in an external system:

```markdown
<!-- canon:ticket:jira:PAY-142 -->
<!-- canon:ticket:linear:ID-301 -->
<!-- canon:ticket:github:42 -->
```

### Realization Evidence

```markdown
<!-- canon:realized-in:PR#<number> <file>:<lines> -->
```

The critical addition — the agent writes this when it verifies that code actually implements the spec section, not just when a ticket is closed:

```markdown
<!-- canon:realized-in:PR#412 src/payments/keys.ts:42-60 -->
```

## Status Transitions

Statuses typically flow in one direction:

```
draft → todo → in_progress → done
                    ↓
                 blocked → in_progress → done
```

The agent auto-transitions statuses based on code evidence:

- `todo` → `in_progress`: When a PR references this section
- `in_progress` → `done`: When all acceptance criteria are realized
- Any → `blocked`: When a dependency is unresolved

PMs can manually set any status. The `deprecated` status is terminal — the agent stops tracking the section.

## Why Hidden Comments?

Hidden HTML comments are invisible when rendering the markdown in GitHub, editors, or documentation sites. This means:

1. **Clean reading experience** — No metadata clutter in the spec
2. **Git-friendly** — Comments are just text, so they diff and merge normally
3. **Tool-agnostic** — Any markdown renderer handles them correctly
4. **Human-editable** — Engineers can manually fix comments if needed

The agent manages these comments automatically. Engineers rarely need to touch them directly.

## Related

- **Reference**: [Spec Format](/reference/spec-format) — formal syntax for all comment types, frontmatter, and ACs
- **Guide**: [Writing Specs](/guides/writing-specs) — how to write specs with proper status lifecycle
- **Concept**: [Living Specs](/concepts/living-specs) — the feedback loop that drives status transitions
- **Concept**: [Spec Coverage](/concepts/coverage) — how realization evidence feeds into coverage metrics
- **Reference**: [CLI](/reference/cli) — `canon start` and `canon done` for manual transitions
- **Reference**: [MCP Tools](/reference/mcp) — `update_section_status` and `add_realization` for agent use
