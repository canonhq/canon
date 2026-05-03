"""Content sync engine: GitHub → PostgreSQL.

Keeps the Postgres content cache in sync with GitHub via two modes:

1. **Incremental sync** (push webhook): sync a single spec file after push.
2. **Full reconciliation** (cron): compare all specs against GitHub using the
   Git Trees API, fetch only changed files, delete removed specs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from canon.db.content_cache_store import ContentCacheStore
from canon.github.client import GitHubClient
from canon.github.spec_utils import filter_spec_files
from canon.parser.parse import ParseOptions, parse_spec

logger = logging.getLogger(__name__)

# Maximum concurrent repo syncs during reconciliation.
DEFAULT_CONCURRENCY = 5


@dataclass
class SyncStats:
    """Counters for a sync operation."""

    github_api_calls: int = 0
    specs_synced: int = 0
    specs_deleted: int = 0
    specs_skipped: int = 0
    errors: list[str] = field(default_factory=list)


class ContentSyncEngine:
    """Syncs spec content from GitHub to PostgreSQL."""

    def __init__(
        self,
        store: ContentCacheStore,
        github_client: GitHubClient,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        self._store = store
        self._github = github_client
        self._concurrency = concurrency

    # ------------------------------------------------------------------
    # Incremental sync (single file, called from push webhook)
    # ------------------------------------------------------------------

    async def sync_spec(
        self,
        owner: str,
        repo: str,
        path: str,
        raw_markdown: str,
        *,
        commit_sha: str = "",
        github_etag: str = "",
    ) -> int:
        """Sync a single spec file into Postgres. Returns the document ID."""
        content_hash = hashlib.sha256(raw_markdown.encode()).hexdigest()[:16]
        result = parse_spec(raw_markdown, ParseOptions(file_path=path))
        doc = result.document
        fm = doc.frontmatter

        sections = _flatten_sections_to_dicts(doc.sections)

        doc_id = await self._store.upsert_spec(
            repo=f"{owner}/{repo}",
            path=path,
            raw_markdown=raw_markdown,
            title=fm.title,
            status=fm.status,
            content_hash=content_hash,
            github_sha=commit_sha,
            github_etag=github_etag,
            doc_type=fm.doc_type,
            sections=sections,
        )

        return doc_id

    # ------------------------------------------------------------------
    # Config sync
    # ------------------------------------------------------------------

    async def sync_config(
        self,
        owner: str,
        repo: str,
        installation_id: int,
    ) -> None:
        """Fetch and cache CANON.yaml for a repo."""
        try:
            config_raw, _ = await self._github.get_file_content(owner, repo, "CANON.yaml")
        except Exception:
            try:
                config_raw, _ = await self._github.get_file_content(owner, repo, "SPECWRIGHT.yaml")
            except Exception:
                logger.debug("No config file found for %s/%s", owner, repo)
                return

        import yaml

        try:
            parsed = yaml.safe_load(config_raw) or {}
        except Exception:
            logger.warning(
                "Malformed CANON.yaml for %s/%s — skipping config update",
                owner,
                repo,
                exc_info=True,
            )
            return  # Don't overwrite valid config with empty dict

        await self._store.upsert_config(
            owner=owner,
            repo=repo,
            installation_id=installation_id,
            config_yaml=config_raw,
            parsed_config=parsed,
        )

    # ------------------------------------------------------------------
    # Full repo sync (reconciliation)
    # ------------------------------------------------------------------

    async def sync_repo(
        self,
        owner: str,
        repo: str,
        installation_id: int,
        *,
        patterns: list[str] | None = None,
    ) -> SyncStats:
        """Full sync of a repo: compare Git tree against cached content.

        Uses the Git Trees API (single call) to list all files, then fetches
        only changed specs (by comparing SHA against cached github_sha).
        """
        stats = SyncStats()
        repo_key = f"{owner}/{repo}"

        await self._store.upsert_sync_state(owner, repo, installation_id, sync_status="syncing")

        try:
            # 1. Get default branch
            default_branch = await self._github.get_default_branch(owner, repo)
            stats.github_api_calls += 1

            # 2. List all files via Git Trees API (single call)
            tree_data = await self._github._get(
                f"/repos/{owner}/{repo}/git/trees/{default_branch}",
                recursive="true",
            )
            stats.github_api_calls += 1

            all_blobs = {
                item["path"]: item["sha"]
                for item in tree_data.get("tree", [])
                if item.get("type") == "blob"
            }

            # 3. Filter to spec files
            spec_paths = filter_spec_files(list(all_blobs.keys()), patterns=patterns)
            github_specs = {p: all_blobs[p] for p in spec_paths}

            # 4. Get currently cached specs
            cached_specs = await self._store.list_specs(repo_key)
            cached_by_path = {s["path"]: s for s in cached_specs}

            # 5. Determine what changed
            to_fetch: list[str] = []
            for path, sha in github_specs.items():
                cached = cached_by_path.get(path)
                if not cached or cached.get("github_sha") != sha:
                    to_fetch.append(path)
                else:
                    stats.specs_skipped += 1

            # 6. Determine what was deleted
            github_path_set = set(github_specs.keys())
            to_delete = [s["path"] for s in cached_specs if s["path"] not in github_path_set]

            # 7. Fetch changed specs
            for path in to_fetch:
                try:
                    content, file_sha = await self._github.get_file_content(
                        owner, repo, path, ref=default_branch
                    )
                    stats.github_api_calls += 1
                    await self.sync_spec(
                        owner,
                        repo,
                        path,
                        content,
                        commit_sha=file_sha,
                    )
                    stats.specs_synced += 1
                except Exception as exc:
                    msg = f"Failed to sync {repo_key}/{path}: {exc}"
                    logger.warning(msg)
                    stats.errors.append(msg)

            # 8. Delete removed specs
            for path in to_delete:
                await self._store.delete_spec(repo_key, path)
                stats.specs_deleted += 1

            # 9. Sync config
            try:
                await self.sync_config(owner, repo, installation_id)
                stats.github_api_calls += 1  # At least one call for config
            except Exception as exc:
                logger.debug("Config sync failed for %s/%s: %s", owner, repo, exc)

            # 10. Update sync state
            await self._store.upsert_sync_state(
                owner,
                repo,
                installation_id,
                sync_status="synced",
                spec_count=len(github_specs),
                default_branch=default_branch,
                last_full_sync_at=datetime.now(UTC),
            )

        except Exception as exc:
            msg = f"Repo sync failed for {repo_key}: {exc}"
            logger.error(msg)
            stats.errors.append(msg)
            await self._store.upsert_sync_state(
                owner,
                repo,
                installation_id,
                sync_status="error",
                error_detail=str(exc),
            )

        logger.info(
            "Sync %s/%s: %d synced, %d skipped, %d deleted, %d API calls, %d errors",
            owner,
            repo,
            stats.specs_synced,
            stats.specs_skipped,
            stats.specs_deleted,
            stats.github_api_calls,
            len(stats.errors),
        )
        return stats

    # ------------------------------------------------------------------
    # Reconcile all repos for given installations
    # ------------------------------------------------------------------

    async def reconcile_all(
        self,
        installations: list[dict],
    ) -> SyncStats:
        """Reconcile all repos across all installations.

        Each installation dict must have 'id' and 'repos' (list of
        {owner, name} dicts), or we'll list repos from GitHub.
        """
        total_stats = SyncStats()
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _sync_one(
            owner: str, repo: str, installation_id: int, gh_client: object
        ) -> SyncStats:
            async with semaphore:
                # Use per-installation client for correct auth
                engine = ContentSyncEngine(self._store, gh_client)
                return await engine.sync_repo(owner, repo, installation_id)

        tasks = []
        for inst in installations:
            installation_id = inst["id"]
            repos = inst.get("repos", [])

            # Create a per-installation GitHub client
            inst_client = self._github.for_installation(str(installation_id))

            if not repos:
                # List repos from GitHub
                try:
                    repo_list = await inst_client.list_installation_repos()
                    total_stats.github_api_calls += 1
                    repos = [{"owner": r["owner"]["login"], "name": r["name"]} for r in repo_list]
                except Exception as exc:
                    logger.error(
                        "Failed to list repos for installation %s: %s",
                        installation_id,
                        exc,
                    )
                    total_stats.errors.append(str(exc))
                    continue

            for r in repos:
                tasks.append(_sync_one(r["owner"], r["name"], installation_id, inst_client))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, SyncStats):
                total_stats.github_api_calls += result.github_api_calls
                total_stats.specs_synced += result.specs_synced
                total_stats.specs_deleted += result.specs_deleted
                total_stats.specs_skipped += result.specs_skipped
                total_stats.errors.extend(result.errors)
            elif isinstance(result, Exception):
                total_stats.errors.append(str(result))

        logger.info(
            "Reconciliation complete: %d synced, %d skipped, %d deleted, %d API calls, %d errors",
            total_stats.specs_synced,
            total_stats.specs_skipped,
            total_stats.specs_deleted,
            total_stats.github_api_calls,
            len(total_stats.errors),
        )
        return total_stats


def _flatten_sections_to_dicts(sections: list) -> list[dict]:
    """Flatten nested SpecSections into dicts for ContentCacheStore."""
    result = []
    for sec in sections:
        result.append(
            {
                "heading": sec.title,
                "level": sec.depth,
                "body": sec.content,
                "status": sec.status.value if hasattr(sec.status, "value") else str(sec.status),
                "ticket_ref": sec.ticket_link.ticket_id if sec.ticket_link else "",
                "raw_content": sec.content,
            }
        )
        if sec.children:
            result.extend(_flatten_sections_to_dicts(sec.children))
    return result
