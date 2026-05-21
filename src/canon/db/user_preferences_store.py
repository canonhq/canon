"""Data access layer for per-(user, org) notification + appearance preferences.

See docs/specs/profile-account-management.md §5 (notifications) and §7
(appearance/locale). Rows are auto-created with defaults on first read so
callers never have to deal with a missing-prefs state.
"""

from __future__ import annotations

import asyncpg

#: Columns that callers may patch via ``update()``. Anything outside this set
#: is rejected with ValueError to keep the dynamic SQL builder safe from
#: arbitrary column names. Keep this in sync with the spec § 5 schema.
ALLOWED_PREFERENCE_COLUMNS: frozenset[str] = frozenset(
    {
        "slack_dm_enabled",
        "slack_dm_pr_comments",
        "slack_dm_spec_drift",
        "email_digest_cadence",
        "email_pr_comments",
        "theme",
        "timezone",
        "relative_time",
    }
)


class UserPreferencesStore:
    """CRUD for the ``user_preferences`` table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, *, user_id: int, org_login: str) -> dict:
        """Return the user's preferences for this org, creating defaults if missing."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM user_preferences
                WHERE user_id = $1 AND org_login = $2
                """,
                user_id,
                org_login,
            )
            if row is not None:
                return dict(row)
            # Lazy-create default row. ON CONFLICT DO UPDATE (instead of DO NOTHING)
            # so RETURNING always yields a row when two concurrent reads both miss.
            row = await conn.fetchrow(
                """
                INSERT INTO user_preferences (user_id, org_login)
                VALUES ($1, $2)
                ON CONFLICT (user_id, org_login) DO UPDATE
                    SET updated_at = user_preferences.updated_at
                RETURNING *
                """,
                user_id,
                org_login,
            )
        return dict(row) if row else {}

    async def update(self, *, user_id: int, org_login: str, patch: dict) -> dict:
        """Patch one or more preference fields; returns the resulting row."""
        # Validate up front so a bad key never reaches SQL construction.
        bad = [k for k in patch if k not in ALLOWED_PREFERENCE_COLUMNS]
        if bad:
            raise ValueError(f"Unknown preference column(s): {', '.join(bad)}")

        # Always ensure the row exists (lazy default creation).
        current = await self.get(user_id=user_id, org_login=org_login)
        if not patch:
            return current

        set_clauses: list[str] = []
        values: list[object] = []
        # Column names are interpolated directly; the allow-list check above
        # is the only thing keeping this injection-safe — don't loosen it.
        for idx, (col, val) in enumerate(patch.items(), start=1):
            set_clauses.append(f"{col} = ${idx}")
            values.append(val)
        # updated_at always bumps
        set_clauses.append("updated_at = now()")
        # WHERE params come after the SET params
        values.append(user_id)
        values.append(org_login)
        user_id_placeholder = len(values) - 1
        org_login_placeholder = len(values)

        sql = (
            "UPDATE user_preferences SET "
            + ", ".join(set_clauses)
            + f" WHERE user_id = ${user_id_placeholder}"
            + f" AND org_login = ${org_login_placeholder}"
            + " RETURNING *"
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *values)
        return dict(row) if row else current
