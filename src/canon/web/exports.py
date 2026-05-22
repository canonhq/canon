"""User data export (§8.1 of docs/specs/profile-account-management.md).

This module ships ``UserExportJob.collect`` — the pure-DB half of the
"export my data" flow. The S3 upload, email dispatch, and cleanup cron
land with the follow-up infra PR that provisions the
``canon-user-exports`` Spaces bucket. See ``settings.user_exports_bucket``
for the gate the route uses to keep the public endpoint off until then.

``collect`` returns a dict that round-trips through ``json.dumps`` and
back (no datetime/UUID objects make it past the boundary — every value
is converted to a JSON-native type here so callers don't need their own
serializer).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """Convert asyncpg-native values to JSON-serializable ones.

    asyncpg returns Postgres TIMESTAMPTZ as ``datetime``, UUID as
    ``uuid.UUID``, and JSONB as already-parsed Python dicts/lists.
    ``json.dumps`` chokes on the first two; this helper handles both
    plus the common collection types recursively.
    """
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    # Fallback — repr is lossy but never raises. We log so an unexpected
    # type doesn't silently end up as a Python-repr string in the export.
    logger.warning("export collect: falling back to str() for %s", type(value).__name__)
    return str(value)


def _rows_to_json(rows: list) -> list[dict]:
    """asyncpg.Record sequence → list of JSON-safe dicts."""
    return [{k: _json_safe(v) for k, v in dict(row).items()} for row in rows]


class UserExportJob:
    """Collects a user's data across the user-scoped tables.

    Today this exposes only ``collect`` — the upload and email steps land
    in the follow-up infra PR. Tests for ``collect`` exercise the SQL
    against mocked connections + the JSON-roundtrip invariant.

    Designed to take an ``asyncpg.Pool``-like object so the existing
    ``app.state.db_pool`` slots in directly. The pool only needs to
    expose ``acquire()`` as an async context manager returning a
    connection with ``fetch``/``fetchrow``.
    """

    # Tables to include in the export bundle. Each entry is
    # (key in the bundle, SQL, list of $1-style params).
    #
    # realization_evidence is intentionally NOT in this list. The 0001
    # baseline schema has no per-user authorship column on that table —
    # it's keyed by (repo, spec_path, section_id, ac_text, pr_number).
    # Including it here would require either a schema addition (deferred)
    # or a heuristic match (the PR-author claim, which is GitHub-side
    # data we don't always have). For now the export omits it; a future
    # migration that adds an authorship column can extend collect()
    # without changing the bundle shape for the other tables.
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def collect(self, user_id: int, org_login: str) -> dict:
        """Return a JSON-roundtrip-safe dict of all user-scoped rows.

        ``user_id`` is the ``users.id`` PK (not the OIDC sub). ``org_login``
        scopes the audit-events query to the org the request came from so
        a multi-org user doesn't pull rows authored under a different org's
        context.

        Bundle shape (keys stable across schema additions):

        - ``schema_version``: bump when the bundle layout changes
        - ``exported_at``: ISO-8601 UTC timestamp
        - ``user_id``: the queried user PK (echo for traceability)
        - ``users``: single-row dict (or None if the user vanished mid-export)
        - ``sessions``: list of session rows (refresh_hash redacted)
        - ``api_keys``: list of api-key rows (key_hash kept, never the raw key)
        - ``user_preferences``: list (one row per (user, org) pair)
        - ``audit_events``: rows where the user was the actor
        """
        async with self._pool.acquire() as conn:
            user_row = await conn.fetchrow(
                """
                SELECT id, oidc_sub, email, name, picture, role, status,
                       created_at, last_login_at
                FROM users
                WHERE id = $1
                """,
                user_id,
            )
            sessions = await conn.fetch(
                """
                SELECT id, org_login, device_label, created_at, last_used_at,
                       expires_at, revoked_at
                FROM sessions
                WHERE user_id = $1
                ORDER BY created_at DESC
                """,
                user_id,
            )
            api_keys = await conn.fetch(
                """
                SELECT id, key_hash, label, org_login, scopes,
                       created_at, expires_at, revoked_at, last_used_at
                FROM api_keys
                WHERE user_id = $1
                ORDER BY created_at DESC
                """,
                user_id,
            )
            user_preferences = await conn.fetch(
                """
                SELECT user_id, org_login, slack_dm_enabled, slack_dm_pr_comments,
                       slack_dm_spec_drift, email_digest_cadence, email_pr_comments,
                       theme, timezone, relative_time
                FROM user_preferences
                WHERE user_id = $1
                """,
                user_id,
            )
            audit_events = await conn.fetch(
                """
                SELECT id, created_at, org, event_type, resource_type, resource_id,
                       detail, ip_address::text AS ip_address
                FROM audit_events
                WHERE actor_id = $1
                  AND ($2 = '' OR org = $2)
                ORDER BY created_at DESC
                """,
                user_id,
                org_login or "",
            )

        return {
            "schema_version": 1,
            "exported_at": datetime.now(UTC).isoformat(),
            "user_id": user_id,
            "users": ({k: _json_safe(v) for k, v in dict(user_row).items()} if user_row else None),
            "sessions": _rows_to_json(sessions),
            "api_keys": _rows_to_json(api_keys),
            "user_preferences": _rows_to_json(user_preferences),
            "audit_events": _rows_to_json(audit_events),
        }
