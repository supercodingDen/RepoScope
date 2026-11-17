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
