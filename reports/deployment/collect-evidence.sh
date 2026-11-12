#!/bin/sh
set -eu
cd /opt/reading-platform/current
exec > /opt/reading-platform/shared/reports/domain-deployment.txt 2>&1
date -u
printf '\n-- Containers --\n'
docker compose --env-file /opt/reading-platform/shared/deploy.env ps
printf '\n-- Origin certificate --\n'
openssl x509 -in /opt/reading-platform/shared/letsencrypt/live/reading-platform-domain/fullchain.pem -noout -subject -issuer -dates -ext subjectAltName
printf '\n-- Trusted origin TLS --\n'
curl --silent --show-error --resolve ty.1byte.online:443:127.0.0.1 -D - https://ty.1byte.online/api/health
printf '\n-- Public domain --\n'
curl --silent --show-error --max-time 30 -D - https://ty.1byte.online/api/health
printf '\n-- HTTP redirect --\n'
curl --silent --show-error -I -H 'Host: ty.1byte.online' http://127.0.0.1/
printf '\n-- IP redirect --\n'
curl --silent --show-error -I --resolve 43.155.140.75:443:127.0.0.1 https://43.155.140.75/
printf '\n-- NGINX --\n'
docker compose --env-file /opt/reading-platform/shared/deploy.env exec -T nginx nginx -t
printf '\n-- Timers --\n'
systemctl list-timers reading-cert-renew.timer reading-backup.timer --no-pager
systemctl show reading-cert-renew.service reading-backup.service -p Id -p Result -p ExecMainStatus
printf '\n-- Data integrity --\n'
docker compose --env-file /opt/reading-platform/shared/deploy.env exec -T app python -c 'import sqlite3,hashlib; p="/app/data/questions.sqlite3"; print("bank_sha256",hashlib.sha256(open(p,"rb").read()).hexdigest()); c=sqlite3.connect(p);print("bank_integrity",c.execute("pragma integrity_check").fetchone()); c=sqlite3.connect("/var/lib/reading/practice.sqlite3");print("runtime_integrity",c.execute("pragma integrity_check").fetchone())'
printf '\n-- Images --\n'
docker image inspect reading-platform:20261112-092959-p1 reading-nginx:20261112-092959-p1 reading-certbot:20261112-092959-p3 --format '{{.RepoTags}} {{.Id}}'
printf '\n-- Deployment config hashes --\n'
sha256sum Dockerfile compose.yaml deploy/nginx/site.conf deploy/nginx/Dockerfile deploy/certbot/Dockerfile deploy/renew-certificate.sh
