#!/bin/sh
set -eu
cd /opt/reading-platform/current
docker compose --env-file /opt/reading-platform/shared/deploy.env run --rm --no-deps certbot renew --quiet --no-random-sleep-on-renew --webroot --webroot-path /var/www/certbot
docker compose --env-file /opt/reading-platform/shared/deploy.env exec -T nginx nginx -t
docker compose --env-file /opt/reading-platform/shared/deploy.env exec -T nginx nginx -s reload
