"""Handle issue_comment events — respond to @canon mentions."""

from __future__ import annotations

import logging
import re

from canon.settings import Settings

from ...agent.analyzer import analyze_pr, format_analysis_comment
from ...agent.prompts import PRAnalysisContext, PRFile, RepoSpec
from ..client import FileChange
from ..spec_utils import load_repo_config, load_repo_specs

logger = logging.getLogger(__name__)
_settings = Settings()

MENTION_RE = re.compile(r"@(?:specwright|canon)\b", re.IGNORECASE)
BOT_MARKER = "<!-- canon-bot -->"


def _parse_command(body: str) -> str:
    lower = body.lower()
    if "@canon dismiss" in lower or "@specwright dismiss" in lower:
        return "dismiss"
    if "@canon apply docs" in lower or "@specwright apply docs" in lower:
        return "apply"
    if "@canon reanalyze" in lower or "@specwright reanalyze" in lower:
        return "reanalyze"
    return "unknown"


async def on_issue_comment(client, payload: dict) -> None:
    """Handle an issue_comment event with @canon mention.

    Args:
        client: GitHubClient instance.
        payload: The webhook payload.
    """
    comment = payload["comment"]
    if not MENTION_RE.search(comment.get("body", "")):
        return

    owner = payload["repository"]["owner"]["login"]
    repo = payload["repository"]["name"]
    issue_number = payload["issue"]["number"]
    is_pr = "pull_request" in payload["issue"]

    logger.info(
        "@canon mentioned in comment on #%d by %s",
        issue_number,
        comment["user"]["login"],
    )

    command = _parse_command(comment["body"])

    if command == "dismiss":
        await _handle_dismiss(client, owner, repo, issue_number)
    elif command == "apply":
        if is_pr:
            await _handle_apply_docs(client, owner, repo, issue_number)
        else:
            await _reply(
                client,
                owner,
                repo,
                issue_number,
                "The `apply docs` command only works on pull requests.",
            )
    elif command == "reanalyze":
        if is_pr:
            await _handle_reanalyze(client, owner, repo, issue_number)
        else:
            await _reply(
                client,
                owner,
                repo,
                issue_number,
                "The `reanalyze` command only works on pull requests.",
            )
    else:
        await _reply(
            client,
            owner,
            repo,
            issue_number,
            "Hi! I can help with your specs. Available commands:\n"
            "- `@canon reanalyze` — re-run spec analysis on this PR\n"
            "- `@canon apply docs` — create a PR with suggested doc updates\n"
            "- `@canon dismiss` — hide the analysis comment",
        )


async def _handle_dismiss(client, owner: str, repo: str, issue_number: int) -> None:
    comments = await client.list_issue_comments(owner, repo, issue_number)
    bot_comment = next(
        (c for c in comments if BOT_MARKER in c.get("body", "")),
        None,
    )
    if bot_comment:
        await client.delete_comment(owner, repo, bot_comment["id"])


async def _handle_reanalyze(client, owner: str, repo: str, pr_number: int) -> None:
    context = await _build_pr_context(client, owner, repo, pr_number)
    if not context:
        await _reply(client, owner, repo, pr_number, "Could not load PR data for reanalysis.")
        return

    result = analyze_pr(context)
    if not result:
        await _reply(
            client, owner, repo, pr_number, "Agent is unavailable — ANTHROPIC_API_KEY not set."
        )
        return

    from ...agent.client import DEFAULT_AGENT_CONFIG

    config = await load_repo_config(client, owner, repo)
    comment = format_analysis_comment(
        result,
        model=DEFAULT_AGENT_CONFIG.model,
        base_url=_settings.platform_url,
        owner=owner,
        repo=repo,
        doc_patterns=config.specs.doc_paths,
    )
    await client.upsert_bot_comment(owner, repo, pr_number, comment)


async def _handle_apply_docs(client, owner: str, repo: str, pr_number: int) -> None:
    context = await _build_pr_context(client, owner, repo, pr_number)
    if not context:
        await _reply(client, owner, repo, pr_number, "Could not load PR data.")
        return

    result = analyze_pr(context)
    if not result:
        await _reply(
            client, owner, repo, pr_number, "Agent is unavailable — ANTHROPIC_API_KEY not set."
        )
        return

    if not result.doc_updates:
        await _reply(client, owner, repo, pr_number, "No doc updates suggested for this PR.")
        return

    # Group updates by file and apply text replacements
    file_updates: dict[str, str] = {}
    for update in result.doc_updates:
        spec = next((s for s in context.specs if s.file_path == update.spec_file), None)
        if not spec:
            continue

        content = file_updates.get(update.spec_file, spec.document.raw)
        content = content.replace(update.current_text, update.suggested_text)
        file_updates[update.spec_file] = content

    if not file_updates:
        await _reply(
            client, owner, repo, pr_number, "Could not apply doc updates — spec files not found."
        )
        return

    branch = f"canon/doc-update-pr-{pr_number}"
    files = [FileChange(path=path, content=content) for path, content in file_updates.items()]

    try:
        doc_pr = await client.create_doc_pr(
            owner,
            repo,
            branch=branch,
            title=f"docs: update specs based on PR #{pr_number}",
            body=(
                f"Automated spec updates suggested by Canon analysis of #{pr_number}.\n\n"
                + "\n".join(
                    f"- **{u.spec_file}** ({u.section_id}): {u.reason}" for u in result.doc_updates
                )
            ),
            files=files,
            commit_message=f"docs: update specs based on PR #{pr_number}",
        )
        await _reply(client, owner, repo, pr_number, f"Created doc update PR: {doc_pr.pr_url}")
    except Exception:
        logger.exception("Failed to create doc update PR")
        await _reply(
            client,
            owner,
            repo,
            pr_number,
            "Failed to create the doc update PR. Check the logs for details.",
        )


async def _build_pr_context(
    client, owner: str, repo: str, pr_number: int
) -> PRAnalysisContext | None:
    try:
        pr = await client.get_pull_request(owner, repo, pr_number)
        raw_files = await client.list_pull_files(owner, repo, pr_number)
        config = await load_repo_config(client, owner, repo, ref=pr["base"]["ref"])
        specs_data = await load_repo_specs(
            client, owner, repo, ref=pr["base"]["ref"], patterns=config.specs.doc_paths
        )

        files = [
            PRFile(
                filename=f["filename"],
                status=f.get("status", "modified"),
                patch=f.get("patch"),
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
            )
            for f in raw_files
        ]

        repo_specs = [
            RepoSpec(file_path=s["file_path"], document=s["document"]) for s in specs_data
        ]

        return PRAnalysisContext(
            pr=PRAnalysisContext.PRInfo(
                number=pr["number"],
                title=pr["title"],
                body=pr.get("body"),
                author=pr["user"]["login"],
                base_branch=pr["base"]["ref"],
                head_branch=pr["head"]["ref"],
                url=pr["html_url"],
            ),
            files=files,
            specs=repo_specs,
        )
    except Exception:
        return None


async def _reply(client, owner: str, repo: str, issue_number: int, body: str) -> None:
    await client.create_comment(owner, repo, issue_number, body)
