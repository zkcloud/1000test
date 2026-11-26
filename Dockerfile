# syntax=docker/dockerfile:1
FROM node:lts-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-alpine AS dependencies
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /build
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --compile-bytecode

FROM python:3.12-alpine AS runtime
RUN apk upgrade --no-cache \
    && addgroup -g 10001 app && adduser -D -u 10001 -G app app \
    && mkdir -p /var/lib/reading /app/data \
    && chown -R app:app /var/lib/reading /app
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=app:app backend/__init__.py backend/__init__.py
COPY --chown=app:app backend/app/ backend/app/
COPY --chown=app:app backend/scripts/__init__.py backend/scripts/backup_runtime.py backend/scripts/
COPY --chown=app:app data/questions.sqlite3 data/vocabulary.sqlite3 data/
COPY --from=frontend --chown=app:app /frontend/dist/ frontend/dist/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"
CMD ["python","-m","uvicorn","backend.app.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips","172.30.50.0/24"]
