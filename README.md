# 试题练习平台

已实现考试与练习平台，接入 10 套试卷、1000 道题的 SQLite 题库。支持限时考试、交卷评分、逐题解析、练习暂停、题组练习、错题重练、标记、自动下一题及当前浏览器历史记录。原 PDF 与已审计题库保留原样。

首期功能与验收记录见 `docs/iterations.md`；发布验收报告见 `reports/release/acceptance.md`；生产配置、备份及恢复见 `docs/deployment.md`。当前为本地验证的发布候选版本，尚未部署到公网。

## 技术栈

- 后端：Python 3.12、uv、FastAPI、Uvicorn
- 前端：Vue 3、TypeScript、Vite，使用 npm 管理依赖
- 数据库：SQLite（Python 标准库 sqlite3）；PDF 导入工具：PyMuPDF（dev 依赖）

## 目录

```text
backend/app/
  main.py       # FastAPI 入口
  api/          # 访客、试卷、作答、交卷与回顾 API
  schemas/      # 请求和响应模型预留
  services/     # 事务、服务端截止计时、评分及练习统计
  db/           # 只读题库与独立作答数据库结构
frontend/
  src/
    App.vue     # 大厅、作答、成绩与回顾
    main.ts     # Vue 入口
    components/ # 共用材料阅读组件
    usePlatform.ts # 类型化会话、自动保存与断网重试
pyproject.toml  # Python 依赖与版本约束
uv.lock         # Python 依赖锁定
.python-version # Python 3.12
```

## 本地开发

需要 uv 和满足 Vite 要求的 Node.js。所有命令从项目根目录执行。

终端一，安装并启动后端：

```powershell
uv sync --locked
$env:PUBLIC_ORIGIN='http://localhost:5173'
uv run uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：http://127.0.0.1:8000/api/health 。默认关闭接口文档；设置 `ENABLE_API_DOCS=1` 后访问 `/api/docs`。开发模式 `PUBLIC_ORIGIN` 必须与前台地址一致。

终端二，安装并启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

首页：http://localhost:5173 。开发服务器会将 `/api` 请求转发到后端 8000 端口，保留 `/api` 前缀；后续业务路由统一使用该前缀。该代理仅用于本地开发，部署时需另行配置。

## 基础检查

```powershell
uv run pytest backend/tests -q
cd frontend
npm run build
```

前端构建包含 TypeScript 类型检查，输出在 `frontend/dist/`。

本机浏览器验收：`cd frontend; npm run test:e2e`（默认使用已安装的 Microsoft Edge，独立测试数据库与业务数据分开）。在其他机器上设置 `PLAYWRIGHT_CHANNEL=chromium` 并先运行 `npx playwright install chromium`。测试证据保存在 `reports/release/`。

也可直接构建并由后端同时提供网页：先执行 `cd frontend; npm ci; npm run build`，再从根目录以 `uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` 启动，访问 http://127.0.0.1:8000 。此模式将 `PUBLIC_ORIGIN` 改为 `http://127.0.0.1:8000` 或清除开发设置。

题库在 `data/questions.sqlite3`（运行时只读），作答记录在 `data/practice.sqlite3`（SQLite WAL，首次启动自动建表）。不能将两个路径设为同一文件。匿名访客 Cookie 丢失后无法找回原历史记录，首期不包含账号登录和跨设备同步。

## 我要背单词

主导航进入「我要背单词」后，可用英文或中文查词，并按 Test 筛选。词库来自原书 Test 01–10 的 270 个 `Vocabulary Check` 板块。词条保留原书位置，例句标注为原书例句或补充例句。用法或例句待核对的义项仍可查阅释义，练习从资料完整的义项中出题。两种练习每轮最多 10 题，提交后显示答案与解析，进度保留在本轮页面。

应用仅读取随代码提供的 `data/vocabulary.sqlite3`。需要从原书重建词库时，在项目根目录执行以下命令。

```shell
uv run python -m backend.scripts.import_vocabulary
```

导入会核对 PDF 与试卷题库的来源，按套次检查板块覆盖，并在通过 SQLite 完整性检查后替换词库。可用 `--pdf`、`--question-bank` 和 `--database` 指定输入与输出。

## 题库

- 数据结构：`docs/data-model.md`
- 建表脚本：`backend/app/db/schema.sql`
- SQLite 数据库：`data/questions.sqlite3`（材料截图以 JPEG BLOB 保存，数据库可单独携带）
- 导入核对报告：`data/import-report.json`
- 连接入口：`backend/app/db/database.py` 中的 `connect_database()`，每个连接开启外键约束

从根目录执行（不需要启动服务）：

```powershell
uv sync --locked
uv run python -m backend.scripts.import_questions
uv run python -m unittest discover -s backend/tests -v
```

导入默认使用根目录唯一的 PDF；可用 `--pdf <路径>` 和 `--database <路径>` 指定输入输出。相同来源以 SHA-256 去重，重复运行跳过，已有题库不会重复写入。导入在单个事务内完成，结构检查失败时回滚本次数据。

题号沿用原书每套的 101–200，Part 5/6/7 分别有 30/16/54 题。Part 6/7 必须同时读取关联材料及 `passage_assets`，部分材料是图片，纯文本并不完整。截图按 `sequence` 顺序展示；图片内文字未进行 OCR。答案保存在独立的 `answers` 表，出题查询只取题目、选项和材料，交卷后再读取答案及解析。

原书有一组范围将 131–134 误写为 131–144，结构化关联已修正，原始引导语与校正记录仍保留。解析中的集中排版已按题序拆分；当前通过自动完整性检查并做了原页抽查，尚未逐题人工校对全部措辞。

## 2026-11-11 数据审计

已固定种子随机抽取 100 题，并扩展到全量 1000 题的原文文字对照和 190 组材料截图检查。修复了 59 组材料的页底裁切缺损，素材数由 357 增至 359，题干、选项、答案和解析未改写。导入时会检查材料截图覆盖，失败则拒绝提交。

- 测试报告：`audit/2026-11-11/report.md`
- 100 题对照证据：`audit/2026-11-11/index.html`
- 完整证据包：`audit/2026-11-11-evidence.zip`
- 文件保留修复前后数据库、源 PDF、原页图、检查日志和 SHA-256 清单。

```powershell
uv run python -m backend.scripts.audit_questions --phase recheck
uv run python -m backend.scripts.audit_spatial --phase recheck
```

## 线上部署

正式地址：https://ty.1byte.online 。运维说明见 [docs/deployment.md](docs/deployment.md)，部署验收见 [reports/deployment/report.md](reports/deployment/report.md)。
