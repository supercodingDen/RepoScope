# T14 release procedure and evidence

The intended repository is `https://github.com/supercodingDen/RepoScope`, with `main` as its default branch. This project is synchronized through the connected GitHub integration because the D-drive working copy has no local `.git` history. GitHub commits and workflow runs provide the remote audit trail. Do not infer publication from local files or a successful API request; inspect the actual branch, run, tag, release, and anonymous visibility.

## Candidate procedure

1. Review and synchronize the T14 source, notes, contribution templates, Dependabot configuration, and release workflow to `main`. Confirm the `quality` workflow is green on that exact commit.
2. Create `release/v0.1.0` at the reviewed commit. Its push runs the four `quality` jobs. The `release` workflow runs only after a successful push run on that branch from this repository; it rejects a moving branch or existing tag/release.
3. The release job checks out the exact successful commit without persisted checkout credentials, installs frozen dependencies, and runs the pinned public-repository demo on new disposable mock-only Compose volumes. It builds the three first-party images from that commit, archives them, produces CycloneDX image SBOMs and a metadata file, and verifies SHA-256 checksums before creating a GitHub `v0.1.0` pre-release and tag at that commit.
4. Inspect the remote release's tag target, six assets, checksum file, job conclusions, and source commit. Keep the release private until the owner has reviewed the results and enabled public repository visibility. Check anonymous access to both source and release afterward.

`release-metadata.json` records the Git commit and tree, frozen lockfile checksum, Docker image IDs, and the image archive checksum. Image IDs are local image-config digests. The project does not push images to a registry, so it does not claim registry manifest digests. `SHA256SUMS` authenticates the five other release assets, while the version tag pins the source. The upstream Redis digest is in [runtime image pins](runtime-images.json). The release notes explain the open T12 performance and live-provider gates.

## Repository settings to check

The connected GitHub integration can write Git data and read CI/release results, but it does not expose repository administration, release creation, or visibility changes directly. The release workflow uses its own narrowly scoped `contents: write` token to create the candidate after CI and demo succeed. Branch protection and required-check rules must be set by the owner in GitHub settings when available for the repository plan. Require the `quality` jobs (`python`, `containers`, `secrets`, `security`) on `main`, prohibit force pushes and branch deletion, and require review before merging. Keep the release branch restricted until its tag exists. GitHub private vulnerability reporting should be enabled before public visibility; use [SECURITY.md](../SECURITY.md) for interim reporting instructions.

Public GitHub source/release visibility, green remote checks on the release commit, and a successful fresh-checkout demo are the T14 acceptance gate. A private pre-release is preparation only. Hosting, HTTPS, backups, and restore/rollback are T15. The measured T12 misses remain open regardless of release status.
