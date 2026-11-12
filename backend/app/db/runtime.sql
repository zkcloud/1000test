PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS visitors(id TEXT PRIMARY KEY,csrf TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(
 id TEXT PRIMARY KEY,visitor_id TEXT NOT NULL REFERENCES visitors(id),exam_id INTEGER NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('exam','practice')),scope INTEGER,created_at REAL NOT NULL,deadline REAL,
 finished_at REAL,status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','finished')),
 current_index INTEGER NOT NULL DEFAULT 0,auto_next INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_attempt_owner ON attempts(visitor_id,created_at);
CREATE TABLE IF NOT EXISTS responses(
 attempt_id TEXT NOT NULL REFERENCES attempts(id),question_id INTEGER NOT NULL,
 selection TEXT CHECK(selection IN ('A','B','C','D')),first_selection TEXT,first_peeked INTEGER NOT NULL DEFAULT 0,
 revealed_at REAL,marked INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(attempt_id,question_id)
);
CREATE TABLE IF NOT EXISTS rate_limits(key TEXT PRIMARY KEY,window REAL NOT NULL,count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS attempt_questions(attempt_id TEXT NOT NULL REFERENCES attempts(id),question_id INTEGER NOT NULL,position INTEGER NOT NULL,
 PRIMARY KEY(attempt_id,question_id),UNIQUE(attempt_id,position));
