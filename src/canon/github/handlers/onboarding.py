"""First-run onboarding for newly installed repositories.

When a team installs the Canon GitHub App, each repo is scanned:
  - If specs exist → post a summary issue with a spec table.
  - If no specs → open a setup PR with starter template files.

Idempotent: uses marker comments to avoid duplicate issues/PRs.
"""

from __future__ import annotations

import logging
from asyncio import sleep as async_sleep

import httpx

from ...config.parse import DEFAULT_CONFIG, parse_canon_yaml
from ...setup import list_setup_files
from ..client import FileChange, GitHubClient
from ..spec_utils import load_repo_specs

logger = logging.getLogger(__name__)

ONBOARD_MARKER = "<!-- canon:onboarding -->"
ONBOARD_BRANCH_PREFIX = "canon/onboard-"
ONBOARD_LABEL = "canon-onboarding"


async def onboard_repos(client: GitHubClient, repos: list[dict]) -> None:
    """Run onboarding for a list of repository dicts.

    Processes repos sequentially with a short delay between each to stay
    comfortably within GitHub's rate limits.
    """
    for i, repo_data in enumerate(repos):
        full_name = repo_data.get("full_name", "")
        if "/" not in full_name:
            logger.warning("Skipping repo with invalid full_name: %r", full_name)
            continue

        owner, repo = full_name.split("/", 1)
        await onboard_repo(client, owner, repo)

        if i < len(repos) - 1:
            # Polite spacing; does not handle 429s.
            # TODO: add retry-after backoff if rate limits become an issue.
            await async_sleep(0.5)


async def onboard_repo(client: GitHubClient, owner: str, repo: str) -> None:
    """Onboard a single repository (safe wrapper)."""
    try:
        await _onboard_repo_inner(client, owner, repo)
    except Exception:
        logger.warning("Onboarding failed for %s/%s", owner, repo, exc_info=True)


async def _onboard_repo_inner(client: GitHubClient, owner: str, repo: str) -> None:
    """Core onboarding logic for a single repo."""
    # Check for existing onboarding issue — skip if found
    existing_issue = await _find_onboard_issue(client, owner, repo)
    if existing_issue is not None:
        logger.info("Onboarding issue already exists for %s/%s (#%d)", owner, repo, existing_issue)
        return

    # Check for existing onboarding PR — skip if found
    branch = f"{ONBOARD_BRANCH_PREFIX}{owner}-{repo}"
    existing_pr = await client.find_open_doc_pr(owner, repo, branch)
    if existing_pr is not None:
        logger.info("Onboarding PR already exists for %s/%s", owner, repo)
        return

    # Try to load CANON.yaml (or legacy SPECWRIGHT.yaml) and collect diagnostics
    config_diagnostics: list[str] = []
    has_config = False
    config = DEFAULT_CONFIG
    try:
        try:
            raw_config, _sha = await client.get_file_content(owner, repo, "CANON.yaml")
        except Exception:
            raw_config, _sha = await client.get_file_content(owner, repo, "SPECWRIGHT.yaml")
        has_config = True
        result = parse_canon_yaml(raw_config)
        if result.config:
            config = result.config
        for d in result.diagnostics:
            config_diagnostics.append(f"- **{d.severity}**: {d.message}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            logger.warning(
                "Unexpected error loading CANON.yaml for %s/%s", owner, repo, exc_info=True
            )
    except Exception:
        logger.warning("Could not load CANON.yaml for %s/%s", owner, repo, exc_info=True)

    # Load existing specs
    specs = await load_repo_specs(client, owner, repo, patterns=config.specs.doc_paths)

    if specs:
        await _post_summary_issue(client, owner, repo, specs, config_diagnostics)
    else:
        await _open_setup_pr(client, owner, repo, branch, has_config)


async def _find_onboard_issue(client: GitHubClient, owner: str, repo: str) -> int | None:
    """Search for an existing onboarding issue by label + marker.

    Filters by the dedicated ``canon-onboarding`` label so the query
    stays within a single page even on repos with thousands of issues.
    Uses state="all" so closed issues are found too (prevents duplicates
    when a user closes the welcome issue).

    Raises on API failure so the caller aborts rather than creating a
    duplicate issue.
    """
    issues = await client.list_issues(owner, repo, labels=ONBOARD_LABEL, state="all")
    for issue in issues:
        body = issue.get("body") or ""
        if ONBOARD_MARKER in body:
            return issue["number"]
    return None


def _format_summary_body(specs: list[dict], config_diagnostics: list[str]) -> str:
    """Build the markdown body for a spec summary issue."""
    lines: list[str] = [
        ONBOARD_MARKER,
        "",
        "# Welcome to Canon",
        "",
        f"We found **{len(specs)} spec(s)** in this repository:",
        "",
        "| Spec | Status | Sections | Acceptance Criteria |",
        "|------|--------|----------|---------------------|",
    ]

    for spec in specs:
        doc = spec["document"]
        fm = doc.frontmatter
        n_sections = len(doc.sections)
        n_ac = sum(len(s.acceptance_criteria) for s in doc.sections)
        lines.append(f"| `{spec['file_path']}` | {fm.status} | {n_sections} | {n_ac} |")

    lines.extend(
        [
            "",
            "## What happens next",
            "",
            "Canon is now watching this repo in **shadow mode**:",
            "",
            "- Push changes to spec files → Canon validates and tracks them",
            "- Open a PR that touches code related to a spec → Canon posts a review comment",
            "- Spec sections can be linked to tickets for bidirectional sync",
            "",
            "To configure behavior, add or edit `CANON.yaml` in your repo root.",
        ]
    )

    if config_diagnostics:
        lines.extend(
            [
                "",
                "## Config diagnostics",
                "",
                "Issues found in your `CANON.yaml`:",
                "",
                *config_diagnostics,
            ]
        )

    lines.extend(
        [
            "",
            "---",
            "_This issue was created by Canon during first-run onboarding._",
        ]
    )

    return "\n".join(lines)


async def _post_summary_issue(
    client: GitHubClient,
    owner: str,
    repo: str,
    specs: list[dict],
    config_diagnostics: list[str],
) -> None:
    """Create a welcome issue summarizing existing specs."""
    body = _format_summary_body(specs, config_diagnostics)
    await client.ensure_label(owner, repo, ONBOARD_LABEL, description="Canon onboarding issue")
    await client.create_issue(
        owner,
        repo,
        title="Canon: Welcome — spec summary",
        body=body,
        labels=[ONBOARD_LABEL],
    )
    logger.info("Posted onboarding summary issue for %s/%s", owner, repo)


async def _open_setup_pr(
    client: GitHubClient,
    owner: str,
    repo: str,
    branch: str,
    has_config: bool,
) -> None:
    """Open a PR with starter spec template and optional CANON.yaml."""
    setup_files = list_setup_files(has_config=has_config)
    files = [FileChange(path=f.path, content=f.content) for f in setup_files]

    body_lines = [
        ONBOARD_MARKER,
        "",
        "# Getting started with Canon",
        "",
        "This PR adds starter files for Canon:",
        "",
        "- `docs/specs/_template.md` — copy this to create new spec documents",
    ]
    if not has_config:
        body_lines.append("- `CANON.yaml` — repo-level configuration for Canon")

    body_lines.extend(
        [
            "",
            "## Next steps",
            "",
            "1. Merge this PR to set up the spec directory",
            "2. Copy `_template.md` to create your first spec (e.g. `docs/specs/my-feature.md`)",
            "3. Push the spec and Canon will start tracking it",
            "",
            "See the [Canon docs](https://canonhq.co) for more details.",
            "",
            "---",
            "_This PR was created by Canon during first-run onboarding._",
        ]
    )

    body = "\n".join(body_lines)

    await client.create_doc_pr(
        owner,
        repo,
        branch=branch,
        title="chore: add Canon starter files",
        body=body,
        files=files,
        commit_message="chore: add Canon starter spec template and config",
    )
    logger.info("Opened onboarding setup PR for %s/%s", owner, repo)
