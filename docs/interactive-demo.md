# Interactive recorded demo

RepoScope's English-language evidence workspace lets a hiring reviewer inspect three recorded backend cases without installing the backend or supplying an API key. The source repository is public. The static frontend and production API are separate deployment targets.

## Entry points

- [Interactive demo](https://supercodingDen.github.io/RepoScope/) — requires the successful Pages deployment described below.
- [Desktop screenshot](assets/demo-desktop.png), [mobile screenshot](assets/demo-mobile.png), and [evaluation screenshot](assets/demo-evaluation.png).
- [Short recorded walkthrough](assets/demo-walkthrough.webm).
- [Validated recording](../web/demo/public/recordings/demo.json) and [ItsDangerous source license](../web/demo/public/recordings/LICENSE.itsdangerous.txt).
- [Existing local backend/CLI walkthrough](demo.md).

## What to inspect in two minutes

1. Open Workbench. Read the mock-mode disclosure and pinned source revision, then play the first case. Select a retrieval result to see its bounded source excerpt.
2. Click a citation and open its immutable GitHub source link. The mock answer is an excerpt from the first retrieved chunk, which can be documentation rather than an implementation. A source citation does not prove semantic correctness.
3. Switch to Focus the search. Its recorded search is restricted to the file cited by that run. The agent run itself was not path-filtered; only the separate search request was scoped.
4. Open Resume a disconnected stream. The capture closes one HTTP connection after sequence 2 and reconnects with its actual Last-Event-ID. Sequences 3 and 4 are received once. This proves stream replay, not worker failover.
5. Inspect Evaluation and Architecture. Historical T12 latency exceeds its target; mock-vector recall is not semantic answer relevance. Review the raw evidence links.

Playback uses an 800 ms presentation interval so that each event can be inspected. Event offsets shown in the timeline come from the actual recording, not that presentation timer. No hidden reasoning, streaming model tokens, confidence probability, or invented tool calls are shown.

## Frontend development

Use Node.js 24.22.1 and npm 12.2.2. The lockfile includes cross-platform optional build dependencies. From `web/demo`, run:

```text
npm ci --ignore-scripts
npm run dev
```

The terminal prints a local URL. The frontend reads only its static recording file, makes no backend/model call, and needs no local dotenv. Build with `npm run build`; check with `npm run lint`, `npm run format:check`, `npm audit --audit-level=high`, and `npm test` after `npx --no-install playwright install chromium`.

The build uses relative asset URLs so it works under `/RepoScope/`. Only `web/demo/dist` is published; project source, local credentials, operational logs, and backend services are not deployment artifacts.

## Reproduce the backend recording

Prerequisites: the existing Python development environment, Docker with Compose, Git, and public GitHub network access. No paid credentials are required. The capture command creates a clean archive of the selected Git commit internally, so existing local changes cannot be mistaken for that backend version.

In PowerShell, from the repository root:

```powershell
$captureCommit = 'a856be4e0db793d6118391d65b2236e853ff3c62'
uv run --frozen python -m scripts.capture_demo --application-commit $captureCommit
```

The script builds only that immutable application commit, creates its own Compose project and random in-memory credentials, disables Compose dotenv loading, forces mock mode and zero paid calls, and removes only its disposable volumes and temporary build directory on exit. It never opens the owner's `.env`. It may download/build images and take several minutes. Every SSE wire ID must match its event payload; reconnection uses the last received wire ID.

After capture, a separate client downloads bounded source files from the fixed public ItsDangerous commit and compares every excerpt with its declared upstream span. AST/token chunks can begin or end partway through a physical line. An [approved excerpt manifest](../web/demo/public/recordings/approved-excerpts.json) stores their SHA-256 digests. Both exporter and browser reject extra numbered lines, duplicate evidence IDs, a changed digest, inconsistent mock output, or an incomplete case set. The manifest provides a reviewed integrity baseline, not an external signature; review manifest changes together with an upstream re-verification.

The current format intentionally rejects live-provider recordings. A future live capture requires a separate reviewed format and evaluation procedure; changing the mock badge alone would misrepresent the evidence.

## GitHub Pages activation

The `demo` workflow verifies npm dependencies, strict types, lint, formatting, build, and Chromium interactions on a PR. On `main`, it uploads only the static build and deploys with job-scoped `pages: write` and `id-token: write`. Other jobs retain read-only repository permissions. Actions are pinned to verified commit SHAs.

If Pages is not already enabled, a repository administrator must open **Settings → Pages → Build and deployment → Source → GitHub Actions**. Then rerun the `demo` workflow on `main` from Actions. If an environment approval is required, approve the `github-pages` deployment after reviewing its commit. The connected GitHub integration cannot change these administrator settings.

After deployment, visit the public URL while signed out, load all four views, switch each case, open a citation, and check the mobile layout. A passing frontend build alone is not proof that the public site is deployed. The FastAPI backend remains unhosted until the separate production setup is completed.
