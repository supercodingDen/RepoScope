"""Measure mock embedding batch size and worker concurrency on real chunks."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys
import time
from pathlib import Path

from bench.t12_corpus import corpus_files
from reposcope.adapters.embedding import MockEmbeddingProvider
from reposcope.domain.indexing import EmbeddingBatch, embedding_input


def batches(inputs: list[tuple[str, int]], limit: int) -> list[EmbeddingBatch]:
    """Pack source chunks within production item and token ceilings."""
    if limit < 1 or limit > 32:
        raise ValueError("Batch limit must be between 1 and 32")
    packed: list[EmbeddingBatch] = []
    current: list[tuple[str, int]] = []
    tokens = 0
    for item in inputs:
        if current and (len(current) == limit or tokens + item[1] > 20_000):
            packed.append(
                EmbeddingBatch(tuple(x[0] for x in current), tuple(x[1] for x in current))
            )
            current = []
            tokens = 0
        current.append(item)
        tokens += item[1]
    if current:
        packed.append(EmbeddingBatch(tuple(x[0] for x in current), tuple(x[1] for x in current)))
    return packed


async def trial(items: list[EmbeddingBatch], concurrency: int) -> dict[str, float | int]:
    """Run one bounded producer/consumer pass without paid provider calls."""
    provider = MockEmbeddingProvider()
    slots = asyncio.Semaphore(concurrency)

    async def process(batch: EmbeddingBatch) -> None:
        async with slots:
            await provider.embed(batch)

    started = time.perf_counter()
    await asyncio.gather(*(process(batch) for batch in items))
    elapsed = time.perf_counter() - started
    count = sum(len(item.inputs) for item in items)
    return {
        "chunks": count,
        "batches": len(items),
        "seconds": round(elapsed, 3),
        "chunks_per_second": round(count / elapsed, 3),
    }


async def measure(output: Path) -> None:
    """Write three warm-cache trials for each batch/concurrency setting."""
    files = list(
        corpus_files(
            Path(os.environ["T12_PYTHON_LIB"]),
            Path(os.environ["T12_SITE_PACKAGES"]),
            Path(os.environ["T12_PYTHON_TOOLS"]),
            target_chunks=1000,
        )
    )
    inputs = [
        (embedding_input(item.chunk), item.chunk.token_count)
        for file in files
        for item in file.chunks
    ]
    result: dict[str, object] = {
        "profile": "real source chunks, mock embeddings, no database write or provider call",
        "files": len(files),
        "chunks": len(inputs),
        "trials": [],
    }
    trials: list[dict[str, object]] = []
    for batch_size in (8, 16, 32):
        packed = batches(inputs, batch_size)
        for concurrency in (1, 2, 4):
            await trial(packed[:2], concurrency)
            observations = [await trial(packed, concurrency) for _ in range(3)]
            trials.append(
                {
                    "batch_limit": batch_size,
                    "worker_concurrency": concurrency,
                    "observations": observations,
                }
            )
    result["trials"] = trials
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Run the source-only microbenchmark with explicit local source roots."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run = measure(arguments.output)
    if sys.platform == "win32":
        asyncio.run(run, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(run)


if __name__ == "__main__":
    main()
