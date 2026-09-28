#!/usr/bin/env bash
# Exit nonzero for an operator alert when a deployment filesystem is nearly full.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: scripts/check_disk.sh /var/lib/docker [/backup/path ...]" >&2
  exit 2
fi
failed=0
for path in "$@"; do
  if [[ ! -e "$path" ]]; then
    echo "Disk-check path is missing: $path" >&2
    failed=1
    continue
  fi
  usage="$(df -P -- "$path" | awk 'NR == 2 {gsub(/%/, "", $5); print $5}')"
  free_kib="$(df -Pk -- "$path" | awk 'NR == 2 {print $4}')"
  if [[ ! "$usage" =~ ^[0-9]+$ || ! "$free_kib" =~ ^[0-9]+$ ]]; then
    echo "Disk-check could not parse capacity for $path" >&2
    failed=1
  elif (( usage >= 80 || free_kib < 10485760 )); then
    echo "Disk capacity threshold exceeded for $path" >&2
    failed=1
  fi
done
exit "$failed"
