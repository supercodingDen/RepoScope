"""Conservative durable admission for explicitly enabled paid embeddings."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_UP, Decimal
from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from reposcope.ports.embedding import EmbeddingBudgetExceeded, EmbeddingPriceStale


class PostgresEmbeddingBudget:
    def __init__(
        self,
        pool: AsyncConnectionPool[AsyncConnection[tuple[str]]],
        daily_limit_usd: Decimal,
        price_per_million_usd: Decimal,
        price_verified_date: date,
    ) -> None:
        self.pool = pool
        self.daily_limit_usd = daily_limit_usd
        self.price_per_million_usd = price_per_million_usd
        self.price_verified_date = price_verified_date

    async def reserve(self, requested_tokens: int) -> UUID:
        if not 1 <= requested_tokens <= 20_000:
            raise ValueError("Invalid embedding token count")
        today = datetime.now(UTC).date()
        if not today - timedelta(days=7) <= self.price_verified_date <= today:
            raise EmbeddingPriceStale()
        # Keep both settled and uncertain reservations against the daily ceiling.
        # A 2x token allowance covers modest provider tokenizer differences.
        ceiling = (self.price_per_million_usd * requested_tokens * 2 / Decimal(1_000_000)).quantize(
            Decimal("0.000000001"), rounding=ROUND_UP
        )
        reservation_id = uuid4()
        async with asyncio.timeout(10), self.pool.connection() as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL lock_timeout='3s'")
                await connection.execute("SET LOCAL statement_timeout='8s'")
                await connection.execute(
                    "SELECT singleton FROM reposcope.admission_lock WHERE singleton=true FOR UPDATE"
                )
                cursor = await connection.execute(
                    "SELECT coalesce(sum(reserved_usd),0)::text FROM "
                    "reposcope.embedding_reservations WHERE budget_day="
                    "(clock_timestamp() AT TIME ZONE 'UTC')::date"
                )
                row = await cursor.fetchone()
                used = Decimal(row[0]) if row is not None else Decimal(0)
                cursor = await connection.execute(
                    "SELECT coalesce(sum(reserved_usd),0)::text FROM "
                    "reposcope.model_attempts WHERE budget_day=%s",
                    (today,),
                )
                model_row = await cursor.fetchone()
                model_day = Decimal(model_row[0]) if model_row is not None else Decimal(0)
                cursor = await connection.execute(
                    "SELECT coalesce(sum(reserved_usd),0)::text FROM "
                    "reposcope.embedding_reservations"
                )
                project_row = await cursor.fetchone()
                embedding_project = (
                    Decimal(project_row[0]) if project_row is not None else Decimal(0)
                )
                cursor = await connection.execute(
                    "SELECT coalesce(sum(reserved_usd),0)::text FROM reposcope.model_attempts"
                )
                model_project_row = await cursor.fetchone()
                model_project = (
                    Decimal(model_project_row[0]) if model_project_row is not None else Decimal(0)
                )
                if (
                    used + model_day + ceiling > self.daily_limit_usd
                    or embedding_project + model_project + ceiling > Decimal("4.00")
                ):
                    raise EmbeddingBudgetExceeded()
                await connection.execute(
                    "INSERT INTO reposcope.embedding_reservations("
                    "reservation_id,budget_day,provider,model,requested_tokens,reserved_usd,state) "
                    "VALUES(%s,(clock_timestamp() AT TIME ZONE 'UTC')::date,"
                    "'openai','text-embedding-3-small',%s,%s,'reserved')",
                    (reservation_id, requested_tokens, ceiling),
                )
        return reservation_id

    async def settle(self, reservation_id: UUID, actual_tokens: int) -> None:
        if actual_tokens < 0:
            raise ValueError("Invalid provider token usage")
        async with asyncio.timeout(10), self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    "UPDATE reposcope.embedding_reservations SET state='settled',"
                    "actual_tokens=%s,updated_at=clock_timestamp() "
                    "WHERE reservation_id=%s AND state='reserved' "
                    "AND requested_tokens*2 >= %s RETURNING reservation_id",
                    (actual_tokens, reservation_id, actual_tokens),
                )
                if await cursor.fetchone() is None:
                    raise RuntimeError("Embedding reservation missing")

    async def uncertain(self, reservation_id: UUID) -> None:
        async with asyncio.timeout(10), self.pool.connection() as connection:
            await connection.execute(
                "UPDATE reposcope.embedding_reservations SET state='uncertain',"
                "updated_at=clock_timestamp() WHERE reservation_id=%s AND state='reserved'",
                (reservation_id,),
            )
