# T09 run events and CLI demo

An admitted run now records ordered `run.started`, `tool.started`, `tool.completed`, and terminal `run.completed` or `run.failed` events in PostgreSQL. Terminal event insertion shares the result/failure transaction. Existing terminal runs receive a single terminal event during migration `0007_run_events`.

With the public API running, use the same bearer token as the other API calls:

```text
GET /v1/runs/{run_id}/events
Authorization: Bearer <token>
Accept: text/event-stream
```

The stream replays persisted events, then follows new ones. Resume by sending the last received `id` as `Last-Event-ID: <run-id>:<sequence>`. It closes after a terminal event. A terminal timeline is readable for 24 hours; a later request returns HTTP 410. PostgreSQL leases limit concurrent streams to two per principal and twenty total. Streams emit keep-alive comments and have a three-minute maximum lifetime; reconnect with the cursor as needed.

The agent augments initial search results with at most four chunks from one static dependency hop. Only Python and local TypeScript import metadata is resolved, and target paths must be present in the admitted generation's source manifest. Combined evidence retains the twelve-chunk and 8,000-token limits. External and dynamic imports are skipped.

The CLI exercises the public API from import to answer. Set `REPOSCOPE_API_TOKEN` in your local environment, then run:

```text
uv run --frozen python scripts/demo.py https://github.com/pallets/itsdangerous "Where is URL-safe signing implemented?" --api-url http://127.0.0.1:8000
```

Use a canonical public GitHub repository URL without a `.git` suffix. The command waits for indexing, submits the question, reconnects to the event stream with its cursor if needed, and prints the answer and immutable citation locations. The default mock provider makes no paid calls and supplies a source excerpt; use explicitly configured live providers only when desired. Import and run share a 30-minute CLI deadline.
