"""STDIO entry point for local MCP server.

Usage: python -m canon.mcp

For Claude Code: claude mcp add canon -- uv run python -m canon.mcp
"""

from __future__ import annotations

import asyncio
import logging
import sys

from ..settings import Settings
from .deps import McpDeps
from .server import create_mcp_server

logger = logging.getLogger(__name__)


async def _run() -> None:
    settings = Settings()

    # Logging to stderr — STDIO transport uses stdout for JSON-RPC
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    pool = None
    search_index = None
    embed_client = None
    github_client = None

    try:
        # Optional DB pool + search index
        if settings.database_url:
            try:
                from ..db import create_pool
                from ..search.index import SearchIndex

                pool = await create_pool(settings.database_url)
                search_index = SearchIndex(pool)
                logger.info("Search index initialised")
            except Exception:
                logger.warning("Failed to connect to database", exc_info=True)

        # Optional embedding client
        try:
            from ..search.embed import EmbeddingClient

            embed_client = EmbeddingClient(
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
                service_account_key=settings.gcp_service_account_key,
            )
            if embed_client.is_available:
                logger.info("Embedding client initialised")
        except Exception:
            logger.warning("Failed to initialise embedding client", exc_info=True)

        # Optional GitHub client
        if settings.gh_app_id and settings.gh_private_key:
            try:
                from ..github.client import GitHubClient

                github_client = GitHubClient(
                    app_id=settings.gh_app_id,
                    private_key=settings.gh_private_key,
                    installation_id=settings.gh_installation_id,
                )
                logger.info("GitHub client initialised")
            except Exception:
                logger.warning("Failed to initialise GitHub client", exc_info=True)

        # Optional agent store (for coverage metrics)
        agent_store = None
        if pool is not None:
            try:
                from ..db.agent_store import AgentStore

                agent_store = AgentStore(pool)
                logger.info("Agent store initialised")
            except Exception:
                logger.warning("Failed to initialise agent store", exc_info=True)

        deps = McpDeps(
            search_index=search_index,
            embed_client=embed_client,
            github_client=github_client,
            settings=settings,
            agent_store=agent_store,
        )

        mcp = create_mcp_server(deps)
        logger.info("Starting MCP server (STDIO transport)")
        await mcp.run_stdio_async()

    finally:
        if github_client is not None:
            await github_client.close()
        if pool is not None:
            from ..db import close_pool

            await close_pool(pool)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
