"""Measure exact/HNSW recall and concurrent search over a loaded T12 scope."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import statistics
import sys
import time
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from contracts.models import SearchRequest
from reposcope.adapters.embedding import MockEmbeddingProvider, _mock_vector
from reposcope.adapters.postgres_retrieval import PostgresRetrievalRepository
from reposcope.application.retrieval import RetrievalService

type Pool = AsyncConnectionPool[AsyncConnection[tuple[str]]]
type Metric = Literal["cosine", "inner_product"]
EF_SEARCH_VALUES = (40, 80, 120, 200, 400, 800, 1000)


def percentile(values: list[float], fraction: float = 0.95) -> float:
    """Use the nearest-rank statistic, retaining raw observations separately."""
    if not values:
        raise ValueError("A percentile requires observations")
    return round(sorted(values)[max(0, int(len(values) * fraction + 0.999999) - 1)], 3)


def numeric(value: object) -> float:
    """Validate a stored numeric observation before aggregation."""
    if not isinstance(value, (int, float)):
        raise TypeError("Benchmark observation is not numeric")
    return float(value)


def query_vector(query: str) -> str:
    """Produce exactly the versioned mock query vector used by RetrievalService."""
    raw = _mock_vector(query)
    magnitude = sum(value * value for value in raw) ** 0.5
    return "[" + ",".join(f"{value / magnitude:.8g}" for value in raw) + "]"


async def vector_top_ten(
    pool: Pool,
    generation_id: UUID,
    vector: str,
    *,
    exact: bool,
    ef_search: int = 80,
    metric: Metric = "cosine",
    path_prefix: str | None = None,
) -> tuple[list[str], float]:
    """Measure the production vector operator with a matching generation filter."""
    path_filter = " AND (path=%s OR left(path,length(%s)+1)=%s || '/')" if path_prefix else ""
    exact_sql = (
        "WITH filtered AS MATERIALIZED (SELECT path,ordinal,embedding "
        "FROM reposcope.index_chunks WHERE generation_id=%s" + path_filter + ") "
        "SELECT path,ordinal FROM filtered ORDER BY embedding <=> %s::vector,path,ordinal LIMIT 10"
    )
    operator = "<#>" if metric == "inner_product" else "<=>"
    approximate_sql = (
        "SELECT path,ordinal FROM reposcope.index_chunks WHERE generation_id=%s" + path_filter + " "
        f"ORDER BY embedding {operator} %s::vector,path,ordinal LIMIT 10"
    )
    parameters: tuple[object, ...] = (generation_id,)
    if path_prefix is not None:
        parameters += (path_prefix, path_prefix, path_prefix)
    parameters += (vector,)
    started = time.perf_counter()
    async with pool.connection() as connection, connection.transaction():
        if not exact:
            await connection.execute(
                "SELECT set_config('hnsw.ef_search',%s,true)", (str(ef_search),)
            )
            await connection.execute("SELECT set_config('hnsw.iterative_scan','strict_order',true)")
        cursor = await connection.execute(exact_sql if exact else approximate_sql, parameters)
        rows = await cursor.fetchall()
    return [f"{cast(tuple[str, int], row)[0]}:{cast(tuple[str, int], row)[1]}" for row in rows], (
        time.perf_counter() - started
    ) * 1000


async def vector_trials(
    pool: Pool,
    generation_id: UUID,
    queries: list[dict[str, str]],
    metric: Metric = "cosine",
    path_prefix: str | None = None,
    ef_values: tuple[int, ...] | None = None,
) -> dict[str, object]:
    """Preserve exact ground truth and three warm-cache ANN trials per ef_search."""
    vectors = [(item["id"], query_vector(item["query"])) for item in queries]
    for _, vector in vectors[:10]:
        await vector_top_ten(pool, generation_id, vector, exact=True, path_prefix=path_prefix)
        await vector_top_ten(
            pool, generation_id, vector, exact=False, metric=metric, path_prefix=path_prefix
        )
    ground_truth: dict[str, list[str]] = {}
    exact_raw: list[dict[str, object]] = []
    for key, vector in vectors:
        rows, ms = await vector_top_ten(
            pool, generation_id, vector, exact=True, path_prefix=path_prefix
        )
        ground_truth[key] = rows
        exact_raw.append({"id": key, "ms": round(ms, 3), "results": rows})
    sweep: dict[str, list[dict[str, object]]] = {}
    values = ef_values or ((400, 420, 450, 500) if path_prefix else EF_SEARCH_VALUES)
    for ef in values:
        trials: list[dict[str, object]] = []
        for trial in range(1, 4):
            raw: list[dict[str, object]] = []
            for key, vector in vectors:
                rows, ms = await vector_top_ten(
                    pool,
                    generation_id,
                    vector,
                    exact=False,
                    ef_search=ef,
                    metric=metric,
                    path_prefix=path_prefix,
                )
                recall = len(set(rows) & set(ground_truth[key])) / 10
                raw.append({"id": key, "ms": round(ms, 3), "recall_at_10": recall})
            trials.append(
                {
                    "trial": trial,
                    "p95_ms": percentile([numeric(row["ms"]) for row in raw]),
                    "mean_recall_at_10": round(
                        statistics.mean(numeric(row["recall_at_10"]) for row in raw), 4
                    ),
                    "raw": raw,
                }
            )
        sweep[str(ef)] = trials
    return {
        "exact": exact_raw,
        "exact_p95_ms": percentile([numeric(row["ms"]) for row in exact_raw]),
        "hnsw": sweep,
        "metric": metric,
        "path_prefix": path_prefix,
    }


async def search_trials(
    pool: Pool,
    principal_id: UUID,
    repository_id: UUID,
    queries: list[dict[str, str]],
    *,
    duration_seconds: float,
) -> list[dict[str, object]]:
    """Run 32 closed-loop clients for three timed trials after warm-up."""
    repository = PostgresRetrievalRepository(pool)
    service = RetrievalService(repository, MockEmbeddingProvider())
    requests = [SearchRequest(repository_id=repository_id, query=item["query"]) for item in queries]
    for request in requests[:10]:
        await service.search(request, principal_id)
    trials: list[dict[str, object]] = []
    for trial in range(1, 4):
        stop = time.perf_counter() + duration_seconds
        observations: list[dict[str, object]] = []
        errors: list[str] = []

        async def client(
            client_number: int,
            *,
            deadline: float = stop,
            trial_errors: list[str] = errors,
            trial_observations: list[dict[str, object]] = observations,
        ) -> None:
            index = client_number
            while time.perf_counter() < deadline:
                request = requests[index % len(requests)]
                started = time.perf_counter()
                try:
                    await service.search(request, principal_id)
                except Exception as error:
                    trial_errors.append(type(error).__name__)
                else:
                    trial_observations.append(
                        {
                            "id": queries[index % len(requests)]["id"],
                            "ms": round((time.perf_counter() - started) * 1000, 3),
                        }
                    )
                index += 32

        started = time.perf_counter()
        await asyncio.gather(*(client(number) for number in range(32)))
        elapsed = time.perf_counter() - started
        latencies = [numeric(row["ms"]) for row in observations]
        trials.append(
            {
                "trial": trial,
                "clients": 32,
                "elapsed_seconds": round(elapsed, 3),
                "completed": len(observations),
                "qps": round(len(observations) / elapsed, 3),
                "p95_ms": percentile(latencies) if latencies else None,
                "errors": errors,
                "raw": observations,
            }
        )
    return trials


async def measure(
    manifest: Path,
    loaded: Path,
    output: Path,
    duration: float,
    *,
    include_vector: bool = True,
    include_search: bool = True,
    metric: Metric = "cosine",
    pool_size: int = 10,
    path_prefix: str | None = None,
    single_ef: int | None = None,
) -> None:
    """Write phase results after each benchmark so an interruption retains evidence."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    scope = json.loads(loaded.read_text(encoding="utf-8"))
    queries: list[dict[str, str]] = data["queries"]
    if len(queries) < 200:
        raise ValueError("T12 requires at least 200 fixed queries")
    if not 1 <= pool_size <= 32:
        raise ValueError("pool_size must be between 1 and 32")
    if single_ef is not None and not 1 <= single_ef <= 1000:
        raise ValueError("single_ef must be between 1 and 1000")
    result: dict[str, object] = {
        "corpus": data["provenance"],
        "queries": len(queries),
        "profile": (
            "mock-embedding application search and database-only vector; no semantic-quality claim"
        ),
        "trial_seconds": duration,
        "pool_size": pool_size,
    }
    async with AsyncConnectionPool(
        os.environ["T12_DATABASE_URL"],
        min_size=min(4, pool_size),
        max_size=pool_size,
        open=False,
    ) as pool:
        generation_id = UUID(scope["generation_id"])
        if include_vector:
            result["vector"] = await vector_trials(
                pool,
                generation_id,
                queries,
                metric,
                path_prefix,
                (single_ef,) if single_ef is not None else None,
            )
            output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if include_search:
            result["application_search"] = await search_trials(
                pool,
                UUID(scope["principal_id"]),
                UUID(scope["repository_id"]),
                queries,
                duration_seconds=duration,
            )
            output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"queries": len(queries), "result": str(output)}))


def main() -> None:
    """Run the isolated scale measurement with explicit data/evidence paths."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--loaded", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trial-seconds", type=float, default=60.0)
    parser.add_argument("--skip-vector", action="store_true")
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--metric", choices=("cosine", "inner_product"), default="cosine")
    parser.add_argument("--pool-size", type=int, default=10)
    parser.add_argument("--path-prefix", choices=("cpython", "packages"))
    parser.add_argument("--single-ef", type=int)
    arguments = parser.parse_args()
    run = measure(
        arguments.manifest,
        arguments.loaded,
        arguments.output,
        arguments.trial_seconds,
        include_vector=not arguments.skip_vector,
        include_search=not arguments.skip_search,
        metric=arguments.metric,
        pool_size=arguments.pool_size,
        path_prefix=arguments.path_prefix,
        single_ef=arguments.single_ef,
    )
    if sys.platform == "win32":
        asyncio.run(run, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(run)


if __name__ == "__main__":
    main()
