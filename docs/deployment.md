# Docker HTTPS 部署与运维

正式地址：https://ty.1byte.online 。服务器：43.155.140.75。DNS 使用 Cloudflare 代理，NGINX 源站使用 Let's Encrypt 公信证书；普通浏览器不需要导入证书。域名证书到期时间为 2027-02-10 00:46:14 UTC。

服务器当前目录 `/opt/reading-platform/current`，持久配置 `/opt/reading-platform/shared/deploy.env`（600 权限），证书目录 `shared/letsencrypt`（仅服务器保管）。应用容器无宿主机端口，仅 NGINX 暴露 TCP 80/443 和 UDP 443。80 提供 ACME 校验及 HTTPS 跳转，IP 的 HTTPS 访问也跳转到域名。请持续保留 80 和 443 的 TCP 入站，以供自动续期；UDP 443 在 NGINX 源站和 Cloudflare 边缘均提供 HTTP/3。

## 日常运维

```sh
cd /opt/reading-platform/current
docker compose --env-file /opt/reading-platform/shared/deploy.env ps
docker compose --env-file /opt/reading-platform/shared/deploy.env logs --tail 100 app nginx
systemctl list-timers reading-cert-renew.timer reading-backup.timer
systemctl start reading-cert-renew.service
systemctl start reading-backup.service
```

证书每 6 小时检查一次，到期前续签后验证配置并重载 NGINX；域名证书及原 IP 短期证书均纳入续期。每天凌晨 03:30 加随机延迟执行 SQLite 一致性备份，校验 integrity_check 后保存到 `/opt/reading-platform/shared/backups`，权限 600。当前备份保留全部版本，需定期关注磁盘。Docker 设置 unless-stopped 并已启用开机启动。运行记录使用 `reading-platform-runtime` 命名卷，更新容器不影响记录。**不要执行 down -v 或删除该卷。**

## 更新与回退

先执行备份服务，再构建新镜像并修改 shared/deploy.env 的镜像版本，运行 `docker compose --env-file /opt/reading-platform/shared/deploy.env up -d --no-build app nginx`。检查健康状态及考试/练习流程后再清理旧镜像。回退应用镜像时保持域名 PUBLIC_ORIGIN、ALLOWED_HOSTS 和当前 NGINX 域名配置；若更新包含数据库迁移，先确认旧版兼容，必要时停应用并从已验证备份恢复。此次部署未更改业务数据库结构。

## 证据

见 `reports/deployment/` 中部署报告、TLS/容器/定时任务输出、漏洞扫描 JSON、桌面和手机测试及截图。发布前漏洞扫描覆盖最终运行镜像与证书工具镜像的 HIGH/CRITICAL，结果反映当时漏洞库，需随漏洞库更新定期复扫。三方基础镜像更新后应重新构建、扫描和验收。

## HTTP/3 与 HTTP/2

NGINX 开启 `listen 443 quic reuseport`、`http3 on` 和 `http2 on`，Compose 发布 `443:443/udp`。响应通告 `Alt-Svc: h3=":443"; ma=86400`，支持 HTTP/3 的客户端可尝试 QUIC，不可用时仍可通过 TCP/HTTP/2 连接。实际协议由客户端和网络协商，首次访问尚未获知 Alt-Svc 时可能先使用 HTTP/2。

域名经过 Cloudflare，浏览器与 Cloudflare、Cloudflare 与源站属于两段连接。Cloudflare 官方文档说明目前回源不支持 HTTP/3；开启源站 HTTP/3 可供直连源站的客户端使用，不改变 Cloudflare 回源行为。参考：https://developers.cloudflare.com/speed/optimization/protocol/http3/ 。验收见 `reports/deployment/http3-report.md`。

## GitHub Actions 发布

功能变更先合入 `master`，发布时向 `release` 提交 PR。面向这两个分支的 PR 会运行 CI，包括 Python 测试和 Chromium 桌面、手机端到端测试。PR 合入 `release` 后，Release 流水线会构建该次合入提交的 Linux amd64 Docker 镜像，检查网页、健康接口和词库接口，再将镜像压缩包与 SHA-256 校验文件发布到 GitHub Releases。关闭未合并的 PR 会跳过发布。

生产服务器可从对应 GitHub Release 下载两个文件，在同一目录运行 `sha256sum -c SHA256SUMS` 和 `docker load -i reading-platform-linux-amd64.tar.gz`。镜像名为 `reading-platform:<合入提交的完整 SHA>`。接下来按上文更新流程备份数据、设置 `APP_IMAGE` 并更新服务。
