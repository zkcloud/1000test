"""汇总可复核的本地验收证据并生成运行部署包。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

from fastapi.testclient import TestClient
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/release"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    backend = ET.parse(REPORT / "iteration-3.xml").getroot()
    suites = list(backend.iter("testsuite"))
    tests = len(list(backend.iter("testcase")))
    assert tests >= 21, "后端测试收集数量异常"
    assert (
        sum(
            int(s.attrib.get("failures", 0)) + int(s.attrib.get("errors", 0))
            for s in suites
        )
        == 0
    )
    browser = load(REPORT / "browser-tests.json")["stats"]
    assert (
        browser["unexpected"] == 0
        and browser["expected"] >= 20
        and not browser["skipped"]
    )
    npm = load(REPORT / "npm-audit.json")
    assert npm["metadata"]["vulnerabilities"]["total"] == 0
    python = load(REPORT / "python-audit.json")
    assert all(not d["vulns"] for d in python["dependencies"])
    smoke = load(REPORT / "package-smoke.json")
    assert smoke["status"] == "passed" and smoke["fresh_runtime_only_environment"]
    bank = ROOT / "data/questions.sqlite3"
    audit = load(ROOT / "audit/2026-11-11/summary.json")
    assert sha(bank) == audit["database_sha256"], "题库被修改"
    # 进程内功能并发检查，不冒充网络或生产环境压力测试。
    with tempfile.TemporaryDirectory() as folder:
        with TestClient(create_app(runtime=Path(folder) / "runtime.sqlite3")) as client:

            def request(_):
                start = time.perf_counter()
                response = client.get("/api/exams")
                assert response.status_code == 200 and len(response.json()) == 10
                return (time.perf_counter() - start) * 1000

            with ThreadPoolExecutor(max_workers=8) as pool:
                latency = list(pool.map(request, range(200)))
            smoke = client.get("/")
            assert smoke.status_code == 200 and 'id="app"' in smoke.text
            assert "frame-ancestors" in smoke.headers["content-security-policy"]
    performance = dict(
        scope="In-process TestClient; 8 threads, 200 read requests; not a production load claim",
        requests=200,
        failures=0,
        p50_ms=round(statistics.median(latency), 2),
        p95_ms=round(sorted(latency)[189], 2),
        max_ms=round(max(latency), 2),
    )
    (REPORT / "concurrency.json").write_text(
        json.dumps(performance, ensure_ascii=False, indent=2), encoding="utf8"
    )
    summary = dict(
        timestamp=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        status="local-acceptance-passed / production-not-deployed",
        backend_tests=tests,
        browser_tests=browser["expected"],
        npm_vulnerabilities=0,
        python_vulnerabilities=0,
        bank_unchanged=True,
        concurrency=performance,
        typescript_compatibility_exception="6.0.3; latest 7.0.2 incompatible with vue-tsc 3.3.14",
    )
    (REPORT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8"
    )
    text = f"""# 首期平台本地验收报告

时间：{summary["timestamp"]}。结论：三个迭代的开发、调测、本地自动验收已完成；当前为 **1.0.0-rc1 发布候选**，未执行公网部署或生产环境验收。

## 已完成范围

- TypeScript + Vue 3 试卷大厅，真实 10 套/1000 题。
- 考试整套 75 分钟，服务端截止判定、后台到时处理、交卷评分、幂等提交、交卷前 API 不返回答案或解析。
- 练习随时查看答案及解析，首次独立作答统计，暂停/继续，整套、Part、完整材料题组，错题/标记题重练。
- 单选自动下一题默认关闭；开启后必须保存成功才跳转，最后一题不自动交整卷；同组材料组件和阅读位置保留。
- 原版多页材料、纯文本、图片缩放，答题卡、标记、成绩分项、结果筛选及只读回顾。
- 当前浏览器身份下历史与刷新恢复，本地待同步选择、断网重试、并发版本冲突和孤立本地记录明确处理。
- 桌面/手机纵向布局，320px、深色主题、键盘入口与原生确认对话框。
- 访客隔离、CSRF、Origin/Host 校验、HttpOnly/SameSite/Secure Cookie、CSP、请求体限制、只读题库、独立运行数据和在线备份工具。

## 分轮验收

| 迭代 | 开发 | 调测与验收 | 证据 |
| --- | --- | --- | --- |
| 1 | 服务端全流程与答案权限 | 15 项 API/题库测试通过（含原有题库测试） | iteration-1.xml |
| 2 | 前端真实题库流程、自动跳题、断网恢复 | 首批桌面/移动 12 项浏览器测试通过 | 最终扩展结果保留在 browser-tests.json |
| 3 | 题组/重练/暂停、部署配置、安全与备份 | 最终 {tests} 项后端测试、{browser["expected"]} 项浏览器测试通过 | iteration-3.xml / browser-tests.json |

类型检查 `vue-tsc -b`、Vite 生产构建均通过。后端测试还包含题库全量 190 组材料覆盖的子用例，JUnit 测试数不把这些子用例重复算成独立功能测试。每轮发现问题后修正再验收，没有仅以页面能打开作为通过标准。

## 安全与依赖

- npm 官方审计接口：**0 个已知漏洞**；pip-audit：**0 个已知漏洞**。两个扫描包含当前安装的开发依赖。扫描不能覆盖未披露漏洞，需在每次发布重新运行。
- 最新可用稳定依赖已解析并锁定；`npm-outdated.json` 唯一直接依赖版本差距为 TypeScript。当前 6.0.3 是与最新 Vue 类型检查器 3.3.14 实测兼容的版本；最新 7.0.2 触发 `typescript/lib/tsc` 未导出错误，未伪称全组件绝对最新版。
- 后端测试使用当前推荐 httpx2 驱动，已移除旧 httpx 测试依赖。依赖清单：python-dependencies.json、npm-dependencies.json；锁文件随源码/部署包保存。
- 题库 SHA-256 与前次数据审计完全一致：`{sha(bank)}`。

## 并发与恢复

8 线程 200 次进程内试卷列表读取，0 失败，P50 **{performance["p50_ms"]} ms**、P95 **{performance["p95_ms"]} ms**、最大 **{performance["max_ms"]} ms**。这只说明本机功能并发检查，不能作为公网吞吐容量承诺。

测试覆盖交卷/作答竞争、旧 revision 覆盖拒绝、访客越权、到时写入拒绝、重复提交稳定、暂停跨进程初始化恢复、WAL 在线备份并读取恢复记录、禁止覆盖备份、禁止将运行库指向题库、拒绝高版本数据库降级启动、生产不安全配置拒绝启动。

## 浏览器与证据

本次使用本机 Microsoft Edge/Chromium，桌面 1440×1000 和 Pixel 7 手机视口模拟，另含 320px 深色主题。不是实际 Android/iOS 硬件测试，也未声称 Safari/Firefox 已验收。

- desktop-home.png / mobile-home.png：大厅。
- desktop-reading.png / mobile-reading.png：材料与作答。
- desktop-result.png / mobile-result.png：交卷结果。
- desktop-dark-320.png / mobile-dark-320.png：320px 深色布局。
- browser-tests.json：{browser["expected"]} 项最终浏览器测试（含孤立本地记录恢复和连续点击防护）；失败时 Playwright 保留截图和 trace。
- iteration-1.xml / iteration-3.xml：后端验证结果；concurrency.json：并发明细。
- package-smoke.json / package-install.log / package-server.log：部署包在独立目录、独立虚拟环境中仅安装运行依赖（锁定离线安装），无需 Node，已验证网页/脚本、Cookie/CSRF、练习、材料图、保存、答案解析和提交结果。不是依靠开发环境才可运行。

## 尚需生产环境落实的发布门槛

配置真实域名与 TLS、服务守护与磁盘、异地备份、日志和告警，并按预期峰值做生产压测与目标终端浏览器验收。首期按已确认设计不包含账号、跨设备找回或收费。匿名 Cookie 丢失无法找回记录；练习需显式暂停或返回大厅停止累计时间。

详见 [部署说明](../../docs/deployment.md)。这些环境事实未提供，因此本报告结论为“首期功能本地验收通过、已具备部署准备”，不将本地通过包装成“已生产上线且永久无漏洞”。
"""
    (REPORT / "acceptance.md").write_text(text, encoding="utf8")
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    files = [
        ROOT / name
        for name in [
            "pyproject.toml",
            "uv.lock",
            ".python-version",
            ".env.example",
            "README.md",
            "backend/__init__.py",
            "data/questions.sqlite3",
            "data/vocabulary.sqlite3",
            "docs/deployment.md",
            "deploy/nginx.conf.example",
            "backend/scripts/__init__.py",
            "backend/scripts/backup_runtime.py",
        ]
    ]
    files.extend(
        p
        for p in (ROOT / "backend/app").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    files.extend(p for p in (ROOT / "frontend/dist").rglob("*") if p.is_file())
    files.extend(
        p for p in REPORT.iterdir() if p.is_file() and p.name != "summary.json"
    )
    manifest = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in files}
    archive = output / "reading-practice-1.0.0-rc1.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in files:
            package.write(path, str(path.relative_to(ROOT)))
        package.writestr("release-manifest.json", json.dumps(manifest, indent=2))
        package.writestr(
            "DEPLOY.txt",
            "运行部署包：解压到新目录，从该目录执行 uv sync --locked --no-dev，然后 uv run --no-dev uvicorn backend.app.main:app --host 127.0.0.1 --port 8000。网页已构建，无须 Node。访问 http://127.0.0.1:8000。公网配置先阅读 docs/deployment.md。完整源码及前端开发/重建请使用工作区仓库；此包仅含运行代码、已构建网页、只读题库和验收证据。备份工具已包含。",
        )
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
    summary.update(package_sha256=sha(archive), package_bytes=archive.stat().st_size)
    (REPORT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
