"""Tests for the background indexing engine."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

from canon.search.background import BackgroundIndexer, IndexTask


class TestIndexTask:
    def test_defaults(self):
        task = IndexTask(task_id="abc", installation_id=1, org_login="org")
        assert task.status == "pending"
        assert task.repos_total == 0
        assert task.repos_done == 0
        assert task.specs_indexed == 0


class TestBackgroundIndexer:
    async def test_schedule_org_index_returns_task_id(self):
        indexer = BackgroundIndexer()
        client = AsyncMock()
        client.list_installation_repos = AsyncMock(return_value=[])
        search_index = AsyncMock()

        task_id = indexer.schedule_org_index(
            installation_id=123,
            org_login="test-org",
            client=client,
            search_index=search_index,
        )

        assert isinstance(task_id, str)
        assert len(task_id) > 0

    async def test_get_tasks_returns_scheduled(self):
        indexer = BackgroundIndexer()
        client = AsyncMock()
        client.list_installation_repos = AsyncMock(return_value=[])
        search_index = AsyncMock()

        indexer.schedule_org_index(
            installation_id=123,
            org_login="test-org",
            client=client,
            search_index=search_index,
        )

        tasks = indexer.get_tasks()
        assert len(tasks) == 1
        assert tasks[0].org_login == "test-org"

    async def test_get_task_by_id(self):
        indexer = BackgroundIndexer()
        client = AsyncMock()
        client.list_installation_repos = AsyncMock(return_value=[])
        search_index = AsyncMock()

        task_id = indexer.schedule_org_index(
            installation_id=123,
            org_login="test-org",
            client=client,
            search_index=search_index,
        )

        task = indexer.get_task(task_id)
        assert task is not None
        assert task.task_id == task_id

    async def test_get_nonexistent_task(self):
        indexer = BackgroundIndexer()
        assert indexer.get_task("nonexistent") is None

    async def test_schedule_repos_index(self):
        indexer = BackgroundIndexer()
        client = AsyncMock()
        search_index = AsyncMock()

        task_id = indexer.schedule_repos_index(
            installation_id=123,
            org_login="test-org",
            repos=["org/repo1", "org/repo2"],
            client=client,
            search_index=search_index,
        )

        task = indexer.get_task(task_id)
        assert task is not None
        assert task.repos_total == 2


class TestBackgroundIndexerRunOrg:
    async def test_completes_with_no_repos(self):
        indexer = BackgroundIndexer()
        client = AsyncMock()
        client.list_installation_repos = AsyncMock(return_value=[])
        search_index = AsyncMock()
        registry = AsyncMock()

        task_id = indexer.schedule_org_index(
            installation_id=123,
            org_login="test-org",
            client=client,
            search_index=search_index,
            registry=registry,
        )

        # Wait for the async task to complete
        await asyncio.sleep(0.2)

        task = indexer.get_task(task_id)
        assert task.status == "completed"
        assert task.repos_done == 0

    async def test_handles_list_repos_failure(self):
        indexer = BackgroundIndexer()
        client = AsyncMock()
        client.list_installation_repos = AsyncMock(side_effect=Exception("API error"))
        search_index = AsyncMock()

        task_id = indexer.schedule_org_index(
            installation_id=123,
            org_login="test-org",
            client=client,
            search_index=search_index,
        )

        await asyncio.sleep(0.2)

        task = indexer.get_task(task_id)
        assert task.status == "failed"
        assert "API error" in task.error_message


class TestPruneOldTasks:
    async def test_prunes_old_completed_tasks(self):
        indexer = BackgroundIndexer()

        # Create a fake completed task with old timestamp
        old_task = IndexTask(
            task_id="old",
            installation_id=1,
            org_login="org",
            status="completed",
            completed_at=1.0,  # Very old
        )
        indexer._tasks["old"] = old_task

        # Trigger prune by scheduling something new
        client = AsyncMock()
        client.list_installation_repos = AsyncMock(return_value=[])
        search_index = AsyncMock()

        indexer.schedule_org_index(
            installation_id=2,
            org_login="org2",
            client=client,
            search_index=search_index,
        )

        assert "old" not in indexer._tasks

    async def test_keeps_recent_completed_tasks(self):
        indexer = BackgroundIndexer()

        recent_task = IndexTask(
            task_id="recent",
            installation_id=1,
            org_login="org",
            status="completed",
            completed_at=time.time(),  # Just now
        )
        indexer._tasks["recent"] = recent_task

        client = AsyncMock()
        client.list_installation_repos = AsyncMock(return_value=[])
        search_index = AsyncMock()

        indexer.schedule_org_index(
            installation_id=2,
            org_login="org2",
            client=client,
            search_index=search_index,
        )

        assert "recent" in indexer._tasks
