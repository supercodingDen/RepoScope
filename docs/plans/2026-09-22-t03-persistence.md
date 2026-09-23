# T03 implementation brief and execution record

## Authority and scope
The owner explicitly requested T03 on 2026-09-22 and retains authorization for direct edits in D:\RepoScope_project\reposcope. No commit/push, Git initialization, secret-file access, paid calls, source cloning, broker publication/consumption, search, SSE or T04+ worker behavior. T01 accepted Python spec/ADR supersedes the original Go roadmap. Read AGENTS.md, docs/spec.md, docs/architecture.md, docs/contracts.md, docs/adr/003-outbox.md and contracts/models.py.

Do not read .env or credential files. Tests supply synthetic credentials in memory. All repository prose/code/docstrings/messages English; fully annotated Python, strict mypy including scripts/tests; no Any or blanket ignores. Existing dependency lock remains unchanged.

## Acceptance
POST /v1/repositories -> RepositoryAccepted 202; GET /v1/jobs/{job_id} -> JobView.
POST /v1/runs -> RunAccepted 202; GET /v1/runs/{run_id} -> RunView.
All business routes require constant-time bearer authentication using REPOSCOPE_API_TOKEN. One configured server-owned principal UUID (REPOSCOPE_PRINCIPAL_ID, stable explicit default) is used; clients cannot supply their own principal. Missing token configuration disables business access safely without breaking public health. Other-principal objects return404. Management app does not register business routes.

Both POSTs require Idempotency-Key 1-128 printable non-space ASCII characters. Canonical validated request JSON includes defaults; whitespace/key order must not change identity. Scope unique on principal+route+key. Same fingerprint replays original202 body/IDs (even after current generation changes); mismatched fingerprint409. Idempotent lookup/replay occurs before capacity, budget and generation re-evaluation. At least seven-day retention and until terminal; T03 may retain indefinitely with no destructive cleanup.

100 concurrent same-key same-body requests must create exactly one job, one generation, one idempotency result and one outbox event. Same guarantee for run, including a single reservation. Different-body races result in one winner and409 losers. Force outbox insertion failure in a real DB transaction (test trigger or constraint), prove NO repository/job/generation/idempotency/reservation residue. No test-only switches in production.

## Layering / ownership
Application services perform business policy/request hashing. Typed repository Protocol(s) hide persistence. PostgreSQL adapters own SQL/transactions; transport authenticates, validates, delegates and serializes. Domain errors have no transport/database imports; central HTTP mapper uses existing ErrorCode/Problem. Use JSON parsing through validated typed contracts at DB boundaries, no unsafe tuple/Any bypass.

One new migration 0002_core.sql under existing owner; do not alter applied0001. Tables: repositories, source_revisions, index_generations, jobs, agent_runs, outbox_events, idempotency_requests, consumer_work and usage_reservations plus a small transactional admission/budget lock row if useful. Schema must support later leases/fencing/attempts/deadlines without implementing T04 processing. FK/check/unique constraints preserve repository/generation/principal references and status/result invariants. Source/chunk vector storage remains T06.

Create pending ingestion generation plus queuedjob and update repository latest-requested pointer atomically. Revision SHA is unknown until T05; API never resolves a network ref. IngestRequested aggregate=job_id, payload principal/repo/job/ref, event_id+trace_id+occurred_at populated as canonical contract. Use persistent application-generated IDs (uuid4) and UTC timestamps; no wire secrets.

Run submission requires an owned repository and its active ready generation with a pinned SHA, else404/INDEX_NOT_READY409. Pin generation+SHA in run/event and persist question only in run row, not outbox event. AgentRequested matches canonical model policy routing-v1. Ready-generation fixtures are created only in integration tests using operator SQL, not a public endpoint.

Capacity limit100 pending queued/running jobs/runs (document whether shared; use shared deployment cap). Protect admission checks by a DB lock, not process locks. Provider budgets are exact Decimal/numeric(18,6): request0.10/day1.00/project4.00 defaults, retained reserved/settled/uncertain amounts count conservatively, released do not. Mock-mode reservations amount0 by default because no paid work occurs. Permit injected typed admission policy in unit/integration tests to exercise nonzero conservative reservations; public request cannot choose cost/policy. Schema and atomic DB admission must support nonzero budget reservations without enabling live model calls. Reservation+run+outbox+idempotency commit together. Daily window is UTC; project accounting across all principals (single deployment). Use finite statement/lock/operation timeouts. Do not hold transactions across network/model calls.

## Runtime integration
Reuse/extend bounded runtime PG pool; don't add a second pool exceeding API10. Construct application service/PG adapter in composition root, inject public app only. Existing create_health_application tests must remain possible with probe doubles. Update readiness required migration to0002_core and adjust migration/readiness fixtures deliberately. Preserve all T02 checks/private metrics/signal behavior.

Limit business request body to64KiB including streamed/chunked payloads; never rely solely on Content-Length. Bound middleware reading and preserve canonical413 and request ID. Invalid JSON/UUID/body422 without input echo; unknown route404, method405+Allow, auth401+WWW-Authenticate, backend unavailable503 safe, invariant/unexpected500 safe. Don't expose DSNs/questions/raw exception text. Avoid framework automatic type coercion defeating strict contracts. Response shape/status matches exported OpenAPI.

API token settings are optional for health-only startup and required by business authentication. Compose must pass token from an empty-secret .env.example placeholder; smoke can generate temporary in-memory token to enable full T03 acceptance. No production reading/writing .env.

## Required tests
Test-first, record red/green then:
- Offline HTTP/auth/validation/body bound/cancellation/error mapping with a small typed test repository; no in-memory implementation claimed as durable.
- Real PG tests under RUN_INTEGRATION_TESTS=1 and MIGRATION_DATABASE_URL/DATABASE_URL/APP_DATABASE_PASSWORD: migrate baseline+core, runtimeDML/noDDL, creation/get persistence, owner isolation,100 concurrent requests (actual ASGI withPG adapter), semantically equivalent JSON replay, changedbody409, route/principal scoping, expired-key preservation whileworkpending, distinctkeys legitimatejobs, queuedrun guard, seededreadygeneration pinnedrun, duplicate run singleevent/reservation, budget/admission races, forcedrollback noorphans, backendfailure safe.
- Real integration tests explicitly enabled but missing config must fail, notskip.
- Entire pytest suite, export_contracts --check, validate_contracts, Ruff format/check, full mypy (not onlysrc), compile checks.
- Parent handles real database provisioning, smoke/CI/docs final evidence and independent review. Communicate exact public constructors, table/schema columns needed by integration fixtures, and any config changes early.

## Execution tasks
1. Write failing core schema/transaction integration tests, implement migration and typed persistence/application boundary.
2. Write failing HTTP/auth/idempotency/budget regressions, implement thin controllers and composition wiring.
3. Run full offline gates; run realPG tests when parent supplies ephemeral URLs. Give report with exact evidence and outstanding limitations, never claim unrun checks.

## Preflight decisions
- Direct checkout/no commits per owner; no worktree created because owner wants VS Code edits in place.
- User's explicit T03 request authorizes proceeding despite outstanding T02 Docker acceptance. Keep that gate truthfully open; do not fabricate it.
- Mock providers remain zero-cost; nonzero budget arithmetic is exercised using injected operator policy, not public cost fields.
- Database-level lock for admission is deliberately simple for this milestone; profiling/optimization belongs to T12.
