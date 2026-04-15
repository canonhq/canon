"""Handle pull_request.closed events — auto-create doc-update PRs on merge."""

from __future__ import annotations

import logging

from canon import analytics

from ...agent.analyzer import extract_analysis_data
from ...parser.models import ParseOptions, flatten_sections
from ...parser.parse import parse_spec
from ...parser.writer import (
    RealizationInsertion,
    StatusUpdate,
    check_off_acs,
    insert_realization_comments,
    update_frontmatter_field,
    update_status_comments,
)
from ..spec_utils import filter_spec_files, is_spec_file, load_repo_config, load_repo_specs

logger = logging.getLogger(__name__)

BOT_MARKER = "<!-- canon-bot -->"


async def on_pull_request_merged(client, payload: dict) -> None:
    """Handle a merged PR — create doc-update PRs if needed.

    Args:
        client: GitHubClient instance.
        payload: The webhook payload.
    """
    pr = payload["pull_request"]
    pr_number = pr["number"]

    # Only act on merged PRs
    if not pr.get("merged"):
        return

    # Skip our own doc-update PRs to avoid infinite loops
    if pr["head"]["ref"].startswith("canon/") or pr["head"]["ref"].startswith("specwright/"):
        return

    owner = payload["repository"]["owner"]["login"]
    repo = payload["repository"]["name"]
    base_ref = pr["base"]["ref"]

    # Check repo config — respect agents.doc_updates setting
    config = await load_repo_config(client, owner, repo, ref=base_ref)
    doc_paths = config.specs.doc_paths

    if not config.agents.doc_updates:
        logger.info("Doc updates disabled via config for PR #%d", pr_number)
        return

    # Auto-advance review_status on approved PR merge
    try:
        pr_files = await client.list_pull_files(owner, repo, pr_number)
        merged_spec_files = filter_spec_files([f["filename"] for f in pr_files], patterns=doc_paths)
        if merged_spec_files:
            # Check if PR was approved
            reviews = await client.list_pull_reviews(owner, repo, pr_number)
            has_approval = any(r.get("state") == "APPROVED" for r in reviews)
            if has_approval:
                for spec_path in merged_spec_files:
                    try:
                        content, file_sha = await client.get_file_content(
                            owner, repo, spec_path, ref=base_ref
                        )
                        parse_result = parse_spec(content, ParseOptions(file_path=spec_path))
                        current_review = parse_result.document.frontmatter.review_status
                        if current_review in ("draft", "in_review", None):
                            updated_content = update_frontmatter_field(
                                content, "review_status", "approved"
                            )
                            await client.create_or_update_file(
                                owner,
                                repo,
                                spec_path,
                                updated_content,
                                f"chore(canon): mark {spec_path} as approved",
                                file_sha,
                                branch=base_ref,
                            )
                            logger.info(
                                "Auto-advanced review_status to approved for %s (PR #%d)",
                                spec_path,
                                pr_number,
                            )
                    except Exception:
                        logger.warning(
                            "Failed to auto-advance review_status for %s",
                            spec_path,
                            exc_info=True,
                        )
    except Exception:
        logger.warning("Failed to check PR approval for review_status advancement", exc_info=True)

    # Find the bot's analysis comment
    comments = await client.list_issue_comments(owner, repo, pr_number)
    bot_comment = next(
        (c for c in comments if BOT_MARKER in c.get("body", "")),
        None,
    )
    if not bot_comment or not bot_comment.get("body"):
        return

    # Extract embedded analysis data
    analysis = extract_analysis_data(bot_comment["body"])
    if not analysis:
        return

    # Build realization insertions from embedded data
    realizations = analysis.get("realizations", [])
    realization_insertions: dict[str, list[RealizationInsertion]] = {}
    # Track fully-realized ACs per spec file so we can check them off.
    realized_ac_texts: dict[str, list[str]] = {}
    for r in realizations:
        if not isinstance(r, dict):
            continue
        status_val = r.get("status", "")
        if status_val not in ("realized", "partially_realized"):
            continue
        spec_file = r.get("spec_file", "")
        if not spec_file:
            continue
        # Both realized and partially_realized ACs get checked off.
        # Only conflicting ACs are excluded (flagged in comment, not checked).
        ac_text = r.get("ac_text", "").strip()
        if ac_text:
            realized_ac_texts.setdefault(spec_file, []).append(ac_text)
        evidence_files = r.get("evidence_files", [])
        for ef in evidence_files or [{}]:
            file_path = ef.get("path", "") if isinstance(ef, dict) else ""
            start = ef.get("start_line", "") if isinstance(ef, dict) else ""
            end = ef.get("end_line", "") if isinstance(ef, dict) else ""
            lines_str = f"{start}-{end}" if start and end else str(start) if start else ""
            realization_insertions.setdefault(spec_file, []).append(
                RealizationInsertion(
                    ac_text=r.get("ac_text", ""),
                    pr_number=pr_number,
                    file_path=file_path,
                    lines=lines_str,
                )
            )

    # Check for actionable items
    doc_updates = analysis.get("doc_updates", [])
    discrepancies = analysis.get("discrepancies", [])
    has_doc_updates = len(doc_updates) > 0
    has_realizations = len(realization_insertions) > 0
    has_conflicts = any(
        d.get("severity") == "conflict" if isinstance(d, dict) else False for d in discrepancies
    )

    if not has_doc_updates and not has_conflicts and not has_realizations:
        return

    # Need explicit doc updates or realizations to auto-generate file changes
    if not has_doc_updates and not has_realizations:
        return

    # Load specs to get current file contents and SHAs
    specs = await load_repo_specs(client, owner, repo, ref=base_ref, patterns=doc_paths)

    # Build lookup of known spec file contents
    spec_contents: dict[str, str] = {}
    # Track original file SHAs — used at commit time to detect conflicts.
    # If the file changed between load and commit, the SHA will mismatch and
    # GitHub returns 409, triggering the safe fallback to a doc-update PR.
    file_shas: dict[str, str] = {}
    for s in specs:
        spec_contents[s["file_path"]] = s["raw"]
        if "sha" in s:
            file_shas[s["file_path"]] = s["sha"]

    # Apply text replacements
    file_updates: dict[str, str] = {}
    for update in doc_updates:
        spec_file = update.get("specFile") or update.get("spec_file", "")
        current_text = update.get("currentText") or update.get("current_text", "")
        suggested_text = update.get("suggestedText") or update.get("suggested_text", "")

        if spec_file in spec_contents:
            content = file_updates.get(spec_file, spec_contents[spec_file])
        elif spec_file in file_updates:
            content = file_updates[spec_file]
        else:
            # Non-spec file — fetch on demand
            try:
                raw, raw_sha = await client.get_file_content(owner, repo, spec_file, ref=base_ref)
                content = raw
                file_shas[spec_file] = raw_sha
            except Exception:
                logger.warning("Failed to fetch non-spec file for doc update: %s", spec_file)
                continue

        content = content.replace(current_text, suggested_text)
        file_updates[spec_file] = content

    # Apply realization evidence comments, check off realized ACs, and
    # auto-advance section status when all ACs in a section are done.
    for spec_file, insertions in realization_insertions.items():
        if spec_file in spec_contents or spec_file in file_updates:
            raw = file_updates.get(spec_file, spec_contents.get(spec_file, ""))
            if raw:
                result = parse_spec(raw, ParseOptions(file_path=spec_file))
                updated = insert_realization_comments(result.document, insertions)
                # Check off fully-realized ACs.
                ac_texts = realized_ac_texts.get(spec_file, [])
                if ac_texts:
                    updated = check_off_acs(updated, ac_texts)
                if updated != raw:
                    file_updates[spec_file] = updated

    # Auto-advance section statuses: if all ACs in a section are now
    # checked, advance the section from in_progress/todo → done.
    # Non-spec files fetched on-demand (via doc_updates) are excluded —
    # they aren't spec documents and don't have section status comments.
    for spec_file, content in list(file_updates.items()):
        if spec_file not in spec_contents:
            continue
        try:
            result = parse_spec(content, ParseOptions(file_path=spec_file))
        except Exception:
            continue

        # Guard against duplicate AC text across sections — check_off_acs
        # matches globally, so identical AC wording in two sections could
        # cause a spurious check-off cascade. Skip auto-advance entirely
        # for files with duplicates.
        all_sections = flatten_sections(result.document.sections)
        all_ac_texts: list[str] = []
        for s in all_sections:
            all_ac_texts.extend(ac.text.strip().lower() for ac in s.acceptance_criteria)
        if len(all_ac_texts) != len(set(all_ac_texts)):
            logger.warning(
                "Skipping auto-advance for %s — duplicate AC text across sections",
                spec_file,
            )
            continue

        status_updates: list[StatusUpdate] = []
        for section in all_sections:
            if not section.acceptance_criteria or not section.section_number:
                continue
            # Only auto-advance from actionable states. Blocked sections
            # require a human to clear the blocker first.
            if section.status.state not in ("todo", "in_progress"):
                continue
            if all(ac.checked for ac in section.acceptance_criteria):
                status_updates.append(
                    StatusUpdate(section_number=section.section_number, new_state="done")
                )
                logger.info(
                    "Auto-advancing %s §%s to done — all ACs checked (PR #%d)",
                    spec_file,
                    section.section_number,
                    pr_number,
                )
        if status_updates:
            file_updates[spec_file] = update_status_comments(result.document, status_updates)

    if not file_updates:
        return

    # --- Auto-commit directly to default branch ---
    # Use the original SHA from when we loaded the file. If another commit
    # landed since then, the SHA will mismatch and GitHub returns 409,
    # triggering the safe fallback to a doc-update PR.
    commit_message = f"chore(canon): update specs from PR #{pr_number}"
    committed_files: list[str] = []
    failed_files: dict[str, str] = {}  # path -> content

    for path, content in file_updates.items():
        try:
            sha = file_shas.get(path)
            if not sha:
                # SHA not tracked (shouldn't happen) — fetch it now
                _current_content, sha = await client.get_file_content(
                    owner, repo, path, ref=base_ref
                )
            await client.create_or_update_file(
                owner, repo, path, content, commit_message, sha, branch=base_ref
            )
            committed_files.append(path)
            logger.info(
                "Auto-committed spec update for %s (PR #%d)",
                path,
                pr_number,
            )
        except Exception:
            logger.warning(
                "Failed to auto-commit %s for PR #%d — will fall back to doc-update PR",
                path,
                pr_number,
                exc_info=True,
            )
            failed_files[path] = content

    # Fall back to a doc-update PR for any files that failed direct commit
    fallback_pr_result = None
    if failed_files:
        from ..client import FileChange

        branch = f"canon/doc-update-pr-{pr_number}"
        fallback_files = [FileChange(path=p, content=c) for p, c in failed_files.items()]
        has_non_spec = any(not is_spec_file(p, patterns=doc_paths) for p in failed_files)
        doc_noun = "docs" if has_non_spec else "specs"
        title = f"docs: update {doc_noun} based on #{pr_number}"
        body = (
            f"Automated doc updates from merged PR #{pr_number} (`{pr['title']}`).\n\n"
            f"Canon could not commit these files directly (possible conflict):\n\n"
            + "\n".join(f"- `{p}`" for p in failed_files)
            + "\n\n---\n_This PR was auto-created by Canon. Please review before merging._"
        )
        fallback_commit_msg = f"docs: update {doc_noun} based on #{pr_number}"

        try:
            # Check if a fallback PR already exists (e.g. webhook retry)
            existing_pr = await client.find_open_doc_pr(owner, repo, branch)
            if existing_pr:
                fallback_pr_result = await client.update_doc_pr(
                    owner,
                    repo,
                    branch=branch,
                    title=title,
                    body=body,
                    files=fallback_files,
                    commit_message=fallback_commit_msg,
                    pr_number=existing_pr.pr_number,
                )
                logger.info(
                    "Updated existing fallback doc-update PR: source=#%d doc=#%d",
                    pr_number,
                    fallback_pr_result.pr_number,
                )
            else:
                fallback_pr_result = await client.create_doc_pr(
                    owner,
                    repo,
                    branch=branch,
                    title=title,
                    body=body,
                    files=fallback_files,
                    commit_message=fallback_commit_msg,
                )
                logger.info(
                    "Created fallback doc-update PR: source=#%d doc=#%d",
                    pr_number,
                    fallback_pr_result.pr_number,
                )
        except Exception:
            logger.exception("Failed to create fallback doc-update PR for PR #%d", pr_number)
            analytics.capture_exception(
                properties={
                    "context": "fallback_doc_pr_creation",
                    "pr_number": pr_number,
                    "repo": f"{owner}/{repo}",
                    "failed_files": list(failed_files.keys()),
                },
            )
            analytics.track(
                "spec_update_total_failure",
                properties={
                    "pr_number": pr_number,
                    "repo": f"{owner}/{repo}",
                    "failed_files": list(failed_files.keys()),
                },
            )

    # Post a summary comment on the original PR listing updated specs
    summary_lines: list[str] = []
    if committed_files:
        summary_lines.append(f"Canon committed spec updates directly to `{base_ref}`:\n")
        for f in committed_files:
            summary_lines.append(f"- `{f}`")
    if fallback_pr_result:
        if summary_lines:
            summary_lines.append("")
        summary_lines.append(
            f"Some files could not be committed directly — "
            f"see fallback PR #{fallback_pr_result.pr_number}: "
            f"{fallback_pr_result.pr_url}"
        )
    if summary_lines:
        try:
            await client.create_comment(owner, repo, pr_number, "\n".join(summary_lines))
        except Exception:
            logger.warning("Failed to post summary comment on PR #%d", pr_number, exc_info=True)
