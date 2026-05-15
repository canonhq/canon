"""Handle pull_request events — analyze PR against specs and post context."""

from __future__ import annotations

import json
import logging
from datetime import UTC

import httpx

from canon import analytics
from canon.evidence.models import SessionRecord
from canon.settings import Settings

from ...agent.analyzer import analyze_pr, format_analysis_comment
from ...agent.client import DEFAULT_AGENT_CONFIG
from ...agent.prompts import ContextDoc, PRAnalysisContext, PRFile, RepoSpec
from ...config.parse import DEFAULT_CONFIG, parse_canon_yaml
from ..spec_utils import (
    CONFIG_ONLY_RE,
    filter_spec_files,
    load_repo_config,
    load_repo_docs,
    load_repo_specs,
)

logger = logging.getLogger(__name__)
_settings = Settings()


def _get_notification_dispatcher():
    """Get NotificationDispatcher from app.state, or None."""
    try:
        from canon.main import app

        return getattr(app.state, "notification_dispatcher", None)
    except Exception:
        return None


def _parse_evidence_payload(content: str) -> list[SessionRecord] | None:
    """Parse a `.canon/session-evidence.json` payload string.

    Returns:
        - list of validated `SessionRecord` instances when the payload is
          valid v1 with sessions
        - empty list when payload is valid v1 but has no sessions, OR all
          sessions failed validation (caller should NOT fall through to the
          DB — the file was present and authoritative)
        - None when the top-level payload is malformed or has an unsupported
          version (caller SHOULD fall back to cold analysis or the DB)

    **Security note**: validates each session via Pydantic BEFORE returning
    so a hostile PR-author-supplied evidence file can't smuggle in fields
    that don't match the canonical schema. Sessions that fail validation
    are dropped silently — the renderer downstream further sanitizes
    `ac_text` content via `_sanitize_ac_text`. See
    `plugin-evidence-pipeline.md` §2 + PR #501 review (security) for the
    full threat model.

    Mostly pure — only side effect is a warning log when sessions are dropped.
    Tested directly.
    """
    try:
        payload = json.loads(content)
    except (ValueError, TypeError):
        return None

    if not isinstance(payload, dict):
        return None

    version = payload.get("version", 1)
    if version != 1:
        return None

    sessions = payload.get("sessions", [])
    if not isinstance(sessions, list):
        return None

    # Validate each session against the canonical SessionRecord shape.
    # Drop entries that fail validation rather than failing the whole load —
    # one corrupt session shouldn't block the rest.
    validated: list[SessionRecord] = []
    total = len(sessions)
    for entry in sessions:
        if not isinstance(entry, dict):
            continue
        try:
            record = SessionRecord.model_validate(entry)
        except Exception:
            continue
        validated.append(record)
    # Log drop count so schema issues are visible without breaking this
    # function's pure-function contract — logging happens in the caller
    # via the returned count vs. total.
    if len(validated) < total:
        logger.warning(
            "session evidence: validated %d/%d sessions (dropped %d)",
            len(validated),
            total,
            total - len(validated),
        )
    return validated


async def _load_session_evidence(
    *,
    client,
    owner: str,
    repo: str,
    head_ref: str,
    head_sha: str | None,
) -> list[SessionRecord]:
    """Best-effort loader for plugin-captured dev-session evidence.

    Tries:
    1. `.canon/session-evidence.json` committed to the PR head ref
    2. SessionEvidenceStore.list_for_branch via app.state (if available)

    Returns an empty list on any failure — cold analysis is the fallback,
    not an error path. Returns `list[SessionRecord]` (validated) so the
    analyzer never sees an unstructured dict from author-controlled input.
    See plugin-evidence-pipeline.md §7.
    """
    # 1. Try the committed file path
    try:
        ref = head_sha or head_ref
        content, _sha = await client.get_file_content(
            owner, repo, ".canon/session-evidence.json", ref=ref
        )
    except httpx.HTTPStatusError as err:
        if err.response.status_code != 404:
            logger.debug(
                "session-evidence fetch failed for %s/%s: HTTP %s",
                owner,
                repo,
                err.response.status_code,
            )
        content = None
    except (httpx.RequestError, OSError) as err:
        logger.debug("session-evidence fetch failed for %s/%s: %s", owner, repo, err)
        content = None

    if content is not None:
        sessions = _parse_evidence_payload(content)
        if sessions is None:
            logger.warning(
                "session-evidence.json malformed or unsupported version for %s/%s; "
                "falling back to cold analysis",
                owner,
                repo,
            )
        else:
            # Honor empty intent: if the file parsed cleanly with no sessions,
            # the developer explicitly cleared it — don't second-guess via DB.
            return sessions

    # 2. Try the database store
    try:
        from canon.main import app

        store = getattr(app.state, "session_evidence_store", None)
        if store is None:
            return []
        rows = await store.list_for_branch(f"{owner}/{repo}", head_ref, limit=20)
    except Exception as err:
        logger.warning("session_evidence DB fetch failed for %s/%s: %s", owner, repo, err)
        return []

    # Validate each row's payload against SessionRecord at the boundary so
    # downstream consumers get typed access. Drop rows that fail validation
    # rather than crashing — schema drift in the DB should not break PR analysis.
    validated: list[SessionRecord] = []
    for row in rows:
        try:
            validated.append(SessionRecord.model_validate(row.payload))
        except Exception:
            logger.warning(
                "dropping malformed session_evidence row %s for %s/%s",
                getattr(row, "id", "?"),
                owner,
                repo,
            )
    return validated


def _get_search_deps() -> tuple | None:
    """Return (search_backend, embed_client) from app.state, or None if unavailable.

    Falls back to the raw ``search_index`` when no backend has been wired,
    keeping pre-Phase-2c boots and tests working.
    """
    try:
        from canon.main import app

        backend = getattr(app.state, "search_backend", None) or getattr(
            app.state, "search_index", None
        )
        if backend is None:
            return None
        embed_client = getattr(app.state, "embed_client", None)
        return (backend, embed_client)
    except Exception:
        return None


def _get_agent_store():
    """Return AgentStore from app.state, or None if unavailable."""
    try:
        from canon.main import app

        return getattr(app.state, "agent_store", None)
    except Exception:
        return None


def _get_pr_review_store():
    """Return PRReviewStore from app.state, or None if unavailable."""
    try:
        from canon.main import app

        return getattr(app.state, "pr_review_store", None)
    except Exception:
        return None


def _should_skip_reanalysis(
    prev_review: dict,
    raw_files: list[dict],
    pr: dict,
) -> str | None:
    """Check if re-analysis can be skipped. Returns skip reason or None."""
    from datetime import datetime

    # Same SHA as previously reviewed → no changes at all
    current_sha = pr["head"].get("sha", "")
    if current_sha and prev_review.get("head_sha") == current_sha:
        return "no_changes"

    # All changed files are config-only
    filenames = [f["filename"] for f in raw_files]
    if filenames and all(CONFIG_ONLY_RE.match(fn) for fn in filenames):
        return "config_only_changes"

    # Spec files changed → always re-analyze
    spec_files = filter_spec_files(filenames)
    if spec_files:
        return None

    # Staleness: if previous review is >24h old, always re-analyze
    prev_created = prev_review.get("created_at")
    if prev_created is not None:
        if isinstance(prev_created, datetime):
            if prev_created.tzinfo is None:
                age = datetime.now(UTC) - prev_created.replace(tzinfo=UTC)
            else:
                age = datetime.now(UTC) - prev_created
        else:
            age = None
        if age is not None and age.total_seconds() > 86400:
            return None

    return "no_spec_relevant_changes"


def _build_search_query(pr: dict, raw_files: list[dict], max_chars: int = 500) -> str:
    """Build a search query from PR title + body + filenames."""
    parts: list[str] = [pr["title"]]
    body = (pr.get("body") or "")[:200]
    if body:
        parts.append(body)
    for f in raw_files:
        filename = f["filename"]
        if not CONFIG_ONLY_RE.match(filename):
            parts.append(filename)
    query = " ".join(parts)
    return query[:max_chars]


async def _retrieve_context_docs(
    search_index,
    embed_client,
    query: str,
    repo: str,
    spec_paths: set[str],
    max_chars: int = 8000,
) -> list[ContextDoc]:
    """Retrieve relevant context docs from the search index."""
    query_embedding = None
    if embed_client and embed_client.is_available:
        try:
            query_embedding = embed_client.embed_query(query)
        except Exception:
            logger.debug("Failed to embed search query, using text-only search")

    try:
        results = await search_index.hybrid_search(
            query_embedding=query_embedding,
            query_text=query,
            repo=repo,
            limit=30,
        )
    except Exception:
        logger.warning("Search index query failed for context docs")
        return []

    seen: set[tuple[str, str]] = set()
    docs: list[ContextDoc] = []
    chars_used = 0

    for r in results:
        # Skip results that are already loaded as full specs
        if r.path in spec_paths:
            continue

        key = (r.path, r.heading)
        if key in seen:
            continue
        seen.add(key)

        body_len = len(r.body)
        if chars_used + body_len > max_chars:
            continue

        docs.append(
            ContextDoc(
                path=r.path,
                doc_title=r.doc_title,
                heading=r.heading,
                body=r.body,
                score=r.rrf_score,
            )
        )
        chars_used += body_len

    return docs


async def _load_context_docs_fallback(
    client,
    owner: str,
    repo: str,
    spec_paths: set[str],
    ref: str | None = None,
    max_chars: int = 8000,
) -> list[ContextDoc]:
    """Fallback: load docs directly from GitHub using doc_paths from CANON.yaml."""
    # Load config to get doc_paths
    doc_paths = None
    try:
        content, _sha = await client.get_file_content(owner, repo, "SPECWRIGHT.yaml", ref=ref)
        result = parse_canon_yaml(content)
        if result.config:
            doc_paths = result.config.specs.doc_paths
    except Exception:
        pass

    if not doc_paths:
        doc_paths = DEFAULT_CONFIG.specs.doc_paths

    try:
        all_docs = await load_repo_docs(client, owner, repo, patterns=doc_paths, ref=ref)
    except Exception:
        logger.debug("Failed to load docs via fallback for %s/%s", owner, repo)
        return []

    docs: list[ContextDoc] = []
    chars_used = 0

    for doc_data in all_docs:
        file_path = doc_data["file_path"]
        # Skip files already loaded as specs
        if file_path in spec_paths:
            continue

        document = doc_data["document"]
        for section in getattr(document, "sections", []):
            body = section.content[:2000] if hasattr(section, "content") else ""
            if not body:
                continue

            body_len = len(body)
            if chars_used + body_len > max_chars:
                break

            docs.append(
                ContextDoc(
                    path=file_path,
                    doc_title=getattr(document.frontmatter, "title", file_path),
                    heading=section.title,
                    body=body,
                )
            )
            chars_used += body_len

        if chars_used >= max_chars:
            break

    return docs


async def on_pull_request(client, payload: dict) -> None:
    """Handle a GitHub pull_request event.

    Args:
        client: GitHubClient instance.
        payload: The webhook payload.
    """
    pr = payload["pull_request"]
    owner = payload["repository"]["owner"]["login"]
    repo = payload["repository"]["name"]
    pr_number = pr["number"]
    action = payload.get("action")
    tag = f"[canon] {owner}/{repo}#{pr_number}"

    try:
        raw_files = await client.list_pull_files(owner, repo, pr_number)

        # Early return if only config/CI files
        has_non_config = any(not CONFIG_ONLY_RE.match(f["filename"]) for f in raw_files)
        if not has_non_config:
            return

        # Smart re-analysis: skip if prior review exists and changes are trivial
        if action == "synchronize":
            pr_review_store = _get_pr_review_store()
            if pr_review_store is not None:
                prev_review = await pr_review_store.get_latest_review(f"{owner}/{repo}", pr_number)
                if prev_review is not None:
                    skip_reason = _should_skip_reanalysis(prev_review, raw_files, pr)
                    if skip_reason:
                        # Preserve existing comment and add skip note
                        prev_sha = prev_review["head_sha"][:7]
                        await client.upsert_bot_comment(
                            owner,
                            repo,
                            pr_number,
                            f"<!-- canon-bot -->\n## Canon\n\n"
                            f"_Previous review (at `{prev_sha}`) still applies — "
                            f"new changes are {skip_reason.replace('_', ' ')}._\n\n"
                            f"<sub>Use `@canon reanalyze` to force a new review.</sub>",
                        )
                        analytics.track(
                            "pr_analysis_skipped",
                            properties={
                                "repo": f"{owner}/{repo}",
                                "pr_number": pr_number,
                                "skip_reason": skip_reason,
                            },
                            groups={"organization": owner},
                        )
                        logger.info("%s — skipped re-analysis: %s", tag, skip_reason)
                        return

        # Load repo config to get configurable doc_paths
        config = await load_repo_config(client, owner, repo, ref=pr["base"]["ref"])
        doc_paths = config.specs.doc_paths

        # Detect spec file changes and add label
        spec_changed_files = filter_spec_files(
            [f["filename"] for f in raw_files], patterns=doc_paths
        )
        if spec_changed_files:
            try:
                await client.ensure_label(
                    owner,
                    repo,
                    "spec-review",
                    color="7057ff",
                    description="PR modifies spec files",
                )
                # Add label to the PR (PRs are issues in GitHub API)
                existing_labels = [lbl["name"] for lbl in pr.get("labels", [])]
                if "spec-review" not in existing_labels:
                    await client.update_issue(
                        owner, repo, pr_number, labels=[*existing_labels, "spec-review"]
                    )
            except Exception:
                logger.warning("%s — failed to add spec-review label", tag, exc_info=True)

        # Load all repo specs
        specs_data = await load_repo_specs(
            client, owner, repo, ref=pr["base"]["ref"], patterns=doc_paths
        )

        if not specs_data:
            spec_files = filter_spec_files([f["filename"] for f in raw_files], patterns=doc_paths)
            if not spec_files:
                return

            file_list = "\n".join(f"- `{f}`" for f in spec_files)
            await client.upsert_bot_comment(
                owner,
                repo,
                pr_number,
                f"<!-- canon-bot -->\n## Canon\n\nThis PR modifies the following spec files:\n\n{file_list}\n\n_No other specs found for cross-reference._",
            )
            return

        # Retrieve context docs from search index or fallback
        spec_paths = {s["file_path"] for s in specs_data}
        context_docs: list[ContextDoc] = []
        search_deps = _get_search_deps()
        if search_deps:
            search_index, embed_client = search_deps
            query = _build_search_query(pr, raw_files)
            context_docs = await _retrieve_context_docs(
                search_index,
                embed_client,
                query,
                f"{owner}/{repo}",
                spec_paths,
            )
        else:
            context_docs = await _load_context_docs_fallback(
                client,
                owner,
                repo,
                spec_paths,
                ref=pr["base"]["ref"],
            )

        # Post a "processing" comment
        spec_list = ", ".join(f"`{s['file_path']}`" for s in specs_data)
        ctx_note = f" + {len(context_docs)} context doc(s)" if context_docs else ""
        spec_changes_note = ""
        if spec_changed_files:
            file_list_md = "\n".join(f"- `{f}`" for f in spec_changed_files)
            spec_changes_note = f"\n\n### Spec Changes\n\nThis PR modifies the following spec files:\n\n{file_list_md}\n"
        await client.upsert_bot_comment(
            owner,
            repo,
            pr_number,
            f"<!-- canon-bot -->\n## Canon\n\n_Analyzing {len(raw_files)} file(s) against {len(specs_data)} spec(s) ({spec_list}){ctx_note}..._"
            + spec_changes_note,
        )

        # Build analysis context
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

        # Load dev-session evidence captured by the canon plugin
        # (plugin-evidence-pipeline §7). Tries the committed file first,
        # falls back to the database table. Returns [] on any failure.
        session_evidence = await _load_session_evidence(
            client=client,
            owner=owner,
            repo=repo,
            head_ref=pr["head"]["ref"],
            head_sha=pr["head"].get("sha"),
        )

        context = PRAnalysisContext(
            pr=PRAnalysisContext.PRInfo(
                number=pr_number,
                title=pr["title"],
                body=pr.get("body"),
                author=pr["user"]["login"],
                base_branch=pr["base"]["ref"],
                head_branch=pr["head"]["ref"],
                url=pr["html_url"],
            ),
            files=files,
            specs=repo_specs,
            context_docs=context_docs,
            session_evidence=session_evidence,
        )

        result = analyze_pr(context)

        if result:
            # Check for active preview deployment. This races with the preview
            # workflow (both trigger on synchronize), so the URL typically appears
            # one push after the first preview deploy completes — not a bug.
            preview_url = await client.get_preview_deployment_url(owner, repo, pr_number)

            comment = format_analysis_comment(
                result,
                model=DEFAULT_AGENT_CONFIG.model,
                preview_url=preview_url,
                base_url=_settings.platform_url,
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                head_sha=pr["head"]["sha"],
                doc_patterns=doc_paths,
            )
            await client.upsert_bot_comment(owner, repo, pr_number, comment)
            logger.info(
                "%s — analysis posted (%din/%dout)",
                tag,
                result.tokens_used.input,
                result.tokens_used.output,
            )

            analytics.track(
                "pr_analyzed",
                properties={
                    "repo": f"{owner}/{repo}",
                    "pr_number": pr_number,
                    "spec_count": len(specs_data),
                    "realization_count": len(result.realizations),
                    "discrepancy_count": len(result.discrepancies),
                    "tokens_in": result.tokens_used.input,
                    "tokens_out": result.tokens_used.output,
                    # plugin-evidence-pipeline §7 telemetry
                    "evidence_used": bool(session_evidence),
                    "evidence_session_count": len(session_evidence),
                },
                groups={"organization": owner},
            )

            # Notify Slack about PR analysis (best-effort)
            dispatcher = _get_notification_dispatcher()
            if dispatcher is not None:
                specs_affected = list({r.spec_file for r in result.realizations})
                acs_realized = sum(
                    1
                    for r in result.realizations
                    if r.status.value in ("realized", "partially_realized")
                )
                try:
                    await dispatcher.send_pr_analysis_summary(
                        pr_title=pr["title"],
                        pr_number=pr_number,
                        specs_affected=specs_affected,
                        acs_realized=acs_realized,
                        github_url=pr["html_url"],
                    )
                except Exception:
                    logger.debug("Failed to send PR analysis notification", exc_info=True)

            if result.realizations:
                for r in result.realizations:
                    if r.status.value in ("realized", "partially_realized"):
                        analytics.track(
                            "ac_realized",
                            properties={
                                "repo": f"{owner}/{repo}",
                                "spec_path": r.spec_file,
                                "section_id": r.section_id,
                                "pr_number": pr_number,
                                "confidence": r.status.value,
                            },
                            groups={"organization": owner},
                        )

            # Store realizations and log event (best-effort)
            if result.realizations:
                agent_store = _get_agent_store()
                if agent_store is not None:
                    full_repo = f"{owner}/{repo}"
                    try:
                        for r in result.realizations:
                            await agent_store.upsert_realization(
                                full_repo,
                                r.spec_file,
                                r.section_id,
                                r.ac_text,
                                status=r.status.value,
                                pr_number=pr_number,
                                pr_url=pr["html_url"],
                                evidence_files=r.evidence_files,
                            )
                        await agent_store.log_event(
                            full_repo,
                            "pr_comment",
                            pr_number=pr_number,
                            actor="canon[bot]",
                            detail={
                                "realizations": len(result.realizations),
                                "discrepancies": len(result.discrepancies),
                            },
                        )
                    except Exception:
                        logger.warning("%s — failed to store realizations", tag, exc_info=True)

            # Persist the full review (best-effort)
            pr_review_store = _get_pr_review_store()
            if pr_review_store is not None:
                try:
                    from ..agent.analyzer import estimate_cost

                    cost_str = estimate_cost(
                        result.tokens_used.input,
                        result.tokens_used.output,
                        DEFAULT_AGENT_CONFIG.model,
                    )
                    await pr_review_store.upsert_review(
                        org=owner,
                        repo=f"{owner}/{repo}",
                        pr_number=pr_number,
                        pr_url=pr["html_url"],
                        pr_title=pr["title"],
                        pr_author=pr["user"]["login"],
                        head_sha=pr["head"]["sha"],
                        base_ref=pr["base"]["ref"],
                        analysis=result.model_dump(mode="json"),
                        model=DEFAULT_AGENT_CONFIG.model,
                        tokens_in=result.tokens_used.input,
                        tokens_out=result.tokens_used.output,
                        cost_estimate=float(cost_str),
                    )
                except Exception:
                    logger.warning("%s — failed to store PR review", tag, exc_info=True)
        else:
            spec_list_md = "\n".join(f"- `{s['file_path']}`" for s in specs_data)
            await client.upsert_bot_comment(
                owner,
                repo,
                pr_number,
                f"<!-- canon-bot -->\n## Canon\n\nFound {len(specs_data)} spec(s) in this repo:\n\n{spec_list_md}\n\n_Agent analysis unavailable — set ANTHROPIC_API_KEY to enable AI-powered spec analysis._",
            )
            logger.info("%s — agent unavailable, posted fallback", tag)

    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        logger.error("%s — error: %s", tag, err_msg)

        try:
            await client.create_comment(
                owner,
                repo,
                pr_number,
                f"{client.BOT_MARKER}\n<!-- canon-bot -->\n## Canon\n\n_Agent analysis encountered an error. Will retry on next update._\n\n<sub>Error: {err_msg}</sub>",
            )
        except Exception:
            logger.error("%s — failed to post error comment", tag)
