"""阅读练习平台 API 与生产静态资源入口。"""

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.app.db.database import DEFAULT_DATABASE
from backend.app.services.platform import Platform
from backend.app.api.platform import router

ROOT = Path(__file__).resolve().parents[2]


def create_app(bank: Path = DEFAULT_DATABASE, runtime: Path | None = None):
    if os.getenv("APP_ENV") == "production":
        origin = urlsplit(os.getenv("PUBLIC_ORIGIN", ""))
        hosts = os.getenv("ALLOWED_HOSTS", "")
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
            or os.getenv("COOKIE_SECURE") != "1"
            or not hosts
            or "*" in hosts
        ):
            raise RuntimeError(
                "生产环境须设置 HTTPS PUBLIC_ORIGIN、COOKIE_SECURE=1 和明确的 ALLOWED_HOSTS"
            )
    store = Platform(
        bank, runtime or Path(os.getenv("APP_DATABASE", ROOT / "data/practice.sqlite3"))
    )

    @asynccontextmanager
    async def lifespan(_app):
        async def clock():
            while True:
                await asyncio.sleep(15)
                try:
                    await asyncio.to_thread(store.expire)
                except Exception:
                    logging.exception("到时结算失败，将在下一轮或下次访问重试")

        task = asyncio.create_task(clock())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(
        title="阅读练习室",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if os.getenv("ENABLE_API_DOCS") == "1" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json"
        if os.getenv("ENABLE_API_DOCS") == "1"
        else None,
    )
    app.state.store = store
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=os.getenv(
            "ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"
        ).split(","),
    )

    @app.middleware("http")
    async def security(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > 16384:
                return JSONResponse({"detail": "请求过大或长度无效"}, 413)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 16384:
                    return JSONResponse({"detail": "请求过大"}, 413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
            origin = request.headers.get("origin")
            expected = os.getenv("PUBLIC_ORIGIN") or str(request.base_url).rstrip("/")
            if origin and origin != expected:
                return JSONResponse({"detail": "来源不允许"}, 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(sqlite3.OperationalError)
    async def database_busy(_request, error):
        logging.error("SQLite operation failed: %s", type(error).__name__)
        return JSONResponse(
            {"detail": "服务暂时繁忙，请重试"}, 503, headers={"Retry-After": "2"}
        )

    app.include_router(router(store))
    dist = ROOT / "frontend/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
