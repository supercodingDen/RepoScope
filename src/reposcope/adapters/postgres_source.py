"""Fenced commit pinning and atomic source-stage publication."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from contracts.models import Contract, IngestRequested, SourceAcquired, SourceAcquiredPayload
from reposcope.adapters.postgres_delivery import PostgresDeliveryRepository
from reposcope.adapters.postgres_work import _read
from reposcope.domain.delivery import Lease, LeaseLost
from reposcope.domain.source_snapshot import SourceSnapshot
from reposcope.ports.source import SourceRequest


class _SourceRow(Contract):
    url: str
    generation_id: UUID
    commit_sha: str | None


class PostgresSourceRepository:
    def __init__(self, delivery: PostgresDeliveryRepository) -> None:
        self.delivery = delivery

    async def prepare(self, lease: Lease) -> SourceRequest:
        if not isinstance(lease.event, IngestRequested):
            raise LeaseLost()
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            row = await _read(
                connection,
                "SELECT "
                "json_build_object('url',r.url,'generation_id',j.generation_id,'commit_sha',j.com"
                "mit_sha)::text AS data "
                "FROM reposcope.jobs j JOIN reposcope.repositories r USING(repository_id) WHERE "
                "j.job_id=%s",
                (lease.event.aggregate_id,),
                _SourceRow,
            )
            if row is None:
                raise LeaseLost()
            await connection.execute(
                "INSERT INTO reposcope.source_attempts(job_id,fencing_token) VALUES(%s,%s) ON "
                "CONFLICT DO NOTHING",
                (lease.event.aggregate_id, lease.token),
            )
            return SourceRequest(row.url, row.generation_id, row.commit_sha)

    async def pin(self, lease: Lease, commit: str) -> str:
        if (
            not isinstance(lease.event, IngestRequested)
            or re.fullmatch(r"[a-f0-9]{40}", commit) is None
        ):
            raise LeaseLost()
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            cursor = await connection.execute(
                "SELECT commit_sha FROM reposcope.jobs WHERE job_id=%s", (lease.event.aggregate_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                raise LeaseLost()
            if row[0] is not None:
                return row[0]
            await connection.execute(
                "INSERT INTO "
                "reposcope.source_revisions(repository_id,principal_id,commit_sha,created_at) "
                "VALUES(%s,%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING",
                (lease.event.payload.repository_id, lease.event.payload.principal_id, commit),
            )
            await connection.execute(
                "UPDATE reposcope.index_generations SET "
                "commit_sha=%s,updated_at=clock_timestamp() WHERE generation_id=(SELECT "
                "generation_id FROM reposcope.jobs WHERE job_id=%s) AND commit_sha IS NULL",
                (commit, lease.event.aggregate_id),
            )
            await connection.execute(
                "UPDATE reposcope.jobs SET commit_sha=%s,updated_at=clock_timestamp() WHERE "
                "job_id=%s AND commit_sha IS NULL",
                (commit, lease.event.aggregate_id),
            )
            return commit

    async def obsolete_attempts(self, lease: Lease) -> tuple[int, ...]:
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            cursor = await connection.execute(
                "SELECT a.fencing_token::text FROM reposcope.source_attempts a "
                "WHERE a.job_id=%s AND a.fencing_token<%s AND NOT EXISTS "
                "(SELECT 1 FROM reposcope.source_manifests m WHERE m.job_id=a.job_id AND "
                "m.fencing_token=a.fencing_token)",
                (lease.event.aggregate_id, lease.token),
            )
            return tuple(int(row[0]) for row in await cursor.fetchall())

    async def stage(self, lease: Lease, snapshot: SourceSnapshot) -> None:
        if not isinstance(lease.event, IngestRequested):
            raise LeaseLost()
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            row = await _read(
                connection,
                "SELECT "
                "json_build_object('url',r.url,'generation_id',j.generation_id,'commit_sha',j.com"
                "mit_sha)::text AS data "
                "FROM reposcope.jobs j JOIN reposcope.repositories r USING(repository_id) WHERE "
                "j.job_id=%s",
                (lease.event.aggregate_id,),
                _SourceRow,
            )
            manifest = snapshot.manifest
            if (
                row is None
                or manifest.commit_sha is None
                or manifest.commit_sha != row.commit_sha
                or manifest.source != row.url
            ):
                raise LeaseLost()
            if (
                snapshot.storage_key
                != f"snapshots/{lease.event.aggregate_id}-{lease.token}/{snapshot.digest}"
            ):
                raise LeaseLost()
            await connection.execute(
                "INSERT INTO "
                "reposcope.source_manifests(job_id,repository_id,generation_id,principal_id,commi"
                "t_sha,manifest_digest,manifest,storage_key,policy_version,fencing_token) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
                (
                    lease.event.aggregate_id,
                    lease.event.payload.repository_id,
                    row.generation_id,
                    lease.event.payload.principal_id,
                    manifest.commit_sha,
                    snapshot.digest,
                    manifest.serialize(),
                    snapshot.storage_key,
                    manifest.policy_version,
                    lease.token,
                ),
            )
            event = SourceAcquired(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC),
                aggregate_id=lease.event.aggregate_id,
                trace_id=lease.event.trace_id,
                payload=SourceAcquiredPayload(
                    job_id=lease.event.aggregate_id,
                    repository_id=lease.event.payload.repository_id,
                    generation_id=row.generation_id,
                    principal_id=lease.event.payload.principal_id,
                    commit_sha=manifest.commit_sha,
                    manifest_digest=snapshot.digest,
                ),
            )
            await connection.execute(
                "INSERT INTO "
                "reposcope.outbox_events(event_id,principal_id,aggregate_id,event_type,payload,oc"
                "curred_at,trace_id,job_id) VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
                (
                    event.event_id,
                    event.payload.principal_id,
                    event.aggregate_id,
                    event.event_type,
                    event.model_dump_json(),
                    event.occurred_at,
                    event.trace_id,
                    event.aggregate_id,
                ),
            )
            await self.delivery.complete_stage(connection, lease)
            await connection.execute(
                "UPDATE reposcope.jobs SET "
                "progress_percent=20,lease_owner=NULL,lease_until=NULL,updated_at=clock_timestamp"
                "() WHERE job_id=%s",
                (event.aggregate_id,),
            )
            await connection.execute(
                "UPDATE reposcope.index_generations SET "
                "status='staged',updated_at=clock_timestamp() WHERE generation_id=%s",
                (row.generation_id,),
            )

    async def cleanup_candidates(self) -> tuple[tuple[UUID, int], ...]:
        async with self.delivery.transaction() as connection:
            cursor = await connection.execute(
                "SELECT json_build_object('job_id',a.job_id,'token',a.fencing_token)::text "
                "FROM reposcope.source_attempts a JOIN reposcope.jobs j USING(job_id) "
                "WHERE (a.cleaned_at IS NULL OR "
                "a.cleaned_at<clock_timestamp()-interval '30 seconds') "
                "AND (j.status IN ('failed','succeeded') "
                "OR a.fencing_token<j.fencing_token) AND NOT EXISTS "
                "(SELECT 1 FROM reposcope.source_manifests m WHERE m.job_id=a.job_id "
                "AND m.fencing_token=a.fencing_token) "
                "ORDER BY coalesce(a.cleaned_at,a.created_at) LIMIT 50"
            )
            rows = [_CleanupRow.model_validate_json(row[0]) for row in await cursor.fetchall()]
            return tuple((row.job_id, row.token) for row in rows)

    async def cleaned(self, job_id: UUID, token: int) -> None:
        async with self.delivery.transaction() as connection:
            await connection.execute(
                "UPDATE reposcope.source_attempts SET cleaned_at=clock_timestamp() "
                "WHERE job_id=%s AND fencing_token=%s",
                (job_id, token),
            )


class _CleanupRow(Contract):
    job_id: UUID
    token: int
