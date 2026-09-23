# ADR-004: Replace the proposed Go API with FastAPI

Status: accepted under user-delegated architecture choice. Date: 2026-09-16.

The earlier roadmap used Go plus Python workers and a private retrieval HTTP interface. The user's T01 instruction proposed FastAPI and delegated the final architecture decision. The owner primarily uses Python and has a short solo delivery window.

Choose FastAPI API plus independently deployed Python indexer and agent processes. Share typed contracts and RetrievalService in one Python package. This removes duplicate DTOs and an internal network retrieval hop while retaining process isolation, asynchronous delivery, outbox, bounded concurrency, and reliable task state.

Alternatives: retain Go for language breadth and a compiled control plane, at the cost of two build ecosystems and more interfaces; or put everything in FastAPI background tasks, which does not provide the required durable worker semantics. Neither is selected for v1.

Consequence: do not claim Go experience from this implementation. CPU parsing stays off the API event loop; role resource limits and independent worker processes are mandatory. If real profiling justifies a dedicated Go gateway later, introduce it through a measured ADR, not a resume-driven rewrite.

The original cross-language gate is replaced by canonical producer/consumer schema fixtures. A future TypeScript frontend consumes generated OpenAPI types with strict validation. No redundant internal retrieval API is maintained.
