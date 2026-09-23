"""Demonstrate public GitHub import through a final cited answer using REST/SSE."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from uuid import uuid4

import httpx


async def _response_json(response: httpx.Response) -> dict[str, object]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("The API returned an invalid response")
    return value


async def demonstrate(
    client: httpx.AsyncClient,
    repository_url: str,
    question: str,
    token: str,
    *,
    timeout_seconds: float = 1800,
    poll_seconds: float = 2,
) -> str:
    """Submit, wait, and resume streaming until the durable terminal event arrives."""
    deadline = time.monotonic() + timeout_seconds
    headers = {"Authorization": f"Bearer {token}"}
    accepted = await _response_json(
        await client.post(
            "/v1/repositories",
            json={"url": repository_url},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
    )
    repository_id, job_id = str(accepted["repository_id"]), str(accepted["job_id"])
    while time.monotonic() < deadline:
        job = await _response_json(await client.get(f"/v1/jobs/{job_id}", headers=headers))
        if job["status"] == "succeeded":
            break
        if job["status"] == "failed":
            raise RuntimeError(f"Import failed: {job.get('failure_code')}")
        await asyncio.sleep(poll_seconds)
    else:
        raise TimeoutError("Repository import did not finish in time")
    run = await _response_json(
        await client.post(
            "/v1/runs",
            json={"repository_id": repository_id, "question": question},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
    )
    run_id = str(run["run_id"])
    cursor: str | None = None
    while time.monotonic() < deadline:
        stream_headers = {**headers, "Accept": "text/event-stream"}
        if cursor is not None:
            stream_headers["Last-Event-ID"] = cursor
        try:
            async with client.stream(
                "GET", f"/v1/runs/{run_id}/events", headers=stream_headers
            ) as response:
                response.raise_for_status()
                event_name = ""
                payload = ""
                pending_id: str | None = None
                async for line in response.aiter_lines():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Run did not finish in time")
                    if line.startswith("id: "):
                        pending_id = line[4:]
                        if not pending_id.startswith(f"{run_id}:"):
                            raise ValueError("The stream returned a foreign event cursor")
                    elif line.startswith("event: "):
                        event_name = line[7:]
                    elif line.startswith("data: "):
                        payload = line[6:]
                    elif line == "" and event_name:
                        data = json.loads(payload).get("data", {})
                        if pending_id is not None:
                            cursor = pending_id
                        if event_name == "run.failed":
                            raise RuntimeError(f"Run failed: {data.get('code', 'unknown')}")
                        if event_name == "run.completed":
                            result = data["result"]
                            lines = [str(result["answer"])]
                            for citation in result["citations"]:
                                lines.append(
                                    f"- {citation['path']}:{citation['start_line']}-"
                                    f"{citation['end_line']} ({citation['commit_sha']}, "
                                    f"chunk {citation['chunk_id']})"
                                )
                            return "\n".join(lines)
                        event_name = payload = ""
                        pending_id = None
        except httpx.TransportError:
            pass
        await asyncio.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
    raise TimeoutError("Run did not finish in time")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import public GitHub code and get a cited answer")
    parser.add_argument("repository_url", help="Canonical public https://github.com/owner/repo URL")
    parser.add_argument("question")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    token = os.environ.get("REPOSCOPE_API_TOKEN")
    if not token:
        parser.error("Set REPOSCOPE_API_TOKEN before running the demo")

    async def execute() -> str:
        async with httpx.AsyncClient(base_url=args.api_url, timeout=20) as client:
            return await demonstrate(client, args.repository_url, args.question, token)

    try:
        print(asyncio.run(execute()))
    except (httpx.HTTPError, TimeoutError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Demo failed: {error}\n")


if __name__ == "__main__":
    main()
