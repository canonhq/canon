"""Installation registry — tracks GitHub App installations and indexing jobs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class Installation:
    """A registered GitHub App installation."""

    installation_id: int
    org_login: str
    org_id: int = 0
    app_id: str = ""
    status: str = "active"
    installed_at: datetime | None = None
    last_indexed_at: datetime | None = None
    repos_count: int = 0
    oidc_org_id: str = ""


@dataclass
class IndexJob:
    """A single repo indexing job."""

    id: int = 0
    installation_id: int = 0
    repo: str = ""
    status: str = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    specs_indexed: int = 0
    errors: int = 0
    error_message: str = ""


class InstallationRegistry:
    """Data access layer for the gh_installations and index_jobs tables."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ─── Installations ─────────────────────────────────

    async def upsert_installation(
        self,
        *,
        installation_id: int,
        org_login: str,
        org_id: int = 0,
        app_id: str = "",
    ) -> Installation:
        """Insert or update an installation. Returns the installation record."""
        from canon.auth.middleware import RESERVED_ORG_SLUGS

        if org_login.lower() in RESERVED_ORG_SLUGS:
            raise ValueError(
                f"Org slug {org_login!r} is reserved and cannot be used as an installation org"
            )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO gh_installations (installation_id, org_login, org_id, app_id, status)
                VALUES ($1, $2, $3, $4, 'active')
                ON CONFLICT (installation_id)
                DO UPDATE SET
                    org_login = EXCLUDED.org_login,
                    org_id = EXCLUDED.org_id,
                    app_id = EXCLUDED.app_id,
                    status = 'active'
                RETURNING *
                """,
                installation_id,
                org_login,
                org_id,
                app_id,
            )
        return _row_to_installation(row)

    async def mark_suspended(self, installation_id: int) -> None:
        """Mark an installation as suspended."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE gh_installations SET status = 'suspended' WHERE installation_id = $1",
                installation_id,
            )

    async def mark_removed(self, installation_id: int) -> None:
        """Mark an installation as removed."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE gh_installations SET status = 'removed' WHERE installation_id = $1",
                installation_id,
            )

    async def mark_unsuspended(self, installation_id: int) -> None:
        """Re-activate a suspended installation."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE gh_installations SET status = 'active' WHERE installation_id = $1",
                installation_id,
            )

    async def update_last_indexed(
        self, installation_id: int, *, repos_count: int | None = None
    ) -> None:
        """Update the last_indexed_at timestamp (and optionally repos_count)."""
        if repos_count is not None:
            sql = "UPDATE gh_installations SET last_indexed_at = now(), repos_count = $2 WHERE installation_id = $1"
            args: tuple = (installation_id, repos_count)
        else:
            sql = "UPDATE gh_installations SET last_indexed_at = now() WHERE installation_id = $1"
            args = (installation_id,)

        async with self._pool.acquire() as conn:
            await conn.execute(sql, *args)

    async def get_active_installations(self) -> list[Installation]:
        """Return all active installations."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM gh_installations WHERE status = 'active' ORDER BY org_login"
            )
        return [_row_to_installation(r) for r in rows]

    async def get_installation_by_org(self, org_login: str) -> Installation | None:
        """Look up an active installation by org login."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM gh_installations WHERE org_login = $1 AND status = 'active'",
                org_login,
            )
        return _row_to_installation(row) if row else None

    async def get_installation_by_id(self, installation_id: int) -> Installation | None:
        """Look up an installation by installation_id."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM gh_installations WHERE installation_id = $1",
                installation_id,
            )
        return _row_to_installation(row) if row else None

    async def set_oidc_org_id(self, installation_id: int, oidc_org_id: str) -> None:
        """Link an OIDC Organization to a GitHub installation."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE gh_installations SET oidc_org_id = $2 WHERE installation_id = $1",
                installation_id,
                oidc_org_id,
            )

    async def get_installation_by_oidc_org(self, oidc_org_id: str) -> Installation | None:
        """Look up an active installation by OIDC org ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM gh_installations WHERE oidc_org_id = $1 AND status = 'active'",
                oidc_org_id,
            )
        return _row_to_installation(row) if row else None

    async def list_orgs(self) -> list[str]:
        """Return all org logins with active installations."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT org_login FROM gh_installations WHERE status = 'active' ORDER BY org_login"
            )
        return [r["org_login"] for r in rows]

    async def get_all_installations(self) -> list[Installation]:
        """Return all installations regardless of status."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM gh_installations ORDER BY org_login")
        return [_row_to_installation(r) for r in rows]

    # ─── Index Jobs ────────────────────────────────────

    async def create_index_job(self, *, installation_id: int, repo: str) -> IndexJob:
        """Create a new pending index job."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO index_jobs (installation_id, repo, status)
                VALUES ($1, $2, 'pending')
                RETURNING *
                """,
                installation_id,
                repo,
            )
        return _row_to_index_job(row)

    async def update_index_job(
        self,
        job_id: int,
        *,
        status: str | None = None,
        specs_indexed: int | None = None,
        errors: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update fields on an index job."""
        sets: list[str] = []
        params: list = []
        idx = 1

        if status is not None:
            sets.append(f"status = ${idx}")
            params.append(status)
            idx += 1
            if status == "running":
                sets.append("started_at = now()")
            elif status in ("completed", "failed"):
                sets.append("completed_at = now()")

        if specs_indexed is not None:
            sets.append(f"specs_indexed = ${idx}")
            params.append(specs_indexed)
            idx += 1

        if errors is not None:
            sets.append(f"errors = ${idx}")
            params.append(errors)
            idx += 1

        if error_message is not None:
            sets.append(f"error_message = ${idx}")
            params.append(error_message)
            idx += 1

        if not sets:
            return

        params.append(job_id)
        sql = f"UPDATE index_jobs SET {', '.join(sets)} WHERE id = ${idx}"

        async with self._pool.acquire() as conn:
            await conn.execute(sql, *params)

    async def get_index_jobs(
        self,
        *,
        installation_id: int | None = None,
        limit: int = 50,
    ) -> list[IndexJob]:
        """Get recent index jobs, optionally filtered by installation."""
        if installation_id is not None:
            sql = "SELECT * FROM index_jobs WHERE installation_id = $1 ORDER BY id DESC LIMIT $2"
            args: tuple = (installation_id, limit)
        else:
            sql = "SELECT * FROM index_jobs ORDER BY id DESC LIMIT $1"
            args = (limit,)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [_row_to_index_job(r) for r in rows]


# ─── Row Mappers ────────────────────────────────────────


def _row_to_installation(row: asyncpg.Record) -> Installation:
    return Installation(
        installation_id=row["installation_id"],
        org_login=row["org_login"],
        org_id=row["org_id"],
        app_id=row["app_id"],
        status=row["status"],
        installed_at=row["installed_at"],
        last_indexed_at=row["last_indexed_at"],
        repos_count=row["repos_count"],
        oidc_org_id=row.get("oidc_org_id", ""),
    )


def _row_to_index_job(row: asyncpg.Record) -> IndexJob:
    return IndexJob(
        id=row["id"],
        installation_id=row["installation_id"],
        repo=row["repo"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        specs_indexed=row["specs_indexed"],
        errors=row["errors"],
        error_message=row["error_message"],
    )
