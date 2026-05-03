"""Background indexing engine — uses asyncio tasks (no Celery/Redis dependency)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Rate limit: pause between repo indexing operations
INTER_REPO_DELAY = 0.5

# Prune completed tasks older than this (seconds)
TASK_PRUNE_AGE = 3600


@dataclass
class IndexTask:
    """Tracks a background indexing operation."""

    task_id: str
    installation_id: int
    org_login: str
    status: str = "pending"  # pending, running, completed, failed
    repos_total: int = 0
    repos_done: int = 0
    specs_indexed: int = 0
    errors: int = 0
    started_at: float = 0.0
    completed_at: float = 0.0
    error_message: str = ""


class BackgroundIndexer:
    """Manages background indexing tasks via asyncio.create_task."""

    def __init__(self) -> None:
        self._tasks: dict[str, IndexTask] = {}
        self._asyncio_tasks: dict[str, asyncio.Task] = {}

    def schedule_org_index(
        self,
        *,
        installation_id: int,
        org_login: str,
        client,
        search_index,
        embed_client=None,
        registry=None,
        content_cache_store=None,
        opensearch_client=None,
    ) -> str:
        """Schedule a full org index. Returns the task_id."""
        self._prune_old_tasks()
        task_id = str(uuid.uuid4())[:8]

        idx_task = IndexTask(
            task_id=task_id,
            installation_id=installation_id,
            org_login=org_login,
        )
        self._tasks[task_id] = idx_task

        coro = self._run_org_index(
            idx_task,
            client,
            search_index,
            embed_client,
            registry,
            content_cache_store,
            opensearch_client,
        )
        self._asyncio_tasks[task_id] = asyncio.create_task(coro)

        logger.info("Scheduled org index: task_id=%s org=%s", task_id, org_login)
        return task_id

    def schedule_repos_index(
        self,
        *,
        installation_id: int,
        org_login: str,
        repos: list[str],
        client,
        search_index,
        embed_client=None,
        registry=None,
        opensearch_client=None,
    ) -> str:
        """Schedule indexing for specific repos. Returns the task_id."""
        self._prune_old_tasks()
        task_id = str(uuid.uuid4())[:8]

        idx_task = IndexTask(
            task_id=task_id,
            installation_id=installation_id,
            org_login=org_login,
            repos_total=len(repos),
        )
        self._tasks[task_id] = idx_task

        coro = self._run_repos_index(
            idx_task, repos, client, search_index, embed_client, registry, opensearch_client
        )
        self._asyncio_tasks[task_id] = asyncio.create_task(coro)

        logger.info("Scheduled repos index: task_id=%s repos=%d", task_id, len(repos))
        return task_id

    def get_tasks(self) -> list[IndexTask]:
        """Return all tracked tasks (newest first)."""
        return sorted(
            self._tasks.values(),
            key=lambda t: t.started_at or 0,
            reverse=True,
        )

    def get_task(self, task_id: str) -> IndexTask | None:
        """Return a specific task by ID."""
        return self._tasks.get(task_id)

    async def _run_org_index(
        self,
        task: IndexTask,
        client,
        search_index,
        embed_client,
        registry,
        content_cache_store=None,
        opensearch_client=None,
    ) -> None:
        """Index all repos for an org installation."""
        task.status = "running"
        task.started_at = time.time()

        try:
            repos = await client.list_installation_repos()
            task.repos_total = len(repos)

            if registry:
                await registry.update_last_indexed(task.installation_id, repos_count=len(repos))

            repo_names = [r["full_name"] for r in repos]

            # Bootstrap content cache alongside search indexing
            if content_cache_store is not None:
                try:
                    from ..sync.content_sync import ContentSyncEngine

                    engine = ContentSyncEngine(content_cache_store, client)
                    installations = [
                        {
                            "id": task.installation_id,
                            "repos": [
                                {"owner": r["owner"]["login"], "name": r["name"]} for r in repos
                            ],
                        }
                    ]
                    await engine.reconcile_all(installations)
                    logger.info(
                        "Content cache bootstrapped for org %s (%d repos)",
                        task.org_login,
                        len(repos),
                    )
                except Exception:
                    logger.warning(
                        "Content cache bootstrap failed for org %s",
                        task.org_login,
                        exc_info=True,
                    )

            await self._index_repos(
                task,
                repo_names,
                client,
                search_index,
                embed_client,
                registry,
                opensearch_client,
            )

            task.status = "completed"
        except Exception as exc:
            task.status = "failed"
            task.error_message = str(exc)
            logger.exception("Org index failed: task_id=%s", task.task_id)
        finally:
            task.completed_at = time.time()

    async def _run_repos_index(
        self,
        task: IndexTask,
        repos: list[str],
        client,
        search_index,
        embed_client,
        registry,
        opensearch_client=None,
    ) -> None:
        """Index specific repos."""
        task.status = "running"
        task.started_at = time.time()

        try:
            await self._index_repos(
                task, repos, client, search_index, embed_client, registry, opensearch_client
            )
            task.status = "completed"
        except Exception as exc:
            task.status = "failed"
            task.error_message = str(exc)
            logger.exception("Repos index failed: task_id=%s", task.task_id)
        finally:
            task.completed_at = time.time()

    async def _index_repos(
        self,
        task: IndexTask,
        repo_names: list[str],
        client,
        search_index,
        embed_client,
        registry,
        opensearch_client=None,
    ) -> None:
        """Index a list of repos, updating task progress."""
        from ..config.parse import parse_canon_yaml
        from ..github.spec_utils import load_repo_docs
        from ..search.indexer import index_spec

        for full_name in repo_names:
            parts = full_name.split("/", 1)
            if len(parts) != 2:
                continue
            owner, repo = parts

            job = None
            if registry:
                job = await registry.create_index_job(
                    installation_id=task.installation_id, repo=full_name
                )
                await registry.update_index_job(job.id, status="running")

            specs_count = 0
            errors_count = 0

            try:
                # Load CANON.yaml (or legacy SPECWRIGHT.yaml) for doc_paths config
                doc_patterns = None
                try:
                    try:
                        content, _ = await client.get_file_content(owner, repo, "CANON.yaml")
                    except Exception:
                        content, _ = await client.get_file_content(owner, repo, "SPECWRIGHT.yaml")
                    config_result = parse_canon_yaml(content)
                    doc_patterns = config_result.config.specs.doc_paths
                except Exception:
                    pass  # No config file — use defaults

                docs = await load_repo_docs(client, owner, repo, patterns=doc_patterns)

                for doc_data in docs:
                    try:
                        await index_spec(
                            doc=doc_data["document"],
                            repo=full_name,
                            search_index=search_index,
                            embed_client=embed_client,
                            opensearch_client=opensearch_client,
                        )
                        specs_count += 1
                    except Exception:
                        errors_count += 1
                        logger.warning(
                            "Failed to index %s in %s",
                            doc_data["file_path"],
                            full_name,
                            exc_info=True,
                        )

                if job and registry:
                    await registry.update_index_job(
                        job.id,
                        status="completed",
                        specs_indexed=specs_count,
                        errors=errors_count,
                    )
            except Exception:
                errors_count += 1
                if job and registry:
                    await registry.update_index_job(
                        job.id,
                        status="failed",
                        errors=errors_count,
                        error_message=f"Failed to index repo {full_name}",
                    )
                logger.warning("Failed to index repo %s", full_name, exc_info=True)

            task.repos_done += 1
            task.specs_indexed += specs_count
            task.errors += errors_count

            # Rate limiting
            await asyncio.sleep(INTER_REPO_DELAY)

    def _prune_old_tasks(self) -> None:
        """Remove completed/failed tasks older than TASK_PRUNE_AGE."""
        now = time.time()
        to_remove = [
            tid
            for tid, t in self._tasks.items()
            if t.status in ("completed", "failed")
            and t.completed_at > 0
            and (now - t.completed_at) > TASK_PRUNE_AGE
        ]
        for tid in to_remove:
            del self._tasks[tid]
            self._asyncio_tasks.pop(tid, None)
