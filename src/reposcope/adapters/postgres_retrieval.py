"""Authorized, generation-scoped pgvector and full-text retrieval."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from reposcope.domain.errors import WorkError
from reposcope.domain.retrieval import Candidate, RetrievalScope

_FILTER = (
    "FROM reposcope.index_chunks c "
    "JOIN reposcope.index_files f ON f.generation_id=c.generation_id AND f.path=c.path "
    "JOIN reposcope.index_generations g ON g.generation_id=c.generation_id "
    "WHERE c.generation_id=%s AND g.repository_id=%s AND g.commit_sha=%s "
    "AND g.embedding_space_version=%s "
    "AND (%s::text IS NULL OR f.language=%s OR "
    "(%s='typescript' AND f.language='tsx') OR "
    "(%s='javascript' AND right(c.path,3)='.js') OR "
    "(%s='go' AND right(c.path,3)='.go')) "
    "AND (%s::text IS NULL OR c.path=%s OR "
    "left(c.path,length(%s)+1)=%s || '/') "
)


def _parameters(
    scope: RetrievalScope, language: str | None, path_prefix: str | None
) -> tuple[object, ...]:
    return (
        scope.generation_id,
        scope.repository_id,
        scope.commit_sha,
        scope.embedding_space_version,
        language,
        language,
        language,
        language,
        language,
        path_prefix,
        path_prefix,
        path_prefix,
        path_prefix,
    )


def _candidates(rows: list[tuple[str, int, int, int, str, str]]) -> tuple[Candidate, ...]:
    return tuple(Candidate(*row) for row in rows)


async def complete_vector_candidates(
    approximate: tuple[Candidate, ...],
    exact: Callable[[], Awaitable[tuple[Candidate, ...]]],
) -> tuple[Candidate, ...]:
    """Recover scoped top-50 when global ANN filtering underfills."""
    return await exact() if len(approximate) < 50 else approximate


class PostgresRetrievalRepository:
    """Read one immutable generation through short, cancellable transactions."""

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[tuple[str]]]) -> None:
        self.pool = pool

    async def active_scope(self, principal_id: UUID, repository_id: UUID) -> RetrievalScope | None:
        async with asyncio.timeout(10), self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT g.generation_id,g.commit_sha,g.embedding_space_version,g.status,"
                "(SELECT count(*)::integer FROM reposcope.index_chunks c "
                "WHERE c.generation_id=g.generation_id) "
                "FROM reposcope.repositories r LEFT JOIN reposcope.index_generations g "
                "ON g.generation_id=r.active_generation_id "
                "WHERE r.repository_id=%s AND r.principal_id=%s",
                (repository_id, principal_id),
            )
            row = cast(
                tuple[UUID | None, str | None, str | None, str | None, int | None] | None,
                await cursor.fetchone(),
            )
        if row is None:
            raise WorkError("NOT_FOUND")
        generation_id, commit_sha, space, status, count = row
        if generation_id is None or commit_sha is None or space is None or status != "ready":
            return None
        return RetrievalScope(repository_id, generation_id, commit_sha, space, count or 0)

    async def candidates(
        self,
        scope: RetrievalScope,
        vector: tuple[float, ...],
        query: str,
        language: str | None,
        path_prefix: str | None,
        *,
        exact: bool = False,
    ) -> tuple[tuple[Candidate, ...], tuple[Candidate, ...]]:
        if len(vector) != 384:
            raise ValueError("Query vector must have 384 dimensions")
        serialized = "[" + ",".join(str(value) for value in vector) + "]"
        fields = "c.path,c.ordinal,c.start_line,c.end_line,c.chunk_text,f.language"
        filters = _parameters(scope, language, path_prefix)
        exact_sql = (
            "WITH filtered AS MATERIALIZED (SELECT " + fields + ",c.embedding " + _FILTER + ") "
            "SELECT path,ordinal,start_line,end_line,chunk_text,language "
            "FROM filtered ORDER BY embedding <=> %s::vector,path,ordinal LIMIT 50"
        )
        approximate_sql = (
            "SELECT "
            + fields
            + " "
            + _FILTER
            + "ORDER BY c.embedding <=> %s::vector,c.path,c.ordinal LIMIT 50"
        )
        lexical_sql = (
            "SELECT "
            + fields
            + " "
            + _FILTER
            + "AND to_tsvector('simple',c.chunk_text) @@ plainto_tsquery('simple',%s) "
            "ORDER BY ts_rank_cd(to_tsvector('simple',c.chunk_text),"
            "plainto_tsquery('simple',%s)) DESC,c.path,c.ordinal LIMIT 50"
        )
        async with asyncio.timeout(10), self.pool.connection() as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL statement_timeout='9000ms'")
                if not exact:
                    await connection.execute("SET LOCAL hnsw.ef_search=80")
                    await connection.execute("SET LOCAL hnsw.iterative_scan='strict_order'")

                async def load_exact() -> tuple[Candidate, ...]:
                    cursor = await connection.execute(exact_sql, (*filters, serialized))
                    rows = cast(list[tuple[str, int, int, int, str, str]], await cursor.fetchall())
                    return _candidates(rows)

                if exact:
                    vector_candidates = await load_exact()
                else:
                    cursor = await connection.execute(approximate_sql, (*filters, serialized))
                    approximate_rows = cast(
                        list[tuple[str, int, int, int, str, str]], await cursor.fetchall()
                    )
                    vector_candidates = await complete_vector_candidates(
                        _candidates(approximate_rows), load_exact
                    )
                cursor = await connection.execute(lexical_sql, (*filters, query, query))
                lexical_rows = cast(
                    list[tuple[str, int, int, int, str, str]], await cursor.fetchall()
                )
        return vector_candidates, _candidates(lexical_rows)
