# T07 independent review

Date: 2026-09-23 UTC. A read-only reviewer checked the T07 design, scoped PostgreSQL queries, HTTP composition, query embedding budget, ranking, citations and tests. The first pass found one Important issue: a global HNSW index could underfill a narrow generation/path scope after filtering, even when exact matches existed. The query now performs a scoped exact top-50 fallback whenever the approximate vector path returns fewer than 50 candidates. The fallback uses the same filters and a materialized scoped CTE to avoid the global ANN path.

A new test compares filtered public search with exact results across old and active generations, and a unit test pins the underfill policy. The reviewer checked the fix and reported no remaining Critical or Important issue. Review does not establish 100K filtered ANN recall, Docker behavior or live-provider latency; those remain open.
