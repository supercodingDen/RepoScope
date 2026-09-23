# RepoScope engineering contract

Read docs/spec.md, docs/architecture.md, docs/project-status.md, and the relevant ADR before edits. T01 authorizes specifications and executable contract validation only. Do not implement T02 or later without a new task instruction.

- Use English for identifiers, docstrings, documentation, messages, logs, commit messages, UI, and deployment files. Only source comments may be Chinese.
- Python is the v1 application language. Every function and method, including scripts, tests, fixtures, and constructors, has complete type annotations. Enforce mypy strict; do not use Any or blanket ignores to bypass validation.
- If TypeScript is added, use strict mode, noUncheckedIndexedAccess, noImplicitAny, no-explicit-any, and no-unsafe-* rules. Validate unknown external values before use.
- Controllers only validate/authenticate/delegate/serialize. Services own workflows, repositories own persistence, and provider adapters own external SDK calls. Domain code imports no transport, database, message, or model SDK.
- HTTP and database I/O use async clients. CPU parsing and blocking file operations run outside the event loop with bounded concurrency. Cancellation must propagate.
- Map errors once at HTTP and worker boundaries. Log safe structured context with request_id, job_id, run_id, event_id, and error_code. Never log credentials, full source files, or prompts by default.
- Long tasks require deadlines, leases, fencing, idempotent checkpoints, and bounded retries. Complete the business transaction before acknowledging a durable event.
- Never run code, builds, hooks, plugins, or package installers from an ingested repository.
- Never read, print, copy, commit, upload, or package .env or secret-bearing files. The developer manages secrets locally. Keep .env.example empty for secret values. Never reuse credentials disclosed in chat.
- Default to mock providers and zero paid calls. Live profiles require ALLOW_PAID_API_CALLS=true, a locally configured key, verified prices, and atomic budget admission. Do not silently upgrade models.
- Prefer gpt-5.6-luna for routine product tasks. Terra escalation is conditional; Sol requires explicit enablement. The 80/18/2 split is an observation target, not random traffic routing.
- Do not use a whole repository as model context. Enforce retrieval, one-hop bounded dependency expansion, and the shared token budget.
- Declare dependencies before implementation, commit uv.lock, and use uv sync --frozen --all-groups. Do not add unreviewed libraries or floating deployment images.
- Generated schemas are derived from contracts/models.py. Run scripts/export_contracts.py after contract changes; review generated diffs and negative examples.
- Tests must cover observable contracts, failure semantics, and security boundaries. Do not fabricate live-provider checks, deployment status, or benchmark results.
- Update docs/project-status.md with evidence and the next task. After each complete task, synchronize reviewed files to the owner's private GitHub RepoScope repository after tests and secret checks, as authorized on 2026-09-23. Public publication and a versioned release remain T14; hosted deployment remains T15. Never claim any remote result based on local files alone.
