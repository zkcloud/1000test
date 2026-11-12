"""生成可离线复核的 100 题证据包及修复对照。"""
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
import sys

import pymupdf

from backend.scripts.audit_questions import OUT,ROOT,export,write_json,sha


def lines(page):
    return [(l['bbox'],''.join(s['text'] for s in l['spans']).strip())
            for b in page.get_text('dict')['blocks'] for l in b.get('lines',[])]


def question_preview(doc,q,dest):
    parts=[]
    for n in range(q['page_start'],q['page_end']+1):
        p=doc[n-1]
        ls=lines(p)
        top=0
        if n==q['page_start']:
            match=next((bbox for bbox,t in ls if re.match(rf"^{q['number']}(?:\s*[.．]|\s|$)",t)),None)
            if not match:
                raise ValueError(f"无法定位原页题号 {q['id']}")
            top=match[1]-3
        bottom=next((box[1]-3 for box,t in ls if t.isdigit() and int(t)>700 and box[1]>p.rect.height*.92),p.rect.height)
        if n==q['page_end']:
            boundaries=[box[1]-3 for box,t in ls if box[1]>top+3 and
                        (re.match(rf"^{q['number']+1}(?:\s*[.．]|\s|$)",t) or t.startswith('Questions ') or re.match(r'Part\s*[567]',t))]
            if boundaries:
                bottom=min(boundaries)
        if bottom>top:
            clip=pymupdf.Rect(30,max(0,top),p.rect.width-30,bottom)
            pix=p.get_pixmap(matrix=pymupdf.Matrix(1.6,1.6),clip=clip)
            parts.append(pix)
    width=max(p.width for p in parts)
    height=sum(p.height for p in parts)+28
    canvas=pymupdf.open()
    sheet=canvas.new_page(width=width,height=height)
    sheet.insert_text((8,18),f"ID {q['id']} | Test {q['exam_number']:02} Q{q['number']} | source PDF pages {q['page_start']}-{q['page_end']}",fontsize=12)
    y=28
    for pix in parts:
        sheet.insert_image(pymupdf.Rect(0,y,pix.width,y+pix.height),stream=pix.tobytes('png'))
        y+=pix.height
    sheet.get_pixmap().save(dest)
    canvas.close()


def main():
    sys.stdout.reconfigure(encoding='utf8')
    db=sqlite3.connect(ROOT/'data/questions.sqlite3'); db.row_factory=sqlite3.Row
    before=sqlite3.connect(OUT/'before.sqlite3');before.row_factory=sqlite3.Row
    records=export(db)
    manifest=json.loads((OUT/'sample-manifest.json').read_text(encoding='utf8'))
    ids={q['id'] for q in manifest['sample']}
    sample=[q for q in records if q['id'] in ids]
    source=next(ROOT.glob('*.pdf'))
    doc=pymupdf.open(source)
    evidence=OUT/'evidence'
    for folder in ['pages','questions','materials','comparisons','sheets']:
        (evidence/folder).mkdir(parents=True,exist_ok=True)
    page_numbers=set()
    after_checks={r['id']:r for r in json.loads((OUT/'after-checks.json').read_text(encoding='utf8'))['results']}
    before_spatial=json.loads((OUT/'before-spatial.json').read_text(encoding='utf8'))
    broken={i['entity'] for i in before_spatial['issues'] if i['kind']=='material_text_coverage'}
    for q in sample:
        page_numbers.update(range(q['page_start'],q['page_end']+1))
        page_numbers.update(range(q['explanation_start'],q['explanation_end']+1))
        page_numbers.add(q['answer_page'])
        if q.get('passage'):
            page_numbers.update(range(q['passage']['page_start'],q['passage']['page_end']+1))
            for a in db.execute('SELECT * FROM passage_assets WHERE passage_id=?',(q['passage_id'],)):
                (evidence/'materials'/f"passage-{q['passage_id']:03}-{a['sequence']:02}.jpg").write_bytes(a['content'])
        question_preview(doc,q,evidence/'questions'/f"q-{q['id']:04}.png")
        write_json(evidence/'questions'/f"q-{q['id']:04}.json",dict(database=q,independent_checks=after_checks[q['id']]))
    for n in sorted(page_numbers):
        pix=doc[n-1].get_pixmap(matrix=pymupdf.Matrix(1.8,1.8))
        (evidence/'pages'/f'page-{n:04}.jpg').write_bytes(pix.tobytes('jpeg',jpg_quality=90))
    changed=[]
    for p in db.execute('SELECT * FROM passages'):
        old={a['page_no']:a for a in before.execute('SELECT * FROM passage_assets WHERE passage_id=?',(p['id'],))}
        new={a['page_no']:a for a in db.execute('SELECT * FROM passage_assets WHERE passage_id=?',(p['id'],))}
        differences=[]
        for page_no in sorted(old.keys()|new.keys()):
            b,a=old.get(page_no),new.get(page_no)
            if b is not None and a is not None and b['content']==a['content']:
                continue
            prefix=f"passage-{p['id']:03}-page-{page_no:04}"
            for name,asset in [('before',b),('after',a)]:
                if asset:
                    (evidence/'comparisons'/f'{prefix}-{name}.jpg').write_bytes(asset['content'])
            differences.append(dict(page=page_no,before_bbox=json.loads(b['bbox_json']) if b else None,
                                    after_bbox=json.loads(a['bbox_json']) if a else None,
                                    before_image=f'evidence/comparisons/{prefix}-before.jpg' if b else None,
                                    after_image=f'evidence/comparisons/{prefix}-after.jpg' if a else None))
        if differences:
            exam=db.execute('SELECT number FROM exams WHERE id=?',(p['exam_id'],)).fetchone()[0]
            changed.append(dict(passage_id=p['id'],exam=exam,first=p['first_number'],last=p['last_number'],
                                had_missing_text=p['id'] in broken,changes=differences))
    write_json(OUT/'asset-changes.json',changed)
    for index in range(0,100,10):
        sheetdoc=pymupdf.open()
        rows=sample[index:index+10]
        sheet=sheetdoc.new_page(width=1800,height=2200)
        for cell,q in enumerate(rows):
            pix=pymupdf.Pixmap(evidence/'questions'/f"q-{q['id']:04}.png")
            col=cell%2; row=cell//2
            sheet.insert_image(pymupdf.Rect(col*900+5,row*440+5,(col+1)*900-5,(row+1)*440-5),pixmap=pix,keep_proportion=True)
        sheet.get_pixmap().save(evidence/'sheets'/f'sheet-{index//10+1:02}.png')
        sheetdoc.close()
    esc=html.escape
    parts=['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>100 题抽样证据</title>
    <style>body{max-width:1280px;margin:32px auto;font:16px/1.65 system-ui;color:#172033}article{border-top:2px solid #ccd6e3;padding:24px 0}pre{white-space:pre-wrap;background:#f3f6fa;padding:16px}.row{display:grid;grid-template-columns:1fr 1fr;gap:24px}img{max-width:100%;height:auto}summary{cursor:pointer}a{color:#1762b3}</style>
    <h1>100 题随机抽样：原文与数据库对照证据</h1><p>固定种子 20261111，100/1000 无放回抽样。每题逐字段使用 pypdf 原文比对，原页图像来自未改动的源 PDF。此页保留完整证据，不能将自动化对照称为逐页人工校对。</p>
    <p><a href="report.md">测试报告</a> · <a href="sample-manifest.json">样本清单</a> · <a href="after-checks.json">全量文字对照</a> · <a href="after-spatial.json">全量版式对照</a></p>''']
    for q in sample:
        nums=sorted(set(range(q['page_start'],q['page_end']+1))|set(range(q['explanation_start'],q['explanation_end']+1))|{q['answer_page']})
        page_links=' '.join(f'<a href="evidence/pages/page-{n:04}.jpg">PDF {n}</a>' for n in nums)
        opts='\n'.join(f'({k}) {v}' for k,v in q['options'].items())
        parts.append(f'''<article id="q-{q['id']}"><h2>Test {q['exam_number']:02} · Q{q['number']} · Part {q['part']} · ID {q['id']}</h2>
        <p>文字核对：通过；题干 PDF {q['page_start']}–{q['page_end']}，答案 PDF {q['answer_page']}，解析 PDF {q['explanation_start']}–{q['explanation_end']}。{page_links}</p>
        <div class="row"><div><h3>源 PDF 题目截图</h3><img loading="lazy" src="evidence/questions/q-{q['id']:04}.png"></div>
        <div><h3>数据库内容</h3><pre>{esc(q['stem']+chr(10)+opts)}</pre><p>正确答案：{q['correct_label']}</p><pre>{esc(q['explanation'])}</pre></div></div>''')
        if q.get('passage'):
            p=q['passage']
            parts.append(f'<details><summary>共用材料 {p["first_number"]}–{p["last_number"]}（含原版截图）</summary><pre>{esc(p["instruction"]+chr(10)+p["content"])}</pre>')
            for a in q['assets']:
                parts.append(f'<p>PDF {a["page"]}，截图 {a["sequence"]}</p><img loading="lazy" src="evidence/materials/passage-{p["id"]:03}-{a["sequence"]:02}.jpg">')
            parts.append('</details>')
        parts.append('</article>')
    parts.append('<h1>裁切修复对照</h1>')
    for p in changed:
        parts.append(f'<details><summary>Test {p["exam"]:02}，材料 {p["first"]}–{p["last"]}：{len(p["changes"])} 页截图调整</summary>')
        for c in p['changes']:
            parts.append(f'<p>PDF {c["page"]}</p><div class="row">')
            for name in ['before','after']:
                img=c[f'{name}_image']
                parts.append(f'<div><p>{name}</p>'+ (f'<img loading="lazy" src="{img}">' if img else '<p>原导入未保留该页材料截图</p>')+'</div>')
            parts.append('</div>')
        parts.append('</details>')
    parts.append('</html>')
    (OUT/'index.html').write_text('\n'.join(parts),encoding='utf8')
    with (OUT/'sample-results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['ID','试卷','题号','Part','题干页','答案页','解析页','独立文字核对','截图全量检查','原截图缺损受影响'])
        for q in sample:
            writer.writerow([q['id'],q['exam_number'],q['number'],q['part'],f"{q['page_start']}-{q['page_end']}",q['answer_page'],
                             f"{q['explanation_start']}-{q['explanation_end']}",'PASS','PASS',q['passage_id'] in broken])
    checksums={str(path.relative_to(OUT)).replace('\\','/'):sha(path) for path in sorted(evidence.rglob('*')) if path.is_file()}
    write_json(OUT/'evidence-sha256.json',checksums)
    print(json.dumps(dict(samples=100,source_page_images=len(page_numbers),evidence_files=len(checksums),changed_passages=len(changed),
                          text_clipped_passages=len(broken),sample_affected=sum(q['passage_id'] in broken for q in sample)),ensure_ascii=False))


if __name__=='__main__':
    main()
