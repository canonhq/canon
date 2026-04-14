# New Spec Action

Scaffold a new spec from a template and open a PR with it. Designed
for `workflow_dispatch` — pass a title (and optional owner, team,
type) and a fresh spec lands as a PR ready for review. Lowers the
barrier for non-technical authors to start a spec without learning
the canon CLI.

```
uses: canonhq/canon/actions/new-spec@v1
```

## Inputs

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `title` | **yes** | — | Spec title (e.g. `Auth Hardening`) |
| `type` | no | `spec` | One of `spec`, `proposal`, `design`, `adr` |
| `owner` | no | `""` | Owner GitHub handle or name |
| `team` | no | `""` | Owning team |
| `output-path` | no | (auto from CANON.yaml) | Explicit output path |
| `branch-name` | no | `canon/new-spec/<slug>` | Branch name for the PR |
| `open-pr` | no | `true` | Open a PR vs commit directly |
| `python-version` | no | `3.12` | |
| `canon-version` | no | `>=1.0.0,<2.0.0` | |

## Outputs

| Name | Description |
|------|-------------|
| `spec-path` | Repo-relative path of the newly created spec file |
| `pr-url` | URL of the opened PR (when `open-pr: true`) |

## Example

```yaml
name: Canon New Spec
on:
  workflow_dispatch:
    inputs:
      title:
        description: "Spec title"
        required: true
      type:
        description: "Document type"
        required: false
        default: "spec"
        type: choice
        options: [spec, proposal, design, adr]
      owner:
        description: "Owner GitHub handle"
        required: false
      team:
        description: "Owning team"
        required: false

jobs:
  scaffold:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: canonhq/canon/actions/new-spec@v1
        with:
          title: ${{ inputs.title }}
          type: ${{ inputs.type }}
          owner: ${{ inputs.owner }}
          team: ${{ inputs.team }}
```

## What it does

1. Installs the Canon CLI
2. Runs `canon new --title ... --type ... --owner ... --team ...` which:
   - Loads the matching template from `canon.parser.templates`
   - Substitutes the title, owner, team, and today's date into the
     frontmatter
   - Slugifies the title to derive the filename
   - Writes the file under the first `doc_paths` directory from
     `CANON.yaml` (or the explicit `output-path`)
3. Commits the new file to a branch named `canon/new-spec/<slug>`
   (or the explicit `branch-name`)
4. Opens a PR with a body that links to the docs and lists the next
   steps for the author
5. (Or, with `open-pr: false`, commits directly to the default branch)

## Underlying CLI

You can scaffold specs locally with the same command:

```bash
canon new --title "Auth Hardening" --owner alice --team platform
# → docs/specs/auth-hardening.md
```

## Permissions

| Mode | Required permissions |
|------|---------------------|
| `open-pr: true` | `contents: write`, `pull-requests: write` |
| `open-pr: false` | `contents: write` |

## Pitfalls

- **`title` is mandatory and shapes the filename**. Pick the title
  carefully — renaming after the spec lands means renaming the file
  too, which invalidates any cross-references.
- **Slug collisions**. If a spec with the same slug already exists,
  `canon new` exits non-zero. Either pick a different title or pass
  `--force` (not exposed via the action by design — use the CLI
  directly if you really mean to overwrite).
- **The PR is empty content**. The new spec has placeholder sections;
  authors fill them in by editing the file in the PR. The
  `spec-lint` and `verify` actions in `pr-checks.yml` will catch
  obvious gaps before merge.
