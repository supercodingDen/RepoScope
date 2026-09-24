# Deployment status and prerequisites

There is **no hosted RepoScope deployment** yet. `compose.yaml` is a localhost development and test stack; it does not install HTTPS, firewall rules, off-host backups, or a rollback procedure. Do not publish its API port on the internet as a shortcut. Public GitHub release is T14 and a verified single-host deployment is T15.

Before T15, the owner must select a Linux VM and spending limit, control a domain/DNS name, provide an HTTPS certificate or a trusted automatic certificate issuer, and choose an off-host backup destination. The operator must install protected runtime secrets outside source control, restrict ingress to the HTTPS proxy, and keep PostgreSQL, NATS, Redis, worker management, and metrics private. The repository must first have a reviewed release commit, immutable image digests, and a recorded advisory assessment.

T15's implementation must add a production Compose/proxy configuration, durable disk and log policies, database backup and restore scripts, and a forward-compatible rollback procedure. It must verify external authenticated HTTPS, a permitted sample import, live agent behavior with explicit cost approval, SSE replay, restart persistence, isolated restore, and rollback against the actual release SHA. A successful localhost Compose test does not satisfy those checks.

For current local operation, follow [development](development.md) and [recovery](failure-modes.md). The current [project status](project-status.md) records measured checks and open gates. The T12 HNSW migration can take several minutes on a 100K-chunk database; schedule an indexing write pause and a backup before any production upgrade. Never assume a schema downgrade is safe.
