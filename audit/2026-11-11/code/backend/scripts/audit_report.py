"""生成审计报告、哈希清单及可离线复核的 ZIP。"""
from collections import Counter
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile

from backend.scripts.audit_questions import ROOT,OUT,write_json,sha
from backend.scripts.import_questions import validate,validate_material_coverage
import pymupdf


def load(name):
    return json.loads((OUT/name).read_text(encoding='utf8'))


def main():
    sys.stdout.reconfigure(encoding='utf8')
    after=load('after-checks.json'); before=load('before-checks.json')
    spatial=load('after-spatial.json'); oldsp=load('before-spatial.json')
    manifest=load('sample-manifest.json'); changes=load('asset-changes.json')
    current=load('after-records.json'); original=load('before-records.json')
    broken={i['entity'] for i in oldsp['issues'] if i['kind']=='material_text_coverage'}
    ids={s['id'] for s in manifest['sample']}
    sample=[q for q in current if q['id'] in ids]
    byexam=Counter(q['exam_number'] for q in sample)
    bypart=Counter(q['part'] for q in sample)
    old_affected=[q for q in original if q['passage_id'] in broken]
    sample_affected=[q for q in old_affected if q['id'] in ids]
    pagefiles=list((OUT/'evidence/pages').glob('*.jpg'))
    evidence_count=len(load('evidence-sha256.json'))
    tables=['questions','options','answers','explanations','passages']
    beforedb=sqlite3.connect(OUT/'before.sqlite3')
    afterdb=sqlite3.connect(ROOT/'data/questions.sqlite3')
    unchanged={table:beforedb.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()==afterdb.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() for table in tables}
    beforedb.row_factory=sqlite3.Row; afterdb.row_factory=sqlite3.Row
    assert all(unchanged.values())
    assert sha(ROOT/'data/questions.sqlite3')==after['summary']['database_sha256']
    assert after['summary']['passed']==1000 and after['summary']['sample_passed']==100
    assert spatial['summary']['failures']==0
    source=next(ROOT.glob('*.pdf'))
    with pymupdf.open(source) as doc:
        try:
            validate_material_coverage(beforedb,doc)
        except ValueError as error:
            (OUT/'before-regression.log').write_text(str(error)+'\nEXPECTED FAILURE: old database rejected by new import gate.\n',encoding='utf8')
        else:
            raise AssertionError('旧数据未触发新回归检查')
        final_integrity=validate(afterdb)
        final_integrity['all_material_text_visible_in_assets']=validate_material_coverage(afterdb,doc)
    beforedb.close();afterdb.close()
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s','backend/tests','-v'],cwd=ROOT,capture_output=True,text=True,encoding='utf8')
    (OUT/'unit-tests.log').write_text(result.stdout+result.stderr,encoding='utf8')
    if result.returncode:
        raise RuntimeError('回归测试失败')
    import_report=json.loads((ROOT/'data/import-report.json').read_text(encoding='utf8'))
    import_report['checks'].update(final_integrity)
    import_report['audit_report']='audit/2026-11-11/report.md'
    write_json(ROOT/'data/import-report.json',import_report)
    shutil.copyfile(ROOT/'data/import-report.json',OUT/'import-report.json')
    shutil.copyfile(source,OUT/'source.pdf')
    shutil.copyfile(ROOT/'data/questions.sqlite3',OUT/'after.sqlite3')
    # 备份产生的物理文件哈希可与检查前原文件不同，分别明确记录。
    manifest['before_backup_sha256']=sha(OUT/'before.sqlite3')
    manifest['original_database_sha256']=before['summary']['database_sha256']
    write_json(OUT/'sample-manifest.json',manifest)
    visual=dict(reviewer='Codex image inspection',scope='100 sampled source question crops in 10 contact sheets; targeted before/after material crops',
                method='Image inspection of sheets 01-10 plus automated independent pypdf field comparison. Answer/explanation pages retained; not claimed as 100 full-page manual semantic reviews.',
                sheets=[f'evidence/sheets/sheet-{n:02}.png' for n in range(1,11)],
                result='No additional missing/duplicate options visible in sampled question crops. Material cutoff confirmed and corrected.',
                targeted_materials=['evidence/comparisons/passage-016-page-0048-before.jpg','evidence/comparisons/passage-016-page-0048-after.jpg','evidence/comparisons/passage-050-page-0129-after.jpg'])
    write_json(OUT/'visual-review.json',visual)
    summary=dict(seed=20261111,sample_size=100,sample_by_exam=dict(sorted(byexam.items())),sample_by_part=dict(sorted(bypart.items())),
                 before=dict(text_passed=100,combined_passed=100-len(sample_affected),affected_sample_count=len(sample_affected),
                             affected_materials=len(broken),affected_question_links=len(old_affected),assets=357),
                 after=dict(sample_passed=100,all_text_questions_passed=1000,spatial_checks=spatial['summary']['checks'],spatial_failures=0,
                            materials=190,assets=359,regression_tests=8),
                 evidence=dict(source_page_images=len(pagefiles),evidence_files=evidence_count),unchanged_tables=unchanged,
                 source_sha256=sha(source),database_sha256=sha(ROOT/'data/questions.sqlite3'),before_backup_sha256=sha(OUT/'before.sqlite3'))
    write_json(OUT/'summary.json',summary)
    report=f'''# 试题库抽样及全量核对测试报告

日期：2026-11-11（Asia/Shanghai）。结论：发现并修复材料截图裁切错误；修复后本报告列明的核对项目全部通过。当前 `data/questions.sqlite3` 已替换为验证后的数据。

## 1. 范围与抽样

从现有 1000 题按固定种子 **20261111** 无放回随机抽取 100 题。先冻结 [检查前数据库](before.sqlite3)，再抽样，修复后复用同一批题号，没有剔除失败样本。所有题目 ID 与题号见 [样本清单](sample-manifest.json) 和 [逐题结果 CSV](sample-results.csv)。

- 各套数量：{dict(sorted(byexam.items()))}
- 各 Part 数量：{dict(sorted(bypart.items()))}
- 所有 10 套、Part 5/6/7 均有覆盖；这是简单随机抽样，不强制每套抽 10 题。

## 2. 核对方法

1. 使用 **pypdf** 直接从原 PDF 重新抽取文字，与原导入使用的 **PyMuPDF** 分离。审计脚本未调用原导入的题目/答案/解析解析函数。检查题干、四个选项、答案表、解析与共用材料正文；随后扩大至全部 **1000 题**。
2. 比较忽略空白、软连字符与长下划线装饰线的数量差异；不忽略其他标点、单词、数字或大小写。Part 6 无独立题干的中文提示属于生成的显示文字，不冒充 PDF 原文。两套解析器均基于同一 PDF 文本层，不能视为两个独立出版来源。
3. 检查 **1000 题题干来源页码 + 1000 条解析来源页码** 的内容覆盖和精确起止页，避免只检查记录数量。
4. 对全部 **190 组材料**，逐字检查截图裁切区内可抽取的文字等于原材料文字；逐张重绘比对截图 JPEG 字节，并检查截图覆盖到的原 PDF 嵌入图片没有被截断。
5. 保存 100 题的原题截图，并查看 10 张汇总图检查题目/选项可见性；原答案页、解析页与材料页保留供离线复核。答案和解析的一致性结论主要来自程序逐字段比对，不声称对全部解析做了人工语义评审。
6. 检查 SQLite 完整性、外键、每套题号连续性、每题四个选项、答案存在、材料所属试卷与题号范围；执行 8 项回归测试。新增材料截图完整性检查也纳入导入提交前和相同来源跳过检查。

## 3. 发现的错误、影响和修复

**问题：材料截图采用固定 `page.height * 0.92` 作为页底。** 原 PDF 正文可能延伸至约 94% 高度，因此旧截图可能截掉一整行文字、部分字形或位于页底的材料引导语。文字题库本身与原文一致，错误发生在阅读材料图片展示数据。

- 全量定位：**59/190 组材料**存在可抽取文字缺失，关联 **{len(old_affected)} 道题**（同一材料多题共享，不能将此数解释为题干错误数）。
- 随机样本：**{len(sample_affected)}/100 题**关联到这些材料。因此修复前综合检查为 **{100-len(sample_affected)}/100 通过**，尽管 100 题文字字段均通过。
- 根因修复：依据原页中实际独立页脚的坐标确定材料页底，不再按固定百分比裁切。材料结束页仍以第一道题的位置为边界，避免把题目混入材料。
- 全量重新生成：**146 组材料**的截图边界有调整，其中 59 组修复了文字缺失，其余也统一按实际页脚位置更新裁切范围；恢复了原先漏掉的 2 张页底材料截图，素材总数 **357 → 359**。
- 题目、选项、答案、解析、材料文字五张表，修复前后逐行比较 **完全一致**。本次没有为了使测试通过而改写题目或答案。
- 原书 `Test 04 / 131–144` 的范围排版错误仍按前次校正关联至 131–134，保留原始引导语及审计记录；本次未更改此项。

示例：Test 01，181–185 组，PDF 第 48 页旧图丢失 “For discerning customers...” 一行。查看 [修复前](evidence/comparisons/passage-016-page-0048-before.jpg)、[修复后](evidence/comparisons/passage-016-page-0048-after.jpg)。Test 03，168–171 组，PDF 第 129 页的页底引导语此前整张未保留，[现在恢复](evidence/comparisons/passage-050-page-0129-after.jpg)。

完整范围和所有变更页见 [截图变更清单](asset-changes.json)，59 组失败明细见 [修复前版式检查](before-spatial.json)。

## 4. 最终结果

| 检查项 | 结果 |
| --- | --- |
| 固定随机样本（题干、选项、答案、解析、材料及截图完整性） | **100/100 通过** |
| 全量题干、选项、答案、解析及共用材料文字 | **1000/1000 题通过** |
| 全量材料截图文字覆盖 | **190/190 组通过** |
| 当前截图来源及像素复现 | **359/359 张通过** |
| 页码、原页文本、截图及嵌入图片覆盖等空间检查 | **{spatial['summary']['checks']}/{spatial['summary']['checks']} 通过，0 失败** |
| SQLite 完整性 / 外键 / 题号 / 材料关联 | 通过 |
| 回归测试 | **8/8 通过** |
| 旧数据库运行新增完整性门禁 | 预期失败，成功捕获旧错误 |

核对结果见 [全量文字检查](after-checks.json)、[全量版式检查](after-spatial.json)、[测试日志](unit-tests.log)、[旧数据回归日志](before-regression.log)、[重复导入检查](idempotency.log)。

## 5. 证据保存

- [100 题原文/数据库对照页面](index.html)：每题原题截图、数据库内容、答案、解析、材料截图及原页链接。
- `evidence/pages/`：**{len(pagefiles)} 张**去重的 PDF 完整原页图，覆盖样本题目、答案、解析及材料。
- `evidence/questions/`：每题 PNG 与数据库字段 JSON；`evidence/materials/`：样本所需材料图片。
- `evidence/comparisons/`：所有发生调整的材料页的修复前后图片；`evidence/sheets/`：100 题分为 10 张汇总图。
- `before.sqlite3` / `after.sqlite3`：修复前后数据库快照；`before-records.json` / `after-records.json`：修复前后文字及图片元数据；`reference-pages.json`：pypdf 原文提取结果。
- `source.pdf`：原 PDF 的证据副本，字节与根目录输入文件一致。
- [图片证据 SHA-256](evidence-sha256.json)、`file-manifest.json`：检测证据文件是否变化。
- `code/`：本次实际审计、导入、回归测试脚本及依赖锁文件快照。

源 PDF SHA-256：`{sha(source)}`  
当前数据库 SHA-256：`{sha(ROOT/'data/questions.sqlite3')}`  
检查前数据库备份 SHA-256：`{sha(OUT/'before.sqlite3')}`

备份通过 SQLite backup API 生成，物理文件页头可与原数据库不同；检查前原文件哈希另记录在样本清单及 before-checks.json 中。

## 6. 可复现命令

从项目根目录执行（保留原抽样清单和 before.sqlite3，不要删除）：

```powershell
uv sync --locked
uv run python -m backend.scripts.audit_questions --phase recheck
uv run python -m backend.scripts.audit_spatial --phase recheck
uv run python -m unittest discover -s backend/tests -v
```

当前库已经修复；直接重复导入相同 SHA-256 的 PDF 会校验并跳过，不会覆盖旧快照。

## 7. 结论边界

此次结论是**导入数据对源 PDF 的一致性、关联和截图完整性通过已列明检查**。没有重新编写原书题目，也没有将原书答案做学术重判。图片内文字未做 OCR，其证据为保留的原版图像及完整覆盖检查；不能把自动文字层核对及 100 题视觉检查称为对全部 1202 页的人工逐字校对。本次未发现其他待修复的导入错误。

## 附录：100 题逐题结果

| ID | 试卷 | 题号 | Part | 原截图问题影响 | 修复后结果 |
| --- | --- | --- | --- | --- | --- |
'''
    for q in sample:
        report+=f"| {q['id']} | {q['exam_number']:02} | {q['number']} | {q['part']} | {'是' if q['passage_id'] in broken else '否'} | [通过](index.html#q-{q['id']}) |\n"
    (OUT/'report.md').write_text(report,encoding='utf8')
    for path in [ROOT/'backend/scripts/import_questions.py',ROOT/'backend/scripts/audit_questions.py',ROOT/'backend/scripts/audit_spatial.py',ROOT/'backend/scripts/audit_evidence.py',ROOT/'backend/scripts/audit_report.py',ROOT/'backend/tests/test_question_bank.py',ROOT/'backend/app/db/schema.sql',ROOT/'pyproject.toml',ROOT/'uv.lock']:
        dest=OUT/'code'/path.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,dest)
    file_manifest={str(p.relative_to(OUT)).replace('\\','/'):dict(sha256=sha(p),bytes=p.stat().st_size) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='file-manifest.json'}
    write_json(OUT/'file-manifest.json',file_manifest)
    archive=OUT.parent/'2026-11-11-evidence.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(OUT.rglob('*')):
            if path.is_file():
                z.write(path,str(path.relative_to(OUT)))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('ZIP',archive.stat().st_size,'bytes',sha(archive))


if __name__=='__main__':
    main()
