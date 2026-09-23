# T06 independent review

Date: 2026-09-23 UTC. Scope: read-only review of the T06 design, event handoff, migration, indexing/storage, provider budget and tests. The reviewer found no authorization, fencing or atomic-publication defect.

The first pass identified two Important issues: cancellation released an indexer slot while a file thread could continue, and each blob read scanned the entire manifest for membership. Both were fixed. Cancellation now signals a monitor and waits for the thread to finish before releasing the slot; a regression test first reproduced the bug and then passed. `SourceSnapshot` builds a file lookup once, making subsequent membership checks constant time. The reviewer also prompted coverage of both historical two- and three-subject NATS topologies and a fresh paid-price check on every reservation. Those cases now have passing tests. Index service dependencies were moved behind typed ports.

The closure review found no remaining Critical or Important issue and no review blocker to synchronization. It did not perform paid calls, Linux/Compose execution or a 50,000-row PostgreSQL/HNSW load. Those limits are reported in [project status](../project-status.md).
