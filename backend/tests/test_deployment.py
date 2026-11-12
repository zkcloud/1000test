import sqlite3
import pytest
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.db.database import DEFAULT_DATABASE


def test_production_rejects_insecure_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PUBLIC_ORIGIN", raising=False)
    with pytest.raises(RuntimeError):
        create_app(runtime=tmp_path / "runtime.sqlite3")
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://reading.example.com")
    monkeypatch.setenv("ALLOWED_HOSTS", "reading.example.com")
    monkeypatch.setenv("COOKIE_SECURE", "1")
    with TestClient(
        create_app(runtime=tmp_path / "runtime.sqlite3"),
        base_url="https://reading.example.com",
    ) as c:
        response = c.get("/api/visitor")
        assert (
            response.status_code == 200
            and "secure" in response.headers["set-cookie"].lower()
        )


def test_runtime_path_and_future_schema_are_protected(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(runtime=DEFAULT_DATABASE)
    path = tmp_path / "runtime.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError):
        create_app(runtime=path)


def test_large_or_chunked_body_is_rejected(tmp_path):
    with TestClient(create_app(runtime=tmp_path / "runtime.sqlite3")) as c:
        assert c.post("/api/attempts", content=b"x" * 17000).status_code == 413
        assert (
            c.post(
                "/api/attempts", content=iter([b"x" * 10000, b"y" * 10000])
            ).status_code
            == 413
        )
