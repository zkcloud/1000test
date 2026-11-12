"""对真实入库结果和已发现的原书排版问题做回归检查。"""
import unittest
import json
from pathlib import Path

import pymupdf

from backend.app.db.database import connect_database
from backend.scripts.import_questions import validate, clean
from backend.scripts.audit_questions import normalized


class QuestionBankTests(unittest.TestCase):
    def setUp(self):
        self.db = connect_database()

    def tearDown(self):
        self.db.close()

    def test_complete_bank(self):
        self.assertEqual(self.db.execute('SELECT count(*) FROM exams').fetchone()[0], 10)
        self.assertEqual(self.db.execute('SELECT count(*) FROM questions').fetchone()[0], 1000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM explanations').fetchone()[0], 1000)
        self.assertEqual(validate(self.db)['integrity_check'], 'ok')

    def test_answers_match_printed_key(self):
        rows = self.db.execute('''SELECT q.number,a.correct_label FROM answers a
            JOIN questions q ON q.id=a.question_id JOIN exams e ON e.id=q.exam_id
            WHERE e.number=1 AND q.number IN (101,131,200) ORDER BY q.number''').fetchall()
        self.assertEqual([tuple(r) for r in rows], [(101,'A'),(131,'D'),(200,'A')])

    def test_delayed_explanations_are_assigned_to_right_question(self):
        for exam, number, expected in [(6,109,'qualified'),(6,110,'committed'),
                                       (6,111,'whether'),(6,112,'emphasis'),
                                       (9,121,'interviewing'),(9,122,'measures'),
                                       (5,135,'compared'),(10,141,'close')]:
            row = self.db.execute('''SELECT x.content FROM explanations x
                JOIN questions q ON q.id=x.question_id JOIN exams e ON e.id=q.exam_id
                WHERE e.number=? AND q.number=?''', (exam,number)).fetchone()
            with self.subTest(exam=exam,number=number):
                self.assertIn(expected, row[0])

    def test_image_only_material_is_preserved(self):
        row = self.db.execute('''SELECT a.content FROM passage_assets a
            JOIN passages p ON p.id=a.passage_id JOIN exams e ON e.id=p.exam_id
            WHERE e.number=1 AND p.first_number=143''').fetchone()
        self.assertTrue(row[0].startswith(b'\xff\xd8'))
        self.assertGreater(len(row[0]), 10000)

    def test_original_range_typo_is_corrected_with_audit(self):
        row = self.db.execute('''SELECT p.last_number,p.instruction FROM passages p
            JOIN exams e ON e.id=p.exam_id WHERE e.number=4 AND p.first_number=131''').fetchone()
        self.assertEqual(row[0],134)
        self.assertIn('131-144',row[1])
        self.assertEqual(self.db.execute("SELECT count(*) FROM import_issues WHERE code='corrected_passage_range'").fetchone()[0],1)

    def test_no_encoding_damage_or_empty_explanation(self):
        for table, col in [('questions','stem'),('options','content'),('passages','content'),('explanations','content')]:
            self.assertEqual(self.db.execute(f'SELECT count(*) FROM {table} WHERE instr({col},char(65533))>0').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM explanations WHERE length(content)<8').fetchone()[0],0)

    def test_wrapped_blank_is_joined(self):
        self.assertEqual(clean('word ----\n---- end'), 'word -------- end')

    def test_all_material_crops_include_complete_source_text(self):
        root=Path(__file__).resolve().parents[2]
        with pymupdf.open(next(root.glob('*.pdf'))) as doc:
            for p in self.db.execute('SELECT * FROM passages'):
                parts=[]
                for a in self.db.execute('SELECT * FROM passage_assets WHERE passage_id=? ORDER BY sequence',(p['id'],)):
                    box=pymupdf.Rect(json.loads(a['bbox_json']))
                    parts.append(doc[a['page_no']-1].get_text(clip=box))
                with self.subTest(passage=p['id']):
                    self.assertEqual(normalized('\n'.join(parts)), normalized(p['instruction']+'\n'+p['content']))


if __name__ == '__main__':
    unittest.main()
