"""Slack integration facade — bridges to the canon-slack extension.

The Slack implementation lives in extensions/canon-slack/src/canon_slack/.
This module re-exports the public API so existing callers (main.py, cron jobs,
GitHub handlers) continue to work with ``from canon.slack import X``.

When the extension is not installed, all symbols are None and SLACK_AVAILABLE
is False. Callers already gate on ``settings.slack_bot_enabled`` so this
degrades gracefully.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure the extension's src/ is on sys.path so ``import canon_slack`` works.
# This supports two layouts:
#   1. Dev: extensions/canon-slack/src/ exists relative to repo root
#   2. Installed: canon_slack is already importable (pip install / symlink)
# ---------------------------------------------------------------------------

_ext_src = Path(__file__).resolve().parents[3] / "extensions" / "canon-slack" / "src"
if _ext_src.is_dir() and str(_ext_src) not in sys.path:
    sys.path.append(str(_ext_src))

# ---------------------------------------------------------------------------
# Try importing from the extension. If unavailable, provide None stubs.
# ---------------------------------------------------------------------------

try:
    from canon_slack import (  # type: ignore[import-untyped]
        IdentityStore,
        NotificationConfig,
        NotificationDispatcher,
        SpecLoader,
        build_digest_blocks,
        create_slack_app,
        invalidate_spec_cache,
    )

    SLACK_AVAILABLE = True
except ImportError:
    logger.debug("canon-slack extension not available — Slack features disabled")
    SLACK_AVAILABLE = False

    # No-op stubs so callers don't crash on import.
    # Functions are callable no-ops; classes are None (callers gate on settings.slack_bot_enabled).
    create_slack_app = lambda *a, **kw: None  # type: ignore[assignment]  # noqa: E731
    IdentityStore = None  # type: ignore[assignment, misc]
    NotificationConfig = None  # type: ignore[assignment, misc]
    NotificationDispatcher = None  # type: ignore[assignment, misc]
    SpecLoader = None  # type: ignore[assignment, misc]
    build_digest_blocks = lambda *a, **kw: []  # type: ignore[assignment]  # noqa: E731
    invalidate_spec_cache = lambda *a, **kw: None  # type: ignore[assignment]  # noqa: E731

__all__ = [
    "SLACK_AVAILABLE",
    "IdentityStore",
    "NotificationConfig",
    "NotificationDispatcher",
    "SpecLoader",
    "build_digest_blocks",
    "create_slack_app",
    "invalidate_spec_cache",
]
