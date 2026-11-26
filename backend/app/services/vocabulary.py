"""Read-only vocabulary lookup and stateless study rounds."""

import base64
import binascii
import hmac
import json
import logging
import re
import secrets
import sqlite3
import time
import unicodedata
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import HTTPException

LOG = logging.getLogger(__name__)
Mode = Literal["choice", "spelling"]
PAGE_SIZE = 20
ROUND_SIZE = 10
QUESTION_LIFETIME = 2 * 60 * 60
RANDOM = secrets.SystemRandom()


def search_key(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


def gloss_keys(text: str) -> set[str]:
    text = re.sub(r"\([^()]*\)", "", search_key(text))
    parts = re.split(r"[,;、/。]", text)
    normalized = {part.strip().removesuffix("的") for part in parts}
    return normalized - {""}


@dataclass(frozen=True)
class Sense:
    id: int
    pos: str
    meaning: str
    usage: str
    example: dict | None
    sources: tuple[dict, ...]
    spelling_prompt: str | None
    variants: tuple[str, ...]
    study_ready: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row, sources: tuple[dict, ...]):
        example = None
        if row["example_kind"] and row["example_text"]:
            example = {
                "kind": row["example_kind"],
                "text": row["example_text"],
                "translation": row["example_translation"],
                "pdf_page": row["example_pdf_page"],
                "printed_page": row["example_printed_page"],
            }
        return cls(
            id=row["id"],
            pos=row["pos"],
            meaning=row["meaning"],
            usage=row["usage"],
            example=example,
            sources=sources,
            spelling_prompt=row["spelling_prompt"],
            variants=tuple(json.loads(row["accepted_variants_json"])),
            study_ready=bool(row["study_ready"]),
        )

    def public(self) -> dict:
        return {
            "id": self.id,
            "pos": self.pos,
            "meaning": self.meaning,
            "usage": self.usage,
            "example": self.example,
            "sources": self.sources,
            "spelling_prompt": self.spelling_prompt,
        }


@dataclass(frozen=True)
class Word:
    id: int
    word: str
    normalized: str
    entry_kind: str
    senses: tuple[Sense, ...]
    tests: tuple[int, ...]
    block_count: int

    @classmethod
    def from_row(cls, row: sqlite3.Row, senses: tuple[Sense, ...]):
        blocks = {
            (source["test_number"], source["block_number"])
            for sense in senses
            for source in sense.sources
        }
        return cls(
            id=row["id"],
            word=row["word"],
            normalized=search_key(row["normalized"]),
            entry_kind=row["entry_kind"],
            senses=senses,
            tests=tuple(sorted({test for test, _ in blocks})),
            block_count=len(blocks),
        )

    def summary(self, senses: tuple[Sense, ...]) -> dict:
        return {
            "id": self.id,
            "word": self.word,
            "meanings": [
                {"pos": sense.pos, "meaning": sense.meaning} for sense in senses
            ],
            "tests": self.tests,
        }


@dataclass(frozen=True)
class QuizSense:
    word: Word
    sense: Sense


class Bank:
    def __init__(self, version: str, words: dict[int, Word], reference):
        self.version = version
        self.words = words
        self.ordered_words = sorted(
            words.values(),
            key=lambda word: (
                -len(word.tests),
                -word.block_count,
                word.normalized,
                word.id,
            ),
        )
        self.glosses: dict[int, set[str]] = {}
        self.spellings: dict[int, set[str]] = {}
        self.words_by_pos: dict[str, dict[int, Word]] = defaultdict(dict)
        self.answer_refs: dict[str, QuizSense] = {}
        self.choice: list[QuizSense] = []
        self.spelling: list[QuizSense] = []
        cue_words: dict[str, set[int]] = defaultdict(set)
        gloss_words: dict[str, set[int]] = defaultdict(set)

        for word in words.values():
            self.glosses[word.id] = set().union(
                *(gloss_keys(s.meaning) for s in word.senses)
            )
            self.spellings[word.id] = {search_key(word.word)} | {
                search_key(variant) for s in word.senses for variant in s.variants
            }
            for gloss in self.glosses[word.id]:
                gloss_words[gloss].add(word.id)
            for sense in word.senses:
                if sense.spelling_prompt:
                    cue_words[search_key(sense.spelling_prompt)].add(word.id)
                if (
                    word.entry_kind == "word"
                    and sense.study_ready
                    and sense.pos
                    and sense.usage
                    and sense.example
                    and sense.example["translation"]
                ):
                    candidate = QuizSense(word, sense)
                    self.choice.append(candidate)
                    self.words_by_pos[sense.pos][word.id] = word
                    self.answer_refs[reference(sense.id)] = candidate

        for candidate in self.choice:
            word, sense = candidate.word, candidate.sense
            if not sense.spelling_prompt:
                continue
            cue = search_key(sense.spelling_prompt)
            if cue_words[cue] != {word.id}:
                continue
            if cue == search_key(sense.meaning) and any(
                gloss_words[gloss] - {word.id} for gloss in gloss_keys(sense.meaning)
            ):
                continue
            self.spelling.append(candidate)


def encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode(payload: str) -> bytes:
    return base64.b64decode(
        payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True
    )


class Vocabulary:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self._lock = Lock()
        self._cached_bank: Bank | None = None
        self._secret = secrets.token_bytes(32)

    def _reference(self, sense_id: int) -> str:
        # Keep the answer's database identifier out of the client-visible token.
        return hmac.digest(self._secret, f"sense:{sense_id}".encode(), "sha256")[
            :16
        ].hex()

    def _option_id(self, nonce: str, word_id: int) -> str:
        return hmac.digest(
            self._secret, f"option:{nonce}:{word_id}".encode(), "sha256"
        )[:12].hex()

    def _read_bank(self, db: sqlite3.Connection, version: str) -> Bank:
        sources: dict[int, list[dict]] = defaultdict(list)
        for row in db.execute(
            "SELECT * FROM sense_sources ORDER BY test_number, block_number, pdf_page, sense_id"
        ):
            source = dict(row)
            sources[source.pop("sense_id")].append(source)
        senses: dict[int, list[Sense]] = defaultdict(list)
        for row in db.execute("SELECT * FROM senses ORDER BY id"):
            senses[row["word_id"]].append(
                Sense.from_row(row, tuple(sources[row["id"]]))
            )
        words = {
            row["id"]: Word.from_row(row, tuple(senses[row["id"]]))
            for row in db.execute("SELECT * FROM words ORDER BY id")
        }
        return Bank(version, words, self._reference)

    def _bank(self) -> Bank:
        try:
            with closing(
                sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            ) as db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN")
                version_row = db.execute(
                    "SELECT value FROM meta WHERE key='version'"
                ).fetchone()
                if version_row is None:
                    raise ValueError("missing vocabulary version")
                version = version_row["value"]
                with self._lock:
                    if (
                        self._cached_bank is None
                        or self._cached_bank.version != version
                    ):
                        self._cached_bank = self._read_bank(db, version)
                    return self._cached_bank
        except (sqlite3.Error, ValueError) as error:
            LOG.warning("Vocabulary bank unavailable: %s", error)
            raise HTTPException(503, "词库暂不可用，请稍后重试。") from error

    def lookup(self, q: str, test: int | None, page: int) -> dict:
        exact = []
        partial = []
        query = search_key(q)
        for word in self._bank().ordered_words:
            if test is not None and test not in word.tests:
                continue
            senses = (
                word.senses
                if test is None
                else tuple(
                    sense
                    for sense in word.senses
                    if any(source["test_number"] == test for source in sense.sources)
                )
            )
            if not query:
                partial.append((word, senses))
                continue
            keys = {word.normalized, search_key(word.word)}
            keys.update(search_key(sense.meaning) for sense in senses)
            keys.update(
                search_key(variant) for sense in senses for variant in sense.variants
            )
            exact_cue = any(
                sense.spelling_prompt and search_key(sense.spelling_prompt) == query
                for sense in senses
            )
            if query in keys or exact_cue:
                exact.append((word, senses))
            elif any(query in key for key in keys):
                partial.append((word, senses))

        matches = exact + partial
        total = len(matches)
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, pages)
        start = (page - 1) * PAGE_SIZE
        return {
            "items": [
                word.summary(senses)
                for word, senses in matches[start : start + PAGE_SIZE]
            ],
            "page": page,
            "pages": pages,
            "total": total,
        }

    def detail(self, word_id: int) -> dict:
        word = self._bank().words.get(word_id)
        if word is None:
            raise HTTPException(404, "词条不存在。")
        return {
            **word.summary(word.senses),
            "senses": [sense.public() for sense in word.senses],
        }

    def _distractors(self, bank: Bank, candidate: QuizSense) -> list[Word]:
        word, sense = candidate.word, candidate.sense
        glosses = gloss_keys(sense.meaning)
        peers = list(bank.words_by_pos[sense.pos].values())
        RANDOM.shuffle(peers)
        choices = []
        used_spellings = bank.spellings[word.id].copy()
        for peer in peers:
            peer_glosses = bank.glosses[peer.id]
            if peer.id == word.id or used_spellings & bank.spellings[peer.id]:
                continue
            if any(a in b or b in a for a in glosses for b in peer_glosses):
                continue
            choices.append(peer)
            used_spellings.update(bank.spellings[peer.id])
            if len(choices) == 3:
                break
        return choices

    def _seal(self, payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.digest(self._secret, raw, "sha256")
        return f"{encode(raw)}.{encode(signature)}"

    def start_round(self, mode: Mode) -> dict:
        bank = self._bank()
        candidates = list(bank.choice if mode == "choice" else bank.spelling)
        RANDOM.shuffle(candidates)
        questions = []
        used_words = set()
        expiry = int(time.time()) + QUESTION_LIFETIME
        for candidate in candidates:
            word, sense = candidate.word, candidate.sense
            if word.id in used_words:
                continue
            options = []
            if mode == "choice":
                distractors = self._distractors(bank, candidate)
                if len(distractors) < 3:
                    continue
                options = [word, *distractors]
                RANDOM.shuffle(options)
            nonce = secrets.token_urlsafe(12)
            question = self._seal(
                {
                    "v": bank.version,
                    "exp": expiry,
                    "mode": mode,
                    "ref": self._reference(sense.id),
                    "options": [option.id for option in options],
                    "nonce": nonce,
                }
            )
            questions.append(
                {
                    "token": question,
                    "prompt": sense.meaning
                    if mode == "choice"
                    else sense.spelling_prompt,
                    "pos": sense.pos if mode == "choice" else None,
                    "options": [
                        {"id": self._option_id(nonce, option.id), "label": option.word}
                        for option in options
                    ],
                }
            )
            used_words.add(word.id)
            if len(questions) == ROUND_SIZE:
                break
        return {"mode": mode, "questions": questions}

    def _open(self, token: str) -> dict:
        try:
            raw, signature = (decode(part) for part in token.split("."))
        except (ValueError, binascii.Error) as error:
            raise HTTPException(400, "题目无效，请重新开始练习。") from error
        if not hmac.compare_digest(hmac.digest(self._secret, raw, "sha256"), signature):
            raise HTTPException(410, "本轮练习已失效，请重新开始。")
        payload = json.loads(raw)
        if time.time() >= payload["exp"]:
            raise HTTPException(410, "本轮练习已失效，请重新开始。")
        return payload

    def grade(self, token: str, answer: str) -> dict:
        entered = answer.strip()
        if not entered:
            raise HTTPException(422, "请先作答。")
        payload = self._open(token)
        bank = self._bank()
        candidate = bank.answer_refs.get(payload["ref"])
        if candidate is None or payload["v"] != bank.version:
            raise HTTPException(410, "词库已更新，请重新开始练习。")
        word, sense = candidate.word, candidate.sense
        if payload["mode"] == "choice":
            option_id = next(
                (
                    option
                    for option in payload["options"]
                    if self._option_id(payload["nonce"], option) == entered
                ),
                None,
            )
            if option_id is None:
                raise HTTPException(422, "请选择本题的一个选项。")
            given = bank.words[option_id].word
            correct = option_id == word.id
        else:
            given = entered
            correct = entered.casefold() in {
                word.word.casefold(),
                *(variant.casefold() for variant in sense.variants),
            }
        return {
            "correct": correct,
            "given_answer": given,
            "correct_answer": word.word,
            "word_id": word.id,
            "sense": sense.public(),
        }
