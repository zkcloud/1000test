import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(runtime=tmp_path / "sessions.sqlite3")
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = c.get("/api/visitor").json()["csrf"]
        yield c


def start(c, mode="exam", scope=None):
    r = c.post("/api/attempts", json=dict(exam_id=1, mode=mode, scope=scope))
    assert r.status_code == 201, r.text
    return r.json()


def save(c, a, qid, label):
    r = c.put(
        f"/api/attempts/{a['id']}/questions/{qid}/answer",
        json=dict(selection=label, revision=a["revision"]),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_exam_answers_are_absent_until_submission(client):
    a = start(client)
    assert len(a["questions"]) == 100 and not a["auto_next"]
    assert "result" not in a
    q = client.get(f"/api/attempts/{a['id']}/questions/1").json()
    assert "answer" not in q and "explanation" not in q
    assert client.post(f"/api/attempts/{a['id']}/questions/1/reveal").status_code == 403
    a = save(client, a, 1, "A")
    a = save(client, a, 2, "B")
    final = client.post(f"/api/attempts/{a['id']}/submit").json()
    assert final["result"]["score"] == 1
    assert final["result"]["wrong"] == 1 and final["result"]["blank"] == 98
    q = client.get(f"/api/attempts/{a['id']}/questions/1").json()
    assert q["answer"] == "A" and q["explanation"]
    again = client.post(f"/api/attempts/{a['id']}/submit").json()
    assert (
        again["finished_at"] == final["finished_at"]
        and again["result"] == final["result"]
    )
    assert (
        client.put(
            f"/api/attempts/{a['id']}/questions/1/answer",
            json=dict(selection="B", revision=final["revision"]),
        ).status_code
        == 409
    )


def test_practice_peek_is_per_question_and_first_answer_immutable(client):
    a = start(client, "practice", 5)
    a = client.post(f"/api/attempts/{a['id']}/questions/1/reveal").json()
    a = save(client, a, 1, "A")
    a = save(client, a, 2, "B")
    a = client.post(f"/api/attempts/{a['id']}/questions/2/reveal").json()
    a = save(client, a, 2, "A")
    assert "answer" not in client.get(f"/api/attempts/{a['id']}/questions/3").json()
    assert client.get(f"/api/attempts/{a['id']}/questions/31").status_code == 404
    result = client.post(f"/api/attempts/{a['id']}/submit").json()["result"]
    assert result["score"] is None
    assert (
        result["peek_first"] == 1
        and result["independent_total"] == 1
        and result["independent_correct"] == 0
    )


def test_deadline_is_authoritative_and_persistent(client):
    a = start(client)
    with sqlite3.connect(client.app.state.store.runtime) as db:
        db.execute(
            "UPDATE attempts SET deadline=? WHERE id=?", (time.time() - 1, a["id"])
        )
    assert (
        client.put(
            f"/api/attempts/{a['id']}/questions/1/answer",
            json=dict(selection="A", revision=a["revision"]),
        ).status_code
        == 409
    )
    final = client.get(f"/api/attempts/{a['id']}").json()
    assert final["status"] == "finished" and final["result"]["blank"] == 100
    assert final["finished_at"] == final["deadline"]


def test_owner_isolation_csrf_and_security_headers(client):
    a = start(client)
    with TestClient(client.app) as other:
        other.headers["X-CSRF-Token"] = other.get("/api/visitor").json()["csrf"]
        assert other.get(f"/api/attempts/{a['id']}").status_code == 404
        assert other.get(f"/api/attempts/{a['id']}/questions/1").status_code == 404
        assert other.get("/api/attempts").json() == []
    assert (
        client.post(
            "/api/attempts",
            json=dict(exam_id=1, mode="exam"),
            headers={"X-CSRF-Token": "bad"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/attempts",
            json=dict(exam_id=1, mode="exam"),
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    r = client.get("/api/exams")
    assert (
        r.headers["cache-control"] == "no-store"
        and r.headers["x-content-type-options"] == "nosniff"
    )
    assert "httponly" in client.get("/api/visitor").headers["set-cookie"].lower()


def test_revisions_reject_stale_writes_and_restore_settings(client):
    a = start(client)
    b = save(client, a, 1, "A")
    assert (
        client.put(
            f"/api/attempts/{a['id']}/questions/1/answer",
            json=dict(selection="B", revision=a["revision"]),
        ).status_code
        == 409
    )
    r = client.patch(
        f"/api/attempts/{a['id']}",
        json=dict(auto_next=True, current_index=30, revision=b["revision"]),
    )
    assert r.status_code == 200
    restored = client.get(f"/api/attempts/{a['id']}").json()
    assert (
        restored["auto_next"]
        and restored["current_index"] == 30
        and restored["responses"]["1"]["selection"] == "A"
    )


def test_input_validation_and_scoped_material(client):
    assert (
        client.post(
            "/api/attempts", json=dict(exam_id=1, mode="exam", scope=5)
        ).status_code
        == 422
    )
    a = start(client, "practice", 6)
    q = client.get(f"/api/attempts/{a['id']}/questions/31").json()
    assert q["passage"]["first_number"] == 131
    image = client.get(q["passage"]["assets"][0]["url"])
    assert image.status_code == 200 and image.content.startswith(b"\xff\xd8")
    assert client.get(f"/api/attempts/{a['id']}/assets/99999").status_code == 404
    assert (
        client.put(
            f"/api/attempts/{a['id']}/questions/31/answer",
            json=dict(selection="E", revision=a["revision"]),
        ).status_code
        == 422
    )


def test_concurrent_submit_and_save_cannot_mutate_finished_attempt(client):
    a = start(client)

    def submit():
        return client.post(f"/api/attempts/{a['id']}/submit").status_code

    def answer():
        return client.put(
            f"/api/attempts/{a['id']}/questions/1/answer",
            json=dict(selection="A", revision=0),
        ).status_code

    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(lambda fn: fn(), [submit, answer]))
    assert statuses[0] == 200 and statuses[1] in (200, 409)
    result = client.get(f"/api/attempts/{a['id']}").json()
    assert result["status"] == "finished" and result["result"]["score"] in (0, 1)
