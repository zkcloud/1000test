PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sources (
 id INTEGER PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
 page_count INTEGER NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS source_pages (
 source_id INTEGER NOT NULL REFERENCES sources(id), page_no INTEGER NOT NULL,
 printed_page TEXT, raw_text TEXT NOT NULL, PRIMARY KEY(source_id, page_no)
);
CREATE TABLE IF NOT EXISTS exams (
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
 number INTEGER NOT NULL CHECK(number BETWEEN 1 AND 10), title TEXT NOT NULL,
 duration_minutes INTEGER NOT NULL DEFAULT 75, UNIQUE(source_id, number)
);
CREATE TABLE IF NOT EXISTS passages (
 id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id),
 part INTEGER NOT NULL CHECK(part IN (6,7)), first_number INTEGER NOT NULL,
 last_number INTEGER NOT NULL, instruction TEXT NOT NULL, content TEXT NOT NULL,
 page_start INTEGER NOT NULL, page_end INTEGER NOT NULL,
 UNIQUE(exam_id, first_number, last_number)
);
CREATE TABLE IF NOT EXISTS passage_assets (
 id INTEGER PRIMARY KEY, passage_id INTEGER NOT NULL REFERENCES passages(id),
 sequence INTEGER NOT NULL, page_no INTEGER NOT NULL, bbox_json TEXT NOT NULL,
 mime_type TEXT NOT NULL DEFAULT 'image/jpeg', content BLOB NOT NULL,
 UNIQUE(passage_id, sequence)
);
CREATE TABLE IF NOT EXISTS questions (
 id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exams(id),
 passage_id INTEGER REFERENCES passages(id), number INTEGER NOT NULL CHECK(number BETWEEN 101 AND 200),
 part INTEGER NOT NULL CHECK(part IN (5,6,7)), type TEXT NOT NULL DEFAULT 'single_choice' CHECK(type='single_choice'),
 stem TEXT NOT NULL, raw_text TEXT NOT NULL, page_start INTEGER NOT NULL, page_end INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ready','needs_review')), UNIQUE(exam_id, number)
);
CREATE TABLE IF NOT EXISTS options (
 question_id INTEGER NOT NULL REFERENCES questions(id), label TEXT NOT NULL CHECK(label IN ('A','B','C','D')),
 content TEXT NOT NULL CHECK(length(trim(content))>0), PRIMARY KEY(question_id, label)
);
CREATE TABLE IF NOT EXISTS answers (
 question_id INTEGER PRIMARY KEY REFERENCES questions(id), correct_label TEXT NOT NULL,
 page_no INTEGER NOT NULL, FOREIGN KEY(question_id, correct_label) REFERENCES options(question_id,label)
);
CREATE TABLE IF NOT EXISTS explanations (
 question_id INTEGER PRIMARY KEY REFERENCES questions(id), content TEXT NOT NULL,
 page_start INTEGER NOT NULL, page_end INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS import_issues (
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
 exam_number INTEGER, question_number INTEGER, code TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_practice ON questions(exam_id, part, status, number);
CREATE INDEX IF NOT EXISTS idx_questions_passage ON questions(passage_id);
PRAGMA user_version = 1;
