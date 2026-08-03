from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    base_url TEXT,
    api_style TEXT NOT NULL DEFAULT 'openai',
    credential_ref TEXT,
    settings_json TEXT NOT NULL DEFAULT '{}',
    input_price REAL NOT NULL DEFAULT 0,
    output_price REAL NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runners (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    runner_type TEXT NOT NULL,
    executable TEXT,
    args_json TEXT NOT NULL DEFAULT '[]',
    env_json TEXT NOT NULL DEFAULT '{}',
    system_prompt TEXT NOT NULL DEFAULT '',
    tools_json TEXT NOT NULL DEFAULT '[]',
    limits_json TEXT NOT NULL DEFAULT '{}',
    model_override_supported INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_cases (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    version TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    definition_json TEXT NOT NULL,
    builtin INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(slug, version)
);

CREATE TABLE IF NOT EXISTS test_suites (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL,
    builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suite_cases (
    suite_id TEXT NOT NULL REFERENCES test_suites(id) ON DELETE CASCADE,
    test_case_id TEXT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(suite_id, test_case_id)
);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    suite_id TEXT NOT NULL REFERENCES test_suites(id),
    participants_json TEXT NOT NULL,
    repetitions INTEGER NOT NULL DEFAULT 1,
    concurrency INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    test_case_id TEXT NOT NULL REFERENCES test_cases(id),
    model_id TEXT NOT NULL REFERENCES models(id),
    runner_id TEXT NOT NULL REFERENCES agent_runners(id),
    repetition INTEGER NOT NULL DEFAULT 1,
    lane TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    final_answer TEXT,
    score REAL,
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    cost_source TEXT NOT NULL DEFAULT 'unavailable',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    steps INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    passed INTEGER,
    workspace_path TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS run_attempts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    prompt TEXT NOT NULL,
    multiplier REAL NOT NULL DEFAULT 1,
    raw_score REAL,
    adjusted_score REAL,
    passed INTEGER NOT NULL DEFAULT 0,
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    steps INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(run_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, seq)
);

CREATE TABLE IF NOT EXISTS validator_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    validator_type TEXT NOT NULL,
    weight REAL NOT NULL,
    score REAL NOT NULL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judge_reviews (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    judge_model_id TEXT,
    judge_runner_id TEXT,
    score REAL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS score_components (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    dimension TEXT NOT NULL,
    score REAL NOT NULL,
    weight REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    subject_type TEXT,
    subject_id TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_experiment ON runs(experiment_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_attempts_run ON run_attempts(run_id, attempt_no);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_tests_category ON test_cases(category);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def initialize(self) -> None:
        with self._write_lock, self.connect() as connection:
            connection.executescript(SCHEMA)
            run_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            for name, declaration in (
                ("cost_source", "TEXT NOT NULL DEFAULT 'unavailable'"),
                ("attempt_count", "INTEGER NOT NULL DEFAULT 1"),
                ("passed", "INTEGER"),
            ):
                if name not in run_columns:
                    connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {declaration}")
            row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta(version) VALUES (3)")
            elif int(row["version"]) < 3:
                connection.execute("UPDATE schema_meta SET version=3")

    @contextmanager
    def transaction(self):
        with self._write_lock, self.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.transaction() as connection:
            connection.execute(sql, tuple(params))

    def executemany(self, sql: str, values: Iterable[Iterable[Any]]) -> None:
        with self.transaction() as connection:
            connection.executemany(sql, [tuple(row) for row in values])

    def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]

    def insert_audit(
        self,
        action: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.execute(
            "INSERT INTO audit_logs(action, subject_type, subject_id, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (action, subject_type, subject_id, json.dumps(detail or {}), utc_now()),
        )
