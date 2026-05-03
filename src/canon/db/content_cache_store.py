"""Data access layer for the spec content cache.

Provides read/write access to cached spec content (raw markdown, parsed
sections) and per-repo sync state, eliminating the need to fetch specs
from GitHub on every dashboard/MCP/cron request.
"""

from __future__ import annotations

import json
import logging

import asyncpg

logger = logging.getLogger(__name__)


class ContentCacheStore:
    """Data access for spec_documents (content), repo_configs, and repo_sync_state."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # spec_documents + spec_sections (content cache)
    # ------------------------------------------------------------------

    async def upsert_spec(
        self,
        repo: str,
        path: str,
        raw_markdown: str,
        *,
        title: str = "",
        status: str = "",
        content_hash: str = "",
        github_sha: str = "",
        github_etag: str = "",
        doc_type: str = "spec",
        sections: list[dict] | None = None,
    ) -> int:
        """Insert or update a spec document with raw markdown and sections.

        Returns the document ID.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                    INSERT INTO spec_documents
                        (repo, path, title, status, content_hash, doc_type,
                         raw_markdown, github_sha, github_etag, synced_at, indexed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now(), now())
                    ON CONFLICT (repo, path) DO UPDATE SET
                        title = EXCLUDED.title,
                        status = EXCLUDED.status,
                        content_hash = EXCLUDED.content_hash,
                        doc_type = EXCLUDED.doc_type,
                        raw_markdown = EXCLUDED.raw_markdown,
                        github_sha = EXCLUDED.github_sha,
                        github_etag = EXCLUDED.github_etag,
                        synced_at = now(),
                        indexed_at = now()
                    RETURNING id
                    """,
                repo,
                path,
                title,
                status,
                content_hash,
                doc_type,
                raw_markdown,
                github_sha,
                github_etag,
            )
            doc_id = row["id"]

            if sections is not None:
                # Replace all sections atomically within the transaction
                await conn.execute("DELETE FROM spec_sections WHERE document_id = $1", doc_id)
                for sec in sections:
                    await conn.execute(
                        """
                            INSERT INTO spec_sections
                                (document_id, heading, level, body, status, ticket_ref,
                                 raw_content, indexed_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                            """,
                        doc_id,
                        sec.get("heading", ""),
                        sec.get("level", 1),
                        sec.get("body", ""),
                        sec.get("status", ""),
                        sec.get("ticket_ref", ""),
                        sec.get("raw_content", ""),
                    )

        return doc_id

    async def get_spec(self, repo: str, path: str) -> dict | None:
        """Get a spec document with metadata (no sections)."""
        row = await self._pool.fetchrow(
            """
            SELECT id, repo, path, title, status, content_hash, doc_type,
                   raw_markdown, github_sha, github_etag, synced_at, indexed_at
            FROM spec_documents
            WHERE repo = $1 AND path = $2
            """,
            repo,
            path,
        )
        return dict(row) if row else None

    async def get_spec_raw(self, repo: str, path: str) -> str | None:
        """Get raw markdown for a spec. Returns None on cache miss."""
        row = await self._pool.fetchrow(
            "SELECT raw_markdown FROM spec_documents WHERE repo = $1 AND path = $2",
            repo,
            path,
        )
        if row and row["raw_markdown"]:
            return row["raw_markdown"]
        return None

    async def list_specs(self, repo: str) -> list[dict]:
        """List spec metadata for a repo (no raw content — efficient for listings)."""
        rows = await self._pool.fetch(
            """
            SELECT id, path, title, status, doc_type, synced_at,
                   github_sha, content_hash
            FROM spec_documents
            WHERE repo = $1 AND raw_markdown IS NOT NULL
            ORDER BY path
            """,
            repo,
        )
        return [dict(r) for r in rows]

    async def list_specs_with_content(self, repo: str) -> list[dict]:
        """List specs with raw markdown included — single query, no N+1."""
        rows = await self._pool.fetch(
            """
            SELECT id, path, title, status, doc_type, synced_at,
                   github_sha, content_hash, raw_markdown
            FROM spec_documents
            WHERE repo = $1 AND raw_markdown IS NOT NULL
            ORDER BY path
            """,
            repo,
        )
        return [dict(r) for r in rows]

    async def list_all_spec_hashes(self) -> list[dict]:
        """Return ``[{repo, path, content_hash}]`` for every cached spec.

        Used by the OpenSearch reconcile cron to diff against the search index.
        """
        rows = await self._pool.fetch(
            """
            SELECT repo, path, content_hash
            FROM spec_documents
            WHERE raw_markdown IS NOT NULL
            ORDER BY repo, path
            """
        )
        return [dict(r) for r in rows]

    async def list_specs_for_org(self, installation_id: int) -> list[dict]:
        """List all specs for an org grouped by repo.

        Joins repo_sync_state to get repos for this installation, then
        fetches spec metadata for each.
        """
        rows = await self._pool.fetch(
            """
            SELECT sd.id, sd.repo, sd.path, sd.title, sd.status,
                   sd.doc_type, sd.synced_at, sd.content_hash
            FROM spec_documents sd
            WHERE sd.repo = ANY(
                SELECT rss.owner || '/' || rss.repo
                FROM repo_sync_state rss
                WHERE rss.installation_id = $1
            )
            ORDER BY sd.repo, sd.path
            """,
            installation_id,
        )
        return [dict(r) for r in rows]

    async def delete_spec(self, repo: str, path: str) -> None:
        """Delete a spec and its cascaded sections."""
        await self._pool.execute(
            "DELETE FROM spec_documents WHERE repo = $1 AND path = $2",
            repo,
            path,
        )

    async def delete_repo_specs(self, repo: str) -> None:
        """Delete all specs for a repo."""
        await self._pool.execute("DELETE FROM spec_documents WHERE repo = $1", repo)

    async def get_section(self, repo: str, path: str, heading: str) -> dict | None:
        """Get a single section by spec path and heading."""
        row = await self._pool.fetchrow(
            """
            SELECT ss.id, ss.heading, ss.level, ss.body, ss.status,
                   ss.ticket_ref, ss.raw_content
            FROM spec_sections ss
            JOIN spec_documents sd ON ss.document_id = sd.id
            WHERE sd.repo = $1 AND sd.path = $2 AND ss.heading = $3
            """,
            repo,
            path,
            heading,
        )
        return dict(row) if row else None

    async def get_sections(self, repo: str, path: str) -> list[dict]:
        """Get all sections for a spec."""
        rows = await self._pool.fetch(
            """
            SELECT ss.id, ss.heading, ss.level, ss.body, ss.status,
                   ss.ticket_ref, ss.raw_content
            FROM spec_sections ss
            JOIN spec_documents sd ON ss.document_id = sd.id
            WHERE sd.repo = $1 AND sd.path = $2
            ORDER BY ss.id
            """,
            repo,
            path,
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # repo_configs (cached CANON.yaml)
    # ------------------------------------------------------------------

    async def upsert_config(
        self,
        owner: str,
        repo: str,
        installation_id: int,
        config_yaml: str,
        parsed_config: dict,
        *,
        github_etag: str = "",
    ) -> None:
        """Insert or update cached CANON.yaml for a repo."""
        await self._pool.execute(
            """
            INSERT INTO repo_configs
                (installation_id, owner, repo, config_yaml, parsed_config,
                 github_etag, synced_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, now())
            ON CONFLICT (owner, repo) DO UPDATE SET
                installation_id = EXCLUDED.installation_id,
                config_yaml = EXCLUDED.config_yaml,
                parsed_config = EXCLUDED.parsed_config,
                github_etag = EXCLUDED.github_etag,
                synced_at = now()
            """,
            installation_id,
            owner,
            repo,
            config_yaml,
            json.dumps(parsed_config),
            github_etag,
        )

    async def get_config(self, owner: str, repo: str) -> dict | None:
        """Get cached CANON.yaml config for a repo."""
        row = await self._pool.fetchrow(
            """
            SELECT id, installation_id, owner, repo, config_yaml,
                   parsed_config, github_etag, synced_at
            FROM repo_configs
            WHERE owner = $1 AND repo = $2
            """,
            owner,
            repo,
        )
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # repo_sync_state
    # ------------------------------------------------------------------

    async def upsert_sync_state(
        self,
        owner: str,
        repo: str,
        installation_id: int,
        **fields: object,
    ) -> None:
        """Insert or update sync state for a repo.

        Accepts keyword arguments for any repo_sync_state column:
        default_branch, last_full_sync_at, last_push_sync_at,
        spec_count, sync_status, error_detail.
        """
        # Build SET clause from provided fields
        allowed = {
            "default_branch",
            "last_full_sync_at",
            "last_push_sync_at",
            "spec_count",
            "sync_status",
            "error_detail",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}

        for col in updates:
            if not col.isidentifier():
                raise ValueError(f"Invalid column name: {col}")

        if not updates:
            # Just ensure the row exists
            await self._pool.execute(
                """
                INSERT INTO repo_sync_state (installation_id, owner, repo)
                VALUES ($1, $2, $3)
                ON CONFLICT (owner, repo) DO NOTHING
                """,
                installation_id,
                owner,
                repo,
            )
            return

        # Build dynamic UPDATE SET clause
        set_parts = ["installation_id = EXCLUDED.installation_id"]
        # Base params: installation_id, owner, repo
        params: list[object] = [installation_id, owner, repo]
        idx = 4

        for col, val in updates.items():
            set_parts.append(f"{col} = ${idx}")
            params.append(val)
            idx += 1

        set_clause = ", ".join(set_parts)

        # Build INSERT column/value lists for the update fields
        extra_cols = ", ".join(updates.keys())
        extra_placeholders = ", ".join(f"${i}" for i in range(4, idx))

        await self._pool.execute(
            f"""
            INSERT INTO repo_sync_state
                (installation_id, owner, repo, {extra_cols})
            VALUES ($1, $2, $3, {extra_placeholders})
            ON CONFLICT (owner, repo) DO UPDATE SET {set_clause}
            """,
            *params,
        )

    async def get_sync_state(self, owner: str, repo: str) -> dict | None:
        """Get sync state for a repo."""
        row = await self._pool.fetchrow(
            """
            SELECT id, installation_id, owner, repo, default_branch,
                   last_full_sync_at, last_push_sync_at, spec_count,
                   sync_status, error_detail
            FROM repo_sync_state
            WHERE owner = $1 AND repo = $2
            """,
            owner,
            repo,
        )
        return dict(row) if row else None

    async def list_sync_states(self, installation_id: int) -> list[dict]:
        """List all sync states for an installation."""
        rows = await self._pool.fetch(
            """
            SELECT id, installation_id, owner, repo, default_branch,
                   last_full_sync_at, last_push_sync_at, spec_count,
                   sync_status, error_detail
            FROM repo_sync_state
            WHERE installation_id = $1
            ORDER BY owner, repo
            """,
            installation_id,
        )
        return [dict(r) for r in rows]

    async def get_stale_repos(self, max_age_hours: int = 2) -> list[dict]:
        """Get repos where last_full_sync_at is older than the threshold."""
        rows = await self._pool.fetch(
            """
            SELECT owner, repo, installation_id, last_full_sync_at, sync_status
            FROM repo_sync_state
            WHERE last_full_sync_at IS NULL
               OR last_full_sync_at < now() - make_interval(hours => $1)
            ORDER BY last_full_sync_at NULLS FIRST
            """,
            max_age_hours,
        )
        return [dict(r) for r in rows]
