#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
# Maintenance window: prevent database/file divergence while snapshotting.
docker compose stop caddy api worker
trap 'docker compose start api worker caddy >/dev/null' EXIT
docker compose exec -T db pg_dump -U pilot -d pilot -Fc > "backups/$stamp.database.dump"
docker compose run --rm --no-deps -T --entrypoint tar api -C /data/documents -czf - . > "backups/$stamp.documents.tar.gz"
printf '%s\n' "Backup created in deploy/backups/$stamp.*. Encrypt and copy it off-host; protect deploy/.env separately."
