# ADR-005: AST-aware retrieval and bounded Luna-first analysis

Status: accepted for v1. Date: 2026-09-16.

The user requested AST parsing, OpenAI embeddings, dependency expansion, and economical model routing. Choose Tree-sitter for Python and TypeScript/TSX first, with explicitly labeled token/line fallback for other languages and syntax errors. Retain parse fallback diagnostics and original line spans.

Use text-embedding-3-small with dimensions=384. This replaces local sentence-transformers in the earlier roadmap, avoids a required local neural-model runtime, and adds a paid external dependency. Mock mode remains available, but mock embeddings cannot establish real retrieval quality. Estimate full-corpus cost before live indexing.

Use exact/FTS/HNSW retrieval followed by a single bounded dependency hop. Static imports/references are evidence hints, not a complete call graph. Impose total context limits before every model call. Never send an entire repository to fill a provider's large context window.

Prefer Luna. Terra is a conditional, budget-authorized escalation; Sol is disabled by default. Do not implement random 80/18/2 routing. Use official AsyncOpenAI behind a typed provider adapter instead of simultaneously adopting an agent framework and custom orchestrator.

Consequence: AST grammar/tokenizer/model revisions are part of index identity; changing them requires a new generation and repeat evaluation. Price/account availability is checked again before live operation.
