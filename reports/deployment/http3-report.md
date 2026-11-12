# HTTP/3 与 HTTP/2 部署验收

日期：2026-11-12（北京时间）。目标：https://ty.1byte.online 。

已开启 NGINX HTTP/3（QUIC/UDP 443）、保留 HTTP/2（TLS/TCP 443），通过 Alt-Svc 通告 h3，Docker 同时映射 TCP 和 UDP 443。NGINX 1.30.6 已编译 http_v2/http_v3 模块，运行 OpenSSL 3.5.9；本次未改动运行镜像、后端或数据库，仅重建 NGINX 容器以生效 UDP 映射。修改前配置备份在服务器 shared/compose.pre-http3.yaml、shared/site.pre-http3.conf。

## 结果

| 检查 | 服务器网络 | 本地外网 |
| --- | --- | --- |
| 源站 HTTP/3（含证书验证） | 200，通过 | 200，通过 |
| 公网域名经 Cloudflare HTTP/3 | 200，通过 | 一次超时，保留失败结果 |
| 源站 HTTP/2 | 200，通过 | 200，通过 |
| 公网域名 HTTP/2 | 200，通过 | 200，通过 |
| 模拟 QUIC 不可用后使用 HTTP/2 | 200，通过 | 200，通过 |

证据：`http3-server.json`、`http3-external.json`；均校验 HTTPS 证书及业务健康响应。`http3-deployment.txt` 保留 NGINX 配置校验、容器端口、宿主机 UDP 监听、配置哈希、HTTP/2 和 Alt-Svc 响应。`probe-http3.py` 为可复跑探针，使用隔离的 aioquic/h2 依赖，不修改项目依赖。

回退测试由探针向未使用 UDP 9 端口请求 QUIC 并设置超时，随后请求同一源站 TCP 443、ALPN 协商 h2；这验证了服务具备回退通道。没有修改生产防火墙，也没有声称此测试覆盖所有浏览器的原生回退时序。客户端请求 h3 的失败日志保留，未将超时计为通过。

## 协议选择

HTTP/3 优先由支持它的浏览器依据 Alt-Svc、缓存和网络状态决定，服务器不能保证每次首个请求都采用 HTTP/3。首次访问可能先通过 HTTP/2 获取 Alt-Svc 后再升级；QUIC 不可用时 TCP/HTTP/2 继续可用。

域名当前经过 Cloudflare，客户端与边缘、边缘与源站分别协商协议。Cloudflare 边缘 HTTP/3 已实际成功验证；其官方文档说明目前不支持 HTTP/3 回源，因此浏览器显示 h3 不代表 Cloudflare 到 NGINX 同样使用 h3。

参考：[NGINX HTTP/3 模块](https://nginx.org/en/docs/http/ngx_http_v3_module.html)、[Cloudflare HTTP/3](https://developers.cloudflare.com/speed/optimization/protocol/http3/)。

## 回退部署

如需撤回此次配置，恢复服务器 shared/compose.pre-http3.yaml 和 shared/site.pre-http3.conf 至 current 对应路径，再执行 `docker compose --env-file /opt/reading-platform/shared/deploy.env up -d --no-build --no-deps nginx` 并验证健康。应用容器与数据库无需重建。
