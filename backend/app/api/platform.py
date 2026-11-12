"""访客身份、CSRF、防越权与考试状态约束均由服务端执行。"""

import hashlib
import os
import secrets
import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Start(Input):
    exam_id: int = Field(gt=0)
    mode: Literal["exam", "practice"]
    scope: Literal[5, 6, 7] | None = None
    passage_id: int | None = Field(default=None, gt=0)
    source_attempt: str | None = Field(default=None, max_length=64)
    retry_filter: Literal["wrong", "marked"] | None = None


class Answer(Input):
    selection: Literal["A", "B", "C", "D"] | None
    revision: int = Field(ge=0)


class Settings(Input):
    revision: int = Field(ge=0)
    current_index: int | None = Field(default=None, ge=0)
    auto_next: bool | None = None


class Mark(Input):
    marked: bool
    revision: int = Field(ge=0)


def router(store):
    api = APIRouter(prefix="/api")

    def owner(request: Request):
        token = request.cookies.get("reader_visitor", "")
        identity = hashlib.sha256(token.encode()).hexdigest()
        with store.connection() as db:
            row = db.execute(
                "SELECT * FROM visitors WHERE id=?", (identity,)
            ).fetchone()
            if not row:
                raise HTTPException(401, "访客身份已失效，请刷新页面")
            if request.method != "GET" and not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), row["csrf"]
            ):
                raise HTTPException(403, "安全令牌无效，请刷新页面")
        return identity

    def throttle(db, key, limit):
        now = time.time()
        db.execute("DELETE FROM rate_limits WHERE window<?", (now - 3600,))
        row = db.execute("SELECT * FROM rate_limits WHERE key=?", (key,)).fetchone()
        if row and now - row["window"] < 60 and row["count"] >= limit:
            raise HTTPException(
                429, "操作过于频繁，请稍后重试", headers={"Retry-After": "60"}
            )
        if not row or now - row["window"] >= 60:
            db.execute("INSERT OR REPLACE INTO rate_limits VALUES(?,?,1)", (key, now))
        else:
            db.execute("UPDATE rate_limits SET count=count+1 WHERE key=?", (key,))

    def question_in(db, a, qid):
        row = db.execute(
            "SELECT q.* FROM bank.questions q JOIN attempt_questions aq ON aq.question_id=q.id WHERE aq.attempt_id=? AND q.id=?",
            (a["id"], qid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "题目不属于当前练习")
        return row

    def revision(db, a, expected):
        if a["revision"] != expected:
            raise HTTPException(409, "其他窗口已修改此记录，请刷新后重试")
        db.execute("UPDATE attempts SET revision=revision+1 WHERE id=?", (a["id"],))

    @api.get("/health")
    def health():
        with store.connection() as db:
            db.execute("SELECT id FROM bank.exams LIMIT 1").fetchone()
        return {"status": "ok"}

    @api.get("/visitor")
    def visitor(request: Request, response: Response):
        token = request.cookies.get("reader_visitor", "")
        identity = hashlib.sha256(token.encode()).hexdigest()
        with store.connection() as db:
            row = db.execute(
                "SELECT * FROM visitors WHERE id=?", (identity,)
            ).fetchone()
            if not row:
                throttle(
                    db,
                    "new:"
                    + hashlib.sha256(
                        (request.client.host if request.client else "unknown").encode()
                    ).hexdigest(),
                    30,
                )
                token = secrets.token_urlsafe(32)
                identity = hashlib.sha256(token.encode()).hexdigest()
                csrf = secrets.token_urlsafe(32)
                db.execute(
                    "INSERT INTO visitors VALUES(?,?,?)", (identity, csrf, time.time())
                )
            else:
                csrf = row["csrf"]
        response.set_cookie(
            "reader_visitor",
            token,
            httponly=True,
            secure=os.getenv("COOKIE_SECURE") == "1",
            samesite="strict",
            max_age=31536000,
            path="/",
        )
        return {"csrf": csrf}

    @api.get("/exams")
    def exams():
        with store.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT e.id,e.number,e.title,e.duration_minutes,count(q.id) total FROM bank.exams e JOIN bank.questions q ON q.exam_id=e.id AND q.status='ready' GROUP BY e.id ORDER BY e.number"
                )
            ]

    @api.post("/attempts", status_code=201)
    def start(body: Start, identity=Depends(owner)):
        if body.mode == "exam" and any(
            x is not None
            for x in [
                body.scope,
                body.passage_id,
                body.source_attempt,
                body.retry_filter,
            ]
        ):
            raise HTTPException(422, "考试必须为整套试卷")
        with store.connection() as db:
            throttle(db, "start:" + identity, 10)
            exam = db.execute(
                "SELECT * FROM bank.exams WHERE id=?", (body.exam_id,)
            ).fetchone()
            if not exam:
                raise HTTPException(404, "试卷不存在")
            qs = db.execute(
                "SELECT id FROM bank.questions WHERE exam_id=? AND status='ready' AND (? IS NULL OR part=?) AND (? IS NULL OR passage_id=?) ORDER BY number",
                (
                    body.exam_id,
                    body.scope,
                    body.scope,
                    body.passage_id,
                    body.passage_id,
                ),
            ).fetchall()
            if body.source_attempt or body.retry_filter:
                if not body.source_attempt or not body.retry_filter:
                    raise HTTPException(422, "重练须指定来源记录与筛选方式")
                source = store.owned(db, body.source_attempt, identity)
                if source["status"] != "finished" or source["exam_id"] != body.exam_id:
                    raise HTTPException(422, "请使用当前试卷的已完成记录重练")
                old = store.view(db, source)
                allowed = (
                    {
                        e["id"]
                        for e in old["result"]["entries"]
                        if (e["selection"] and not e["correct"])
                    }
                    if body.retry_filter == "wrong"
                    else {
                        int(qid) for qid, r in old["responses"].items() if r["marked"]
                    }
                )
                qs = [q for q in qs if q["id"] in allowed]
            if not qs:
                raise HTTPException(422, "当前筛选没有可练习题目")
            aid = secrets.token_urlsafe(24)
            now = time.time()
            deadline = (
                now + exam["duration_minutes"] * 60 if body.mode == "exam" else None
            )
            db.execute(
                "INSERT INTO attempts(id,visitor_id,exam_id,mode,scope,created_at,deadline,active_since) VALUES(?,?,?,?,?,?,?,?)",
                (
                    aid,
                    identity,
                    body.exam_id,
                    body.mode,
                    body.scope,
                    now,
                    deadline,
                    now if body.mode == "practice" else None,
                ),
            )
            db.executemany(
                "INSERT INTO attempt_questions VALUES(?,?,?)",
                [(aid, q["id"], i) for i, q in enumerate(qs)],
            )
            return store.view(db, store.owned(db, aid, identity))

    @api.get("/attempts")
    def history(identity=Depends(owner)):
        with store.connection() as db:
            db.execute(
                "UPDATE attempts SET status='finished',finished_at=deadline,revision=revision+1 WHERE visitor_id=? AND status='active' AND deadline<=?",
                (identity, time.time()),
            )
            rows = db.execute(
                "SELECT * FROM attempts WHERE visitor_id=? ORDER BY created_at DESC LIMIT 100",
                (identity,),
            ).fetchall()
            return [store.view(db, row) for row in rows]

    @api.get("/attempts/{aid}")
    def attempt(aid: str, identity=Depends(owner)):
        with store.connection() as db:
            return store.view(db, store.owned(db, aid, identity))

    @api.get("/attempts/{aid}/questions/{qid}")
    def question(aid: str, qid: int, identity=Depends(owner)):
        with store.connection() as db:
            a = store.owned(db, aid, identity)
            q = question_in(db, a, qid)
            payload = {
                k: q[k]
                for k in [
                    "id",
                    "number",
                    "part",
                    "stem",
                    "passage_id",
                    "page_start",
                    "page_end",
                ]
            }
            payload["options"] = [
                dict(r)
                for r in db.execute(
                    "SELECT label,content FROM bank.options WHERE question_id=? ORDER BY label",
                    (qid,),
                )
            ]
            payload["passage"] = None
            if q["passage_id"]:
                p = db.execute(
                    "SELECT * FROM bank.passages WHERE id=?", (q["passage_id"],)
                ).fetchone()
                payload["passage"] = {
                    k: p[k]
                    for k in [
                        "id",
                        "first_number",
                        "last_number",
                        "instruction",
                        "content",
                    ]
                }
                payload["passage"]["assets"] = [
                    dict(
                        id=r["id"],
                        page=r["page_no"],
                        url=f"/api/attempts/{aid}/assets/{r['id']}",
                    )
                    for r in db.execute(
                        "SELECT id,page_no FROM bank.passage_assets WHERE passage_id=? ORDER BY sequence",
                        (p["id"],),
                    )
                ]
            r = db.execute(
                "SELECT * FROM responses WHERE attempt_id=? AND question_id=?",
                (aid, qid),
            ).fetchone()
            if (
                a["status"] == "finished"
                or a["mode"] == "practice"
                and r
                and r["revealed_at"]
            ):
                payload["answer"] = db.execute(
                    "SELECT correct_label FROM bank.answers WHERE question_id=?", (qid,)
                ).fetchone()[0]
                x = db.execute(
                    "SELECT content FROM bank.explanations WHERE question_id=?", (qid,)
                ).fetchone()
                payload["explanation"] = x[0] if x else None
            return payload

    @api.get("/attempts/{aid}/assets/{asset_id}")
    def asset(aid: str, asset_id: int, identity=Depends(owner)):
        with store.connection() as db:
            a = store.owned(db, aid, identity)
            row = db.execute(
                """SELECT x.content,x.mime_type FROM bank.passage_assets x WHERE x.id=? AND EXISTS
                (SELECT 1 FROM attempt_questions aq JOIN bank.questions q ON q.id=aq.question_id WHERE aq.attempt_id=? AND q.passage_id=x.passage_id)""",
                (asset_id, a["id"]),
            ).fetchone()
            if not row:
                raise HTTPException(404, "材料不存在")
            return Response(row["content"], media_type=row["mime_type"])

    @api.put("/attempts/{aid}/questions/{qid}/answer")
    def answer(aid: str, qid: int, body: Answer, identity=Depends(owner)):
        with store.connection() as db:
            a = store.owned(db, aid, identity)
            if a["status"] != "active":
                return JSONResponse(
                    {"detail": "已交卷或已到截止时间，作答不可修改"}, 409
                )
            store.mutable(a)
            question_in(db, a, qid)
            revision(db, a, body.revision)
            db.execute(
                "INSERT OR IGNORE INTO responses(attempt_id,question_id) VALUES(?,?)",
                (aid, qid),
            )
            db.execute(
                """UPDATE responses SET selection=?,first_peeked=CASE WHEN first_selection IS NULL AND ? IS NOT NULL
                THEN revealed_at IS NOT NULL ELSE first_peeked END,first_selection=COALESCE(first_selection,?)
                WHERE attempt_id=? AND question_id=?""",
                (body.selection, body.selection, body.selection, aid, qid),
            )
            return store.view(db, store.owned(db, aid, identity))

    @api.patch("/attempts/{aid}")
    def settings(aid: str, body: Settings, identity=Depends(owner)):
        with store.connection() as db:
            a = store.owned(db, aid, identity)
            store.mutable(a)
            if body.current_index is not None and body.current_index >= len(
                store.questions(db, a)
            ):
                raise HTTPException(422, "题目位置超出范围")
            revision(db, a, body.revision)
            if body.current_index is not None:
                db.execute(
                    "UPDATE attempts SET current_index=? WHERE id=?",
                    (body.current_index, aid),
                )
            if body.auto_next is not None:
                db.execute(
                    "UPDATE attempts SET auto_next=? WHERE id=?", (body.auto_next, aid)
                )
            return store.view(db, store.owned(db, aid, identity))

    @api.post("/attempts/{aid}/questions/{qid}/reveal")
    def reveal(aid: str, qid: int, identity=Depends(owner)):
        with store.connection() as db:
            a = store.owned(db, aid, identity)
            question_in(db, a, qid)
            if a["mode"] == "exam" and a["status"] != "finished":
                raise HTTPException(403, "考试交卷后才可查看答案")
            if a["status"] == "active":
                store.mutable(a)
                db.execute(
                    "INSERT OR IGNORE INTO responses(attempt_id,question_id) VALUES(?,?)",
                    (aid, qid),
                )
                db.execute(
                    "UPDATE responses SET revealed_at=COALESCE(revealed_at,?) WHERE attempt_id=? AND question_id=?",
                    (time.time(), aid, qid),
                )
                db.execute("UPDATE attempts SET revision=revision+1 WHERE id=?", (aid,))
            return store.view(db, store.owned(db, aid, identity))

    @api.put("/attempts/{aid}/questions/{qid}/mark")
    def mark(aid: str, qid: int, body: Mark, identity=Depends(owner)):
        with store.connection() as db:
            a = store.owned(db, aid, identity)
            store.mutable(a)
            question_in(db, a, qid)
            revision(db, a, body.revision)
            db.execute(
                "INSERT OR IGNORE INTO responses(attempt_id,question_id) VALUES(?,?)",
                (aid, qid),
            )
            db.execute(
                "UPDATE responses SET marked=? WHERE attempt_id=? AND question_id=?",
                (body.marked, aid, qid),
            )
            return store.view(db, store.owned(db, aid, identity))

    @api.post("/attempts/{aid}/submit")
    def submit(aid: str, identity=Depends(owner)):
        with store.connection() as db:
            a = store.owned(db, aid, identity)
            if a["status"] == "active":
                store.pause(db, a)
                db.execute(
                    "UPDATE attempts SET status='finished',finished_at=?,revision=revision+1 WHERE id=?",
                    (time.time(), aid),
                )
            return store.view(db, store.owned(db, aid, identity))

    @api.get("/exams/{exam_id}/passages")
    def passages(exam_id: int):
        with store.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,part,first_number,last_number FROM bank.passages WHERE exam_id=? ORDER BY first_number",
                    (exam_id,),
                )
            ]

    @api.post("/attempts/{aid}/pause")
    def pause(aid: str, identity=Depends(owner)):
        with store.connection() as db:
            a = store.owned(db, aid, identity)
            if a["mode"] != "practice":
                raise HTTPException(422, "考试不可暂停")
            if a["status"] != "active":
                raise HTTPException(409, "记录已完成")
            store.pause(db, a)
            return store.view(db, store.owned(db, aid, identity))

    @api.post("/attempts/{aid}/resume")
    def resume(aid: str, identity=Depends(owner)):
        with store.connection() as db:
            a = store.owned(db, aid, identity)
            if (
                a["mode"] == "practice"
                and a["status"] == "active"
                and a["active_since"] is None
            ):
                db.execute(
                    "UPDATE attempts SET active_since=?,revision=revision+1 WHERE id=?",
                    (time.time(), aid),
                )
            return store.view(db, store.owned(db, aid, identity))

    return api
