# 域名 HTTPS 部署验收报告

日期：2026-11-12（北京时间）。正式地址：https://ty.1byte.online 。源站：43.155.140.75。

## 结果

域名的 Let's Encrypt 公信证书已签发并部署到 NGINX，证书有效期至 **2027-02-10 00:46:14 UTC**。DNS 当前经过 Cloudflare。公网域名及使用 --resolve 直连源站均返回 HTTP 200，均启用正常 TLS 校验，没有跳过证书验证。HTTP 和原 IP HTTPS 均 308 跳转至域名。业务的正式 Origin、允许 Host、Secure Cookie 已切换至域名。

## 验证与证据

- `domain-deployment.txt`：证书 SAN/签发者/有效期、公网及源站 TLS HTTP 响应、NGINX 配置校验、容器健康、运行镜像 ID、定时任务和部署配置哈希。
- `domain-renewal-dry-run.txt`：使用最终 Certbot 镜像模拟域名续期成功。
- `security-summary.json`、`app-patched.json`、`nginx-patched.json`、`certbot-patched3.json`：Trivy 0.76 对三个最终镜像扫描，HIGH/CRITICAL 均为 0。修复前扫描亦保留。更新系统包及证书依赖，并移除证书运行镜像中不需要的 pip/setuptools/wheel、清理安装缓存。扫描仅代表当时漏洞库结果。
- 题库 SHA-256：`990b60fdd11b1d1e83a2d156e3dd16903c87b302e4ad86ec723b3b1aa8f7d897`，与发布前一致。题库及作答数据库 `PRAGMA integrity_check` 均为 ok。
- 更新前、更新后均完成 SQLite 一致性备份，现有记录使用同一命名卷保留。实际备份和续期服务 Result=success，定时器已启用。

## 浏览器验收

本机经 Cloudflare 直连的首轮浏览器测试出现导航超时、试卷接口等待超时；未将这些失败计为通过。服务器与本机 curl 的域名 HTTPS 请求成功。后续浏览器通过 SSH SOCKS 网络通道访问同一公开域名及 Cloudflare，保留正常 HTTPS 证书验证，以隔离本机出口链路。最终 **4/4 通过，0 失败、0 重试**，耗时约 1.4 分钟，覆盖桌面和手机的练习、评分、答案隐藏、只读回顾及 Secure/HttpOnly/SameSite Cookie。测试统计见 `live-browser.json`，截图见同目录桌面/手机 reading/result PNG。该结果证明代理通道下的域名业务链路通过，不消除本地出口先前出现的偶发超时。

## 运行与限制

容器仅由 NGINX 发布 TCP 80/443，后端不直接暴露。每天自动一致性备份，每 6 小时检查续期，续期后配置校验并重载 NGINX。续期需继续放通 TCP 80。当前备份保存在同机，未配置异地备份及可用性告警；匿名历史记录仍依赖浏览器身份，原 IP Cookie 不跨域迁移。运维及回退说明见 `../../docs/deployment.md`。
