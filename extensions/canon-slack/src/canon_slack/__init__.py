"""Canon Slack extension — interactive bot for spec queries and workflow actions."""

from __future__ import annotations

from .app import create_slack_app
from .commands import invalidate_spec_cache
from .digest import build_digest_blocks
from .identity_store import IdentityStore
from .notifications import NotificationConfig, NotificationDispatcher
from .spec_loader import SpecLoader

__all__ = [
    "IdentityStore",
    "NotificationConfig",
    "NotificationDispatcher",
    "SpecLoader",
    "build_digest_blocks",
    "create_slack_app",
    "invalidate_spec_cache",
]
