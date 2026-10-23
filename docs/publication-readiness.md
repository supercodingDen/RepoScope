# Public repository readiness

This record separates publication of GitHub source from hosting the API. The owner chose to make the existing `supercodingDen/RepoScope` repository public, including its commit-author metadata. No API credential belongs in Git, a release asset, an Actions variable, or a screenshot. Future live credentials must be created and mounted from protected host files after hosting is selected; see [manual configuration](manual-configuration.md).

## Pre-publication audit, 2026-10-22

| Surface | Checked result | Publication gate |
| --- | --- | --- |
| `main`, release branch, 11 Dependabot branches | All 13 current branch trees returned without truncation. `.env.example` was the only environment-like filename; no tracked `.env`, key, or named credential file. The only blob over 1 MB was `bench/data/t12-raw-evidence.zip`. | Recheck immediately before visibility change. |
| Historical commits | The previous `quality` workflow checked out full history, but its Gitleaks command did not explicitly request all refs. The updated job requests `--all` and scans current-tree archives; it has not yet run remotely. Scanner-blind custom tokens remain possible. | Confirm the updated redacted scan passes on the final commit; independently review all refs and any opaque data before publication. |
| Benchmark archive | Inspected all 16 JSON entries (20.9 MB uncompressed) without printing their contents. Pattern counts for email addresses, private-key headers, common provider/GitHub tokens, and credential assignments were zero. A separate redacted Gitleaks archive scan found no leaks. | Preserve only if the final source/archive scan stays clean. |
| Actions history | Enumerated 142 workflow runs and 337 jobs. Scanned 285 retrievable logs for recognizable provider/GitHub tokens and private-key headers; zero matches. All 142 runs returned no attached workflow artifacts. Logs for 48 skipped jobs, three cancelled jobs, and one old successful `python` job returned no downloadable blob; that successful job's step summaries were all successful. | Review the old unavailable log in the GitHub UI; do not infer that inaccessible logs are clean. |
| v0.1.0 pre-release | Six assets and GitHub SHA-256 digests exist. The archive was built by the guarded release workflow from the tagged source with `.dockerignore`; the release branch quality/demo job passed. The binary image archive could not be independently downloaded through this connection. | Independently download and verify all six assets/checksums, then scan the image archive before visibility change; otherwise remove/quarantine the unverified release asset while still private. |
| GitHub settings | Repository is private; `main` reports `protected=false`; ruleset list is empty. The connected GitHub integration has no repository-administration method. | Owner must apply the settings below in GitHub UI. |

These checks reduce risk; they cannot establish that arbitrary historical text, custom opaque secrets, or unavailable artifacts contain no sensitive data. A real finding blocks publication until credentials are revoked/rotated and the exposed material is removed from *all* public surfaces. Never rely on removing only the latest file.

## Controls delivered with the source

- `.gitignore` and `.dockerignore` exclude standard dotenv files, credential basenames, key formats, and secret directories. Ignore patterns are a safety net, not a security boundary.
- `scripts/publication_guard.py` fails the `secrets` CI job if a tracked credential path or populated secret value in `.env.example` appears. The same job scans all fetched branch/tag references and the current tree (including one level of archives) with redacted Gitleaks. The `security` job scans source and images with Trivy; all four `quality` jobs must pass on the final commit.
- Production Compose reads database/API/provider credentials from host-mounted files under `REPOSCOPE_SECRETS_DIR`; `compose.production.live.yaml` is required only for explicitly enabled paid mode. Do not place those files in the checkout or GitHub Actions secrets for this publication task.

## Owner-controlled GitHub settings

1. While still private, open **Settings → Rules → Rulesets** and add an active branch ruleset targeting `main`. Require a pull request, current `python`, `containers`, `secrets`, and `security` checks, and block force pushes and deletions. Use zero required approvals for a solo owner until a reviewer exists; do not create an impossible approval requirement. Restrict `release/*` changes and tag creation to trusted maintainers. Verify the resulting `main` branch reports protected. If account-plan limits prevent a ruleset, use equivalent branch protection and record the limitation.
2. Audit the release archive, unavailable log, and any workflow artifacts. Review the repository's **Security and quality → Advanced Security** settings. Resolve any actual secret alert before publication. Recheck latest source SHA and four green jobs.
3. Only then use **Settings → General → Danger Zone → Change repository visibility → Public**. The GitHub integration used here cannot perform this administrator operation. GitHub warns that code, Actions history, and logs become publicly visible. A visibility change may disable push rulesets; recheck all protections immediately afterward.
4. Enable available secret scanning, push protection, Dependabot alerts, and code scanning under **Advanced Security**. Enable **Private vulnerability reporting** and subscribe to security notifications. Do not bypass a legitimate secret alert to make CI green.
5. From a signed-out session, inspect source, commit history, release assets, and Actions. Confirm the final SHA and four `quality` jobs, settings, and absence of accidental credentials. Record the public URLs and date in [acceptance](acceptance.md) and [project status](project-status.md). Keep the service-hosting gate separate: no VM, domain, or live provider is configured by publishing the repository.

## Open Dependabot pull-request review, 2026-10-22

Each proposed change was checked individually for its changed files and the latest quality run at its PR head. None is needed for publication and none was merged. A green historical PR run is not a fresh check against the current `main`.

| PR | Change and present disposition |
| --- | --- |
| [#16](https://github.com/supercodingDen/RepoScope/pull/16) | Redis container 8.6.6 → 8.10.1 in both Compose files; `containers` and `security` failed. Hold for image/security review and clean CI. |
| [#15](https://github.com/supercodingDen/RepoScope/pull/15) | `setup-uv` action 6.8.0 → 10.3.0 in two workflows; `containers` and `security` failed. Hold for workflow review and clean CI. |
| [#14](https://github.com/supercodingDen/RepoScope/pull/14) | Python base image 3.12 → 3.14; conflicts with supported Python `<3.14`, and `containers`/`security` failed. Reject or replace with a compatible version. |
| [#13](https://github.com/supercodingDen/RepoScope/pull/13) | pgvector image 0.8.6 → 0.8.7; `containers` and `security` failed. Hold for image and migration review. |
| [#12](https://github.com/supercodingDen/RepoScope/pull/12) | OpenAI SDK 3.14.1 → 3.19.2; prior quality run passed. Hold for live-provider compatibility review; no paid call was made. |
| [#11](https://github.com/supercodingDen/RepoScope/pull/11) | Uvicorn 0.53.0 → 0.54.0; prior quality run passed. Hold for current-base HTTP/SSE regression checks. |
| [#9](https://github.com/supercodingDen/RepoScope/pull/9) | Psycopg 3.3.5 → 3.3.6; prior quality run passed. Hold for current-base database integration checks. |
| [#8](https://github.com/supercodingDen/RepoScope/pull/8) | Redis Python client 7.4.1 → 8.1.0; `python` failed. Hold for API compatibility repair and green CI. |
| [#6](https://github.com/supercodingDen/RepoScope/pull/6) | Mypy 1.20.2 → 2.3.1; prior quality run passed. Hold for compiler-policy review on the current base. |
| [#2](https://github.com/supercodingDen/RepoScope/pull/2) | Checkout action 4.4.0 → 7.0.1 in two workflows; prior quality run passed. Hold for workflow review on the current base. |
| [#1](https://github.com/supercodingDen/RepoScope/pull/1) | NATS image 2.14.7 → 2.15.0; prior quality run passed. Hold for image scan and NATS integration checks. |
