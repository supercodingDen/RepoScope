# Demo execution ledger — plan: docs/superpowers/plans/2026-11-17-demo.md

Baseline: a856be4e0db793d6118391d65b2236e853ff3c62; 389 tests passed, 80 skipped.

Ruling: Work in the owner's opened D-drive folder on feat/interactive-demo, as explicitly requested; initialize Git metadata from public origin without checking out files. Existing edits in migrations 0003 and 0004 are preserved and excluded from commits.

Pre-flight: Task 1 produces schema_version=1 recordings; Task 2 validates that exact interface; Task 3 deploys only the Task 2 static build. No public HTTP contract changes are needed.

Ruling: The shell-oriented skill bookkeeping scripts are replaced by this durable English ledger on Windows; the approved scope and test-before-code gates remain in force.

Task 1: capture/export tests observed RED before implementation; three mock-only Docker recordings passed. Reconnection observed real events 3 and 4. Upstream license retained.

Task 2: browser tests observed missing-interface failures, then passed for evidence selection, case/timer reset, invalid data, mobile overflow and keyboard access. Frontend build, strict types, lint and npm audit passed.

Final review: independent read-only review by demo_final_review, 2026-11-17. No critical findings. Important findings reproduced before fixes: extra source lines, duplicate evidence IDs, non-mock/repeated starts, missing resume/case requirements, unapproved changed excerpts, unchecked wire cursors, and caller-supplied source provenance. Regression tests first failed, then passed after strict validation, independent upstream excerpt approval, wire-ID parsing and internal Git-archive creation. Vite dotenv loading is explicitly disabled.

Final: Ruling: Treat the review's keyboard-tab, production-prefix test, benchmark-date and source-notice items as acceptance defects rather than deferred polish; these affect the approved accessibility, deployment, provenance and attribution requirements. Added roving keyboard tabs, built-site /RepoScope/ browser testing, the historical date and corrected redistribution notices. Cost is a small localhost-only test server and additional regression coverage.

Task 3: README screenshots and walkthrough video prepared; Pages workflow uploads only frontend dist and grants deployment permissions only to its main-branch job. PR/remote checks and actual Pages deployment remain to be recorded after synchronization.

Final verification: 417 Python tests passed, 80 skipped; strict mypy 137 files, Ruff lint/format, 48 exported contracts, 20 schema/example pairs and two OpenAPI documents passed. Six Chromium tests passed against the built /RepoScope/ site; frontend lint, format, strict build and npm audit passed (zero vulnerabilities). All 60 Markdown files passed local link validation. A fresh Docker capture with internally archived application source, wire-cursor validation and independent upstream excerpt approval passed. No deferred review findings remain.

Remote integration: PR #23 created. The first frontend CI run exposed npm 11's incomplete optional-dependency lock on Linux under npm 12.2.2. A clean npm 12 lock-only regeneration added the missing @emnapi optional entries; the prior failure was reproduced locally with Linux-targeted npm ci dry-run, then the same check and a fresh Windows npm ci passed. The Docker smoke on reviewed staged source also passed startup, migrations, business API, dependency loss/recovery, isolation and shutdown. The initial remote security job found four fixable high/critical runtime advisories; investigation is recorded before any merge.

Ruling: Patch the container prerequisites blocking the protected main CI gate as part of demo integration. Debian's official trackers confirm apt 2.6.2 fixes CVE-2026-109518 and OpenSSL 3.0.22-1~deb12u2 fixes CVE-2026-84782. Both runtime and PostgreSQL use these exact packages; bootstrap APT retries are disabled until the patched client is installed. The existing Redis 8.6.6 base has fixable musl/zlib findings; a derived non-root image retains that Redis binary and installs Alpine's available musl 1.2.5-r24 / zlib 1.4-r0 packages. CI and both Compose paths use the reviewed image. Cost: production configuration now requires REPOSCOPE_REDIS_IMAGE and a fourth reviewed image build, documented in the owner guide; no host deployment is performed.

Container patch verification: local Trivy rebuilt runtime: secrets=0, high/critical=120, fixable=0; rebuilt PostgreSQL: secrets=0, high/critical=112, fixable=0; rebuilt Redis: secrets=0, high/critical=0, fixable=0. NATS had no fixable high/critical findings. Unfixed findings are retained as residual review items, not waived as safe. The frontend push and PR workflows both passed after the cross-platform lock fix.

Task 3: complete. PR #23 merged to main as 4df448a75983caa2b4a1470865be963c975dcafc with protection intact. The push container job initially failed during initialization with only a safe generic Docker error, while the identical PR job and local smoke passed; the failed job was rerun without a code change and passed. No root cause is claimed and no check was bypassed. All four main quality jobs passed in run 44038889853. Pages build and deployment passed in run 44038889877 after the owner selected GitHub Actions as the Pages source.

Public acceptance: https://supercodingden.github.io/RepoScope/ returned HTTP 200 in a fresh browser context on 2026-11-17. All three cases replayed four events, citations linked to pinned signer.py spans, all four views loaded, and the 390-pixel layout had no horizontal overflow. Browser page errors and external runtime requests were zero. The structured result is retained in 2026-11-17-demo-public.json. The final documentation sync records this accepted state; backend hosting and paid-provider evaluation remain deferred.
