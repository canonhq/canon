# Spec Coverage

Spec coverage measures what percentage of spec acceptance criteria are verified against actual code. Unlike test coverage (which measures code execution), spec coverage measures **intent realization** — is the software doing what the spec says it should?

## Coverage Model

Coverage is calculated at three levels:

### Acceptance Criteria Level

Each acceptance criterion is evaluated as:

| Status | Meaning |
|--------|---------|
| **Realized** | Code fully implements this AC — evidence links to file and line |
| **Partially realized** | Partial implementation — explanation of what's missing |
| **Conflicting** | Code contradicts this AC — explanation of how |
| **Not addressed** | No code touches this area yet |

### Section Level

A section's coverage is the ratio of realized ACs to total ACs:

```
Section coverage = realized ACs / total ACs
```

Section status auto-transitions based on coverage:
- **0%** → stays at current status
- **1-99%** → `in_progress`
- **100%** → `done`

### Spec Level

A spec's coverage aggregates all its sections:

```
Spec coverage = realized ACs across all sections / total ACs
```

## Evidence Trail

Every realization includes evidence — the PR, file, and line numbers where the implementation lives:

```markdown
<!-- canon:realized-in:PR#412 src/payments/keys.ts:42-60 -->
```

This creates an audit trail connecting specs to code. If the code changes in a later PR, the agent can re-evaluate whether the realization still holds.

## Coverage Dashboard

The `/canon-status` command (or the web dashboard) shows coverage at a glance:

```
Spec Coverage — payments-overhaul.md

  §1 Background                    ████████████ 100%  done
  §2 Stripe Migration              ██████░░░░░░  50%  in_progress
    §2.1 API Integration           ████░░░░░░░░  25%  in_progress
    §2.2 Webhook Handler           ████████████ 100%  done
  §3 Idempotency Layer             ░░░░░░░░░░░░   0%  blocked
  §4 Multi-Currency Support        ░░░░░░░░░░░░   0%  todo
  §5 Monitoring & Alerts           ———————————— n/a   deprecated

Overall: 8/18 ACs realized (44%)
```

## Staleness Detection

Coverage isn't static. When code changes but specs don't, sections become stale:

- A PR modifies `src/payments/retry.ts` which was evidence for §3.2
- The agent re-evaluates: does the code still satisfy the acceptance criteria?
- If not, the section is flagged as stale and the coverage drops

Configure staleness detection in [CANON.yaml](/getting-started/configuration):

```yaml
agents:
  stale_detection: "30d"  # flag sections not updated within 30 days
```

## Org-Wide Coverage

At the org level (Tier 3), coverage aggregates across all repos:

- **Per-team coverage** — Which team has the best spec-to-code alignment?
- **Trend lines** — Is coverage improving or degrading over time?
- **Health score** — Composite metric weighing coverage, staleness, and completeness

## Related

- **Concept**: [Living Specs](/concepts/living-specs) — the feedback loop that produces realization evidence
- **Concept**: [Delta Tracking](/concepts/delta-tracking) — how realization comments are stored in spec markdown
- **Guide**: [Writing Specs](/guides/writing-specs) — how to write testable acceptance criteria
- **Reference**: [CLI](/reference/cli) — `canon status` for the coverage dashboard, `canon verify` for AC verification
- **Reference**: [MCP Tools](/reference/mcp) — `get_coverage` for programmatic coverage queries
- **Reference**: [Claude Code Skills](/reference/skills) — `/canon-status` for interactive coverage views
