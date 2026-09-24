"""Fenced per-file index checkpoints and atomic generation publication."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import cast
from uuid import UUID

from pydantic import TypeAdapter

from contracts.models import SourceAcquired
from reposcope.adapters.postgres_delivery import PostgresDeliveryRepository
from reposcope.domain.delivery import Lease, LeaseLost
from reposcope.domain.indexing import (
    CHUNK_POLICY_VERSION,
    PARSER_VERSION,
    TOKENIZER_VERSION,
    ChunkedFile,
    EmbeddingResponse,
    embedding_input,
)
from reposcope.domain.source_snapshot import SourceManifest, SourceSnapshot
from reposcope.ports.index import IndexPreparation


class PostgresIndexRepository:
    def __init__(self, delivery: PostgresDeliveryRepository) -> None:
        self.delivery = delivery

    async def cached_embeddings(
        self, space_version: str, input_hashes: tuple[str, ...]
    ) -> dict[str, tuple[float, ...]]:
        if not input_hashes:
            return {}
        async with self.delivery.transaction() as connection:
            cursor = await connection.execute(
                "SELECT input_sha256,embedding::text FROM reposcope.embedding_cache "
                "WHERE space_version=%s AND input_sha256=ANY(%s)",
                (space_version, list(input_hashes)),
            )
            return {
                row[0]: TypeAdapter(tuple[float, ...]).validate_json(row[1])
                for row in cast(list[tuple[str, str]], await cursor.fetchall())
            }

    async def prepare(self, lease: Lease, pipeline_version: str) -> IndexPreparation:
        if not isinstance(lease.event, SourceAcquired):
            raise LeaseLost()
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            cursor = await connection.execute(
                "SELECT manifest::text,storage_key FROM reposcope.source_manifests "
                "WHERE job_id=%s AND generation_id=%s AND repository_id=%s "
                "AND principal_id=%s AND commit_sha=%s AND manifest_digest=%s",
                (
                    lease.event.aggregate_id,
                    lease.event.payload.generation_id,
                    lease.event.payload.repository_id,
                    lease.event.payload.principal_id,
                    lease.event.payload.commit_sha,
                    lease.event.payload.manifest_digest,
                ),
            )
            raw_row = await cursor.fetchone()
            if raw_row is None:
                raise LeaseLost()
            row = cast(tuple[str, str], raw_row)
            manifest = TypeAdapter(SourceManifest).validate_json(row[0])
            if (
                manifest.digest != lease.event.payload.manifest_digest
                or manifest.commit_sha != lease.event.payload.commit_sha
            ):
                raise LeaseLost()
            cursor = await connection.execute(
                "SELECT path,pipeline_version FROM reposcope.index_files WHERE generation_id=%s",
                (lease.event.payload.generation_id,),
            )
            rows = cast(list[tuple[str, str]], await cursor.fetchall())
            if any(item[1] != pipeline_version for item in rows):
                raise ValueError("Index pipeline changed during generation")
            completed = frozenset(item[0] for item in rows)
            if not completed.issubset({file.path for file in manifest.files}):
                raise LeaseLost()
            return IndexPreparation(SourceSnapshot(manifest, row[1]), completed)

    async def stage_file(
        self,
        lease: Lease,
        file: ChunkedFile,
        content_sha256: str,
        byte_count: int,
        response: EmbeddingResponse | None,
        pipeline_version: str,
    ) -> None:
        if not isinstance(lease.event, SourceAcquired):
            raise LeaseLost()
        if (response is None) != (not file.chunks):
            raise ValueError("Embedding response must match file chunks")
        if response is not None and len(response.vectors) != len(file.chunks):
            raise ValueError("Embedding response count mismatch")
        if response is not None and not pipeline_version.endswith("/" + response.space.version):
            raise ValueError("Embedding space does not match pipeline")
        if hashlib.sha256(b"").hexdigest() == content_sha256 and byte_count != 0:
            raise ValueError("Invalid source size")
        async with asyncio.timeout(45), self.delivery.pool.connection() as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL lock_timeout='3s'")
                await connection.execute("SET LOCAL statement_timeout='30s'")
                await self.delivery.lock_lease(connection, lease)
                cursor = await connection.execute(
                    "SELECT 1 FROM reposcope.source_manifests m WHERE m.job_id=%s "
                    "AND m.generation_id=%s AND m.manifest->'files' @> %s::jsonb",
                    (
                        lease.event.aggregate_id,
                        lease.event.payload.generation_id,
                        json.dumps(
                            [{"path": file.path, "sha256": content_sha256, "size": byte_count}]
                        ),
                    ),
                )
                if await cursor.fetchone() is None:
                    raise LeaseLost()
                await connection.execute(
                    "INSERT INTO reposcope.index_files(generation_id,path,content_sha256,"
                    "byte_count,language,parse_mode,pipeline_version,dependencies,chunk_count) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
                    (
                        lease.event.payload.generation_id,
                        file.path,
                        content_sha256,
                        byte_count,
                        file.language,
                        file.parse_mode,
                        pipeline_version,
                        json.dumps(file.dependencies),
                        len(file.chunks),
                    ),
                )
                if response is not None:
                    rows = [
                        (
                            lease.event.payload.generation_id,
                            file.path,
                            chunk.ordinal,
                            chunk.start_byte,
                            chunk.end_byte,
                            chunk.start_line,
                            chunk.end_line,
                            chunk.sha256,
                            chunk.token_count,
                            chunk.symbol,
                            chunk.text,
                            "[" + ",".join(str(value) for value in vector) + "]",
                        )
                        for chunk, vector in zip(file.chunks, response.vectors, strict=True)
                    ]
                    async with connection.cursor() as cursor:
                        await cursor.executemany(
                            "INSERT INTO reposcope.index_chunks(generation_id,path,ordinal,"
                            "start_byte,end_byte,start_line,end_line,content_sha256,token_count,"
                            "symbol,chunk_text,embedding) "
                            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)",
                            rows,
                        )
                        await cursor.executemany(
                            "INSERT INTO reposcope.embedding_cache(space_version,input_sha256,"
                            "embedding) VALUES(%s,%s,%s::vector) ON CONFLICT DO NOTHING",
                            [
                                (
                                    response.space.version,
                                    hashlib.sha256(
                                        embedding_input(chunk).encode("utf-8")
                                    ).hexdigest(),
                                    "[" + ",".join(str(value) for value in vector) + "]",
                                )
                                for chunk, vector in zip(file.chunks, response.vectors, strict=True)
                            ],
                        )
                await connection.execute(
                    "UPDATE reposcope.jobs SET progress_percent=least(95,20+75*(SELECT "
                    "count(*) FROM reposcope.index_files WHERE generation_id=%s)/greatest(1, "
                    "jsonb_array_length((SELECT manifest->'files' FROM "
                    "reposcope.source_manifests WHERE job_id=%s)))),updated_at=clock_timestamp() "
                    "WHERE job_id=%s",
                    (
                        lease.event.payload.generation_id,
                        lease.event.aggregate_id,
                        lease.event.aggregate_id,
                    ),
                )

    async def publish(self, lease: Lease, expected_files: int, space_version: str) -> str:
        """Complete the consumer and job in the same transaction as ready visibility."""
        if not isinstance(lease.event, SourceAcquired):
            raise LeaseLost()
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            cursor = await connection.execute(
                "SELECT count(*)::integer,coalesce(sum(chunk_count),0)::integer "
                "FROM reposcope.index_files WHERE generation_id=%s",
                (lease.event.payload.generation_id,),
            )
            counts = cast(tuple[int, int] | None, await cursor.fetchone())
            if counts is None or counts[0] != expected_files:
                raise ValueError("Incomplete generation")
            cursor = await connection.execute(
                "SELECT count(*)::integer FROM reposcope.index_chunks WHERE generation_id=%s",
                (lease.event.payload.generation_id,),
            )
            chunks = cast(tuple[int] | None, await cursor.fetchone())
            if chunks is None or chunks[0] != counts[1]:
                raise ValueError("Incomplete chunk set")
            cursor = await connection.execute(
                "SELECT latest_requested_generation_id FROM reposcope.repositories "
                "WHERE repository_id=%s AND principal_id=%s FOR UPDATE",
                (lease.event.payload.repository_id, lease.event.payload.principal_id),
            )
            repository = await cursor.fetchone()
            if repository is None:
                raise LeaseLost()
            current = cast(UUID, repository[0]) == lease.event.payload.generation_id
            status = "ready" if current else "superseded"
            await connection.execute(
                "UPDATE reposcope.index_generations SET status=%s,parser_version=%s,"
                "tokenizer_version=%s,embedding_space_version=%s,chunk_count=%s,"
                "updated_at=clock_timestamp() "
                "WHERE generation_id=%s AND status='staged'",
                (
                    status,
                    PARSER_VERSION + "/" + CHUNK_POLICY_VERSION,
                    TOKENIZER_VERSION,
                    space_version,
                    chunks[0],
                    lease.event.payload.generation_id,
                ),
            )
            if current:
                await connection.execute(
                    "UPDATE reposcope.repositories SET active_generation_id=%s "
                    "WHERE repository_id=%s AND principal_id=%s",
                    (
                        lease.event.payload.generation_id,
                        lease.event.payload.repository_id,
                        lease.event.payload.principal_id,
                    ),
                )
            await connection.execute(
                "UPDATE reposcope.jobs SET status='succeeded',progress_percent=100,"
                "lease_owner=NULL,lease_until=NULL,updated_at=clock_timestamp() WHERE job_id=%s",
                (lease.event.aggregate_id,),
            )
            await self.delivery._completion(
                connection, lease.consumer, lease.event, "succeeded", None
            )
            return status
