"""一致性备份，不直接拷贝正在使用的 SQLite/WAL 文件。"""

import argparse
from pathlib import Path
import sqlite3


def backup(source: Path, target: Path):
    if not source.is_file():
        raise ValueError("源数据库不存在")
    if target.exists() or source.resolve() == target.resolve():
        raise ValueError("备份目标已存在，请使用新的文件名")
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src,
        sqlite3.connect(target) as dst,
    ):
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("备份完整性检查失败")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    backup(args.source, args.target)
    print(f"备份已验证：{args.target}")
