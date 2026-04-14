# Canon Actions Fixture Repo

A minimal sample repository used by the Canon Actions test suite.

## Structure

- `CANON.yaml` — points lint/audit/verify at `docs/specs/*.md`.
- `docs/specs/valid-feature.md` — positive fixture, no lint issues, mixed
  realized / in-progress ACs.
- `docs/specs/lint-errors.md` — negative fixture, trips multiple lint rules:
  `frontmatter.title`, `frontmatter.owner`, `frontmatter.team`,
  `frontmatter.created`, `section.numbering`, `comment.unknown`,
  `depends_on.unresolved`.
- `docs/specs/seeded-drift.md` — drift fixture: ACs reference code that
  already exists in `src/sample.py` but sections are marked `todo`. Used
  by `audit` action integration tests.
- `src/sample.py` — realized implementation referenced by `seeded-drift.md`.

## Usage

This fixture is consumed by action integration tests in
`tests/test_actions/`. It is also mirrored to the public `canonhq/canon`
repo by `export-oss.sh` so the post-sync smoke test can run against it.
