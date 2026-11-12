"""题库只读，访客作答独立存储，事务串行化交卷和保存竞争。"""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
from fastapi import HTTPException


class Platform:
    def __init__(self, bank: Path, runtime: Path):
        self.bank = bank.resolve()
        self.runtime = runtime.resolve()
        if self.bank == self.runtime:
            raise RuntimeError("题库与作答数据库必须使用不同文件")
        if not self.bank.is_file():
            raise RuntimeError("题库不存在，请先导入题目")
        self.runtime.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.runtime) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] > 2:
                raise RuntimeError("作答数据库版本高于当前程序，不能降级启动")
            db.executescript(
                Path(__file__)
                .parents[1]
                .joinpath("db/runtime.sql")
                .read_text(encoding="utf8")
            )
            columns = {r[1] for r in db.execute("PRAGMA table_info(attempts)")}
            for name, sql_type in [
                ("active_since", "REAL"),
                ("elapsed_seconds", "REAL NOT NULL DEFAULT 0"),
            ]:
                if name not in columns:
                    db.execute(f"ALTER TABLE attempts ADD COLUMN {name} {sql_type}")
            if "active_since" not in columns:
                db.execute(
                    "UPDATE attempts SET active_since=created_at WHERE mode='practice' AND status='active'"
                )
            db.execute("PRAGMA user_version=2")
        with self.connection() as db:
            for a in db.execute(
                "SELECT * FROM attempts WHERE NOT EXISTS (SELECT 1 FROM attempt_questions aq WHERE aq.attempt_id=attempts.id)"
            ).fetchall():
                qs = db.execute(
                    "SELECT id FROM bank.questions WHERE exam_id=? AND status='ready' AND (? IS NULL OR part=?) ORDER BY number",
                    (a["exam_id"], a["scope"], a["scope"]),
                ).fetchall()
                db.executemany(
                    "INSERT INTO attempt_questions VALUES(?,?,?)",
                    [(a["id"], q["id"], i) for i, q in enumerate(qs)],
                )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.runtime, timeout=10, uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("ATTACH DATABASE ? AS bank", (self.bank.as_uri() + "?mode=ro",))
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def owned(db, aid, owner):
        row = db.execute(
            "SELECT * FROM attempts WHERE id=? AND visitor_id=?", (aid, owner)
        ).fetchone()
        if not row:
            raise HTTPException(404, "记录不存在")
        if (
            row["status"] == "active"
            and row["deadline"]
            and time.time() >= row["deadline"]
        ):
            db.execute(
                "UPDATE attempts SET status='finished',finished_at=deadline,revision=revision+1 WHERE id=?",
                (aid,),
            )
            row = db.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
        return row

    @staticmethod
    def questions(db, a):
        return db.execute(
            "SELECT q.id,q.number,q.part,q.passage_id FROM bank.questions q JOIN attempt_questions aq ON aq.question_id=q.id WHERE aq.attempt_id=? ORDER BY aq.position",
            (a["id"],),
        ).fetchall()

    @staticmethod
    def mutable(a):
        if a["status"] != "active":
            raise HTTPException(409, "已交卷或已到截止时间，作答不可修改")
        if a["mode"] == "practice" and a["active_since"] is None:
            raise HTTPException(409, "练习已暂停，请继续后作答")

    def view(self, db, a):
        qs = self.questions(db, a)
        responses = {
            r["question_id"]: dict(r)
            for r in db.execute(
                "SELECT * FROM responses WHERE attempt_id=?", (a["id"],)
            )
        }
        result = {
            k: a[k]
            for k in [
                "id",
                "exam_id",
                "mode",
                "scope",
                "created_at",
                "deadline",
                "finished_at",
                "status",
                "current_index",
                "revision",
            ]
        }
        result.update(
            auto_next=bool(a["auto_next"]),
            server_time=time.time(),
            questions=[dict(q) for q in qs],
            responses={
                qid: {
                    k: r[k]
                    for k in [
                        "selection",
                        "first_selection",
                        "first_peeked",
                        "revealed_at",
                        "marked",
                    ]
                }
                for qid, r in responses.items()
            },
        )
        duration = (
            max(0, (a["finished_at"] or time.time()) - a["created_at"])
            if a["mode"] == "exam"
            else a["elapsed_seconds"]
            + (
                max(0, time.time() - a["active_since"])
                if a["active_since"] and a["status"] == "active"
                else 0
            )
        )
        result.update(
            paused=a["mode"] == "practice" and a["active_since"] is None,
            duration_seconds=int(duration),
        )
        if a["status"] == "finished":
            answers = {
                r["question_id"]: r["correct_label"]
                for r in db.execute(
                    "SELECT a.* FROM bank.answers a JOIN bank.questions q ON q.id=a.question_id WHERE q.exam_id=?",
                    (a["exam_id"],),
                )
            }
            entries = [
                dict(
                    id=q["id"],
                    number=q["number"],
                    part=q["part"],
                    selection=responses.get(q["id"], {}).get("selection"),
                    answer=answers[q["id"]],
                    correct=responses.get(q["id"], {}).get("selection")
                    == answers[q["id"]],
                )
                for q in qs
            ]
            independent = [
                q
                for q in qs
                if responses.get(q["id"], {}).get("first_selection")
                and not responses[q["id"]]["first_peeked"]
            ]
            correct = sum(e["correct"] for e in entries)
            blank = sum(e["selection"] is None for e in entries)
            result["result"] = dict(
                total=len(qs),
                correct=correct,
                wrong=len(qs) - correct - blank,
                blank=blank,
                score=correct if a["mode"] == "exam" else None,
                independent_total=len(independent),
                independent_correct=sum(
                    responses[q["id"]]["first_selection"] == answers[q["id"]]
                    for q in independent
                ),
                peek_first=sum(
                    bool(r.get("revealed_at"))
                    and (not r.get("first_selection") or r.get("first_peeked"))
                    for r in responses.values()
                ),
                duration_seconds=int(duration),
                entries=entries,
            )
        return result

    def expire(self):
        with self.connection() as db:
            db.execute(
                "UPDATE attempts SET status='finished',finished_at=deadline,revision=revision+1 WHERE status='active' AND deadline<=?",
                (time.time(),),
            )

    @staticmethod
    def pause(db, a):
        if (
            a["mode"] == "practice"
            and a["status"] == "active"
            and a["active_since"] is not None
        ):
            db.execute(
                "UPDATE attempts SET elapsed_seconds=elapsed_seconds+?,active_since=NULL,revision=revision+1 WHERE id=?",
                (max(0, time.time() - a["active_since"]), a["id"]),
            )
