import hashlib
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from backend.scripts.extract_vocabulary import extract_vocabulary

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "【2019版新东方】阅读全真模拟1000题.pdf"
BANK = ROOT / "data/vocabulary.sqlite3"


def test_extracts_every_section_and_joins_wrapped_entries():
    entries = extract_vocabulary(PDF)
    blocks = {(entry.test_number, entry.block_number) for entry in entries}
    assert Counter(test for test, _ in blocks) == {test: 27 for test in range(1, 11)}
    assert len(entries) > 5000

    first = [entry for entry in entries if entry.test_number == entry.block_number == 1]
    assert first[0].term == "additional"
    assert {entry.pdf_page for entry in first} == {450, 451}
    assert any(
        entry.term == "construction" and entry.pdf_page == 451 for entry in first
    )
    assert any(
        entry.block_pdf_page == 465 and entry.pdf_page == 466 for entry in entries
    )

    last = {entry.term: entry.meaning for entry in entries if entry.pdf_page == 1198}
    assert last["come to a decision"] == "做出决定"
    assert "通知" in last["inform"]
    assert "某人" in last["pick up"]


def test_shipped_word_bank_has_book_provenance_and_practice_material():
    with PDF.open("rb") as stream:
        source_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    with closing(sqlite3.connect(BANK.as_uri() + "?mode=ro", uri=True)) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert conn.execute("PRAGMA foreign_key_check").fetchone() is None
        assert conn.execute(
            "SELECT value FROM meta WHERE key='source_sha256'"
        ).fetchone() == (source_sha,)
        assert conn.execute(
            "SELECT count(*) FROM (SELECT DISTINCT test_number, block_number FROM sense_sources)"
        ).fetchone() == (270,)

        additional = conn.execute(
            """SELECT s.meaning, s.usage, s.example_text, s.example_translation, ss.printed_page
            FROM words AS w
            JOIN senses AS s ON s.word_id=w.id
            JOIN sense_sources AS ss ON ss.sense_id=s.id
            WHERE w.normalized='additional' AND ss.pdf_page=450 AND s.study_ready=1"""
        ).fetchone()
        assert additional is not None and all(additional)
        assert "附加" in additional[0] and additional[-1] == "1221"
        assert conn.execute(
            "SELECT count(*) FROM senses JOIN words ON words.id=senses.word_id WHERE normalized='additional'"
        ).fetchone() == (1,)

        assert (
            conn.execute(
                "SELECT count(DISTINCT word_id) FROM senses WHERE spelling_prompt IS NOT NULL"
            ).fetchone()[0]
            >= 10
        )
        assert {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT example_kind FROM senses WHERE study_ready=1"
            )
        } == {"original", "supplemental"}
