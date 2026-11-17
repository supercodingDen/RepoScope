# Interactive recorded demo design

Approved scope: the owner's 2026-11-17 approval of phases A-D in this conversation.

## Intent

Give an AI Engineer hiring reviewer a two-minute, English-language walkthrough of RepoScope without a login, backend installation, or paid provider call. Keep the existing CLI reproducible path. Show evidence and operational behavior rather than a fabricated chatbot.

## Approach

Screenshots alone are easy to consume but cannot expose citations. A hosted live agent needs hosting, credentials, admission, and operational acceptance. The approved first version is an interactive static recording with README images, a reproducible capture script, and GitHub Pages deployment. Live-model recordings remain deferred until the owner configures a key and explicitly enables paid calls.

## Product

- Three cases on the existing pinned ItsDangerous revision: implementation lookup, path-scoped lookup, and an actual SSE disconnect/reconnect recording.
- English interface: preset cases, hybrid search results, recorded tool/status timeline, cited source excerpts with line numbers and immutable GitHub links, architecture, benchmark evidence, and reproduction instructions.
- Playback is a presentation of recorded timestamps, never claimed to be a currently running model. No hidden reasoning or invented tool calls.
- Default recordings use mock embeddings and mock agent output; show this prominently. No free-form prompt box that pretends to answer unseen queries.
- Historical T12 figures retain workload, source links, date, mock-vector labels, and unmet targets. ANN recall is not semantic answer accuracy.

## Boundaries

- React, strict TypeScript, Vite; no browser credentials, analytics, external runtime CDN, or backend service requirement.
- Export only explicitly modeled public fields. Require the fixed public repository and commit, validate citations and event order, and fail closed on unexpected capture data. Never read local dotenv files. Preserve third-party license and attribution for included snippets.
- Public data contains bounded source excerpts, not downloaded repositories, private logs, or full prompts from arbitrary runs.
- Preserve existing local user changes. Source work occurs in the owner's opened D-drive directory on a feature branch; publish through a reviewed PR because main is protected.
- Deployment artifacts contain only the frontend build. GitHub Pages administrative setup is an owner step if the connected integration cannot configure it. A successful static site is separate from hosted backend acceptance.

## Acceptance

- All three cases are backed by captured responses from the pinned source; replay/resume is verified using Last-Event-ID.
- Result citations resolve to recorded source spans and immutable upstream links.
- Case changes, replay/pause/reset, evidence selection, tabs, and failure/loading states work on desktop and mobile with keyboard access and reduced motion.
- Export negative tests, browser interaction tests, type/lint/build checks, existing Python checks, and source secret scans pass before sync.
- README leads to the demo, includes a screenshot, and accurately states public repository / unhosted backend status.
