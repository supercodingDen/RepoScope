"""Measure a real HTTP non-search endpoint without authentication data."""

from __future__ import annotations

import argparse
import asyncio
import json
import selectors
import sys
import time
from pathlib import Path

import httpx

from bench.t12_measure import percentile


async def measure(url: str, output: Path) -> None:
    """Run three 32-client HTTP trials against the read-only health endpoint."""
    if url != "http://127.0.0.1:8000/healthz":
        raise ValueError("The benchmark only supports the local public health endpoint")
    result: dict[str, object] = {
        "profile": "real loopback HTTP, development API container, non-search health endpoint",
        "url": url,
        "clients": 32,
        "requests_per_trial": 2000,
        "trials": [],
    }
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)
    async with httpx.AsyncClient(limits=limits, timeout=10.0) as client:
        for _ in range(100):
            response = await client.get(url)
            if response.status_code != 200:
                raise RuntimeError("Health endpoint did not return 200")
        trials: list[dict[str, object]] = []
        for trial in range(1, 4):
            slots = asyncio.Semaphore(32)
            raw: list[float] = []
            errors: list[str] = []

            async def request(
                *,
                trial_slots: asyncio.Semaphore = slots,
                trial_errors: list[str] = errors,
                trial_raw: list[float] = raw,
            ) -> None:
                async with trial_slots:
                    started = time.perf_counter()
                    try:
                        response = await client.get(url)
                        if response.status_code != 200:
                            trial_errors.append(f"HTTP {response.status_code}")
                        else:
                            trial_raw.append(round((time.perf_counter() - started) * 1000, 3))
                    except httpx.HTTPError as error:
                        trial_errors.append(type(error).__name__)

            started = time.perf_counter()
            await asyncio.gather(*(request() for _ in range(2000)))
            elapsed = time.perf_counter() - started
            trials.append(
                {
                    "trial": trial,
                    "elapsed_seconds": round(elapsed, 3),
                    "completed": len(raw),
                    "qps": round(len(raw) / elapsed, 3),
                    "p95_ms": percentile(raw) if raw else None,
                    "errors": errors,
                    "raw_ms": raw,
                }
            )
        result["trials"] = trials
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Run the local endpoint profile with raw per-request timings."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run = measure("http://127.0.0.1:8000/healthz", arguments.output)
    if sys.platform == "win32":
        asyncio.run(run, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(run)


if __name__ == "__main__":
    main()
