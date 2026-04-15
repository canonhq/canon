# Creating Extensions

Build your own Canon extensions to add org-specific workflows, ticket system adapters, or custom automation.

## Scaffold a New Extension

```bash
# Create with a skill and command
canon extension create my-extension --skill --command

# With all options
canon extension create my-extension \
  --skill \
  --command \
  --hook \
  --author "Your Name" \
  --output ./my-extension
```

This generates:

```
my-extension/
├── canon-extension.yml          # Extension manifest
├── README.md                    # Documentation
├── skills/
│   └── my-extension/
│       └── SKILL.md             # Skill template
└── commands/
    └── my-extension.md          # Command template
```

## The Manifest

Every extension needs a `canon-extension.yml` at its root. Here's a complete example:

```yaml
schema_version: "1"

extension:
  id: "sprint-plan"
  name: "Sprint Planning"
  version: "1.0.0"
  description: "AI-assisted sprint planning from spec coverage data"
  author: "Your Team"
  repository: "https://github.com/your-org/canon-ext-sprint-plan"
  license: "MIT"

requires:
  canon_version: ">=1.50.0"

provides:
  skills:
    - name: "sprint-plan"
      file: "skills/sprint-plan/SKILL.md"
      description: "Plan sprints based on spec coverage gaps"

  commands:
    - name: "canon-sprint"
      file: "commands/canon-sprint.md"
      description: "Generate sprint plan from current coverage"

tags:
  - "planning"
  - "agile"
  - "workflow"
```

See the [Extension Manifest Reference](/reference/extensions) for the full schema.

## Writing Skills

Skills are the most common extension component. A skill is a `SKILL.md` file with YAML frontmatter and markdown instructions:

```markdown
---
name: sprint-plan
description: "Plan sprints based on spec coverage gaps and team velocity"
---

# Sprint Planning

You are helping the user plan their next sprint based on Canon spec coverage.

## Steps

1. Run `canon status` to get current coverage
2. Identify sections with status `todo` or `in_progress`
3. Estimate effort based on acceptance criteria count
4. Propose a sprint plan respecting the configured velocity

## Configuration

Read sprint config from CANON.yaml:

\`\`\`yaml
extensions:
  sprint-plan:
    sprint_length_days: 14
    velocity_points: 40
\`\`\`
```

Skills are placed at `.canon/skills/{name}/SKILL.md` on install and become available in Claude Code (and other supported IDEs).

### Skill Best Practices

- **Be specific about when the skill applies** — the `description` field controls when the IDE suggests it
- **Reference Canon MCP tools** — skills can call `search`, `get_spec`, `get_coverage` etc.
- **Include example output** — show what the skill should produce
- **Keep instructions actionable** — tell the agent what to do, not what it could do

## Writing Commands

Commands provide slash-command shortcuts. They're simpler than skills — just a markdown file with frontmatter:

```markdown
---
description: "Generate sprint plan from current coverage"
---

# Sprint Plan

Generate a sprint plan based on Canon spec coverage.

## Arguments

$ARGUMENTS

## Instructions

1. Use the canon MCP `get_coverage` tool to fetch current spec coverage
2. List all `todo` sections sorted by priority
3. Output a markdown table with: Section, Spec, ACs, Estimate
```

Commands are placed at `.claude/commands/{name}.md` and appear in Claude Code's `/` autocomplete.

## Development Workflow

### 1. Scaffold

```bash
canon extension create sprint-plan --skill --command
```

### 2. Develop with Dev Mode

```bash
# Install as symlink — edits propagate instantly
canon extension add --dev ./sprint-plan
```

Now edit `sprint-plan/skills/sprint-plan/SKILL.md` and the changes are immediately visible in your IDE — no reinstall needed.

### 3. Validate

```bash
canon extension validate ./sprint-plan
```

Checks manifest schema, file references, and version compatibility.

### 4. Test

Open your IDE in a Canon-enabled repo and try invoking your skill or command. Iterate on the instructions until the agent behaves as expected.

### 5. Share

Push your extension to a Git repo. Others can install it with:

```bash
git clone https://github.com/your-org/canon-ext-sprint-plan
canon extension add ./canon-ext-sprint-plan
```

## Ticket Adapters (Phase 2)

::: info Coming Soon
Python-based ticket adapters will be supported in Phase 2. Adapters implement the `TicketAdapter` protocol and register via Python entry points.
:::

```python
# Example: adapters/azure_devops.py (Phase 2)
from canon.sync.adapters.base import AdapterCapabilities, TicketAdapter

class AzureDevOpsAdapter:
    @property
    def system_name(self) -> str:
        return "azure-devops"

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_custom_fields=True,
            supports_hierarchy=True,
            supports_subtasks=True,
        )

    async def create_ticket(self, input):
        # Azure DevOps API call
        ...
```

The manifest will declare the adapter:

```yaml
provides:
  adapters:
    - id: "azure-devops"
      entry_point: "canon_ext_azure_devops:AzureDevOpsAdapter"
      capabilities:
        supports_custom_fields: true
        supports_hierarchy: true
```

## Extension ID Rules

- Lowercase letters, digits, and hyphens only
- 3-50 characters
- Must start with a letter, end with a letter or digit
- Reserved IDs: `canon`, `core`, `builtin`

Good: `sprint-plan`, `azure-devops`, `jira-hygiene`
Bad: `MyExtension`, `x`, `canon-core`, `sprint_plan`

## Directory Structure Reference

```
my-extension/
├── canon-extension.yml    # Required: manifest
├── README.md              # Recommended: documentation
├── LICENSE                 # Recommended: license file
├── skills/                # Optional: SKILL.md files
│   └── {skill-name}/
│       └── SKILL.md
├── commands/              # Optional: command markdown files
│   └── {command-name}.md
├── hooks/                 # Optional: lifecycle hook scripts
├── agents/                # Optional: AGENT.md files
│   └── {agent-name}/
│       └── AGENT.md
└── config/                # Optional: config templates
    └── my-ext.template.yml
```
