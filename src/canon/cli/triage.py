"""canon triage — AI-powered issue classification and spec matching."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from issue_triage.models import IssueContext, TriageResult


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the triage subcommand."""
    p = subparsers.add_parser(
        "triage",
        help="Classify a GitHub issue and match it to specs",
        description=(
            "AI-powered issue triage: classify issues as feature-request, bug, "
            "question, duplicate, or support, and relate them to existing specs."
        ),
    )
    p.add_argument(
        "--issue",
        type=int,
        required=True,
        help="GitHub issue number to triage",
    )
    p.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Repository in owner/name format (auto-detected from git remote if omitted)",
    )
    p.add_argument(
        "--specs",
        type=str,
        default="docs/specs",
        help="Path to specs directory (default: docs/specs)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Apply labels and post triage comment on the issue",
    )
    p.add_argument(
        "--create-spec",
        action="store_true",
        help="Create a draft spec PR for unmatched feature requests",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without making changes",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON",
    )
    p.add_argument(
        "--confidence-threshold",
        type=float,
        default=None,
        help="Minimum confidence (0.0-1.0) to act on classification",
    )


def run_triage(
    issue: int,
    repo: str | None = None,
    specs: str = "docs/specs",
    apply: bool = False,
    create_spec: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
    confidence_threshold: float | None = None,
) -> int:
    """Run the triage command."""
    import asyncio
    import os

    # Resolve repo from git remote if not provided
    if not repo:
        repo = _detect_repo()
        if not repo:
            print("Error: Could not detect repository. Use --repo owner/name.", file=sys.stderr)
            return 1

    if "/" not in repo:
        print("Error: Repository must be in owner/name format.", file=sys.stderr)
        return 1

    owner, name = repo.split("/", 1)

    # Load specs
    specs_path = Path(specs)
    if not specs_path.is_absolute():
        specs_path = Path.cwd() / specs_path

    # Import extension modules — try installed package first, fall back to local path
    try:
        from issue_triage.matcher import load_spec_summaries
    except ImportError:
        sys.path.insert(
            0,
            str(
                Path(__file__).parent.parent.parent.parent
                / "extensions"
                / "canon-issue-triage"
                / "src"
            ),
        )
        from issue_triage.matcher import load_spec_summaries

    spec_summaries = load_spec_summaries(specs_path) if specs_path.exists() else []

    # Fetch issue from GitHub
    github_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not github_token:
        print("Error: GITHUB_TOKEN or GH_TOKEN environment variable required.", file=sys.stderr)
        return 1

    issue_ctx = asyncio.run(_fetch_issue(owner, name, issue, github_token))
    if not issue_ctx:
        print(f"Error: Could not fetch issue #{issue} from {repo}.", file=sys.stderr)
        return 1

    # Check ignore rules from CANON.yaml
    triage_config = _load_triage_config()
    if not triage_config.get("enabled", True):
        print("Issue triage is disabled in CANON.yaml.", file=sys.stderr)
        return 0

    ignore_labels = set(triage_config.get("ignore_labels", []))
    if ignore_labels & set(issue_ctx.labels):
        print(f"Issue #{issue} has an ignored label. Skipping.", file=sys.stderr)
        return 0

    ignore_authors = set(triage_config.get("ignore_authors", []))
    if issue_ctx.author in ignore_authors:
        print(f"Issue #{issue} author is ignored. Skipping.", file=sys.stderr)
        return 0

    # Classify
    from issue_triage.classifier import classify_issue

    from canon.agent.client import ClaudeClient

    client = ClaudeClient()
    result = classify_issue(client, issue_ctx, spec_summaries)

    confidence_threshold_val = (
        confidence_threshold
        if confidence_threshold is not None
        else triage_config.get("confidence_threshold", 0.7)
    )

    # Build output dict (used for JSON mode)
    output = {
        "issue": issue,
        "repo": repo,
        "classification": result.classification.value,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "related_specs": [
            {"path": s.path, "relevance": s.relevance, "section": s.section}
            for s in result.related_specs
        ],
        "suggested_labels": result.suggested_labels,
        "duplicate_of": result.duplicate_of,
        "above_threshold": result.confidence >= confidence_threshold_val,
        "spec_pr_url": None,
    }

    # Apply actions if above threshold and requested
    spec_pr_url = None
    if result.confidence >= confidence_threshold_val and not dry_run and apply:
        try:
            spec_pr_url = asyncio.run(_apply_actions(issue_ctx, result, github_token, create_spec))
            output["spec_pr_url"] = spec_pr_url
        except Exception as exc:
            print(f"Error applying triage actions: {exc}", file=sys.stderr)
            return 1

    # Print results
    if json_output:
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{'=' * 60}")
        print(f"Issue #{issue}: {issue_ctx.title}")
        print(f"{'=' * 60}")
        print(f"\nClassification: {result.classification.value}")
        print(f"Confidence:     {result.confidence:.0%}")
        print(f"Reasoning:      {result.reasoning}")
        if result.related_specs:
            print("\nRelated Specs:")
            for spec in result.related_specs:
                section_ref = f" §{spec.section}" if spec.section else ""
                print(f"  - {spec.path}{section_ref} (relevance: {spec.relevance:.0%})")
        if result.duplicate_of:
            print(f"\nDuplicate of: #{result.duplicate_of}")
        if spec_pr_url:
            print(f"\nSpec PR: {spec_pr_url}")
        print()

        if result.confidence < confidence_threshold_val:
            print(
                f"Confidence ({result.confidence:.0%}) below threshold "
                f"({confidence_threshold_val:.0%}). Skipping actions."
            )
        elif dry_run:
            print("[dry-run] Would apply labels and comment. Use --apply to execute.")

    return 0


async def _fetch_issue(owner: str, repo: str, issue_number: int, token: str) -> IssueContext | None:
    """Fetch issue details from GitHub API."""
    import httpx
    from issue_triage.models import IssueContext

    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return None
        data = resp.json()

    return IssueContext(
        number=issue_number,
        title=data["title"],
        body=data.get("body") or "",
        author=data["user"]["login"],
        labels=[label["name"] for label in data.get("labels", [])],
        repo_owner=owner,
        repo_name=repo,
    )


async def _apply_actions(
    issue_ctx: IssueContext,
    result: TriageResult,
    token: str,
    create_spec: bool,
) -> str | None:
    """Apply triage actions: labels, comment, optionally create spec. Returns spec PR URL if created."""
    import httpx
    from issue_triage.models import IssueCategory
    from issue_triage.responder import apply_labels, create_spec_pr, post_comment

    spec_pr_url = None
    async with httpx.AsyncClient() as client:
        await apply_labels(client, issue_ctx, result, token)
        await post_comment(client, issue_ctx, result, token)

        if (
            create_spec
            and result.classification == IssueCategory.FEATURE_REQUEST
            and all(s.relevance < 0.3 for s in result.related_specs)
        ):
            # Generate spec content
            spec_content = _generate_spec_content(issue_ctx)
            spec_pr_url = await create_spec_pr(client, issue_ctx, spec_content, token)
            if spec_pr_url:
                # Comment on the issue with the PR link
                comment_body = (
                    f"I've created a draft spec PR for this feature request: {spec_pr_url}\n\n"
                    f"Please review and refine before merging."
                )
                url = (
                    f"https://api.github.com/repos/{issue_ctx.repo_owner}/"
                    f"{issue_ctx.repo_name}/issues/{issue_ctx.number}/comments"
                )
                headers = {
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                }
                resp = await client.post(url, headers=headers, json={"body": comment_body})
                if resp.status_code >= 300:
                    import logging

                    logging.getLogger(__name__).warning(
                        "Failed to post spec-PR link comment: %d %s",
                        resp.status_code,
                        resp.text,
                    )

    return spec_pr_url


def _sanitize_issue_body(body: str) -> str:
    """Strip Canon-namespaced HTML comments from issue body to prevent marker injection."""
    import re

    return re.sub(r"<!--\s*canon:[^>]*-->", "", body).strip()


def _generate_spec_content(issue_ctx: IssueContext) -> str:
    """Generate a draft spec from issue context."""
    from datetime import date

    safe_title = issue_ctx.title.replace("\\", "\\\\").replace('"', '\\"')
    body = (
        _sanitize_issue_body(issue_ctx.body[:2000])
        if issue_ctx.body
        else "Brief overview of this feature."
    )
    return f"""\
---
title: "{safe_title}"
status: draft
owner: {issue_ctx.author}
team: tbd
ticket_project: null
created: {date.today().isoformat()}
updated: {date.today().isoformat()}
tags: []
---

# {issue_ctx.title}

<!-- canon:ticket:github:{issue_ctx.number} -->

{body}

## 1. Background

Why this feature exists and what problem it solves.

## 2. Requirements

<!-- canon:system:2 status:todo -->

### Acceptance Criteria

- [ ] (to be defined)

## 3. Design

<!-- canon:system:3 status:draft -->

Technical approach to be determined.

## 4. Open Questions

- What is the scope of this feature?
- Are there dependencies on other work?
"""


def _load_triage_config() -> dict:
    """Load triage config from CANON.yaml if present."""
    config_path = Path.cwd() / "CANON.yaml"
    if not config_path.exists():
        return {"enabled": True}

    try:
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return data.get("triage", {"enabled": True})
    except Exception:
        return {"enabled": True}


def _detect_repo() -> str | None:
    """Detect the repo from git remote origin."""
    import re
    import subprocess

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
        url = result.stdout.strip()
        # Handle SSH: git@github.com:owner/repo.git
        m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
        # Handle HTTPS: https://github.com/owner/repo.git
        m = re.match(r"https://github\.com/(.+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except subprocess.CalledProcessError:
        pass
    return None
