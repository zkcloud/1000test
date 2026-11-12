"""共享的 SQLite 连接入口。"""
import sqlite3
from pathlib import Path

DEFAULT_DATABASE = Path(__file__).resolve().parents[3] / 'data' / 'questions.sqlite3'


def connect_database(path: Path = DEFAULT_DATABASE) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    return connection
