# Owner manual configuration: complete path

This checklist covers every remaining owner-controlled step. Follow it only on systems and accounts you control. Never send passwords, tokens, private keys, or secret-file contents to this repository or chat. The [status page](project-status.md) distinguishes source delivery from deployment evidence. Docker's Linux engine was unavailable for the T15/T16 local check, so the container, host, and recovery steps below are **not executed evidence**.

## 1. Finish GitHub ownership and public release (T14)

1. Sign in as owner of [supercodingDen/RepoScope](https://github.com/supercodingDen/RepoScope). Review the current `main` commit, Actions runs, license, security notes, and `v0.1.0` pre-release assets/metadata. Deploy only an exact commit whose CI is green.
2. To satisfy the PDF's public-submission gate, choose **Settings → General → Danger Zone → Change repository visibility → Public**. Review source, release assets, Actions history, and logs before changing visibility. Check both repository and release URLs in a signed-out browser afterward. Remaining private is allowed but leaves T14 open.
3. Under **Settings → Rules → Rulesets**, protect `main`: require pull-request review and the `quality` jobs (`python`, `containers`, `secrets`, `security`), block force pushes and deletion. Apply rules supported by your account plan. Once public, enable **Settings → Advanced Security → Private vulnerability reporting**, or retain the private contact in [SECURITY.md](../SECURITY.md). Record screenshots/links without secrets.

## 2. Run the existing local Windows demo (optional)

Start Docker Desktop's Linux engine and check `docker version` and `docker compose version`. Install Python 3.12.14 and uv 0.12.11, then run `uv sync --frozen --all-groups` in the project. Privately fill the ignored local `.env` from `.env.example` with **three distinct** random values of at least 32 characters for `POSTGRES_PASSWORD`, `APP_DATABASE_PASSWORD`, and `REPOSCOPE_API_TOKEN`; keep mock mode and paid calls disabled. Never commit, upload, or send that file, and do not reuse the password previously disclosed in chat. Run `docker compose up --build --wait --wait-timeout 180`, check `http://127.0.0.1:8000/readyz`, and follow the [pinned demo](demo.md). `docker compose down` retains volumes; never use `down -v` on data you need.

## 3. Select and secure a Linux host (T15)

1. Choose a funded VM and record provider, monthly cap, region, public IP, OS, CPU/RAM, SSD, filesystem, and Docker versions. The original reference benchmark needs **8 vCPU, 16 GiB RAM, SSD**; a smaller demo host cannot validate those targets. Buy/control a domain and create an A/AAAA record, e.g. `api.example.com`, pointing to the host. Verify public DNS resolution.
2. Create a non-root SSH operator and key, disable password SSH, patch the OS, and set cloud and host firewalls. Limit SSH 22 to your IP; allow public TCP 80/443 to Caddy. Never expose 5432, 6379, 4222, 8222, 8000, or 9000. Permit outbound HTTPS/DNS to GitHub, registries, certificate authorities, and OpenAI only when live mode is enabled. Check time synchronization. Treat Docker socket/group access as host-root equivalent.
3. Install Docker Engine and Compose from [official Docker instructions](https://docs.docker.com/engine/install/) and verify both versions. Provision disk for source quota, PostgreSQL, JetStream, images, and backups. Wire `scripts/check_disk.sh /var/lib/docker /srv/reposcope-backups` to a real alert receiver and test a failed alert. Restrict backup and Docker access to administrators.
4. Clone the reviewed repository and check out the exact green SHA. If still private, use a read-only deploy key or authenticated transfer. Do not put a personal token in a URL, shell history, or Compose file. Keep the checkout under the operator account.

## 4. Prepare protected secrets and reviewed images

On the **Linux host**, create files outside the checkout as a trusted administrator. These commands generate new values without printing them:

```bash
sudo install -d -m 0700 /etc/reposcope/secrets /srv/reposcope-backups
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/reposcope/secrets/postgres_password; openssl rand -hex 32 > /etc/reposcope/secrets/app_database_password; openssl rand -hex 32 > /etc/reposcope/secrets/api_token'
sudo chmod 0600 /etc/reposcope/secrets/*
```

Create `/etc/reposcope/production.env` with mode 0600 and **only non-secret** assignments: `REPOSCOPE_SECRETS_DIR=/etc/reposcope/secrets`, `REPOSCOPE_DOMAIN=<your-domain>`, `REPOSCOPE_APP_IMAGE=reposcope:<reviewed-sha>`, `REPOSCOPE_POSTGRES_IMAGE=reposcope-postgres:<reviewed-sha>`, `REPOSCOPE_NATS_IMAGE=reposcope-nats:<reviewed-sha>`, `CADDY_IMAGE=caddy:<reviewed-version>@sha256:<reviewed-manifest-digest>`, `PROVIDER_MODE=mock`, `ALLOW_PAID_API_CALLS=false`, and optionally a fixed `REPOSCOPE_PRINCIPAL_ID` UUID. Pin the official Caddy manifest digest for your architecture, inspecting it with `docker buildx imagetools inspect caddy:<reviewed-version>`. Record version and digest. No secret value belongs in this file.

The `v0.1.0` archive predates the production secret launcher. From the **new exact source SHA**, first run offline checks and `python -m scripts.smoke_test` in an isolated Compose project once Docker works; then build and retain images:

```bash
docker build --target runtime -t "reposcope:<reviewed-sha>" .
docker build -f Dockerfile.postgres -t "reposcope-postgres:<reviewed-sha>" .
docker build -f Dockerfile.nats -t "reposcope-nats:<reviewed-sha>" .
docker image inspect --format '{{.Id}}' "reposcope:<reviewed-sha>" "reposcope-postgres:<reviewed-sha>" "reposcope-nats:<reviewed-sha>"
```

Save the three images with `docker save`, hash the archive with `sha256sum`, and keep it in protected storage for rollback. Record image IDs, source SHA, checksum, CI URL, and Caddy/Redis digests. These image IDs are local config digests, not registry manifest digests. A later reviewed registry release can replace this host build. Pull the pinned Caddy and Redis images.

## 5. Deploy mock mode and verify the public boundary

In a trusted operator shell, from the project root, load the **non-secret** config and inspect the resolved Compose model:

```bash
set -a
. /etc/reposcope/production.env
set +a
docker compose -f compose.production.yaml config --quiet
docker compose -f compose.production.yaml up -d --wait --wait-timeout 180
docker compose -f compose.production.yaml ps
```

Never source an untrusted file. Confirm valid TLS and HTTP 200 from `https://<your-domain>/healthz` and `/readyz`; confirm a business route without a bearer token returns 401. Confirm only proxy ports 80/443 are reachable. Set the API token privately in the demo client's shell and run the [pinned demo](demo.md) with `--api-url https://<your-domain>`. Record completed job, immutable citation commit, SSE reconnect/replay, safe errors, endpoint, timestamp, and redacted logs. Restart with `docker compose -f compose.production.yaml restart`; verify the same job/run and source citation persist. Do not delete named volumes.

## 6. Back up off host, restore, and rehearse rollback

Run `scripts/backup.sh /srv/reposcope-backups` in a maintenance window. It pauses traffic/workers, backs up PostgreSQL and source blobs, hashes both, then resumes. Its local output is sensitive. Configure independent SFTP/object storage and an encryption tool such as restic. Privately create a restic password file and storage credential, set protected `RESTIC_REPOSITORY` and `RESTIC_PASSWORD_FILE`, run `restic init`, `restic backup /srv/reposcope-backups`, `restic snapshots`, and periodic `restic check`. Schedule daily backups/retention and alert on failure or stale age. A directory on the same VM is **not** off-host backup. Retrieve an off-host snapshot, verify its SHA-256 manifest, and document the retrieval.

For a concrete SFTP example, provision a **separate** backup server and a restricted `backupuser` account with a writable `/srv/restic/reposcope` directory. On the app host, generate a dedicated SSH key with `ssh-keygen -t ed25519 -f /root/.ssh/reposcope_backup` and install **only its public key** in that account's `authorized_keys`. In root's `/root/.ssh/config`, set a `Host reposcope-backup` entry with `HostName backup.example.com`, `User backupuser`, `IdentityFile /root/.ssh/reposcope_backup`, and `IdentitiesOnly yes`; pin the server host key and verify `ssh reposcope-backup`. Install [restic](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html) from its official package/release. Generate `/etc/reposcope/restic_password` with `umask 077; openssl rand -hex 32 > /etc/reposcope/restic_password`, and protect it at mode 0600. In a root-only `/etc/reposcope/backup.env` (mode 0600), set `RESTIC_REPOSITORY=sftp:reposcope-backup:/srv/restic/reposcope` and `RESTIC_PASSWORD_FILE=/etc/reposcope/restic_password`. Load that file in the trusted operator shell before `restic init` and each backup/check/restore. Preserve the restic password and SSH recovery key somewhere **independent of the app host**; losing them makes the encrypted backup unusable. Schedule a root-only daily job that loads `/etc/reposcope/production.env` and `/etc/reposcope/backup.env`, runs `scripts/backup.sh`, then `restic backup /srv/reposcope-backups`; add retention (`restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 3 --prune`) and a weekly `restic check`. Alert on any nonzero exit or a stale last snapshot. Test `restic restore latest --target /srv/reposcope-restore-download` on a separate machine, then verify `SHA256SUMS` inside the recovered backup directory. Replace the example host/user/path with your actual backup service.

Restore a verified backup with `scripts/restore.sh reposcope-restore-<unique-name> /absolute/backup-directory`. Use fresh project volumes. Check its private API through an operator-only tunnel/local client, restored jobs and runs, source citations, migration grants, NATS/outbox reconciliation, and recovery duration. Rehearse rollback using a retained **compatible** prior image archive and its pre-migration database backup in an isolated project. Do not assume database schema downgrade safety or destroy production volumes to test recovery.

## 7. Optional paid provider and open T12 targets

Keep `PROVIDER_MODE=mock` unless you intentionally approve spend. For live mode, create protected `/etc/reposcope/secrets/openai_api_key` (mode 0600) from your own account, set `PROVIDER_MODE=openai` and `ALLOW_PAID_API_CALLS=true`, and include **both** `-f compose.production.yaml -f compose.production.live.yaml` in every Compose operation. Verify current official embedding and agent input/output prices, then enter `EMBEDDING_DAILY_BUDGET_USD`, `EMBEDDING_PRICE_PER_MILLION_USD`, `EMBEDDING_PRICE_VERIFIED_DATE`, `AGENT_INPUT_PRICE_PER_MILLION_USD`, `AGENT_OUTPUT_PRICE_PER_MILLION_USD`, and `AGENT_PRICE_VERIFIED_DATE`. Dates must be within seven days. Set account billing limits/alerts; run a small paid test and inspect usage before a separately budgeted semantic evaluation. Do not claim live quality from mock vectors.

To close the [T12 performance gaps](t12-performance.md), use the recorded 8-vCPU/16-GiB/SSD reference host, fixed 100K real-source corpus and 200 queries, three measured trials, 32 clients, raw p95/QPS and exact/HNSW recall, and a human-reviewed semantic set. Measure cold live query embeddings and full agent latency separately. Run a **single-job** 100K ingestion and record memory/time. Keep misses open or revise them explicitly; never substitute a database-only profile for end-to-end behavior.

## 8. Close T16 handover

Fill [the acceptance matrix](acceptance.md) with GitHub/demo URLs, exact CI SHA, image IDs, host details, HTTPS checks, demo transcript, fault/benchmark evidence, backup/restore/rollback results, costs, and limitations. Use [the interview guide](interview-guide.md) for a five-minute explanation. Mark a row passed only after executing its check. GitHub visibility/settings, host purchase, DNS, secret creation, public HTTPS, off-host storage, live billing, and performance validation remain manual.
