#!/bin/sh
set -eu
cd /opt/reading-platform/current
stamp=$(date -u +%Y%m%dT%H%M%SZ)
target=/var/lib/reading/backups/practice-$stamp.sqlite3
docker compose --env-file /opt/reading-platform/shared/deploy.env exec -T app python -m backend.scripts.backup_runtime /var/lib/reading/practice.sqlite3 "$target"
container=$(docker compose --env-file /opt/reading-platform/shared/deploy.env ps -q app)
docker cp "$container:$target" "/opt/reading-platform/shared/backups/practice-$stamp.sqlite3"
chmod 600 "/opt/reading-platform/shared/backups/practice-$stamp.sqlite3"
