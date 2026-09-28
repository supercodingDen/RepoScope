#!/usr/bin/env bash
# Quiescent PostgreSQL and source-volume backup for one production Compose project.
set -euo pipefail

if [[ $# -ne 1 || ! -d "$1" ]]; then
  echo "Usage: scripts/backup.sh /absolute/existing/off-repository/backup-directory" >&2
  exit 2
fi
destination="$(cd -- "$1" && pwd -P)"
if [[ "$destination" != /* || "$destination" == "$(pwd -P)"* ]]; then
  echo "Backup destination must be an absolute directory outside the repository." >&2
  exit 2
fi
: "${REPOSCOPE_SECRETS_DIR:?Set REPOSCOPE_SECRETS_DIR}"
: "${REPOSCOPE_DOMAIN:?Set REPOSCOPE_DOMAIN}"
: "${CADDY_IMAGE:?Set CADDY_IMAGE}"
: "${REPOSCOPE_APP_IMAGE:?Set REPOSCOPE_APP_IMAGE}"
compose=(docker compose -f compose.production.yaml)
if [[ "${PROVIDER_MODE:-mock}" == openai ]]; then
  compose+=(-f compose.production.live.yaml)
fi
backup_dir="$destination/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 0700 -- "$backup_dir"
resume() {
  "${compose[@]}" up -d api indexer agent proxy >/dev/null
}
trap resume EXIT
"${compose[@]}" stop proxy api indexer agent >/dev/null
"${compose[@]}" exec -T postgres sh -ec \
  'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec pg_dump -U reposcope_migrator -d reposcope -Fc' \
  > "$backup_dir/database.dump"
docker run --rm --network none \
  -v reposcope-production_source-data:/source:ro \
  --entrypoint /bin/tar "$REPOSCOPE_APP_IMAGE" \
  -C /source -czf - . > "$backup_dir/source-data.tgz"
(cd -- "$backup_dir" && sha256sum database.dump source-data.tgz > SHA256SUMS)
chmod 0600 -- "$backup_dir"/*
echo "Local backup created at $backup_dir. Encrypt and copy it off host; verify that copy."
