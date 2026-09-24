# T11 public boundary and security review

T11 verifies the public API boundary and records repeatable source, dependency, secret, and image scans. It does not place RepoScope on the internet. The API remains bound to `127.0.0.1`; a funded HTTPS host, reverse proxy, domain, backup/restore, and rollback are T15 work.

## Public HTTP surface

Unauthenticated callers can use only `/healthz` and `/readyz`. Repository admission, job status, run admission/status/events, and search require the server-owned bearer token. Duplicate credentials fail, IDs and request bodies are validated, and the body limit is 64 KiB even without a trustworthy `Content-Length`. Public `/metrics`, OpenAPI, and interactive docs return 404. Business responses and errors have `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Content-Security-Policy: default-src 'none'`. TLS and HSTS belong at the future HTTPS proxy; no plaintext internet listener is authorized here.

The API alone publishes a host port, bound to localhost. PostgreSQL, Redis, NATS, worker management endpoints, and metrics have no host bindings. API and worker processes use UID 10001 and read-only roots. PostgreSQL uses its `postgres` user. Redis drops to UID 999. NATS now uses UID 10001 with a persistent JetStream volume; an existing local NATS volume required a one-time ownership update before recreation. Compose retains CPU/memory limits and separate internal backend, API ingress, and source egress networks. These are local container controls, not a substitute for a network firewall or a hosted TLS configuration.

## Scans and policy

On 2026-09-24, checksum-verified Trivy 0.74.0 scanned a source-only snapshot containing `uv.lock`, the built runtime image, and the three infrastructure images. The source scan found zero secret matches and zero dependency advisories. The built runtime, PostgreSQL, Redis, and NATS images had zero **fixable** high/critical findings after refreshing immutable Python/Redis/NATS digests, patching PostgreSQL's `libpcre2-8-0`, removing its unused `gosu` helper, and running PostgreSQL and NATS without root. No new Python dependency was added.

The same scan still reported 95 high/critical findings in the runtime image and 93 in PostgreSQL with no fixed version in the scanner data; Redis and NATS reported zero high/critical findings. These counts are point-in-time advisory results, not proof that every finding is exploitable or harmless. The remaining findings require re-evaluation before public hosting and whenever base images or advisory data change. A source or image scan failure must not be described as a clean result.

CI now uses a checksum-pinned Trivy binary to scan the checked-out source and all four built/pinned images. `scripts/security_report.py` fails on any secret match or fixable high/critical finding and prints only counts. The existing Gitleaks job checks committed history separately. CI results for the remote GitHub commit are reported only after observing that run; local scans do not imply remote CI success.

## Remaining security work

T15 must select a host and install HTTPS termination with its own request/time limits, firewall rules, HSTS policy, persistent-volume backup/restore, and rollback test before any internet-facing exposure. Advisory findings without a current fix remain an explicit release review item. No live provider key, paid call, or public deployment was used for T11 verification.
