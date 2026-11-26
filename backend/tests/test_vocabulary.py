import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.fixture
def bank_path(tmp_path):
    path = tmp_path / "vocabulary.sqlite3"
    schema = Path(__file__).resolve().parents[1] / "app/db/vocabulary.sql"
    with sqlite3.connect(path) as db:
        db.executescript(schema.read_text(encoding="utf-8"))
        db.execute("INSERT INTO meta VALUES ('version', 'fixture-v1')")
        for index, (word, meaning) in enumerate(
            (
                ("strict", "严格的；严厉的"),
                ("stern", "严厉的"),
                ("recent", "最近的"),
                ("formal", "正式的"),
                ("flexible", "灵活的"),
                ("nonrefundable", "不能退款的"),
                ("unverified", "未核对的"),
            ),
            1,
        ):
            db.execute(
                "INSERT INTO words VALUES (?, ?, ?, 'word')", (index, word, word)
            )
            ready = word != "unverified"
            cue = "不能退款的，形容款项无法退回" if word == "nonrefundable" else None
            variants = '["non-refundable"]' if cue else "[]"
            db.execute(
                """INSERT INTO senses VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?
                )""",
                (
                    index,
                    index,
                    "adj." if ready else "",
                    meaning,
                    f"a {word} policy" if ready else "",
                    f"This is a {word} policy." if ready else None,
                    "这是相关政策。" if ready else None,
                    "supplemental" if ready else None,
                    ready,
                    cue,
                    variants,
                ),
            )
            test = 1 if index < 6 else 10
            db.execute(
                "INSERT INTO sense_sources VALUES (?, ?, 450, '1221', 1, 450, 101, 105)",
                (index, test),
            )
        db.execute(
            "INSERT INTO sense_sources VALUES (1, 10, 1197, '1968', 26, 1197, 191, 195)"
        )
    return path


@pytest.fixture
def client(tmp_path, bank_path):
    with TestClient(
        create_app(runtime=tmp_path / "practice.sqlite3", vocabulary_bank=bank_path)
    ) as client:
        yield client


def test_vocabulary_lookup_preserves_provenance_and_missing_enrichment(client):
    response = client.get("/api/vocabulary/words", params={"test": 10, "page": 7})
    assert response.status_code == 200
    result = response.json()
    assert result["page"] == result["pages"] == 1
    assert [word["word"] for word in result["items"]] == [
        "strict",
        "nonrefundable",
        "unverified",
    ]
    search = client.get("/api/vocabulary/words", params={"q": "　NON-REFUNDABLE  "})
    assert search.json()["items"][0]["word"] == "nonrefundable"
    partial_cue = client.get("/api/vocabulary/words", params={"q": "款项无法"})
    assert partial_cue.json()["items"] == []
    exact_cue = client.get(
        "/api/vocabulary/words", params={"q": "不能退款的，形容款项无法退回"}
    )
    assert exact_cue.json()["items"][0]["word"] == "nonrefundable"
    strict = client.get("/api/vocabulary/words/1").json()["senses"][0]
    assert [(s["test_number"], s["pdf_page"]) for s in strict["sources"]] == [
        (1, 450),
        (10, 1197),
    ]
    unverified = client.get("/api/vocabulary/words/7").json()["senses"][0]
    assert unverified["example"] is None
    assert unverified["meaning"] == "未核对的"


def test_rounds_check_option_membership_and_spelling_variants(client):
    response = client.post("/api/vocabulary/rounds", json={"mode": "choice"})
    assert response.status_code == 200
    questions = response.json()["questions"]
    assert len(questions) == 6
    assert len({question["token"] for question in questions}) == len(questions)
    question = next(q for q in questions if q["prompt"] == "严格的；严厉的")
    assert set(question) == {"token", "prompt", "pos", "options"}
    assert len(question["options"]) == 4
    options = {option["label"]: option["id"] for option in question["options"]}
    assert "stern" not in options
    assert "unverified" not in options
    assert options["strict"] != "strict"

    def grade(token, answer):
        return client.post(
            "/api/vocabulary/answers", json={"question_token": token, "answer": answer}
        )

    assert grade(question["token"], "非法选项").status_code == 422
    token = question["token"]
    payload, signature = token.split(".")
    wrong_signature = ("B" if signature.startswith("A") else "A") + signature[1:]
    assert grade(f"{payload}.{wrong_signature}", options["strict"]).status_code == 410
    correct = grade(question["token"], options["strict"]).json()
    assert correct["correct"] is True
    assert correct["correct_answer"] == "strict"
    assert correct["sense"]["example"]["kind"] == "supplemental"
    alternative = next(word for word in options if word != "strict")
    incorrect = grade(question["token"], options[alternative]).json()
    assert incorrect["correct"] is False
    assert incorrect["given_answer"] == alternative

    response = client.post("/api/vocabulary/rounds", json={"mode": "spelling"}).json()
    (question,) = response["questions"]
    assert question["options"] == []
    assert question["pos"] is None
    assert grade(question["token"], "  NON-REFUNDABLE ").json()["correct"] is True
    assert grade(question["token"], "nonrefudable").json()["correct"] is False
    assert grade(question["token"], "  ").status_code == 422


def test_bank_update_invalidates_questions_and_missing_bank_is_scoped(
    client, bank_path, tmp_path
):
    round_response = client.post("/api/vocabulary/rounds", json={"mode": "spelling"})
    question = round_response.json()["questions"][0]
    with sqlite3.connect(bank_path) as db:
        db.execute("UPDATE meta SET value='fixture-v2' WHERE key='version'")
    assert (
        client.post(
            "/api/vocabulary/answers",
            json={"question_token": question["token"], "answer": "nonrefundable"},
        ).status_code
        == 410
    )

    missing_bank = tmp_path / "missing.sqlite3"
    with TestClient(
        create_app(runtime=tmp_path / "other.sqlite3", vocabulary_bank=missing_bank)
    ) as c:
        assert c.get("/api/vocabulary/words").status_code == 503
        assert c.get("/api/exams").status_code == 200
    assert not missing_bank.exists()
