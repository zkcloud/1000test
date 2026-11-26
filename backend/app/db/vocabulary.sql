PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE words (
    id INTEGER PRIMARY KEY,
    word TEXT NOT NULL CHECK (length(trim(word)) > 0),
    normalized TEXT NOT NULL UNIQUE,
    entry_kind TEXT NOT NULL CHECK (entry_kind IN ('word', 'phrase'))
);

CREATE TABLE senses (
    id INTEGER PRIMARY KEY,
    word_id INTEGER NOT NULL REFERENCES words(id),
    pos TEXT NOT NULL,
    meaning TEXT NOT NULL CHECK (length(trim(meaning)) > 0),
    usage TEXT NOT NULL,
    example_text TEXT,
    example_translation TEXT,
    example_kind TEXT CHECK (example_kind IN ('original', 'supplemental')),
    example_pdf_page INTEGER,
    example_printed_page TEXT,
    study_ready INTEGER NOT NULL CHECK (study_ready IN (0, 1)),
    spelling_prompt TEXT,
    accepted_variants_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE (word_id, pos, meaning),
    CHECK (spelling_prompt IS NULL OR study_ready = 1),
    CHECK (study_ready = 0 OR (
        length(trim(pos)) > 0 AND length(trim(usage)) > 0
        AND example_kind IS NOT NULL AND example_text IS NOT NULL
        AND example_translation IS NOT NULL
    )),
    CHECK (example_kind IS NOT 'original' OR example_pdf_page IS NOT NULL)
);

CREATE TABLE sense_sources (
    sense_id INTEGER NOT NULL REFERENCES senses(id),
    test_number INTEGER NOT NULL CHECK (test_number BETWEEN 1 AND 10),
    pdf_page INTEGER NOT NULL CHECK (pdf_page > 0),
    printed_page TEXT,
    block_number INTEGER NOT NULL CHECK (block_number BETWEEN 1 AND 27),
    pdf_page_end INTEGER NOT NULL CHECK (pdf_page_end >= pdf_page),
    question_first INTEGER,
    question_last INTEGER,
    PRIMARY KEY (sense_id, test_number, block_number, pdf_page)
);

CREATE INDEX idx_vocabulary_sources_test ON sense_sources(test_number, sense_id);
