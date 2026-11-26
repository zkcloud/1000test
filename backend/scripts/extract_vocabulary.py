"""读取 2019 版《托业阅读全真模拟 1000 题》答案册的 Vocabulary Check。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

_TITLE = "▼ Vocabulary Check"
_TEST_TITLE = re.compile(r"Test (\d{2})$")
_QUESTION = re.compile(r'^(1\d{2}|200)(?:[.．]?(?:\s+|$)|(?=[“"‘]))')
_GROUP = re.compile(r"^Questions\s+(\d{3})\s*[-–—~～]\s*\d{3}\b")
_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]|\d")
_HAN = re.compile(r"[\u3400-\u9fff]")
_MEANING_PLACEHOLDER = re.compile(r"[AB]|\d+")
_CLOSE_PARENTHESIS = re.compile(r"[)）]")
_ENGLISH_FONT = "TimesNewRomanPSMT"
_CHINESE_FONT = "SimSun"


@dataclass(frozen=True)
class RawVocabulary:
    term: str
    meaning: str
    test_number: int
    pdf_page: int
    printed_page: int | None
    block_number: int
    block_pdf_page: int
    pdf_page_end: int
    question_first: int
    question_last: int


@dataclass(frozen=True)
class _Line:
    pdf_page: int
    printed_page: int | None
    text: str
    spans: tuple[tuple[str, str], ...]


@dataclass
class _Block:
    pdf_page: int
    question_first: int
    lines: list[_Line]


def _answer_starts(doc: pymupdf.Document) -> list[int]:
    starts = {}
    answer_level = None
    for level, title, page in doc.get_toc():
        if answer_level is not None and level <= answer_level:
            answer_level = None
        if title.strip() == "答案册":
            answer_level = level
        elif answer_level is not None and level == answer_level + 1:
            match = _TEST_TITLE.fullmatch(title.strip())
            if match:
                starts[int(match[1])] = page
    if list(starts) != list(range(1, 11)) or sorted(set(starts.values())) != list(
        starts.values()
    ):
        raise ValueError(f"PDF 答案册 Test 01–10 的起始页异常：{starts}")
    return list(starts.values())


def _page_lines(page: pymupdf.Page) -> list[_Line]:
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    blocks = page.get_text("dict", flags=flags)["blocks"]
    # 保留 PDF 里的文本顺序。按坐标排序会把同一版本的段落拆开。
    lines = [line for block in blocks for line in block.get("lines", [])]
    spans = [
        tuple((span["font"], span["text"]) for span in line["spans"]) for line in lines
    ]
    texts = ["".join(value for _, value in parts).strip() for parts in spans]
    footers = {
        index: int(value)
        for index, (line, value) in enumerate(zip(lines, texts))
        if line["bbox"][1] > page.rect.height * 0.92 and re.fullmatch(r"\d{3,4}", value)
    }
    printed_page = next(iter(footers.values()), None)
    return [
        _Line(page.number + 1, printed_page, value, parts)
        for index, (value, parts) in enumerate(zip(texts, spans))
        if index not in footers and value
    ]


def _vocabulary_blocks(
    doc: pymupdf.Document, start: int, end: int, test_number: int
) -> list[_Block]:
    blocks = []
    active = None
    first_question = None
    related_group = None
    for page_index in range(start - 1, end):
        for line in _page_lines(doc[page_index]):
            if line.text == _TITLE:
                question = (
                    related_group if related_group is not None else first_question
                )
                if question is None:
                    raise ValueError(
                        f"Test {test_number:02d} PDF 第 {line.pdf_page} 页的词汇缺少原题范围"
                    )
                active = _Block(line.pdf_page, question, [])
                blocks.append(active)
                first_question = related_group = None
                continue

            group = _GROUP.match(line.text)
            question = _QUESTION.match(line.text)
            if group:
                related_group = int(group[1])
                active = None
            elif question and "Bold" in line.spans[0][0]:
                if first_question is None:
                    first_question = int(question[1])
                active = None
            elif (
                line.text.startswith("▶")
                or line.text == "Answer Sheet"
                or _TEST_TITLE.fullmatch(line.text)
            ):
                active = None
            elif active is not None:
                if any(
                    font not in {_CHINESE_FONT, _ENGLISH_FONT} for font, _ in line.spans
                ):
                    raise ValueError(
                        f"Test {test_number:02d} PDF 第 {line.pdf_page} 页有未识别的词汇排版"
                    )
                active.lines.append(line)

    starts = [block.question_first for block in blocks]
    if (
        len(blocks) != 27
        or starts != sorted(set(starts))
        or starts[0] != 101
        or starts[-1] > 200
    ):
        raise ValueError(
            f"Test {test_number:02d} 的 Vocabulary Check 分组异常：{starts}"
        )
    return blocks


def _split_after_meaning(value: str, meaning: str) -> tuple[str, str]:
    boundary = _WORD.search(value)
    # 释义有少量 “将 A … B”“30 天”之类的写法。
    if boundary is None or _MEANING_PLACEHOLDER.fullmatch(value.strip()):
        return value, ""
    before_word = meaning + value[: boundary.start()]
    if before_word.count("(") + before_word.count("（") > before_word.count(
        ")"
    ) + before_word.count("）"):
        close = _CLOSE_PARENTHESIS.search(value, boundary.start())
        if close is None:
            return value, ""
        boundary = _WORD.search(value, close.end())
        if boundary is None:
            return value, ""
    return value[: boundary.start()], value[boundary.start() :]


def _parse_block(
    block: _Block, test_number: int, block_number: int, question_last: int
) -> list[RawVocabulary]:
    entries = []
    term = ""
    meaning = ""
    first_line = last_line = None

    def append_entry() -> None:
        if (
            first_line is None
            or last_line is None
            or not _WORD.search(term)
            or not _HAN.search(meaning)
        ):
            raise ValueError(
                f"PDF 第 {block.pdf_page} 页词条缺少英文或释义：{term!r} {meaning!r}"
            )
        entries.append(
            RawVocabulary(
                term=" ".join(term.split()),
                meaning=meaning.strip(),
                test_number=test_number,
                pdf_page=first_line.pdf_page,
                printed_page=first_line.printed_page,
                block_number=block_number,
                block_pdf_page=block.pdf_page,
                pdf_page_end=last_line.pdf_page,
                question_first=block.question_first,
                question_last=question_last,
            )
        )

    for line in block.lines:
        for font, value in line.spans:
            value = value.replace("\u00ad", "")
            if not value.strip():
                continue
            if font == _CHINESE_FONT:
                # 如“driver’s license (驾驶执照)”中的左括号和英文共用一个 span。
                if not meaning and term.rstrip().endswith(("(", "（")):
                    term = term.rstrip()
                    meaning = term[-1]
                    term = term[:-1]
                meaning += value.strip()
            elif meaning:
                suffix, next_term = _split_after_meaning(value, meaning)
                if suffix.strip():
                    meaning += suffix.strip()
                    last_line = line
                if next_term:
                    append_entry()
                    term = next_term
                    meaning = ""
                    first_line = line
            else:
                if first_line is None:
                    first_line = line
                if term and last_line is not line:
                    # 连字符结尾的英文会折行，例如 full-\n time。
                    term = term.rstrip() + (
                        "" if term.rstrip().endswith(("-", "‐", "‑")) else " "
                    )
                    value = value.lstrip()
                term += value
            last_line = line

    append_entry()
    return entries


def extract_vocabulary(pdf: Path) -> list[RawVocabulary]:
    """按书中顺序返回原始词条，每套试卷的词汇块编号为 1–27。"""
    entries = []
    with pymupdf.open(pdf) as doc:
        starts = _answer_starts(doc)
        ends = [start - 1 for start in starts[1:]] + [len(doc)]
        for test_number, (start, end) in enumerate(zip(starts, ends), 1):
            blocks = _vocabulary_blocks(doc, start, end, test_number)
            last_questions = [block.question_first - 1 for block in blocks[1:]] + [200]
            for number, (block, last_question) in enumerate(
                zip(blocks, last_questions), 1
            ):
                entries.extend(_parse_block(block, test_number, number, last_question))
    return entries
