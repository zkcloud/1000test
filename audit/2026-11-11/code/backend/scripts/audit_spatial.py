"""检查来源页码、材料截图完整性及原文像素一致性。"""
import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pymupdf

from backend.scripts.audit_questions import ROOT,OUT,normalized,write_json,export


def main():
    sys.stdout.reconfigure(encoding='utf8')
    p=argparse.ArgumentParser()
    p.add_argument('--database',type=Path,default=ROOT/'data/questions.sqlite3')
    p.add_argument('--phase',default='before')
    args=p.parse_args()
    db=sqlite3.connect(args.database)
    db.row_factory=sqlite3.Row
    records=export(db)
    doc=pymupdf.open(next(ROOT.glob('*.pdf')))
    pages=json.loads((OUT/'reference-pages.json').read_text(encoding='utf8'))['pages']
    issues=[]
    checks=[]
    def record(kind,entity,ok,detail=None):
        item=dict(kind=kind,entity=entity,passed=bool(ok))
        if not ok:
            item['detail']=detail
            issues.append(item)
        checks.append(item)
    for q in records:
        key=f"{q['exam_number']:02}/{q['number']}"
        for prefix,content,start,end in [('question',q['raw_text'],q['page_start'],q['page_end']),
                                         ('explanation',q['explanation'],q['explanation_start'],q['explanation_end'])]:
            ref=normalized('\n'.join(pages[start-1:end]))
            record(prefix+'_page_citation',key,normalized(content) in ref,
                   dict(pages=[start,end],content=content,reference=ref))
            # 精确校验第一页/最后一页的确包含正文边界，不能只验证宽泛区间。
            n=normalized(content)
            chunks=[normalized(p) for p in pages[start-1:end]]
            joined=''.join(chunks)
            pos=joined.find(n)
            cumulative=[0]
            for chunk in chunks:
                cumulative.append(cumulative[-1]+len(chunk))
            actual_start=start+bisect_right(cumulative,pos)-1 if pos>=0 else None
            actual_end=start+bisect_right(cumulative,pos+len(n)-1)-1 if pos>=0 else None
            record(prefix+'_page_bounds',key,[actual_start,actual_end]==[start,end],
                   dict(pages=[start,end],actual=[actual_start,actual_end]))
    for psg in db.execute('SELECT * FROM passages ORDER BY id'):
        assets=db.execute('SELECT * FROM passage_assets WHERE passage_id=? ORDER BY sequence',(psg['id'],)).fetchall()
        text=[]
        for a in assets:
            page=doc[a['page_no']-1]
            box=pymupdf.Rect(json.loads(a['bbox_json']))
            pix=page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5),clip=box)
            record('asset_pixels',a['id'],hashlib.sha256(pix.tobytes('jpeg',jpg_quality=85)).digest()==hashlib.sha256(a['content']).digest())
            text.append(page.get_text(clip=box))
            for image_index,img in enumerate(page.get_image_info()):
                ib=pymupdf.Rect(img['bbox'])
                overlap=(ib & box).get_area()
                if overlap>1:
                    ratio=overlap/ib.get_area()
                    record('embedded_image_complete',f"{a['id']}/{image_index}",ratio>.999,
                           dict(coverage=ratio,page=a['page_no'],image_bbox=list(ib),clip=list(box)))
        expected=normalized(psg['instruction']+'\n'+psg['content'])
        actual=normalized('\n'.join(text))
        record('material_text_coverage',psg['id'],expected==actual,dict(expected=expected,actual=actual))
    for page in db.execute('SELECT * FROM source_pages'):
        record('source_page_text',page['page_no'],page['raw_text']==doc[page['page_no']-1].get_text())
    report=dict(summary=dict(checks=len(checks),passed=sum(c['passed'] for c in checks),
                             failures=len(issues),failures_by_kind=dict(Counter(i['kind'] for i in issues))),issues=issues,checks=checks)
    write_json(OUT/f'{args.phase}-spatial.json',report)
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))
    for i in issues:
        print(i['kind'],i['entity'],str(i.get('detail'))[:250])
    db.close()


if __name__=='__main__':
    main()
