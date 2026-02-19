-- Начальная миграция: основные таблицы

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    role TEXT NOT NULL,           -- user | assistant | system
    content TEXT NOT NULL,         -- JSON: полное содержимое сообщения
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversations_project
    ON conversations(project_id, created_at);

CREATE TABLE IF NOT EXISTS conversation_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    messages_start_id INTEGER NOT NULL,
    messages_end_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_input TEXT,               -- JSON
    tool_result TEXT,              -- JSON (обрезается до 10KB)
    model TEXT NOT NULL,
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    is_error BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_project
    ON tool_calls(project_id, created_at);

CREATE TABLE IF NOT EXISTS cost_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,             -- YYYY-MM-DD
    project_id TEXT NOT NULL,
    model TEXT NOT NULL,
    requests_count INTEGER DEFAULT 0,
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    UNIQUE(date, project_id, model)
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_input TEXT NOT NULL,       -- JSON
    status TEXT DEFAULT 'pending',  -- pending | approved | rejected | expired
    telegram_message_id INTEGER,
    conversation_context TEXT,      -- JSON: сохранённый контекст для продолжения
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scheduler_state (
    job_id TEXT PRIMARY KEY,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    status TEXT DEFAULT 'idle'      -- idle | running | error
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
