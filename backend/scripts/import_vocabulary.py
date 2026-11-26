"""从指定原书离线生成用于查词和练习的只读 SQLite 词库。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from backend.scripts.enrich_vocabulary import EnrichedVocabulary, enrich_vocabulary
from backend.scripts.extract_vocabulary import RawVocabulary, extract_vocabulary

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PDF = ROOT / "【2019版新东方】阅读全真模拟1000题.pdf"
DEFAULT_DATABASE = ROOT / "data/vocabulary.sqlite3"
DEFAULT_QUESTIONS = ROOT / "data/questions.sqlite3"
SCHEMA = ROOT / "backend/app/db/vocabulary.sql"
WORD = re.compile(r"[a-z]+(?:[-'][a-z]+)*")
MEANING_SEPARATORS = re.compile(r"[，,；;、]+")

# 提示用中文限定书中的义项。带有符号的登记拼写可保留明确的等价变体。
SPELLING_CLUES = {
    "anniversary": ("周年", "周年纪念日，指某件事发生后每年在同一日期纪念的日子"),
    "applicant": ("申请", "申请者，指已经递交申请以获得职位或资格的人"),
    "attachment": ("附件", "附件，指随电子邮件一同发送的独立文件"),
    "brochure": ("册", "小册子，印有图片和产品、服务或旅游介绍的宣传读物"),
    "cashier": ("收银", "收银员，负责在商店柜台收取货款的人"),
    "commuter": ("通勤", "通勤者，指经常往返住所和工作地点的人"),
    "concierge": ("礼宾", "酒店礼宾人员，帮助住客预订服务和查询当地信息"),
    "construction": ("建设", "建设或施工，指盖楼、修路等建造活动"),
    "contractor": ("承包", "承包商，按合同负责完成一项工程或服务的个人或公司"),
    "distributor": ("经销", "经销商，负责把生产商的产品分销到零售网点的企业"),
    "donation": ("捐", "捐赠，指无偿提供给慈善组织的款项或物品"),
    "endorsement": ("认可", "认可或背书，指公开表示支持某人、某产品或某项主张"),
    "extension": ("分机", "电话分机号码，指同一总机下某个内部电话的号码"),
    "fundraiser": ("募集", "募捐活动，指为某个组织或目标筹集款项的活动"),
    "handpick": ("选", "精选，指亲自从候选者中仔细挑选合适的人"),
    "hospitality": ("款待", "款待，指主人对客人的友好接待和照顾"),
    "inconvenience": ("不便", "不便，指某件事给安排或日常活动带来的麻烦"),
    "interviewer": ("面试", "面试官，指在面试中提出问题、评估应聘者的人"),
    "inventory": ("库存", "库存，指企业目前持有、可用于销售或生产的货物"),
    "invoice": ("发票", "发票，列出所供商品或服务及其应付金额的单据"),
    "lasagna": ("面", "千层面，用多层宽面片夹肉酱或奶酪烤制的意大利菜"),
    "luggage": ("行李", "行李，指旅行时随身携带的箱包和物品总称"),
    "memorandum": ("备忘", "备忘录，指单位内部传达信息或事项的简短书面文件"),
    "morale": ("士气", "士气，指一个团队共同工作时的信心和斗志"),
    "mortgage": ("按揭", "按揭贷款，以房产作担保、通常分期偿还的贷款"),
    "negotiation": ("谈判", "谈判，为了达成协议而进行的协商过程"),
    "nonrefundable": ("退款", "不能退款的，形容支付后的订金或票款无法退回"),
    "payroll": ("工资", "工资发放名册，企业记录雇员和应发工资金额的清单"),
    "ragweed": ("豚草", "豚草，一种花粉容易引起过敏的菊科植物"),
    "refund": ("退", "退款，商家退回给消费者的款项"),
    "reservation": ("预订", "预订，指提前为自己保留的客房、座位或餐位"),
    "retirement": ("退休", "退休，即结束职业生涯、离开工作岗位"),
    "reimbursement": ("报销", "报销款，单位退还给个人事先垫付的公务费用"),
    "subscription": ("订阅", "订阅，指付费定期收到刊物或持续使用某项服务的安排"),
    "treadmill": ("跑步机", "跑步机，可以在室内原地走路或跑步的健身设备"),
    "warranty": ("保", "保修，指厂家承诺在约定期限内免费修理或更换有缺陷的产品"),
}


def normalize_term(term: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", term).casefold().split())


def meaning_key(meaning: str) -> tuple[str, ...]:
    parts = MEANING_SEPARATORS.split(unicodedata.normalize("NFKC", meaning))
    return tuple(sorted({"".join(part.split()) for part in parts if part.strip()}))


def merge_overlapping_glosses(senses):
    # A shared, verified usage confirms that a shorter gloss belongs to the
    # same sense. Keep the most complete wording and all source occurrences.
    merged = {}
    for key in sorted(senses, key=lambda key: (-len(key[1]), key)):
        pos, gloss = key
        candidates = senses[key]
        usage = {entry.usage for entry in candidates if entry.study_ready}
        for existing, existing_candidates in merged.items():
            existing_pos, existing_gloss = existing
            if (
                pos
                and pos == existing_pos
                and set(gloss) < set(existing_gloss)
                and any(
                    entry.study_ready and entry.usage in usage
                    for entry in existing_candidates
                )
            ):
                existing_candidates.extend(candidates)
                break
        else:
            merged[key] = candidates
    return merged


def group_senses(
    entries: list[EnrichedVocabulary],
) -> dict[str, dict[tuple[str, tuple[str, ...]], list[EnrichedVocabulary]]]:
    grouped = defaultdict(lambda: defaultdict(list))
    for entry in entries:
        word = normalize_term(entry.source.term)
        gloss = meaning_key(entry.source.meaning)
        if not word or not gloss:
            raise ValueError(f"词条缺少单词或释义：{entry.source}")
        grouped[word][(entry.pos or "", gloss)].append(entry)
    for word, senses in grouped.items():
        positions = defaultdict(list)
        for pos, gloss in senses:
            if pos:
                positions[gloss].append(pos)
        for key in list(senses):
            pos, gloss = key
            if pos or len(positions[gloss]) != 1:
                continue
            senses[(positions[gloss][0], gloss)].extend(senses.pop(key))
        grouped[word] = merge_overlapping_glosses(senses)
    return grouped


def quality(entry: EnrichedVocabulary) -> tuple[bool, bool, bool, bool]:
    return (
        entry.study_ready,
        entry.example_kind == "book",
        bool(entry.example_translation),
        bool(entry.pos),
    )


def spelling_clue(word: str, entry: EnrichedVocabulary) -> str | None:
    if not entry.study_ready or not WORD.fullmatch(word):
        return None
    reviewed = SPELLING_CLUES.get(word)
    if reviewed and reviewed[0] in entry.source.meaning:
        return reviewed[1]
    return entry.spelling_prompt


def source_location(source: RawVocabulary) -> tuple:
    return (
        source.test_number,
        source.pdf_page,
        source.printed_page,
        source.block_number,
        source.pdf_page_end or source.pdf_page,
        source.question_first,
        source.question_last,
    )


def write_word_bank(
    conn: sqlite3.Connection,
    source: Path,
    source_sha: str,
    raw: list[RawVocabulary],
    entries: list[EnrichedVocabulary],
    printed_pages: dict[int, str],
) -> dict:
    if [entry.source for entry in entries] != raw:
        raise ValueError("词条补全结果与 PDF 提取条目不一致")
    grouped = group_senses(entries)
    version = hashlib.sha256(source_sha.encode())
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    with conn:
        conn.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            (("source_filename", source.name), ("source_sha256", source_sha)),
        )
        for word, senses in sorted(grouped.items()):
            display = next(iter(senses.values()))[0].source.term.strip()
            kind = "word" if WORD.fullmatch(word) else "phrase"
            word_id = conn.execute(
                "INSERT INTO words (word, normalized, entry_kind) VALUES (?,?,?)",
                (display, word, kind),
            ).lastrowid
            version.update(
                json.dumps((display, word, kind), ensure_ascii=False).encode()
            )
            for (pos, gloss), candidates in sorted(senses.items()):
                entry = max(candidates, key=quality)
                meaning = next(
                    candidate.source.meaning.strip()
                    for candidate in candidates
                    if meaning_key(candidate.source.meaning) == gloss
                )
                variants = sorted(
                    {
                        variant
                        for candidate in candidates
                        for input_value in candidate.spell_variants
                        if (variant := normalize_term(input_value)) != word
                        and WORD.fullmatch(variant)
                    }
                )
                example_kind = {"book": "original", "supplemental": "supplemental"}.get(
                    entry.example_kind
                )
                example_printed = printed_pages.get(entry.example_pdf_page)
                fields = (
                    word_id,
                    pos,
                    meaning,
                    entry.usage or "",
                    entry.example,
                    entry.example_translation,
                    example_kind,
                    entry.example_pdf_page,
                    example_printed,
                    int(entry.study_ready),
                    spelling_clue(word, entry),
                    json.dumps(variants, ensure_ascii=False),
                )
                sense_id = conn.execute(
                    """INSERT INTO senses (
                        word_id, pos, meaning, usage, example_text, example_translation,
                        example_kind, example_pdf_page, example_printed_page, study_ready,
                        spelling_prompt, accepted_variants_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    fields,
                ).lastrowid
                locations = {}
                for candidate in candidates:
                    location = source_location(candidate.source)
                    key = (location[0], location[3], location[1])
                    previous = locations.get(key)
                    if not previous or location[4] > previous[4]:
                        locations[key] = location
                locations = list(locations.values())
                conn.executemany(
                    "INSERT INTO sense_sources VALUES (?,?,?,?,?,?,?,?)",
                    [(sense_id, *location) for location in locations],
                )
                version.update(
                    json.dumps((fields, locations), ensure_ascii=False).encode()
                )
        conn.execute("INSERT INTO meta VALUES ('version', ?)", (version.hexdigest(),))
    blocks = dict(
        conn.execute(
            "SELECT test_number, count(DISTINCT block_number) FROM sense_sources GROUP BY test_number"
        )
    )
    if blocks != {test: 27 for test in range(1, 11)}:
        raise ValueError(f"词汇板块数量不完整：{blocks}")
    if (
        conn.execute("PRAGMA integrity_check").fetchone() != ("ok",)
        or conn.execute("PRAGMA foreign_key_check").fetchone()
    ):
        raise ValueError("词库 SQLite 完整性检查失败")
    return {
        "source": source.name,
        "source_sha256": source_sha,
        "blocks_per_test": blocks,
        "extracted_entries": len(raw),
        "words": conn.execute("SELECT count(*) FROM words").fetchone()[0],
        "single_words": conn.execute(
            "SELECT count(*) FROM words WHERE entry_kind='word'"
        ).fetchone()[0],
        "senses": conn.execute("SELECT count(*) FROM senses").fetchone()[0],
        "study_ready": conn.execute(
            "SELECT count(*) FROM senses WHERE study_ready=1"
        ).fetchone()[0],
        "original_examples": conn.execute(
            "SELECT count(*) FROM senses WHERE example_kind='original'"
        ).fetchone()[0],
        "supplemental_examples": conn.execute(
            "SELECT count(*) FROM senses WHERE example_kind='supplemental'"
        ).fetchone()[0],
        "spelling_words": conn.execute(
            "SELECT count(DISTINCT word_id) FROM senses WHERE spelling_prompt IS NOT NULL"
        ).fetchone()[0],
    }


def import_vocabulary(source: Path, destination: Path, question_bank: Path) -> dict:
    if destination.resolve() in (source.resolve(), question_bank.resolve()):
        raise ValueError("词库输出路径必须有别于原书 PDF 和试卷题库")
    with source.open("rb") as pdf_file:
        source_sha = hashlib.file_digest(pdf_file, "sha256").hexdigest()
    raw = extract_vocabulary(source)
    with closing(
        sqlite3.connect(question_bank.resolve().as_uri() + "?mode=ro", uri=True)
    ) as conn:
        if not conn.execute(
            "SELECT 1 FROM sources WHERE sha256=?", (source_sha,)
        ).fetchone():
            raise ValueError("试卷题库对应的 PDF 与词汇来源不一致")
        printed_pages = dict(
            conn.execute(
                "SELECT page_no, printed_page FROM source_pages JOIN sources ON sources.id=source_pages.source_id "
                "WHERE sources.sha256=? AND printed_page IS NOT NULL",
                (source_sha,),
            )
        )
    entries = enrich_vocabulary(source, raw, question_bank=question_bank)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    os.close(descriptor)
    temp = Path(temp_name)
    try:
        conn = sqlite3.connect(temp)
        try:
            report = write_word_bank(
                conn, source, source_sha, raw, entries, printed_pages
            )
        finally:
            conn.close()
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--question-bank", type=Path, default=DEFAULT_QUESTIONS)
    args = parser.parse_args()
    report = import_vocabulary(args.pdf, args.database, args.question_bank)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
