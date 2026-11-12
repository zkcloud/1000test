import sqlite3
import time
from fastapi.testclient import TestClient
from backend.app.main import create_app


def test_group_selection_retry_preserves_material_and_scope(tmp_path):
    with TestClient(create_app(runtime=tmp_path / "runtime.sqlite3")) as c:
        c.headers["X-CSRF-Token"] = c.get("/api/visitor").json()["csrf"]
        groups = c.get("/api/exams/1/passages").json()
        group = groups[0]
        a = c.post(
            "/api/attempts",
            json=dict(exam_id=1, mode="practice", passage_id=group["id"]),
        ).json()
        assert [q["number"] for q in a["questions"]] == [131, 132, 133, 134]
        aid = a["id"]
        a = c.put(
            f"/api/attempts/{aid}/questions/31/answer",
            json=dict(selection="A", revision=a["revision"]),
        ).json()
        a = c.put(
            f"/api/attempts/{aid}/questions/31/mark",
            json=dict(marked=True, revision=a["revision"]),
        ).json()
        c.post(f"/api/attempts/{aid}/submit")
        for kind in ["wrong", "marked"]:
            retry = c.post(
                "/api/attempts",
                json=dict(
                    exam_id=1, mode="practice", source_attempt=aid, retry_filter=kind
                ),
            ).json()
            assert [q["id"] for q in retry["questions"]] == [31]
            q = c.get(f"/api/attempts/{retry['id']}/questions/31").json()
            assert q["passage"]["last_number"] == 134
            assert c.get(f"/api/attempts/{retry['id']}/questions/32").status_code == 404
        assert (
            c.post(
                "/api/attempts",
                json=dict(
                    exam_id=2, mode="practice", source_attempt=aid, retry_filter="wrong"
                ),
            ).status_code
            == 422
        )


def test_pause_does_not_accumulate_idle_time_and_survives_restart(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    app = create_app(runtime=path)
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = c.get("/api/visitor").json()["csrf"]
        a = c.post("/api/attempts", json=dict(exam_id=1, mode="practice")).json()
        with sqlite3.connect(path) as db:
            db.execute(
                "UPDATE attempts SET active_since=? WHERE id=?",
                (time.time() - 45, a["id"]),
            )
        a = c.post(f"/api/attempts/{a['id']}/pause").json()
        assert a["paused"] and 44 <= a["duration_seconds"] <= 46
        assert (
            c.put(
                f"/api/attempts/{a['id']}/questions/1/answer",
                json=dict(selection="A", revision=a["revision"]),
            ).status_code
            == 409
        )
        create_app(runtime=path)  # 模拟进程重启，不应重启已暂停的计时
        a = c.get(f"/api/attempts/{a['id']}").json()
        assert a["paused"] and 44 <= a["duration_seconds"] <= 46
        a = c.post(f"/api/attempts/{a['id']}/resume").json()
        assert not a["paused"]
        r = c.post(f"/api/attempts/{a['id']}/submit").json()["result"]
        assert 44 <= r["duration_seconds"] <= 47
