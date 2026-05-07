"""GitHub integration — label, comment, and create spec PRs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import quote

from .models import IssueCategory, IssueContext, TriageResult

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

# Label prefix to namespace canon labels
LABEL_PREFIX = "canon:"

# Category → label mapping
CATEGORY_LABELS: dict[IssueCategory, str] = {
    IssueCategory.FEATURE_REQUEST: f"{LABEL_PREFIX}feature-request",
    IssueCategory.BUG_REPORT: f"{LABEL_PREFIX}bug",
    IssueCategory.QUESTION: f"{LABEL_PREFIX}question",
    IssueCategory.DUPLICATE: f"{LABEL_PREFIX}duplicate",
    IssueCategory.SUPPORT: f"{LABEL_PREFIX}support",
}

# Label colors (hex without #)
LABEL_COLORS: dict[str, str] = {
    f"{LABEL_PREFIX}feature-request": "0e8a16",
    f"{LABEL_PREFIX}bug": "d73a4a",
    f"{LABEL_PREFIX}question": "d876e3",
    f"{LABEL_PREFIX}duplicate": "cfd3d7",
    f"{LABEL_PREFIX}support": "fbca04",
}


def build_triage_comment(result: TriageResult, issue: IssueContext) -> str:
    """Build a markdown comment summarizing the triage results."""
    lines = [
        "## Canon Issue Triage",
        "",
        f"**Classification:** {result.classification.value} (confidence: {result.confidence:.0%})",
        "",
        "\n".join(f"> {line}" for line in result.reasoning.splitlines()),
        "",
    ]

    if result.related_specs:
        lines.append("### Related Specs")
        lines.append("")
        for spec in result.related_specs:
            section_ref = f" §{spec.section}" if spec.section else ""
            lines.append(f"- `{spec.path}`{section_ref} — relevance: {spec.relevance:.0%}")
        lines.append("")

    if result.classification == IssueCategory.FEATURE_REQUEST and not result.related_specs:
        lines.append(
            "*No existing spec matches this feature request. A draft spec may be created.*"
        )
        lines.append("")

    if result.classification == IssueCategory.DUPLICATE and result.duplicate_of:
        lines.append(f"This appears to be a duplicate of #{result.duplicate_of}.")
        lines.append("")

    lines.append("---")
    lines.append("*Triaged by [Canon](https://github.com/canonhq/canon) issue-triage extension*")

    return "\n".join(lines)


async def apply_labels(
    http_client: httpx.AsyncClient,
    issue: IssueContext,
    result: TriageResult,
    token: str,
) -> None:
    """Apply classification labels to the issue."""
    label_name = CATEGORY_LABELS.get(result.classification)
    if not label_name:
        return

    repo = f"{issue.repo_owner}/{issue.repo_name}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Ensure label exists
    await _ensure_label(http_client, repo, label_name, headers)

    # Add label to issue
    url = f"https://api.github.com/repos/{repo}/issues/{issue.number}/labels"
    resp = await http_client.post(url, headers=headers, json={"labels": [label_name]})
    if resp.status_code < 300:
        logger.info("Applied label %s to issue #%d", label_name, issue.number)
    else:
        logger.warning(
            "Failed to apply label %s: %d %s",
            label_name,
            resp.status_code,
            resp.text,
        )


async def post_comment(
    http_client: httpx.AsyncClient,
    issue: IssueContext,
    result: TriageResult,
    token: str,
) -> str | None:
    """Post the triage comment on the issue. Returns comment URL."""
    repo = f"{issue.repo_owner}/{issue.repo_name}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    comment_body = build_triage_comment(result, issue)
    url = f"https://api.github.com/repos/{repo}/issues/{issue.number}/comments"
    resp = await http_client.post(url, headers=headers, json={"body": comment_body})

    if resp.status_code < 300:
        data = resp.json()
        logger.info("Posted triage comment on issue #%d", issue.number)
        return data.get("html_url")
    else:
        logger.warning("Failed to post comment: %d %s", resp.status_code, resp.text)
        return None


async def create_spec_pr(
    http_client: httpx.AsyncClient,
    issue: IssueContext,
    spec_content: str,
    token: str,
) -> str | None:
    """Create a branch with a new spec file and open a PR. Returns PR URL."""
    import re
    from base64 import b64encode

    repo = f"{issue.repo_owner}/{issue.repo_name}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Generate slug from issue title
    slug = re.sub(r"[^a-z0-9]+", "-", issue.title.lower()).strip("-")[:50]
    if not slug:
        slug = f"issue-{issue.number}"
    branch_name = f"spec/issue-{issue.number}-{slug}"
    spec_path = f"docs/specs/{slug}.md"

    # Get default branch SHA
    repo_url = f"https://api.github.com/repos/{repo}"
    repo_resp = await http_client.get(repo_url, headers=headers)
    if repo_resp.status_code >= 300:
        logger.error("Failed to get repo info: %s", repo_resp.text)
        return None

    default_branch = repo_resp.json()["default_branch"]
    ref_url = f"https://api.github.com/repos/{repo}/git/ref/heads/{default_branch}"
    ref_resp = await http_client.get(ref_url, headers=headers)
    if ref_resp.status_code >= 300:
        logger.error("Failed to get ref: %s", ref_resp.text)
        return None

    base_sha = ref_resp.json()["object"]["sha"]

    # Create branch
    create_ref_url = f"https://api.github.com/repos/{repo}/git/refs"
    create_resp = await http_client.post(
        create_ref_url,
        headers=headers,
        json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
    )
    if create_resp.status_code >= 300:
        logger.error("Failed to create branch: %s", create_resp.text)
        return None

    # Create file on the branch
    content_b64 = b64encode(spec_content.encode()).decode()
    file_url = f"https://api.github.com/repos/{repo}/contents/{spec_path}"
    file_resp = await http_client.put(
        file_url,
        headers=headers,
        json={
            "message": f"docs: draft spec from issue #{issue.number}",
            "content": content_b64,
            "branch": branch_name,
        },
    )
    if file_resp.status_code >= 300:
        logger.error("Failed to create file: %s", file_resp.text)
        return None

    # Open PR
    pr_url = f"https://api.github.com/repos/{repo}/pulls"
    pr_body = (
        f"Draft spec created from issue #{issue.number}.\n\n"
        f"<!-- canon:ticket:github:{issue.number} -->\n\n"
        f"This spec was auto-generated by Canon's issue triage extension. "
        f"Please review and refine before merging."
    )
    pr_resp = await http_client.post(
        pr_url,
        headers=headers,
        json={
            "title": f'docs: spec for "{issue.title}"',
            "body": pr_body,
            "head": branch_name,
            "base": default_branch,
            "draft": True,
        },
    )
    if pr_resp.status_code < 300:
        pr_data = pr_resp.json()
        logger.info("Created spec PR: %s", pr_data["html_url"])
        return pr_data["html_url"]
    else:
        logger.error("Failed to create PR: %s", pr_resp.text)
        return None


async def _ensure_label(
    http_client: httpx.AsyncClient,
    repo: str,
    label_name: str,
    headers: dict[str, str],
) -> None:
    """Ensure a label exists on the repo, creating it if needed."""
    url = f"https://api.github.com/repos/{repo}/labels/{quote(label_name, safe='')}"
    resp = await http_client.get(url, headers=headers)
    if resp.status_code == 404:
        create_url = f"https://api.github.com/repos/{repo}/labels"
        color = LABEL_COLORS.get(label_name, "ededed")
        create_resp = await http_client.post(
            create_url,
            headers=headers,
            json={"name": label_name, "color": color},
        )
        # 422 is benign (concurrent creation race), other errors are real failures
        if create_resp.status_code >= 400 and create_resp.status_code != 422:
            logger.warning(
                "Failed to create label %s: %d %s",
                label_name,
                create_resp.status_code,
                create_resp.text,
            )
