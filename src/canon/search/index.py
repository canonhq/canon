"""Search index: upsert, delete, and hybrid search over spec documents."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single hybrid search result."""

    section_id: int
    document_id: int
    repo: str
    path: str
    doc_title: str
    heading: str
    body: str
    status: str
    rrf_score: float


class SearchIndex:
    """Manages spec documents and sections in PostgreSQL with pgvector + ParadeDB."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_spec(
        self,
        *,
        repo: str,
        path: str,
        title: str,
        status: str,
        content: str,
        doc_embedding: list[float] | None,
        sections: list[dict],
        commit_sha: str = "",
        doc_type: str = "spec",
    ) -> int:
        """Upsert a spec document and its sections. Returns the document ID."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        async with self._pool.acquire() as conn, conn.transaction():
            doc_id = await conn.fetchval(
                """
                    INSERT INTO spec_documents (repo, path, title, status, content_hash, commit_sha, embedding, doc_type, last_doc_change_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
                    ON CONFLICT (repo, path)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        status = EXCLUDED.status,
                        content_hash = EXCLUDED.content_hash,
                        commit_sha = EXCLUDED.commit_sha,
                        embedding = EXCLUDED.embedding,
                        doc_type = EXCLUDED.doc_type,
                        last_doc_change_at = now(),
                        indexed_at = now()
                    RETURNING id
                    """,
                repo,
                path,
                title,
                status,
                content_hash,
                commit_sha,
                _to_pgvector(doc_embedding),
                doc_type,
            )

            await conn.execute(
                "DELETE FROM spec_sections WHERE document_id = $1",
                doc_id,
            )

            if sections:
                await conn.executemany(
                    """
                        INSERT INTO spec_sections
                            (document_id, heading, level, body, status, ticket_ref, embedding)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                    [
                        (
                            doc_id,
                            s["heading"],
                            s["level"],
                            s["body"],
                            s["status"],
                            s.get("ticket_ref", ""),
                            _to_pgvector(s.get("embedding")),
                        )
                        for s in sections
                    ],
                )

        return doc_id

    async def delete_spec(self, repo: str, path: str) -> bool:
        """Delete a spec document (sections cascade). Returns True if deleted."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM spec_documents WHERE repo = $1 AND path = $2",
                repo,
                path,
            )
            return result == "DELETE 1"

    async def delete_repo(self, repo: str) -> int:
        """Delete all documents for a repo (sections cascade). Returns count deleted."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM spec_documents WHERE repo = $1",
                repo,
            )
            # result is like "DELETE 5"
            try:
                return int(result.split()[-1])
            except (ValueError, IndexError):
                return 0

    async def get_indexed_paths(self, repo: str | None = None) -> dict[str, dict]:
        """Get all indexed document paths, keyed by 'repo/path'.

        Returns dict of {f"{repo}/{path}": {"indexed_at": datetime, "has_embedding": bool}}.
        """
        if repo:
            sql = "SELECT repo, path, indexed_at, (embedding IS NOT NULL) AS has_embedding FROM spec_documents WHERE repo = $1"
            args: tuple = (repo,)
        else:
            sql = "SELECT repo, path, indexed_at, (embedding IS NOT NULL) AS has_embedding FROM spec_documents"
            args = ()

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)

        return {
            f"{row['repo']}/{row['path']}": {
                "indexed_at": row["indexed_at"],
                "has_embedding": row["has_embedding"],
            }
            for row in rows
        }

    async def get_facet_counts(
        self,
        *,
        repo: str | None = None,
    ) -> dict[str, dict[str, int]]:
        """Get aggregate counts for faceted filtering.

        Returns {"status": {"draft": 5, "in_progress": 3, ...}, "repo": {"org/repo": 10, ...}}.
        """
        filters: list[str] = []
        params: list = []
        idx = 1

        if repo:
            filters.append(f"repo = ${idx}")
            params.append(repo)
            idx += 1

        where = ("WHERE " + " AND ".join(filters)) if filters else ""

        status_sql = f"""
        SELECT status, COUNT(*) AS cnt
        FROM spec_documents
        {where}
        GROUP BY status
        ORDER BY cnt DESC
        """

        repo_sql = f"""
        SELECT repo, COUNT(*) AS cnt
        FROM spec_documents
        {where}
        GROUP BY repo
        ORDER BY cnt DESC
        """

        async with self._pool.acquire() as conn:
            status_rows = await conn.fetch(status_sql, *params)
            repo_rows = await conn.fetch(repo_sql, *params)

        return {
            "status": {row["status"]: row["cnt"] for row in status_rows if row["status"]},
            "repo": {row["repo"]: row["cnt"] for row in repo_rows},
        }

    async def hybrid_search(
        self,
        *,
        query_embedding: list[float] | None = None,
        query_text: str,
        repo: str | None = None,
        status: str | None = None,
        limit: int = 20,
        rrf_k: int = 60,
    ) -> list[SearchResult]:
        """Hybrid search combining pgvector cosine similarity and ParadeDB BM25 via RRF.

        If query_embedding is None or empty, falls back to BM25-only search.
        If BM25 is unavailable, falls back to vector-only search.
        """
        if not query_embedding:
            return await self._bm25_only_search(
                query_text=query_text,
                repo=repo,
                status=status,
                limit=limit,
            )

        filters: list[str] = []
        params: list = [_to_pgvector(query_embedding)]
        idx = 2

        if repo:
            filters.append(f"d.repo = ${idx}")
            params.append(repo)
            idx += 1

        if status:
            filters.append(f"s.status = ${idx}")
            params.append(status)
            idx += 1

        where = " AND ".join(filters) if filters else "TRUE"

        bm25_idx = idx
        params.append(query_text)
        idx += 1

        limit_idx = idx
        params.append(limit)

        sql = f"""
        WITH vector_results AS (
            SELECT s.id,
                   ROW_NUMBER() OVER (ORDER BY s.embedding <=> $1) AS rank
            FROM spec_sections s
            JOIN spec_documents d ON d.id = s.document_id
            WHERE s.embedding IS NOT NULL AND {where}
            LIMIT 100
        ),
        bm25_results AS (
            SELECT s.id,
                   ROW_NUMBER() OVER (ORDER BY paradedb.score(s.id) DESC) AS rank
            FROM spec_sections s
            JOIN spec_documents d ON d.id = s.document_id
            WHERE s @@@ paradedb.parse(${bm25_idx})
              AND {where}
            LIMIT 100
        ),
        rrf AS (
            SELECT
                COALESCE(v.id, b.id) AS section_id,
                COALESCE(1.0 / ({rrf_k} + v.rank), 0)
                + COALESCE(1.0 / ({rrf_k} + b.rank), 0) AS rrf_score
            FROM vector_results v
            FULL OUTER JOIN bm25_results b ON v.id = b.id
        )
        SELECT
            rrf.section_id,
            s.document_id,
            d.repo,
            d.path,
            d.title AS doc_title,
            s.heading,
            s.body,
            s.status,
            rrf.rrf_score
        FROM rrf
        JOIN spec_sections s ON s.id = rrf.section_id
        JOIN spec_documents d ON d.id = s.document_id
        ORDER BY rrf.rrf_score DESC
        LIMIT ${limit_idx}
        """

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        except Exception:
            # BM25 might not be available — fall back to vector-only
            logger.info("Hybrid search failed, falling back to vector-only search")
            return await self._vector_only_search(
                query_embedding=query_embedding,
                repo=repo,
                status=status,
                limit=limit,
            )

        return [
            SearchResult(
                section_id=row["section_id"],
                document_id=row["document_id"],
                repo=row["repo"],
                path=row["path"],
                doc_title=row["doc_title"],
                heading=row["heading"],
                body=row["body"],
                status=row["status"],
                rrf_score=float(row["rrf_score"]),
            )
            for row in rows
        ]

    async def _bm25_only_search(
        self,
        *,
        query_text: str,
        repo: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Fallback search using BM25 only (when embeddings are unavailable)."""
        filters: list[str] = []
        params: list = [query_text]
        idx = 2

        if repo:
            filters.append(f"d.repo = ${idx}")
            params.append(repo)
            idx += 1

        if status:
            filters.append(f"s.status = ${idx}")
            params.append(status)
            idx += 1

        where = (" AND " + " AND ".join(filters)) if filters else ""

        params.append(limit)
        limit_idx = idx

        sql = f"""
        SELECT
            s.id AS section_id,
            s.document_id,
            d.repo,
            d.path,
            d.title AS doc_title,
            s.heading,
            s.body,
            s.status,
            paradedb.score(s.id) AS bm25_score
        FROM spec_sections s
        JOIN spec_documents d ON d.id = s.document_id
        WHERE s @@@ paradedb.parse($1)
          {where}
        ORDER BY bm25_score DESC
        LIMIT ${limit_idx}
        """

        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        except Exception:
            # ParadeDB not available — fall back to simple ILIKE search
            logger.info("BM25 search unavailable, falling back to ILIKE search")
            return await self._ilike_search(
                query_text=query_text,
                repo=repo,
                status=status,
                limit=limit,
            )

        return [
            SearchResult(
                section_id=row["section_id"],
                document_id=row["document_id"],
                repo=row["repo"],
                path=row["path"],
                doc_title=row["doc_title"],
                heading=row["heading"],
                body=row["body"],
                status=row["status"],
                rrf_score=float(row["bm25_score"]),
            )
            for row in rows
        ]

    async def _vector_only_search(
        self,
        *,
        query_embedding: list[float],
        repo: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Fallback search using vector similarity only."""
        filters: list[str] = []
        params: list = [_to_pgvector(query_embedding)]
        idx = 2

        if repo:
            filters.append(f"d.repo = ${idx}")
            params.append(repo)
            idx += 1

        if status:
            filters.append(f"s.status = ${idx}")
            params.append(status)
            idx += 1

        where = " AND ".join(filters) if filters else "TRUE"

        params.append(limit)
        limit_idx = idx

        sql = f"""
        SELECT
            s.id AS section_id,
            s.document_id,
            d.repo,
            d.path,
            d.title AS doc_title,
            s.heading,
            s.body,
            s.status,
            1.0 - (s.embedding <=> $1) AS similarity
        FROM spec_sections s
        JOIN spec_documents d ON d.id = s.document_id
        WHERE s.embedding IS NOT NULL AND {where}
        ORDER BY s.embedding <=> $1
        LIMIT ${limit_idx}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [
            SearchResult(
                section_id=row["section_id"],
                document_id=row["document_id"],
                repo=row["repo"],
                path=row["path"],
                doc_title=row["doc_title"],
                heading=row["heading"],
                body=row["body"],
                status=row["status"],
                rrf_score=float(row["similarity"]),
            )
            for row in rows
        ]

    async def mark_code_change(
        self,
        repo: str,
        paths: list[str],
        *,
        threshold_days: int = 30,
    ) -> list[int]:
        """Update last_code_change_at for docs related to changed code paths.

        If the gap between last_code_change_at and last_doc_change_at exceeds
        threshold_days and stale_since is null, sets stale_since.

        Returns list of document IDs that were marked stale.
        """
        if not paths:
            return []

        newly_stale: list[int] = []
        async with self._pool.acquire() as conn:
            # Update last_code_change_at for all docs in this repo
            await conn.execute(
                """
                UPDATE spec_documents
                SET last_code_change_at = now()
                WHERE repo = $1
                """,
                repo,
            )

            # Set stale_since where gap exceeds threshold
            rows = await conn.fetch(
                """
                UPDATE spec_documents
                SET stale_since = now()
                WHERE repo = $1
                  AND stale_since IS NULL
                  AND last_doc_change_at IS NOT NULL
                  AND last_code_change_at IS NOT NULL
                  AND last_code_change_at - last_doc_change_at > make_interval(days => $2)
                RETURNING id
                """,
                repo,
                threshold_days,
            )
            newly_stale = [r["id"] for r in rows]

        return newly_stale

    async def find_related_docs(
        self,
        repo: str,
        code_paths: list[str],
        *,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Find docs semantically related to changed code paths.

        Uses path-based heuristics (directory matching) as a lightweight approach.
        """
        if not code_paths:
            return []

        # Extract unique directory prefixes from code paths
        dirs: set[str] = set()
        for p in code_paths:
            parts = p.split("/")
            if len(parts) > 1:
                dirs.add(parts[0])
                if len(parts) > 2:
                    dirs.add("/".join(parts[:2]))

        if not dirs:
            return []

        # Build ILIKE conditions for directory matching
        conditions = []
        params: list = [repo]
        idx = 2
        for d in list(dirs)[:5]:  # Limit to 5 dirs
            conditions.append(f"s.body ILIKE ${idx}")
            params.append(f"%{d}%")
            idx += 1

        where = " OR ".join(conditions)
        params.append(limit)

        sql = f"""
        SELECT
            s.id AS section_id,
            s.document_id,
            d.repo,
            d.path,
            d.title AS doc_title,
            s.heading,
            s.body,
            s.status
        FROM spec_sections s
        JOIN spec_documents d ON d.id = s.document_id
        WHERE d.repo = $1 AND ({where})
        ORDER BY s.id
        LIMIT ${idx}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [
            SearchResult(
                section_id=row["section_id"],
                document_id=row["document_id"],
                repo=row["repo"],
                path=row["path"],
                doc_title=row["doc_title"],
                heading=row["heading"],
                body=row["body"],
                status=row["status"],
                rrf_score=0.0,
            )
            for row in rows
        ]

    async def _ilike_search(
        self,
        *,
        query_text: str,
        repo: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Last-resort fallback using ILIKE (no BM25, no vectors)."""
        filters: list[str] = []
        params: list = [f"%{query_text}%"]
        idx = 2

        if repo:
            filters.append(f"d.repo = ${idx}")
            params.append(repo)
            idx += 1

        if status:
            filters.append(f"s.status = ${idx}")
            params.append(status)
            idx += 1

        where = (" AND " + " AND ".join(filters)) if filters else ""

        params.append(limit)
        limit_idx = idx

        sql = f"""
        SELECT
            s.id AS section_id,
            s.document_id,
            d.repo,
            d.path,
            d.title AS doc_title,
            s.heading,
            s.body,
            s.status
        FROM spec_sections s
        JOIN spec_documents d ON d.id = s.document_id
        WHERE (s.heading ILIKE $1 OR s.body ILIKE $1 OR d.title ILIKE $1)
          {where}
        ORDER BY s.id
        LIMIT ${limit_idx}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        return [
            SearchResult(
                section_id=row["section_id"],
                document_id=row["document_id"],
                repo=row["repo"],
                path=row["path"],
                doc_title=row["doc_title"],
                heading=row["heading"],
                body=row["body"],
                status=row["status"],
                rrf_score=0.0,
            )
            for row in rows
        ]


def _to_pgvector(values: list[float] | None) -> str | None:
    """Convert a list of floats to pgvector string format '[0.1,0.2,...]'."""
    if values is None:
        return None
    return "[" + ",".join(str(v) for v in values) + "]"
