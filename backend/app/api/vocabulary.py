"""词条、出题和逐题判分接口。"""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.app.services.vocabulary import Mode, Vocabulary


class RoundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Mode


class GradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_token: str = Field(min_length=1, max_length=768)
    answer: str = Field(min_length=1, max_length=160)


def router(bank: Vocabulary) -> APIRouter:
    api = APIRouter(prefix="/api/vocabulary", tags=["vocabulary"])

    @api.get("/words")
    def words(
        q: Annotated[str, Query(max_length=160)] = "",
        test: Annotated[int | None, Query(ge=1, le=10)] = None,
        page: Annotated[int, Query(ge=1)] = 1,
    ):
        return bank.lookup(q, test, page)

    @api.get("/words/{word_id}")
    def word(word_id: int):
        return bank.detail(word_id)

    @api.post("/rounds")
    def start_round(body: RoundRequest):
        return bank.start_round(body.mode)

    @api.post("/answers")
    def grade(body: GradeRequest):
        return bank.grade(body.question_token, body.answer)

    return api
