"""Database connection pool and schema management."""

from __future__ import annotations

from .agent_store import AgentStore
from .connection_store import UserConnectionStore
from .error_store import ErrorStore
from .integration_store import IntegrationStore
from .pool import close_pool, create_pool
from .registry import InstallationRegistry
from .schema import ensure_schema
from .session_store import SessionStore
from .sync_history_store import SyncHistoryStore
from .user_store import UserStore

__all__ = [
    "AgentStore",
    "ErrorStore",
    "InstallationRegistry",
    "IntegrationStore",
    "SessionStore",
    "SyncHistoryStore",
    "UserConnectionStore",
    "UserStore",
    "close_pool",
    "create_pool",
    "ensure_schema",
]
