"""独立使用 pypdf 对原 PDF 与 SQLite 做全量对照，并固定抽样 100 题保留证据。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re
import sqlite3
import sys

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'audit' / '2026-11-11'
SEED = 20261111


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def normalized(text):
    # 独立比较只忽略空白和软连字符，保留标点与字母大小写。
    text=re.sub(r'_{5,}', '<decorative-line>', text)
    return re.sub(r'\s+', '', text.replace('\u00ad','').replace('\u00a0',' '))


def export(db):
    result = []
    for row in db.execute('''SELECT q.*,e.number exam_number,a.correct_label,a.page_no answer_page,
                            x.content explanation,x.page_start explanation_start,x.page_end explanation_end
                            FROM questions q JOIN exams e ON e.id=q.exam_id
                            JOIN answers a ON a.question_id=q.id JOIN explanations x ON x.question_id=q.id
                            ORDER BY e.number,q.number'''):
        q = dict(row)
        q['options'] = {r['label']:r['content'] for r in db.execute('SELECT * FROM options WHERE question_id=? ORDER BY label', (q['id'],))}
        if q['passage_id']:
            q['passage'] = dict(db.execute('SELECT * FROM passages WHERE id=?',(q['passage_id'],)).fetchone())
            q['assets'] = [dict(id=r['id'], page=r['page_no'], sequence=r['sequence'],bbox=json.loads(r['bbox_json']),
                                sha256=hashlib.sha256(r['content']).hexdigest()) for r in db.execute('SELECT * FROM passage_assets WHERE passage_id=? ORDER BY sequence',(q['passage_id'],))]
        result.append(q)
    return result


def prepare(db_path):
    OUT.mkdir(parents=True,exist_ok=True)
    snapshot = OUT/'before.sqlite3'
    if snapshot.exists():
        return
    with sqlite3.connect(db_path) as source, sqlite3.connect(snapshot) as dest:
        source.backup(dest)
    with sqlite3.connect(snapshot) as db:
        db.row_factory=sqlite3.Row
        records=export(db)
    sample=sorted(random.Random(SEED).sample([q['id'] for q in records],100))
    write_json(OUT/'sample-manifest.json',dict(seed=SEED,method='random.Random(seed).sample(sorted question IDs, 100), without replacement',
                                              original_database_sha256=sha(snapshot),
                                              sample=[dict(id=q['id'],exam=q['exam_number'],number=q['number'],part=q['part']) for q in records if q['id'] in sample]))
    write_json(OUT/'before-records.json',records)


def reference_pages(pdf):
    target=OUT/'reference-pages.json'
    if target.exists():
        cache=json.loads(target.read_text(encoding='utf-8'))
        if cache['pdf_sha256']==sha(pdf):
            return cache['pages']
    reader=PdfReader(pdf)
    pages=[]
    for i,page in enumerate(reader.pages):
        t=page.extract_text()
        t=re.sub(r'\n\d{3,4}\s*$', '\n',t)
        pages.append(t)
        if (i+1)%100==0:
            print(f'pypdf reference: {i+1}/{len(reader.pages)} pages',flush=True)
    write_json(target,dict(engine='pypdf',pdf_sha256=sha(pdf),pages=pages))
    return pages


def sequential(pattern,text):
    matches=[]
    for m in re.finditer(pattern,text,re.M):
        if int(m[1])==101+len(matches):
            matches.append(m)
    if len(matches)!=100:
        raise ValueError(f'独立解析题号不完整: {[m[1] for m in matches]}')
    return matches


def references(pages):
    starts=[i for i,t in enumerate(pages) if re.search(r'Test\s+\d{2}',t) and 'Reading Test' in t]
    answer_starts=[i for i,t in enumerate(pages) if len(re.findall(r'1\d{2}\.\s*\([ABCD]\)',t))>70]
    assert len(starts)==len(answer_starts)==10
    result={}
    for exam,start in enumerate(starts,1):
        end=starts[exam] if exam<10 else answer_starts[0]
        text='\n'.join(pages[start:end])
        qs=sequential(r'^\s*(1\d{2}|200)(?:\s*\.\s*|\s+(?=[A-Z(\-]))',text)
        groups=list(re.finditer(r'Questions\s+(\d{3})\s*[-–—]\s*(\d{3})\s*\.?\s+r+efer to the following[^.]*\.',text,re.I))
        boundaries=sorted([m.start() for m in qs+groups]+[m.start() for m in re.finditer(r'Part\s*[567]\b',text)]+[len(text)])
        keytext='\n'.join(pages[answer_starts[exam-1]:answer_starts[exam] if exam<10 else len(pages)])
        keys=list(re.finditer(r'(1\d{2}|200)\.\s*\(([ABCD])\)',keytext))[:100]
        assert [int(m[1]) for m in keys]==list(range(101,201))
        tail=keytext[keys[-1].end():]
        marks=sequential(r'^\s*(1\d{2}|200)(?!\d)\.?\s*',tail)
        pending=[]
        exp={}
        for j,m in enumerate(marks):
            pending.append(int(m[1]))
            frag=tail[m.end():marks[j+1].start() if j<99 else len(tail)]
            es=list(re.finditer(r'▶\s*解析\s*|^\s*→',frag,re.M))
            for k,e in enumerate(es):
                value=frag[e.end():es[k+1].start() if k+1<len(es) else len(frag)]
                value=re.split(r'▼\s*Vocabulary Check|Questions\s+\d{3}|\nTest\s+\d{2}',value)[0].strip()
                exp[pending.pop(0)]=value
        for j,m in enumerate(qs):
            n=int(m[1])
            stop=next(b for b in boundaries if b>m.start())
            body=text[m.end():stop].strip()
            opts=list(re.finditer(r'\(([ABCD])\)',body))
            if [o[1] for o in opts]!=list('ABCD'):
                raise ValueError(f'独立选项解析异常 {exam}/{n}')
            stem=body[:opts[0].start()].strip()
            if not stem and 131<=n<=146:
                stem=f'选择第 {n} 空的最佳答案。'
            p=next((g for k,g in enumerate(groups) if int(g[1])<=n<=min(int(g[2]),int(groups[k+1][1])-1 if k+1<len(groups) else 200)),None)
            material=text[p.end():next(q.start() for q in qs if int(q[1])==int(p[1]))].strip() if p else None
            result[(exam,n)]=dict(stem=stem,options={o[1]:body[o.end():opts[k+1].start() if k<3 else len(body)].strip() for k,o in enumerate(opts)},
                                 answer=keys[j][2],explanation=exp.get(n),material=material)
    return result


def compare(records,refs):
    results=[]
    for q in records:
        ref=refs[(q['exam_number'],q['number'])]
        checks={}
        evidence={}
        fields={'stem':(q['stem'],ref['stem']),'answer':(q['correct_label'],ref['answer']),
                'explanation':(q['explanation'],ref['explanation'] or '')}
        fields.update({f'option_{k}':(q['options'][k],ref['options'][k]) for k in 'ABCD'})
        if 'passage' in q:
            fields['material_text']=(q['passage']['content'],ref['material'] or '')
        for name,(actual,expected) in fields.items():
            checks[name]=normalized(actual)==normalized(expected)
            if not checks[name]:
                evidence[name]=dict(database=actual,reference=expected)
        results.append(dict(id=q['id'],exam=q['exam_number'],number=q['number'],checks=checks,
                            passed=all(checks.values()),differences=evidence))
    return results


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',type=Path,default=ROOT/'data/questions.sqlite3')
    p.add_argument('--phase',default='before')
    args=p.parse_args()
    prepare(args.database)
    pdf=next(ROOT.glob('*.pdf'))
    pages=reference_pages(pdf)
    refs=references(pages)
    with sqlite3.connect(args.database) as db:
        db.row_factory=sqlite3.Row
        records=export(db)
    checks=compare(records,refs)
    ids={s['id'] for s in json.loads((OUT/'sample-manifest.json').read_text(encoding='utf-8'))['sample']}
    summary=dict(phase=args.phase,pdf_sha256=sha(pdf),database_sha256=sha(args.database),
                 total=len(checks),passed=sum(c['passed'] for c in checks),
                 sample_count=100,sample_passed=sum(c['passed'] for c in checks if c['id'] in ids),
                 failures_by_field=dict(Counter(k for c in checks for k,v in c['checks'].items() if not v)))
    write_json(OUT/f'{args.phase}-checks.json',dict(summary=summary,results=checks))
    write_json(OUT/f'{args.phase}-records.json',records)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    for c in checks:
        if not c['passed']:
            print(c['exam'],c['number'],list(c['differences']))


if __name__=='__main__':
    main()
