from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 4


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
    definition_hash TEXT,
    builtin INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(slug, version)
);

CREATE TABLE IF NOT EXISTS test_case_revisions (
    id TEXT PRIMARY KEY,
    test_case_id TEXT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    version TEXT NOT NULL,
    definition_hash TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(test_case_id, definition_hash)
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
    benchmark_generation TEXT NOT NULL DEFAULT 'v2',
    scoring_profile TEXT NOT NULL DEFAULT 'balanced-v2',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    test_case_id TEXT NOT NULL REFERENCES test_cases(id),
    test_revision_id TEXT REFERENCES test_case_revisions(id),
    model_id TEXT NOT NULL REFERENCES models(id),
    runner_id TEXT NOT NULL REFERENCES agent_runners(id),
    repetition INTEGER NOT NULL DEFAULT 1,
    lane TEXT NOT NULL,
    scoring_profile TEXT NOT NULL DEFAULT 'balanced-v2',
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
CREATE INDEX IF NOT EXISTS idx_revisions_case ON test_case_revisions(test_case_id, created_at);
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

    def _backup_before_migration(self, target_version: int) -> Path | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        try:
            with sqlite3.connect(self.path) as probe:
                has_meta = probe.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
                ).fetchone()
                if not has_meta:
                    return None
                row = probe.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
                current_version = int(row[0]) if row else 0
        except (OSError, sqlite3.DatabaseError, TypeError, ValueError):
            return None
        if current_version >= target_version:
            return None
        backup_dir = self.path.parent / "migration-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / (
            f"{self.path.stem}-pre-schema-v{target_version}-{timestamp}{self.path.suffix}"
        )
        with sqlite3.connect(self.path) as source, sqlite3.connect(backup_path) as target:
            source.backup(target)
        return backup_path

    def initialize(self) -> None:
        self._backup_before_migration(SCHEMA_VERSION)
        with self._write_lock, self.connect() as connection:
            connection.executescript(SCHEMA)
            run_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            for name, declaration in (
                ("cost_source", "TEXT NOT NULL DEFAULT 'unavailable'"),
                ("attempt_count", "INTEGER NOT NULL DEFAULT 1"),
                ("passed", "INTEGER"),
                ("test_revision_id", "TEXT"),
                ("scoring_profile", "TEXT NOT NULL DEFAULT 'balanced-v2'"),
            ):
                if name not in run_columns:
                    connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {declaration}")
            experiment_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(experiments)").fetchall()
            }
            for name, declaration in (
                ("benchmark_generation", "TEXT NOT NULL DEFAULT 'v2'"),
                ("scoring_profile", "TEXT NOT NULL DEFAULT 'balanced-v2'"),
            ):
                if name not in experiment_columns:
                    connection.execute(
                        f"ALTER TABLE experiments ADD COLUMN {name} {declaration}"
                    )
            test_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(test_cases)").fetchall()
            }
            if "definition_hash" not in test_columns:
                connection.execute("ALTER TABLE test_cases ADD COLUMN definition_hash TEXT")
            row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
            elif int(row["version"]) < SCHEMA_VERSION:
                connection.execute("UPDATE schema_meta SET version=?", (SCHEMA_VERSION,))

    @staticmethod
    def _definition_digest(definition_json: str) -> str:
        try:
            value = json.loads(definition_json)
            canonical = json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        except (TypeError, json.JSONDecodeError):
            canonical = definition_json
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def sync_test_case_revisions(self, test_case_id: str | None = None) -> None:
        """Archive immutable test definitions and bind legacy runs to the best known revision.

        Built-in catalog rows are refreshed during application upgrades.  A run must keep
        using the exact definition that existed when the experiment was created, so revisions
        are append-only even when a catalog row keeps the same public version string.
        """
        where = " WHERE id=?" if test_case_id else ""
        params: tuple[str, ...] = (test_case_id,) if test_case_id else ()
        with self.transaction() as connection:
            rows = connection.execute(
                f"SELECT id,slug,version,definition_json FROM test_cases{where}", params
            ).fetchall()
            for row in rows:
                digest = self._definition_digest(row["definition_json"])
                revision_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"agentbench:test-revision:{row['id']}:{digest}",
                    )
                )
                connection.execute(
                    "INSERT OR IGNORE INTO test_case_revisions("
                    "id,test_case_id,slug,version,definition_hash,definition_json,created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        revision_id,
                        row["id"],
                        row["slug"],
                        row["version"],
                        digest,
                        row["definition_json"],
                        utc_now(),
                    ),
                )
                connection.execute(
                    "UPDATE test_cases SET definition_hash=? WHERE id=?",
                    (digest, row["id"]),
                )
                connection.execute(
                    "UPDATE runs SET test_revision_id=? "
                    "WHERE test_case_id=? AND test_revision_id IS NULL",
                    (revision_id, row["id"]),
                )

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
