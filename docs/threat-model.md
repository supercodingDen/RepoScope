# Threat model

## Assets and trust boundaries

Assets: OpenAI and deployment credentials; source provenance; task/result integrity; model/embedding spend; availability; persistent data and audit evidence. Trust boundaries: public HTTP, third-party repositories, broker messages, provider responses, privileged deployment tooling, and untrusted pull requests.

Public source and model output are untrusted data. A public repository can still contain secrets, malicious instructions, symlinks, crafted parser inputs, or enormous files. Public availability is not consent to unrestricted redistribution or execution.

| Threat | Required mitigation | Verification owner |
| --- | --- | --- |
| Disclosed credentials | Revoke outside the project; enter replacement directly into local secret storage; .env excluded from Git, images, archives, and logs | T01/T11 |
| SSRF and credential forwarding | Canonical GitHub URLs only; verified DNS/egress; no private/link-local/metadata destinations; disallow unsafe redirects and credentials; isolate Git environment | T05 |
| Path/symlink traversal | Reject unsafe wire paths and resolve filesystem containment without following escapes; never accept API local paths | T05/T08 |
| Git hooks/config execution | Argument-array subprocesses; isolated HOME/config; hooks disabled; no recursive submodules/LFS/smudge filters; no repo build/install | T05 |
| Parser and archive exhaustion | Size/count/disk/time quotas; bounded parser executor; kill process tree and clean temporary state; no unrestricted archive extraction | T05/T06 |
| Prompt injection in code/comments | Untrusted-data framing; read-only typed tools; server-pinned repo scope; no shell/browser/remote-fetch tool; validate citations | T08 |
| SQL or tool argument injection | Parameterized queries; typed schemas; allowlisted filters/tool names; reject unknown fields | T03/T07/T08 |
| Unauthorized or cross-scope reads | Server-side principal and resource check, same-generation tool context, no client-selected scope override | T03/T08/T11 |
| Billing abuse and retry storms | Paid mode off by default; atomic shared budget reservation; finite model/embedding attempts; token caps; fail closed on unknown price or unavailable admission | T08/T10 |
| Duplicates and stale writers | Outbox, renewable leases, atomic fencing checks, unique source locations, completion before ACK | T04/T06 |
| Partial/stale search results | Isolated generations; atomic publication; runs pin generation; cache keys include all revisions and filters | T06/T07 |
| Leaky errors/logs/traces | Standard problem bodies; secrets and source/prompt text redacted; no sensitive tracing by default | T02/T10 |
| Public infrastructure ports | Private DB/broker/cache/worker metrics; HTTPS entry only; least-privilege credentials and non-root containers | T11/T15 |
| Dependency/CI compromise | Locked packages; reviewed image digests and CI action SHAs; no secrets for fork PRs; no privileged pull_request_target execution of untrusted code | T02/T11/T14 |
| Data loss | Durable volumes and off-host backup; restore test; outbox/job reconciliation; tested migration/rollback | T15 |

Residual limits: a single-host installation has a single failure domain; static dependency analysis is incomplete; prompts cannot guarantee elimination of every injection attempt; provider response and billing behavior are external dependencies. Read-only capabilities and quotas reduce impact without making absolute security claims.

## Secret handling status

No credential supplied in chat is copied into this repository or its deliverables. The developer's local `.env` is ignored by Git and Docker build context; it may contain locally generated credentials and must never be read, copied, scanned, or uploaded by source tooling. A credential disclosed elsewhere is not revoked by exclusion from source control; its account owner must rotate it outside the project. Do not request a replacement credential in chat.
