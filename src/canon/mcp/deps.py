"""Dependency container for MCP tools — decouples from FastAPI app.state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class McpDeps:
    """Dependencies injected into MCP tool functions.

    Both STDIO and HTTP modes populate the same dataclass,
    just from different sources.
    """

    search_index: Any = None  # SearchIndex | None
    search_backend: Any = None  # SearchBackend | None
    embed_client: Any = None  # EmbeddingClient | None
    github_client: Any = None  # GitHubClient | None
    cache: Any = None  # TTLCache | None
    settings: Any = None  # Settings | None
    agent_store: Any = None  # AgentStore | None
    session_evidence_store: Any = None  # SessionEvidenceStore | None
    content_cache_store: Any = None  # ContentCacheStore | None
