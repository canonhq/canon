# CI Integration

Add Canon validation to your CI/CD pipeline to catch spec drift before it reaches production.

## GitHub Actions

### Spec Lint

Validate spec format and frontmatter in pull requests:

```yaml
name: Spec Lint

on:
  pull_request:
    paths:
      - "docs/specs/**"
      - "CANON.yaml"

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"

      - run: uv run canon lint docs/specs/
```

### Coverage Gate

Block merges when spec coverage drops below a threshold:

```yaml
name: Spec Coverage

on:
  pull_request:
    branches: [main]

jobs:
  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"

      - name: Check spec coverage
        run: uv run canon coverage --min 60
```

### Config Validation

Validate `CANON.yaml` syntax:

```yaml
name: Config Check

on:
  pull_request:
    paths:
      - "CANON.yaml"

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"

      - run: uv run canon validate-config
```

## What Gets Validated

### Spec Lint

The `canon lint` command checks:

- Valid YAML frontmatter (required fields: `title`, `status`)
- Valid status values (`draft`, `todo`, `in_progress`, `done`, `blocked`, `deprecated`)
- Section numbering consistency
- Acceptance criteria format (checkbox syntax)
- Status comment syntax (`<!-- canon:system:... -->`)

### Config Validation

The `canon validate-config` command checks:

- Valid YAML syntax
- Known configuration keys (warns on unknown keys)
- Valid `doc_paths` glob patterns
- Valid ticket system names and project keys

## Combining with Existing CI

Add spec checks alongside your existing test and lint jobs:

```yaml
name: CI

on:
  pull_request:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4

      - run: uv sync --extra dev
      - run: uv run ruff check
      - run: uv run pytest
      - run: uv run canon lint docs/specs/
```
