"""Combine verified book contexts and authored supplementary study notes.

The normal PDF import does not load NLP models or call an external service.
The optional language-index command stages contextual POS and translations
with local spaCy and Argos models for the edition used by the audited bank.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path

from backend.app.db.database import DEFAULT_DATABASE
from backend.scripts.extract_vocabulary import RawVocabulary

DATA = DEFAULT_DATABASE.parent
SUPPLEMENTS = DATA / "vocabulary-supplements.json"
LANGUAGE_INDEX = DATA / "vocabulary-language.json"

POS = {
    "NOUN": "n.",
    "VERB": "v.",
    "AUX": "v.",
    "ADJ": "adj.",
    "ADV": "adv.",
    "ADP": "prep.",
    "PRON": "pron.",
    "DET": "det.",
    "CCONJ": "conj.",
    "SCONJ": "conj.",
    "NUM": "num.",
    "INTJ": "int.",
}
POS_NAMES = {
    "n.": "名词",
    "v.": "动词",
    "adj.": "形容词",
    "adv.": "副词",
    "prep.": "介词",
    "pron.": "代词",
    "det.": "限定词",
    "conj.": "连词",
    "num.": "数词",
    "int.": "感叹词",
    "phr.": "固定搭配",
}
WORD = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
BLANK = re.compile(r"[-−_–—]{2,}(?:\s*[-−_–—]+)*")
CJK = re.compile(r"[\u3400-\u9fff]")
MEANING_EQUIVALENTS = {
    "关于": ("有关",),
    "另外的": ("额外", "补充", "更多"),
    "精选": ("特意选", "亲自挑选", "精心挑选"),
    "申请者": ("申请人",),
    "批准": ("核准",),
    "预定": ("预订",),
    "预订": ("预定",),
    "雇员": ("员工",),
    "员工": ("雇员",),
    "志愿者": ("义工",),
    "严格的": ("严格",),
    "严厉的": ("严厉",),
}
TIME_PREFIX = re.compile(r"^\[\d{1,2}:\d{2}\s*(?:[AP]\s*\.\s*M\s*\.)?\]\s*")
SPEAKER_LINE = re.compile(
    r"^(?:[A-Za-z][A-Za-z.'’ -]*\s+)?\[\d{1,2}:\d{2}\s*(?:[AP]\s*\.\s*M\s*\.)?\]\s*$"
)


@dataclass(frozen=True)
class EnrichedVocabulary:
    source: RawVocabulary
    pos: str | None = None
    usage: str = ""
    example: str | None = None
    example_translation: str | None = None
    example_pdf_page: int | None = None
    example_kind: str | None = None
    spell_variants: tuple[str, ...] = ()
    study_ready: bool = False
    spelling_prompt: str | None = None


def _digest(pdf: Path) -> str:
    with pdf.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _sense_key(entry: RawVocabulary) -> str:
    return f"{_normalized(entry.term)}｜{_normalized(entry.meaning)}"


def _supplements() -> dict:
    return json.loads(SUPPLEMENTS.read_text(encoding="utf-8"))


def _curated(supplements: dict, entry: RawVocabulary) -> dict:
    return next(
        (
            note
            for note in supplements.get(_normalized(entry.term), ())
            if _normalized(note["meaning"]) in _normalized(entry.meaning)
        ),
        {},
    )


def enrich_vocabulary(
    pdf: Path, entries: list[RawVocabulary], *, question_bank: Path | None = None
) -> list[EnrichedVocabulary]:
    """Attach contextual notes, keeping unmatched senses browsable."""
    supplements = _supplements()
    source_digest = _digest(pdf)
    index = {}
    if LANGUAGE_INDEX.is_file():
        artifact = json.loads(LANGUAGE_INDEX.read_text(encoding="utf-8"))
        if artifact["source_sha256"] == source_digest:
            index = artifact["senses"]
    if question_bank is not None:
        with closing(_connect_bank(question_bank)) as db:
            _validate_book(db, source_digest)

    results = []
    for entry in entries:
        curated = _curated(supplements, entry)
        context = index.get(_sense_key(entry), {})
        if curated.get("pos") and context.get("pos") != curated["pos"]:
            context = {}
        fields = context if context.get("example") else curated
        result = EnrichedVocabulary(
            source=entry,
            pos=fields.get("pos") or context.get("pos"),
            usage=curated.get("usage") or fields.get("usage", ""),
            example=fields.get("example"),
            example_translation=fields.get("example_translation"),
            example_pdf_page=fields.get("example_pdf_page"),
            example_kind=fields.get("example_kind", "supplemental")
            if fields.get("example")
            else None,
            spell_variants=tuple(curated.get("spell_variants", ())),
            spelling_prompt=curated.get("spelling_prompt"),
        )
        results.append(
            replace(
                result,
                study_ready=bool(
                    result.pos
                    and result.usage
                    and result.example
                    and result.example_translation
                ),
            )
        )
    return results


def _connect_bank(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _validate_book(db: sqlite3.Connection, source_digest: str) -> None:
    if (
        db.execute(
            "SELECT 1 FROM sources WHERE sha256 = ?", (source_digest,)
        ).fetchone()
        is None
    ):
        raise ValueError("题库和词汇 PDF 不是同一原书版本")


@dataclass(frozen=True)
class _BookText:
    test: int
    first_question: int
    last_question: int
    first_page: int
    last_page: int
    text: str
    translation: str = ""


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    return " ".join(text.replace("’", "'").split())


def _clean_translation(text: str) -> str:
    text = text.replace("▁", " ")
    text = re.sub(r"\s+1[2-9]\d{2}\s*$", "", text)
    text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)
    text = re.sub(r"(?<=[\u3400-\u9fff]),\s*(?=[\u3400-\u9fff])", "，", text)
    return " ".join(text.split())


def _part_five_translations(pages: dict[int, str]) -> dict[tuple[int, int], str]:
    starts = [
        page
        for page, text in pages.items()
        if len(re.findall(r"1\d\d\.\s*\([ABCD]\)", text)) > 70
    ]
    translations = {}
    for test, start in enumerate(starts, 1):
        text = "\n".join(pages[page] for page in range(start, start + 20))
        for item in re.finditer(
            r"(?ms)^(1[012]\d|130)[. ]+[^\n]*.*?▶(?!\s*解析)(.*?)▶\s*解析", text
        ):
            translation = _clean_translation(_clean(item[2]))
            if (
                CJK.search(translation)
                and len(translation) < 230
                and "Vocabulary Check" not in translation
            ):
                translations[(test, int(item[1]))] = translation
    return translations


def _passage_text(raw: str, answers: dict[int, str]) -> str:
    def fill(match: re.Match) -> str:
        return answers.get(int(match[1]), match[0]) + " "

    text = re.sub(r"\(\s*(1\d{2})\s*\)\s*[-−_–—]{2,}(?:\s*[-−_–—]+)*", fill, raw)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if SPEAKER_LINE.fullmatch(line):
            continue
        line = TIME_PREFIX.sub("", line)
        if re.match(r"(?i)^(?:to|from|subject|date|sent|attachment|cc)\s*:", line):
            continue
        if line.startswith(("Dear ", "Sincerely", "Regards", "Best regards")):
            continue
        # The original material may begin with a title or an address.
        title_words = [
            word
            for word in line.split()
            if word[:1].isalpha()
            and word.lower()
            not in {
                "a",
                "an",
                "at",
                "for",
                "in",
                "of",
                "on",
                "the",
                "to",
                "with",
                "and",
            }
        ]
        if (
            re.fullmatch(r"[\w .&,'’()\-/]+", line)
            and not line.endswith(".")
            and (
                line.isupper()
                or re.match(r"^(?:Mr|Mrs|Ms|Dr)\. ", line)
                or (
                    1 < len(title_words) <= 6
                    and all(word[:1].isupper() for word in title_words)
                )
            )
        ):
            continue
        lines.append(line)
    return _clean(" ".join(lines))


def _book_texts(db: sqlite3.Connection) -> tuple[list[_BookText], dict[int, str]]:
    pages = {
        row["page_no"]: row["raw_text"]
        for row in db.execute(
            "SELECT page_no, raw_text FROM source_pages ORDER BY page_no"
        )
    }
    translations = _part_five_translations(pages)
    rows = db.execute(
        """SELECT e.number AS test, q.number, q.stem, q.part, q.page_start,
                  q.page_end, q.passage_id, o.content AS answer
           FROM questions AS q JOIN exams AS e ON q.exam_id=e.id
           JOIN answers AS a ON a.question_id=q.id
           JOIN options AS o ON o.question_id=q.id AND o.label=a.correct_label
           ORDER BY e.number, q.number"""
    )
    texts = []
    passage_answers = defaultdict(dict)
    for row in rows:
        answer = row["answer"]
        if row["passage_id"] is not None:
            passage_answers[row["passage_id"]][row["number"]] = answer
        if row["part"] == 5:
            stem = BLANK.sub(lambda _, value=answer: value, row["stem"], count=1)
            examples = [(stem, translations.get((row["test"], row["number"]), ""))]
        else:
            examples = [(row["stem"], ""), (answer, "")]
        for raw, translation in examples:
            if raw and len(raw.split()) >= 4:
                texts.append(
                    _BookText(
                        row["test"],
                        row["number"],
                        row["number"],
                        row["page_start"],
                        row["page_end"],
                        _clean(raw),
                        translation,
                    )
                )
    for row in db.execute(
        """SELECT p.*, e.number AS test FROM passages AS p JOIN exams AS e ON p.exam_id=e.id
           WHERE length(trim(p.content)) > 0 ORDER BY e.number, p.first_number"""
    ):
        value = _passage_text(row["content"], passage_answers[row["id"]])
        if value:
            texts.append(
                _BookText(
                    row["test"],
                    row["first_number"],
                    row["last_number"],
                    row["page_start"],
                    row["page_end"],
                    value,
                )
            )
    return texts, pages


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        match.group(0).lower() for match in WORD.finditer(value.replace("’", "'"))
    )


def _term_tokens(value: str) -> tuple[str, ...]:
    value = re.sub(r"\([^()]*(?:=|also)[^()]*\)", "", _normalized(value))
    value = re.sub(r"^cf\.\s*", "", value)
    return _tokens(value)


def _locate_page(
    example: str, source: _BookText, page_words: dict[int, str]
) -> int | None:
    words = _tokens(example)
    # Corrected blanks and sentences across a page boundary need shorter
    # anchors. Quoted text still has to match an audited page.
    for width in (7, 5, 4):
        for start in range(min(len(words) - width + 1, 8)):
            anchor = " ".join(words[start : start + width])
            for page in range(source.first_page, source.last_page + 1):
                if f" {anchor} " in page_words[page]:
                    return page
    return None


def _meaning_anchors(meaning: str) -> tuple[str, ...]:
    text = re.sub(r"[（(][^()（）]*[）)]", "", meaning)
    return tuple(
        "".join(CJK.findall(chunk))
        for chunk in re.split(r"[，、；。;,/…~]", text)
        if CJK.search(chunk)
    )


def _translation_strength(meaning: str, translation: str) -> int:
    chinese = "".join(CJK.findall(translation))
    anchors = _meaning_anchors(meaning)
    equivalents = (
        candidate
        for anchor in anchors
        for candidate in MEANING_EQUIVALENTS.get(anchor, ())
    )
    return max(
        (len(anchor) for anchor in (*anchors, *equivalents) if anchor in chinese),
        default=0,
    )


def _sentence_is_valid(span) -> bool:
    text = span.text.strip()
    return (
        4 <= len(_tokens(text)) <= 38
        and text[-1:] in ".?!"
        and not BLANK.search(text)
        and not re.search(r"\d{3}\s*[:).]|@|https?://|\[\d]|\([ABCD]\)", text)
        and " - " not in text
        and "\ufffd" not in text
        and span.root.pos_ in {"AUX", "VERB"}
        and not CJK.search(text)
    )


def _collocation(word_tokens, pos: str) -> str:
    token = next(
        (word for word in word_tokens if word.head not in word_tokens), word_tokens[0]
    )
    reference = token.head
    tokens = list(word_tokens)
    if len(tokens) == 1 and token.i >= 2:
        prefix, hyphen = token.doc[token.i - 2 : token.i]
        if hyphen.text == "-" and not hyphen.whitespace_ and not prefix.whitespace_:
            compound = token.doc[prefix.i : token.i + 1].text
            return f"{POS_NAMES[pos]}。例句中用在复合词 {compound} 中。"
    if len(tokens) == 1:
        if token.dep_ in {"amod", "advmod", "compound", "poss", "pobj", "dobj"}:
            tokens.append(reference)
        elif token.pos_ in {"VERB", "ADJ"}:
            child = next(
                (
                    node
                    for node in token.children
                    if node.dep_ in {"prt", "dobj", "xcomp", "prep"}
                    and node.pos_ not in {"DET", "PRON"}
                ),
                None,
            )
            if child is not None:
                tokens.append(child)
        elif token.pos_ == "NOUN":
            modifier = next(
                (node for node in token.children if node.dep_ in {"amod", "compound"}),
                None,
            )
            if modifier is not None:
                tokens.append(modifier)
    start = min(node.i for node in tokens)
    end = max(node.i for node in tokens) + 1
    collocation = token.doc[start:end].text
    original = token.doc[word_tokens[0].i : word_tokens[-1].i + 1].text
    if end - start > 6 or re.search(r"\([^)]*\)|[,;:]", collocation):
        collocation = original
    if collocation != original:
        return f"{POS_NAMES[pos]}。例句搭配：{collocation}。"
    behavior = {
        "nsubj": "在句中作主语",
        "dobj": "在句中作宾语",
        "pobj": "在句中作介词宾语",
        "ROOT": "在句中作谓语",
        "acomp": "在句中作表语",
        "conj": "与并列项搭配使用",
        "amod": "用来修饰名词",
        "advmod": "用于修饰动作或程度",
    }.get(token.dep_)
    return (
        f"{POS_NAMES[pos]}，{behavior}：{original}。"
        if behavior
        else f"{POS_NAMES[pos]}。例句中的用法：{original}。"
    )


@dataclass(frozen=True)
class _Candidate:
    source: _BookText
    page: int
    pos: str
    usage: str
    example: str
    translation: str
    exact: bool
    attributive: bool


def _possible_pos(directory: Path) -> dict[str, set[str]]:
    positions = defaultdict(set)
    for suffix, position in (
        ("noun", "n."),
        ("verb", "v."),
        ("adj", "adj."),
        ("adv", "adv."),
    ):
        with (directory / f"index.{suffix}").open(encoding="utf-8") as index:
            for line in index:
                if line[:1].isspace():
                    continue
                term = line.split(" ", maxsplit=1)[0].replace("_", " ")
                positions[term].add(position)
    return positions


def _word_forms(token) -> set[str]:
    forms = set(_tokens(token.text) + _tokens(token.lemma_))
    if token.pos_ == "VERB" and token.text.lower().endswith("ed"):
        forms.add(token.text.lower()[:-2])
    return forms


def _examples(nlp, texts, pages, aliases, positions):
    tokens_by_start = defaultdict(list)
    for term, words in aliases.items():
        if words:
            tokens_by_start[words[0]].append((term, words))
    page_words = {
        page: " " + " ".join(_tokens(text)) + " " for page, text in pages.items()
    }
    by_term = defaultdict(list)
    for source, doc in zip(
        texts, nlp.pipe((item.text for item in texts), batch_size=64), strict=True
    ):
        for sentence in doc.sents:
            if not _sentence_is_valid(sentence):
                continue
            example = TIME_PREFIX.sub("", sentence.text.strip())
            page = _locate_page(example, source, page_words)
            if page is None:
                continue
            words = [
                token for token in sentence if not token.is_space and not token.is_punct
            ]
            lexical = [_word_forms(token) for token in words]
            for position, forms in enumerate(lexical):
                for first in sorted(forms):
                    for term, alias in tokens_by_start[first]:
                        span = words[position : position + len(alias)]
                        if len(span) != len(alias) or not all(
                            expected in lexical[position + offset]
                            for offset, expected in enumerate(alias)
                        ):
                            continue
                        pos = "phr." if len(alias) > 1 else POS.get(span[0].pos_)
                        if pos is None:
                            continue
                        allowed = positions.get(term)
                        if pos != "phr." and allowed and pos not in allowed:
                            token = span[0]
                            if (
                                token.dep_ == "conj"
                                and POS.get(token.head.pos_) in allowed
                            ):
                                pos = POS[token.head.pos_]
                            else:
                                continue
                        exact = tuple(token.text.lower() for token in span) == alias
                        by_term[term].append(
                            _Candidate(
                                source,
                                page,
                                pos,
                                _collocation(span, pos),
                                example,
                                source.translation
                                if len(example) >= len(source.text) - 4
                                else "",
                                exact,
                                span[0].dep_ in {"amod", "compound"}
                                and span[0].head.pos_ == "NOUN",
                            )
                        )
    return by_term


def _context_rank(candidate: _Candidate, occurrences: list[RawVocabulary]) -> int:
    return max(
        3
        if candidate.source.test == entry.test_number
        and candidate.source.first_question <= entry.question_last
        and candidate.source.last_question >= entry.question_first
        else 1
        if candidate.source.test == entry.test_number
        else 0
        for entry in occurrences
    )


def _contextual_pos(
    candidate: _Candidate, entry: RawVocabulary, allowed: set[str]
) -> _Candidate:
    anchors = _meaning_anchors(entry.meaning)
    if (
        candidate.pos == "n."
        and candidate.attributive
        and "adj." in allowed
        and anchors
        and anchors[0].endswith("的")
    ):
        return replace(
            candidate, pos="adj.", usage=candidate.usage.replace("名词", "形容词", 1)
        )
    return candidate


def _translate(model_dir: Path, texts: set[str]) -> dict[str, str]:
    import ctranslate2
    import sentencepiece

    piece = sentencepiece.SentencePieceProcessor(
        model_file=str(model_dir / "sentencepiece.model")
    )
    model = ctranslate2.Translator(
        str(model_dir / "model"), device="cpu", inter_threads=2, intra_threads=1
    )
    sentences = sorted(texts, key=lambda text: (len(text), text))
    translated = {}
    for start in range(0, len(sentences), 64):
        batch = sentences[start : start + 64]
        outputs = model.translate_batch(
            piece.encode(batch, out_type=str), beam_size=2, max_batch_size=32
        )
        for original, output in zip(batch, outputs, strict=True):
            translation = _clean_translation(piece.decode(output.hypotheses[0]))
            if CJK.search(translation):
                translated[original] = translation
    return translated


def rebuild_language_index(
    pdf: Path, bank: Path, model_dir: Path, destination: Path, wordnet: Path
) -> None:
    import spacy

    from backend.scripts.extract_vocabulary import extract_vocabulary

    digest = _digest(pdf)
    with closing(_connect_bank(bank)) as db:
        _validate_book(db, digest)
        texts, pages = _book_texts(db)
    entries = extract_vocabulary(pdf)
    occurrences = defaultdict(list)
    for entry in entries:
        occurrences[_sense_key(entry)].append(entry)
    aliases = {_normalized(entry.term): _term_tokens(entry.term) for entry in entries}
    model = spacy.load("en_core_web_sm", exclude=["ner"])
    positions = _possible_pos(wordnet)
    by_term = _examples(model, texts, pages, aliases, positions)
    supplements = _supplements()
    candidates_by_sense = {}
    for key, group in sorted(occurrences.items()):
        entry = group[0]
        term = _normalized(entry.term)
        curated = _curated(supplements, entry)
        matching = (
            _contextual_pos(candidate, entry, positions.get(term, set()))
            for candidate in by_term.get(term, ())
        )
        candidates = [
            (candidate, _context_rank(candidate, group))
            for candidate in matching
            if not curated or candidate.pos == curated["pos"]
        ]
        candidates.sort(
            key=lambda value: (
                value[1],
                bool(value[0].translation),
                value[0].exact,
                -len(value[0].example),
            ),
            reverse=True,
        )
        unique = {}
        for candidate, rank in candidates:
            unique.setdefault(candidate.example, (candidate, rank))
        candidates_by_sense[key] = list(unique.values())[:6]
    transcripts = {
        candidate.example
        for candidates in candidates_by_sense.values()
        for candidate, _ in candidates
        if not candidate.translation
    }
    print(
        f"分析 {len(entries)} 个出处和 {len(by_term)} 个上下文词条，翻译 {len(transcripts)} 个候选句。",
        flush=True,
    )
    translated = _translate(model_dir, transcripts)
    senses = {}
    for key, candidates in candidates_by_sense.items():
        entry = occurrences[key][0]
        approved = []
        for candidate, rank in candidates:
            translation = candidate.translation or translated.get(candidate.example, "")
            alignment = _translation_strength(entry.meaning, translation)
            if alignment >= 2 or (alignment == 1 and rank == 3 and candidate.exact):
                approved.append(
                    (
                        rank,
                        bool(candidate.translation),
                        alignment,
                        candidate,
                        translation,
                    )
                )
        if approved:
            _, _, _, candidate, translation = max(
                approved,
                key=lambda value: (
                    value[0],
                    value[1],
                    value[2],
                    -len(value[3].example),
                ),
            )
            senses[key] = {
                "pos": candidate.pos,
                "usage": candidate.usage,
                "example": candidate.example,
                "example_translation": translation,
                "example_pdf_page": candidate.page,
                "example_kind": "book",
            }
        else:
            allowed = positions.get(_normalized(entry.term), set())
            if len(allowed) == 1:
                senses[key] = {"pos": next(iter(allowed))}
    destination.write_text(
        '{"source_sha256":'
        + json.dumps(digest)
        + ',"methods":{"grammar":"spaCy en_core_web_sm","lexical_pos":"Princeton WordNet","translation":"Argos en-zh"}'
        + ',"senses":{\n'
        + ",\n".join(
            f"{json.dumps(key, ensure_ascii=False)}:{json.dumps(note, ensure_ascii=False)}"
            for key, note in senses.items()
        )
        + "\n}}\n",
        encoding="utf-8",
    )
    print(
        f"已标注 {len(senses)} 个义项，其中原书例句 {sum('example' in note for note in senses.values())} 个。"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用本地模型重建原书上下文索引")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--question-bank", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--translation-model", type=Path, required=True)
    parser.add_argument("--wordnet", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=LANGUAGE_INDEX)
    args = parser.parse_args()
    rebuild_language_index(
        args.pdf, args.question_bank, args.translation_model, args.output, args.wordnet
    )
