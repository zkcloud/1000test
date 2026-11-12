import sqlite3
import pytest
from backend.scripts.backup_runtime import backup


def test_wal_backup_restores_committed_records_and_never_overwrites(tmp_path):
    source = tmp_path / "live.sqlite3"
    target = tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE records(id INTEGER PRIMARY KEY,value TEXT)")
        db.execute("INSERT INTO records VALUES(1,'saved')")
        db.commit()
        backup(source, target)
        with sqlite3.connect(target) as restored:
            assert (
                restored.execute("SELECT value FROM records").fetchone()[0] == "saved"
            )
        with pytest.raises(ValueError):
            backup(source, target)
