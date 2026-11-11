# 试题练习平台

仅搭建项目骨架，尚未实现题库、答题、评分、用户或数据库功能。现有 PDF 保留原样，尚未导入。

## 技术栈

- 后端：Python 3.12、uv、FastAPI、Uvicorn
- 前端：Vue 3、TypeScript、Vite，使用 npm 管理依赖

## 目录

```text
backend/app/
  main.py       # FastAPI 入口
  api/          # 业务路由预留
  schemas/      # 请求和响应模型预留
  services/     # 业务逻辑预留
frontend/
  src/
    App.vue     # 占位首页
    main.ts     # Vue 入口
    components/ # 组件预留
pyproject.toml  # Python 依赖与版本约束
uv.lock         # Python 依赖锁定
.python-version # Python 3.12
```

## 本地开发

需要 uv 和满足 Vite 要求的 Node.js。所有命令从项目根目录执行。

终端一，安装并启动后端：

```powershell
uv sync --locked
uv run uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

接口文档：http://127.0.0.1:8000/docs 。目前没有业务接口。

终端二，安装并启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

首页：http://localhost:5173 。开发服务器会将 `/api` 请求转发到后端 8000 端口，保留 `/api` 前缀；后续业务路由统一使用该前缀。该代理仅用于本地开发，部署时需另行配置。

## 基础检查

```powershell
uv run python -c "from backend.app.main import app; assert app.openapi()['info']['title'] == '试题练习平台'"
cd frontend
npm run build
```

前端构建包含 TypeScript 类型检查，输出在 `frontend/dist/`。
