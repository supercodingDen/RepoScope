# Models, context, and cost policy

Policy version: routing-v1. Documentation checked on 2026-09-16. The public API identifiers below were found in official model pages; account-specific availability has not been tested. No dated immutable snapshot was listed on the reviewed Luna page, so do not invent one. Record the provider-returned model ID and date in every real evaluation.

| Role | API model | Standard input/output USD per 1M tokens | Default |
| --- | --- | --- | --- |
| Routine code questions and reports | gpt-5.6-luna | 0.20 / 1.20 | First choice |
| Harder multi-file analysis | gpt-5.6-terra | 2.00 / 12.00 | Escalation disabled until enabled |
| Selected expert analysis | gpt-5.6-sol | 4.00 / 20.00 | Disabled |
| Code/query embeddings | text-embedding-3-small | 0.02 input | Live mode disabled |

Sources: [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [embeddings model](https://developers.openai.com/api/docs/models/text-embedding-3-small). These are a dated planning price snapshot, not a permanent price guarantee; no cache or batch discount is assumed in the initial reserve calculation. Recheck prices before enabling paid mode and after the configured 30-day price-validity period. Sol's listed promotional price is time-limited.

The official Luna page lists a 1,050,000-token context window and higher full-request rates above 272K input tokens: 2x input and 1.5x output. The application imposes a much smaller 24,000-input-token limit per model call; that count includes system instructions, tool schemas/results, retained conversation, and source evidence. A large provider context window is not the application memory strategy.

The [embedding guide](https://developers.openai.com/api/docs/guides/embeddings) lists 1536 as text-embedding-3-small's default dimension and supports an explicit dimensions parameter. We request 384 to preserve the earlier benchmark shape and reduce vector storage. This does not establish equivalent retrieval quality to 1536; compare quality empirically before changing dimensions. A dimensions/model change creates a new embedding-space version and requires complete reindexing, never mixing vectors in one generation.

## Routing algorithm contract

1. Retrieve bounded evidence from the admitted generation before the first model call. One-hop dependency expansion is scheduled for T09; T08 does not claim it.
2. Start with Luna at low reasoning effort for routine locate/explain tasks. Use the official Responses API with validated function tools and structured final output; keep the SDK in one adapter.
3. Validate citations, output structure, and whether the requested analysis has adequate evidence. Missing evidence triggers one bounded retrieval expansion or an insufficient-evidence result, not an automatic larger-model call.
4. A complex multi-file task with adequate evidence but invalid/inadequate output may use Terra only if the operator enables escalation, permits the model, and reserves the worst-case next call within all budgets. All retries/escalations count toward the same six model-attempt ceiling.
5. Sol requires explicit operator enablement for a selected run and sufficient remaining budget. Never spend just to achieve an 80/18/2 distribution.
6. Authentication, unavailable-model, and budget errors fail visibly. A 429/timeout uses bounded same-model retry only when a reservation permits; there is no hidden expensive fallback.

The desired high Luna share is measured after real traffic; the proposed 80/18/2 ratios are not quotas. Record model, route reason, estimated/actual token use, latency, and cost without logging source or prompts.

## Context management

AST boundaries → bounded chunks → embeddings → hybrid search → deduplication → token budgeting → model analysis. Same-generation one-hop dependency expansion is planned for T09.

Use at most 12 evidence chunks and 8,000 evidence tokens, including expanded dependencies. A tool response is bounded by both tokens and bytes/characters. Compact step history by dropping already-referenced duplicate source and retaining identifiers and safe observations, not model-generated hidden reasoning. Reject a request when the complete model payload cannot fit within the cap; never silently exceed it.

The initial six model attempts and 2,000 max output tokens cap include reasoning tokens as reported/billed by the provider. Use provider token-counting capabilities or a validated model tokenizer when available; use a documented conservative estimator and margin otherwise. Do not assume the embedding tokenizer exactly predicts GPT model token use.

## Budget accounting

Use decimal or integer micro-USD amounts; never binary float money. Before every external attempt, atomically reserve estimated uncached input plus worst-case allowed output and a 20% estimation margin across run, UTC day, and deployment lifetime. Shared counters reside in PostgreSQL. Embedding calls, including search query embeddings and retries, use the same global budget and their own operation reservation.

Set OpenAI SDK automatic retries to zero so retries cannot bypass the application's attempt/cost ledger. On success, settle provider-reported usage. On timeout after dispatch, retain an uncertain reservation until reconciled; do not assume the provider did no work. Reject new paid work on exhausted budget, missing/expired prices, or unavailable admission storage. The project budget is a conservative application control, not a guarantee of the provider's final invoice.

Default limits are USD 0.10/run, 1.00/UTC day, and 4.00/deployment lifetime, with live mode off. Full-corpus indexing requires a preflight token/cost estimate and may require an explicit operator increase. For example, 100K chunks averaging 500 billed tokens represent roughly 50M embedding tokens before extra query/retry costs; reducing vector dimensions does not reduce billed input tokens.

## SDK choice

Use the official OpenAI Python SDK AsyncOpenAI and a small typed tool loop behind AgentProvider. Do not add Agents SDK and a custom loop simultaneously. The earlier Agents SDK recommendation is replaced by this minimal adapter for direct control over routing, retries, budgets, and durable run state. A future framework swap must preserve the same contracts.
