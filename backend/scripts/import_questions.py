"""从本书 PDF 导入题库：uv run python -m backend.scripts.import_questions。"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

import pymupdf

from backend.app.db.database import DEFAULT_DATABASE, connect_database

ROOT = Path(__file__).resolve().parents[2]
QUESTION = re.compile(r'(?m)^(1\d{2}|200)(?:\s*[.．]\s*|[ \t]+(?=[A-Z(\-]))')
GROUP = re.compile(r'Questions\s+(\d{3})\s*[-–—]\s*(\d{3})\.?\s+r+efer to the following[^.]*\.', re.I)
OPTION = re.compile(r'\(([ABCD])\)')


def clean(text: str) -> str:
    text = text.replace('\u00ad', '').replace('\u00a0', ' ')
    text = re.sub(r'(-{2,})\s*\n\s*(-{2,})', r'\1\2', text)
    return re.sub(r'\s+', ' ', text).strip()


@dataclass
class Line:
    offset: int
    page: int
    bbox: tuple


class Stream:
    def __init__(self, doc, start, end):
        self.text = ''
        self.lines = []
        for i in range(start - 1, end):
            page = doc[i]
            blocks = page.get_text('dict')['blocks']
            for block in blocks:
                for line in block.get('lines', []):
                    value = ''.join(s['text'] for s in line['spans']).strip()
                    # 本书页脚的书内页码，不删除正文中的数字。
                    if value.isdigit() and int(value) >= 700 and line['bbox'][1] > page.rect.height * .92:
                        continue
                    self.lines.append(Line(len(self.text), i + 1, tuple(line['bbox'])))
                    self.text += value + '\n'
        self.offsets = [line.offset for line in self.lines]

    def location(self, offset):
        return self.lines[max(0, bisect_right(self.offsets, offset) - 1)]


def parse_exam(doc, start, end):
    stream = Stream(doc, start, end)
    text = stream.text
    matches = []
    for candidate in QUESTION.finditer(text):
        if int(candidate[1]) == 101 + len(matches):
            matches.append(candidate)
    numbers = [int(m[1]) for m in matches]
    if numbers != list(range(101, 201)):
        raise ValueError(f'题号不完整/重复，PDF {start}-{end}: {numbers}')
    groups = list(GROUP.finditer(text))
    part_markers = list(re.finditer(r'(?m)^Part\s*[567]\b', text))
    boundaries = sorted([m.start() for m in matches + groups + part_markers] + [len(text)])
    passages = []
    for group_index, group in enumerate(groups):
        first, last = int(group[1]), int(group[2])
        printed_last = last
        if group_index + 1 < len(groups):
            last = min(last, int(groups[group_index + 1][1]) - 1)
        first_q = next(m for m in matches if int(m[1]) == first)
        passages.append(dict(first=first, last=last, instruction=clean(group[0]),
                             content=text[group.end():first_q.start()].strip(),
                             start=group.start(), end=first_q.start(), printed_last=printed_last))
    questions = []
    for match in matches:
        end_offset = next(b for b in boundaries if b > match.start())
        body = text[match.end():end_offset].strip()
        options = list(OPTION.finditer(body))
        labels = [o[1] for o in options]
        if labels != list('ABCD'):
            raise ValueError(f'PDF {start}, 题号 {match[1]}, 选项异常: {labels}, {body}')
        choices = {o[1]: clean(body[o.end():options[i+1].start() if i+1 < 4 else len(body)])
                   for i, o in enumerate(options)}
        number = int(match[1])
        stem = clean(body[:options[0].start()])
        questions.append(dict(number=number, stem=stem, options=choices, raw=body,
                              page_start=stream.location(match.start()).page,
                              page_end=stream.location(end_offset - 1).page))
    return stream, passages, questions


def parse_answers(doc, start, end):
    stream = Stream(doc, start, end)
    text = stream.text
    keys = list(re.finditer(r'(1\d{2}|200)\.\s*\(([ABCD])\)', text))
    # 答案速查表在每套解析的最前面，严格按 101–200 取值。
    keys = keys[:100]
    if [int(m[1]) for m in keys] != list(range(101, 201)):
        raise ValueError(f'答案速查表异常: PDF {start}')
    answers = {int(m[1]): (m[2], stream.location(m.start()).page) for m in keys}
    tail_start = keys[-1].end()
    markers = []
    for marker in re.finditer(r'(?m)^(1\d{2}|200)(?!\d)(?:[.．])?(?:\s+|(?=[“"‘]))', text[tail_start:]):
        if int(marker[1]) == 101 + len(markers):
            markers.append(marker)
    if len(markers) != 100:
        raise ValueError(f'解析区题号异常: PDF {start}, {[m[1] for m in markers]}')
    explanations = {}
    pending = []
    for i, marker in enumerate(markers):
        number = int(marker[1])
        pending.append(number)
        a = tail_start + marker.end()
        b = tail_start + markers[i+1].start() if i+1 < len(markers) else len(text)
        fragment = text[a:b]
        # Part 5 的译文后有“解析”，其他题型采用箭头引出说明。
        explanation_markers = list(re.finditer(r'▶\s*解析\s*|(?m:^→)', fragment))
        for j, explanation in enumerate(explanation_markers):
            stop = explanation_markers[j+1].start() if j+1 < len(explanation_markers) else len(fragment)
            content = fragment[explanation.end():stop]
            content = re.split(r'▼\s*Vocabulary Check|Questions\s+\d{3}|\nTest\s+\d{2}', content)[0]
            if not pending:
                raise ValueError(f'PDF {start}, {number}: 解析条数超出题目数')
            target = pending.pop(0)
            explanations[target] = (content.strip(), stream.location(a+explanation.start()).page,
                                    stream.location(a+explanation.end()+len(content)-1).page)
    return answers, explanations


def render_passage(doc, stream, passage):
    first = stream.location(passage['start'])
    last = stream.location(passage['end'])
    assets = []
    for page_no in range(first.page, last.page + 1):
        page = doc[page_no - 1]
        top = max(0, first.bbox[1] - 3) if page_no == first.page else 0
        # 正文可延伸至页面 94% 的位置，不能用固定百分比截断。
        # 只在已定位到独立页脚时移除页脚，否则保留至页面底部。
        footer_top = page.rect.height
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', []):
                value = ''.join(s['text'] for s in line['spans']).strip()
                if value.isdigit() and int(value) >= 700 and line['bbox'][1] > page.rect.height * .92:
                    footer_top = min(footer_top, line['bbox'][1] - 3)
        bottom = last.bbox[1] - 3 if page_no == last.page else footer_top
        if bottom <= top:
            continue
        clip = pymupdf.Rect(0, top, page.rect.width, bottom)
        # 某些分页仅留下边框底线，不生成空白材料截图。
        has_image = any((pymupdf.Rect(info['bbox']) & clip).get_area() > 1
                        for info in page.get_image_info())
        if not page.get_text('words', clip=clip) and not has_image:
            continue
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), clip=clip)
        assets.append((page_no, json.dumps(list(clip)), pix.tobytes('jpeg', jpg_quality=85)))
    return assets


def validate(db):
    errors = []
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        errors.append('integrity_check failed')
    if db.execute('PRAGMA foreign_key_check').fetchall():
        errors.append('foreign_key_check failed')
    bad = db.execute('''SELECT q.id FROM questions q LEFT JOIN options o ON o.question_id=q.id
                        GROUP BY q.id HAVING count(o.label) != 4''').fetchall()
    if bad:
        errors.append(f'选项数量异常: {len(bad)}')
    for exam in db.execute('SELECT id FROM exams'):
        rows = db.execute('SELECT number,part FROM questions WHERE exam_id=? ORDER BY number', (exam[0],)).fetchall()
        if [r[0] for r in rows] != list(range(101,201)):
            errors.append(f'试卷 {exam[0]} 题号不连续')
        if [r[1] for r in rows] != [5]*30 + [6]*16 + [7]*54:
            errors.append(f'试卷 {exam[0]} Part 分布异常')
    for sql, label in [
        ('SELECT count(*) FROM questions q LEFT JOIN answers a ON a.question_id=q.id WHERE a.question_id IS NULL', '缺少答案'),
        ('SELECT count(*) FROM questions WHERE part>5 AND passage_id IS NULL', '缺少阅读材料'),
        ('SELECT count(*) FROM questions q JOIN passages p ON p.id=q.passage_id WHERE q.exam_id!=p.exam_id OR q.number NOT BETWEEN p.first_number AND p.last_number', '材料关联异常'),
        ('SELECT count(*) FROM passages p WHERE NOT EXISTS (SELECT 1 FROM passage_assets a WHERE a.passage_id=p.id)', '缺少材料原版截图'),
        ("SELECT count(*) FROM questions WHERE length(trim(stem))=0", '空题干'),
    ]:
        count = db.execute(sql).fetchone()[0]
        if count:
            errors.append(f'{label}: {count}')
    if errors:
        raise ValueError('; '.join(errors))
    return dict(integrity_check='ok', foreign_key_check='ok', four_options_per_question=True,
                all_questions_have_answers=True, all_reading_questions_have_passages=True,
                exam_numbers_and_parts_complete=True, passage_links_and_assets_valid=True)


def validate_material_coverage(db, doc):
    """原材料的所有可抽取文字必须出现在截图范围内，防止截图截断。"""
    for passage in db.execute('SELECT * FROM passages ORDER BY id'):
        fragments=[]
        for asset in db.execute('SELECT * FROM passage_assets WHERE passage_id=? ORDER BY sequence',(passage['id'],)):
            box=pymupdf.Rect(json.loads(asset['bbox_json']))
            fragments.append(doc[asset['page_no']-1].get_text(clip=box))
        if clean(' '.join(fragments)) != clean(passage['instruction']+' '+passage['content']):
            raise ValueError(f"材料 {passage['id']} 的截图文字覆盖不完整，停止入库")
    return True


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    pdfs = list(ROOT.glob('*.pdf'))
    if args.pdf is None and len(pdfs) != 1:
        parser.error('请使用 --pdf 指定源文件')
    source = args.pdf or pdfs[0]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    db = connect_database(args.database)
    try:
        has_schema = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sources'").fetchone()
        if has_schema and db.execute('SELECT id FROM sources WHERE sha256=?', (digest,)).fetchone():
            checks=validate(db)
            with pymupdf.open(source) as doc:
                checks['all_material_text_visible_in_assets']=validate_material_coverage(db,doc)
            print('相同来源已入库，跳过。', checks)
            return
        db.executescript((ROOT / 'backend/app/db/schema.sql').read_text(encoding='utf-8'))
        with pymupdf.open(source) as doc, db:
            raw = [p.get_text() for p in doc]
            question_starts = [i+1 for i, t in enumerate(raw) if 'Reading Test' in t and re.search(r'Test\s+\d{2}', t)]
            answer_starts = [i+1 for i, t in enumerate(raw) if len(re.findall(r'1\d{2}\.\s*\([ABCD]\)', t)) > 70]
            if len(question_starts) != 10 or len(answer_starts) != 10:
                raise ValueError(f'试卷/答案区数量异常: {question_starts}, {answer_starts}')
            sid = db.execute('INSERT INTO sources(filename,sha256,page_count) VALUES(?,?,?)', (source.name,digest,len(doc))).lastrowid
            for i, t in enumerate(raw):
                footer = re.search(r'\n(\d{3,4})\s*$', t)
                db.execute('INSERT INTO source_pages VALUES(?,?,?,?)', (sid,i+1,footer[1] if footer else None,t))
            issues = []
            for index, start in enumerate(question_starts):
                end = question_starts[index+1]-1 if index < 9 else answer_starts[0]-1
                answer_end = answer_starts[index+1]-1 if index < 9 else len(doc)
                stream, passages, questions = parse_exam(doc, start, end)
                answers, explanations = parse_answers(doc, answer_starts[index], answer_end)
                exam_id = db.execute('INSERT INTO exams(source_id,number,title) VALUES(?,?,?)', (sid,index+1,f'Test {index+1:02}')).lastrowid
                links = {}
                for p in passages:
                    if p['printed_last'] != p['last']:
                        detail = f"原书 {p['first']}-{p['printed_last']}，依据下一组起始题号修正为 {p['first']}-{p['last']}；原始引导语保留"
                        issues.append(dict(exam=index+1,question=p['first'],code='corrected_passage_range',detail=detail))
                        db.execute('INSERT INTO import_issues(source_id,exam_number,question_number,code,detail) VALUES(?,?,?,?,?)', (sid,index+1,p['first'],'corrected_passage_range',detail))
                    part = 6 if p['first'] < 147 else 7
                    first_page = stream.location(p['start']).page
                    last_page = stream.location(p['end']).page
                    pid = db.execute('''INSERT INTO passages(exam_id,part,first_number,last_number,instruction,content,page_start,page_end)
                                        VALUES(?,?,?,?,?,?,?,?)''', (exam_id,part,p['first'],p['last'],p['instruction'],p['content'],first_page,last_page)).lastrowid
                    for seq, (page_no,bbox,blob) in enumerate(render_passage(doc,stream,p), 1):
                        db.execute('INSERT INTO passage_assets(passage_id,sequence,page_no,bbox_json,content) VALUES(?,?,?,?,?)', (pid,seq,page_no,bbox,blob))
                    for n in range(p['first'],p['last']+1):
                        if n in links:
                            raise ValueError('阅读材料题号范围重叠')
                        links[n] = pid
                for q in questions:
                    n = q['number']
                    part = 5 if n < 131 else 6 if n < 147 else 7
                    stem = q['stem'] or (f'选择第 {n} 空的最佳答案。' if part == 6 else '')
                    if not stem or (part > 5 and n not in links):
                        raise ValueError(f'Test {index+1}, {n} 缺少题干或材料')
                    qid = db.execute('''INSERT INTO questions(exam_id,passage_id,number,part,stem,raw_text,page_start,page_end,status)
                                        VALUES(?,?,?,?,?,?,?,?,?)''', (exam_id,links.get(n),n,part,stem,q['raw'],q['page_start'],q['page_end'],'ready')).lastrowid
                    for label, content in q['options'].items():
                        db.execute('INSERT INTO options VALUES(?,?,?)', (qid,label,content))
                    label, page = answers[n]
                    db.execute('INSERT INTO answers VALUES(?,?,?)', (qid,label,page))
                    if n in explanations:
                        db.execute('INSERT INTO explanations VALUES(?,?,?,?)', (qid,*explanations[n]))
                    else:
                        issue = dict(exam=index+1,question=n,code='missing_explanation',detail='未定位到独立解析，保留原始页文本以供核对')
                        issues.append(issue)
                        db.execute('INSERT INTO import_issues(source_id,exam_number,question_number,code,detail) VALUES(?,?,?,?,?)', (sid,index+1,n,issue['code'],issue['detail']))
                print(f'Test {index+1:02}: {len(questions)} 题，{len(passages)} 组材料，{len(explanations)} 条解析', flush=True)
            checks = validate(db)
            checks['all_material_text_visible_in_assets']=validate_material_coverage(db,doc)
            report = dict(source=source.name,sha256=digest,pdf_pages=len(doc),
                          counts={table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in
                                  ['exams','passages','passage_assets','questions','options','answers','explanations','import_issues']},
                          checks=checks,issues=issues)
        report_path = args.database.parent / 'import-report.json'
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2), encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        db.close()


if __name__ == '__main__':
    main()
