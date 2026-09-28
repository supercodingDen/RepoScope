#!/usr/bin/env bash
# Restore only to a fresh isolated project; never overwrite production volumes.
set -euo pipefail

if [[ $# -ne 2 || "$1" != reposcope-restore-* || ! -d "$2" ]]; then
  echo "Usage: scripts/restore.sh reposcope-restore-NAME /absolute/backup-directory" >&2
  exit 2
fi
project="$1"
backup_dir="$(cd -- "$2" && pwd -P)"
if [[ "$backup_dir" != /* ]]; then
  echo "Backup directory must be absolute." >&2
  exit 2
fi
: "${REPOSCOPE_SECRETS_DIR:?Set REPOSCOPE_SECRETS_DIR}"
: "${REPOSCOPE_DOMAIN:?Set REPOSCOPE_DOMAIN}"
: "${CADDY_IMAGE:?Set CADDY_IMAGE}"
: "${REPOSCOPE_APP_IMAGE:?Set REPOSCOPE_APP_IMAGE}"
(cd -- "$backup_dir" && sha256sum -c SHA256SUMS)
for volume in postgres-data nats-data source-data caddy-data caddy-config; do
  if docker volume inspect "${project}_${volume}" >/dev/null 2>&1; then
    echo "Refusing restore: project volume already exists." >&2
    exit 2
  fi
done
compose=(docker compose -p "$project" -f compose.production.yaml)
if [[ "${PROVIDER_MODE:-mock}" == openai ]]; then
  compose+=(-f compose.production.live.yaml)
fi
"${compose[@]}" up -d postgres
"${compose[@]}" run --rm migrate
"${compose[@]}" exec -T postgres sh -ec \
  'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec pg_restore -U reposcope_migrator -d reposcope --clean --if-exists --no-owner' \
  < "$backup_dir/database.dump"
docker volume create "${project}_source-data" >/dev/null
docker run --rm --network none --user 0:0 \
  -v "${project}_source-data:/source" \
  --entrypoint /bin/chown "$REPOSCOPE_APP_IMAGE" \
  10001:10001 /source
docker run --rm -i --network none \
  -v "${project}_source-data:/source" \
  --entrypoint /bin/tar "$REPOSCOPE_APP_IMAGE" \
  -C /source -xzf - < "$backup_dir/source-data.tgz"
"${compose[@]}" run --rm migrate
"${compose[@]}" up -d redis nats api indexer agent
echo "Isolated restore started. Verify API, jobs, outbox and source citations before any promotion."
