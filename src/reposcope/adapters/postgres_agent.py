"""Fenced agent preparation and bounded read-only snapshot metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal
from typing import cast

from pydantic import TypeAdapter

from contracts.models import AgentRequested
from reposcope.adapters.postgres_delivery import PostgresDeliveryRepository
from reposcope.domain.delivery import Lease, LeaseLost
from reposcope.domain.errors import WorkError
from reposcope.domain.source_snapshot import SourceManifest, SourceSnapshot


@dataclass(frozen=True, slots=True)
class AgentPreparation:
    question: str
    snapshot: SourceSnapshot
    chunk_count: int
    languages: tuple[str, ...]


class PostgresAgentRepository:
    def __init__(self, delivery: PostgresDeliveryRepository) -> None:
        self.delivery = delivery

    async def prepare(self, lease: Lease) -> AgentPreparation:
        if not isinstance(lease.event, AgentRequested):
            raise LeaseLost()
        scope = lease.event.payload
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            cursor = await connection.execute(
                "SELECT r.question,m.manifest::text,m.storage_key,m.manifest_digest,"
                "(SELECT count(*)::integer FROM reposcope.index_chunks c "
                "WHERE c.generation_id=r.generation_id),"
                "(SELECT coalesce(array_agg(DISTINCT f.language),ARRAY[]::text[]) "
                "FROM reposcope.index_files f WHERE f.generation_id=r.generation_id) "
                "FROM reposcope.agent_runs r "
                "JOIN reposcope.index_generations g ON g.generation_id=r.generation_id "
                "JOIN reposcope.jobs j ON j.generation_id=g.generation_id "
                "JOIN reposcope.source_manifests m ON m.generation_id=g.generation_id "
                "WHERE r.run_id=%s AND r.repository_id=%s AND r.generation_id=%s "
                "AND r.principal_id=%s AND r.commit_sha=%s "
                "AND g.status IN ('ready','superseded') AND j.status='succeeded'",
                (
                    scope.run_id,
                    scope.repository_id,
                    scope.generation_id,
                    scope.principal_id,
                    scope.commit_sha,
                ),
            )
            row = cast(
                tuple[str, str, str, str, int, list[str]] | None,
                await cursor.fetchone(),
            )
        if row is None:
            raise LeaseLost()
        question, raw, key, digest, count, languages = row
        manifest = TypeAdapter(SourceManifest).validate_json(raw)
        if manifest.digest != digest or manifest.commit_sha != scope.commit_sha:
            raise LeaseLost()
        return AgentPreparation(question, SourceSnapshot(manifest, key), count, tuple(languages))

    async def record_tool_step(self, lease: Lease) -> int:
        if not isinstance(lease.event, AgentRequested):
            raise LeaseLost()
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            cursor = await connection.execute(
                "UPDATE reposcope.agent_runs SET tool_steps=tool_steps+1 "
                "WHERE run_id=%s AND tool_steps<6 RETURNING tool_steps",
                (lease.event.payload.run_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("Tool step limit exceeded")
            return int(row[0])

    async def reserved_cost(self, lease: Lease) -> Decimal:
        if not isinstance(lease.event, AgentRequested):
            raise LeaseLost()
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            cursor = await connection.execute(
                "SELECT coalesce(sum(reserved_usd),0)::text FROM reposcope.model_attempts "
                "WHERE run_id=%s",
                (lease.event.payload.run_id,),
            )
            row = await cursor.fetchone()
            assert row is not None
            return Decimal(row[0])

    async def reserve_model_attempt(
        self,
        lease: Lease,
        estimated_input_tokens: int,
        input_price: Decimal,
        output_price: Decimal,
        verified_date: date,
    ) -> tuple[int, Decimal]:
        """Commit a worst-case reservation before any provider dispatch."""
        if not isinstance(lease.event, AgentRequested):
            raise LeaseLost()
        today = datetime.now(UTC).date()
        if not today - timedelta(days=7) <= verified_date <= today:
            raise WorkError("PROVIDER_UNAVAILABLE")
        if not 1 <= estimated_input_tokens <= 24000:
            raise WorkError("VALIDATION_ERROR")
        cost = (
            (Decimal(estimated_input_tokens) * input_price + Decimal(2000) * output_price)
            * Decimal("1.2")
            / Decimal(1_000_000)
        ).quantize(Decimal("0.000001"), rounding=ROUND_UP)
        async with self.delivery.transaction() as connection:
            await connection.execute(
                "SELECT singleton FROM reposcope.admission_lock WHERE singleton=true FOR UPDATE"
            )
            await self.delivery.lock_lease(connection, lease)
            cursor = await connection.execute(
                "SELECT attempts FROM reposcope.agent_runs WHERE run_id=%s",
                (lease.event.payload.run_id,),
            )
            row = await cursor.fetchone()
            if row is None or int(row[0]) >= 6:
                raise WorkError("BUDGET_EXCEEDED")
            attempt = int(row[0]) + 1
            cursor = await connection.execute(
                "SELECT coalesce(sum(reserved_usd),0)::text FROM reposcope.model_attempts "
                "WHERE run_id=%s",
                (lease.event.payload.run_id,),
            )
            spent_run_row = await cursor.fetchone()
            assert spent_run_row is not None
            spent_run = Decimal(spent_run_row[0])
            cursor = await connection.execute(
                "SELECT coalesce(sum(reserved_usd),0)::text FROM reposcope.model_attempts "
                "WHERE budget_day=%s",
                (today,),
            )
            spent_day_row = await cursor.fetchone()
            assert spent_day_row is not None
            spent_day = Decimal(spent_day_row[0])
            cursor = await connection.execute(
                "SELECT coalesce(sum(reserved_usd),0)::text FROM reposcope.model_attempts"
            )
            spent_project_row = await cursor.fetchone()
            assert spent_project_row is not None
            spent_project = Decimal(spent_project_row[0])
            cursor = await connection.execute(
                "SELECT coalesce(sum(reserved_usd),0)::text FROM "
                "reposcope.embedding_reservations WHERE budget_day=%s",
                (today,),
            )
            embeddings_day_row = await cursor.fetchone()
            assert embeddings_day_row is not None
            embeddings_day = Decimal(embeddings_day_row[0])
            cursor = await connection.execute(
                "SELECT coalesce(sum(reserved_usd),0)::text FROM reposcope.embedding_reservations"
            )
            embeddings_project_row = await cursor.fetchone()
            assert embeddings_project_row is not None
            embeddings_project = Decimal(embeddings_project_row[0])
            cursor = await connection.execute(
                "SELECT coalesce(sum(amount_usd),0)::text FROM reposcope.usage_reservations "
                "WHERE state <> 'released'"
            )
            admission_row = await cursor.fetchone()
            assert admission_row is not None
            admission = Decimal(admission_row[0])
            if (
                spent_run + cost > Decimal("0.10")
                or spent_day + embeddings_day + admission + cost > Decimal("1.00")
                or spent_project + embeddings_project + admission + cost > Decimal("4.00")
            ):
                raise WorkError("BUDGET_EXCEEDED")
            await connection.execute(
                "INSERT INTO reposcope.model_attempts "
                "(run_id,attempt_no,model,estimated_input_tokens,max_output_tokens,"
                "reserved_usd,state,budget_day) VALUES (%s,%s,'gpt-5.6-luna',%s,2000,%s,"
                "'reserved',%s)",
                (lease.event.payload.run_id, attempt, estimated_input_tokens, cost, today),
            )
            await connection.execute(
                "UPDATE reposcope.agent_runs SET attempts=%s WHERE run_id=%s",
                (attempt, lease.event.payload.run_id),
            )
            return attempt, cost

    async def settle_model_attempt(
        self, lease: Lease, attempt: int, input_tokens: int | None, output_tokens: int | None
    ) -> None:
        if not isinstance(lease.event, AgentRequested):
            raise LeaseLost()
        async with self.delivery.transaction() as connection:
            await self.delivery.lock_lease(connection, lease)
            await connection.execute(
                "UPDATE reposcope.model_attempts SET state=%s,actual_input_tokens=%s,"
                "actual_output_tokens=%s,updated_at=clock_timestamp() "
                "WHERE run_id=%s AND attempt_no=%s AND state='reserved'",
                (
                    "settled"
                    if input_tokens is not None and output_tokens is not None
                    else "uncertain",
                    input_tokens,
                    output_tokens,
                    lease.event.payload.run_id,
                    attempt,
                ),
            )
