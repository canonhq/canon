# Canon Sprint Planning Extension

AI-assisted sprint planning from spec coverage data. Identifies todo sections, estimates effort by acceptance criteria count, and proposes a sprint plan respecting team velocity.

## Installation

```bash
canon extension add /path/to/extensions/canon-sprint-plan

# Or dev mode
canon extension add --dev /path/to/extensions/canon-sprint-plan
```

## Usage

In Claude Code:

```
/canon-sprint
/canon-sprint focus on payment specs, 30 points this sprint
```

Or invoke the skill directly by asking about sprint planning.

## Configuration

Add to your `CANON.yaml`:

```yaml
extensions:
  sprint-plan:
    sprint_length_days: 14    # Sprint duration (default: 14)
    velocity_points: 40       # Team velocity in story points (default: 40)
```

## How It Works

1. Fetches spec coverage data via Canon MCP tools
2. Identifies all `todo` and `in_progress` sections
3. Estimates effort using acceptance criteria count as a proxy
4. Prioritizes by: in-progress items first, then coverage impact, then dependencies
5. Proposes a sprint plan that fits within velocity budget
