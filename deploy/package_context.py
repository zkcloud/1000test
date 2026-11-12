"""仅打包部署必需文件；不包含 SSH 密钥、运行记录、审计快照或本地环境。"""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import tarfile

root=Path(__file__).resolve().parents[1]
release=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
target=root/'tmp'/f'deploy-{release}.tar.gz'
target.parent.mkdir(exist_ok=True)
files=[root/n for n in ['Dockerfile','.dockerignore','compose.yaml','pyproject.toml','uv.lock','backend/__init__.py','backend/scripts/__init__.py','backend/scripts/backup_runtime.py','data/questions.sqlite3','frontend/package.json','frontend/package-lock.json','frontend/index.html','frontend/vite.config.ts','frontend/tsconfig.json','frontend/tsconfig.app.json','frontend/tsconfig.node.json']]
for directory in ['backend/app','frontend/src','frontend/public','deploy']:
    files.extend(p for p in (root/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
files=sorted(set(files))
manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
with tarfile.open(target,'w:gz') as archive:
    for p in files:
        archive.add(p,arcname=p.relative_to(root).as_posix(),recursive=False)
info=dict(release=release,archive=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),files=manifest)
(root/'reports/deployment/context.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in info.items() if k!='files'},ensure_ascii=False))
